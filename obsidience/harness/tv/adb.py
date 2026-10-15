"""ADB transport to the registered TV: one bounded, cancellable client per command, never replayed.

`row` is the TV inventory (state/television.json) that tv.control validated; its address names the
transport, and its serial and model are what `guard` rechecks on the TV before an effect.
"""
from __future__ import annotations

import shlex
import subprocess
import time


def run(row, cancel, *args, timeout=8, connect=False):
    """One ADB command to the TV row's transport (or `adb connect` to it); its stdout bytes.

    Cancellation and the deadline kill the client. OSError when ADB rejects the command or loses the
    connection, TimeoutError past the deadline, InterruptedError when cancelled.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError('TV command cancelled')
    target = row['ip'] + ':5555'
    argv = ['/usr/bin/adb', *(['connect', target] if connect else ['-s', target, *args])]
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('TV command cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('TV ADB connection timed out; the TV may be in network standby or disconnected'
                                       if connect else 'TV ADB command timed out before a response was received')
                try:
                    out, err = process.communicate(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise OSError('ADB rejected or lost the TV connection: ' + err.decode(errors='replace')[:200])
            if len(out) > 16 * 1024 * 1024:
                raise ValueError('TV response exceeded its bound')
            return out
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def shell(row, cancel, command, timeout=8):
    """One shell command on the TV, as text."""
    return run(row, cancel, 'shell', command, timeout=timeout).decode(errors='replace')


def guard(row):
    """A shell prefix that rechecks the TV's identity in the same command before any effect."""
    return ('test "$(getprop ro.serialno)" = ' + shlex.quote(row['serial'])
            + ' && test "$(getprop ro.product.oemmodel)" = ' + shlex.quote(row['model']) + ' && ')
