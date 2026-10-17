"""Finite owner-requested acoustic/optical observation through existing owners.

No video device is opened here. The camera owner holds its motor for this bounded
measurement and supplies timestamped frames. Audio and pictures remain in RAM;
the local caller receives a private NPZ capture, never an Agent or Memory record.
"""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import selectors
import subprocess
import time

import numpy as np

from ...realtime import tracking
from . import calibration, visualize


def capture(payload, cancel):
    if (not isinstance(payload, dict) or set(payload) != {'microphone_id', 'seconds'}
            or type(payload['microphone_id']) is not int
            or type(payload['seconds']) is not int or not 10 <= payload['seconds'] <= 30):
        raise ValueError('Choose an observed microphone_id and 10 to 30 seconds')
    if not calibration._RUN.acquire(blocking=False):
        raise RuntimeError('Another light measurement is active')
    calibration._CANCEL.clear()
    lease = None
    try:
        with visualize._STATE:
            session = visualize._SESSION
        if session is None or session.state != 'running':
            raise RuntimeError('Start the music visualizer before observation')
        rows, nodes, _metadata = visualize._graph()
        mic = nodes.get(payload['microphone_id'], {})
        if (visualize._props(mic).get('media.class') != 'Audio/Source'
                or visualize._props(mic).get('device.api') != 'alsa'):
            raise ValueError('Select an observed physical microphone')
        mic_identity = visualize._identity(mic)
        lease = tracking.begin_measurement_hold()
        deadline = time.monotonic() + 4
        previous = None
        while True:
            calibration._check(deadline, cancel)
            pose = calibration._pose()
            if previous is not None and max(abs(a-b) for a,b in zip(pose, previous)) <= .1 and tracking.snapshot().get('submitted_speed') == {'yaw': 0.0, 'pitch': 0.0}:
                break
            previous = pose
            cancel.wait(.25)
        deadline = time.monotonic() + payload['seconds']

        def check():
            if cancel.is_set() or calibration._CANCEL.is_set() or session.stop_event.is_set():
                raise InterruptedError('Observation cancelled')

        def audio(name, target):
            props = 'node.dont-fallback=true' + (' stream.capture.sink=true' if name != 'room_mic' else '')
            child = subprocess.Popen(['pw-record', '--target', target, '--properties', props,
                '--raw', '--format', 's16', '--rate', '48000', '--channels', '2', '--latency', '20ms', '-'],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            chunks, clocks, total = [], [], 0
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    while time.monotonic() < deadline:
                        check()
                        if not selector.select(.05):
                            continue
                        chunk = os.read(child.stdout.fileno(), 8192)
                        if not chunk:
                            raise RuntimeError('Measurement audio ended')
                        total += len(chunk)
                        if total > 192000 * 31:
                            raise RuntimeError('Measurement audio exceeded bound')
                        chunks.append(chunk)
                        clocks.append((time.monotonic(), total / 192000))
                if not clocks:
                    raise RuntimeError('No measurement audio')
                samples = np.frombuffer(b''.join(chunks), dtype='<i2').reshape(-1, 2).mean(axis=1).astype('float32') / 32768
                clock = np.array(clocks)
                return {name: samples, name + '_origin': float(np.quantile(clock[:,0]-clock[:,1], .1)),
                        name + '_jitter_ms': float(np.std(clock[:,0]-clock[:,1])*1000)}
            except BaseException:
                cancel.set()
                raise
            finally:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()

        def camera():
            frames, stamps, arrivals, poses = [], [], [], []
            identity = None
            try:
                while time.monotonic() < deadline:
                    check()
                    stamp, image, current = calibration._frame()
                    identity = current if identity is None else identity
                    if current != identity:
                        raise RuntimeError('Camera identity changed during observation')
                    if not stamps or stamp > stamps[-1]:
                        frames.append(image.astype('uint8')); stamps.append(stamp)
                        arrivals.append(time.monotonic()); poses.append(calibration._pose())
                    cancel.wait(.04)
                return {'camera': np.array(frames), 'camera_pts': np.array(stamps),
                        'camera_arrivals': np.array(arrivals), 'camera_pose': np.array(poses)}
            except BaseException:
                cancel.set()
                raise

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix='light-observation') as pool:
            jobs = [pool.submit(audio, name, target) for name,target in (
                ('reference', session.name), ('speaker_monitor', session.sink_identity[2]),
                ('room_mic', mic_identity[2]))] + [pool.submit(camera)]
            result = {}
            for job in jobs:
                result.update(job.result())
        check()
        _rows, nodes, _metadata = visualize._graph()
        if visualize._identity(nodes.get(mic_identity[0], {'id': -1})) != mic_identity:
            raise RuntimeError('Microphone identity changed during observation')
        session._audit_audio()
        result['metadata'] = json.dumps({'microphone_id': mic_identity[0], 'microphone_serial': mic_identity[1],
            'audio_clock': 'receipt_clock_estimate', 'camera_clock': 'v4l2_driver_monotonic',
            'sensor_exposure_offset_verified': False, 'microphone_processing_delay_verified': False,
            'visualizer': session.snapshot()})
        output = io.BytesIO()
        np.savez_compressed(output, **result)
        return output.getvalue()
    finally:
        try:
            if lease is not None:
                tracking.end_measurement_hold(lease)
        finally:
            calibration._RUN.release()
