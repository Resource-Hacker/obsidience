"""Read-only native image regions and finite, activation-owned CPU text work."""
from __future__ import annotations

import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from PIL import Image

PRIVATE_REGIONS_FIELD = '_private_regional_evidence'
PRIVATE_TEXT_FIELD = '_private_text_evidence'
OCR_OWNER_FIELD = '_regional_ocr_owner'
READ_SECONDS = 2.0


def request_region(arguments: dict) -> tuple[dict | None, bool, str]:
    region = arguments.get('region')
    if 'region' in arguments and (
        not isinstance(region, dict) or set(region) != {'left', 'top', 'right', 'bottom'}
        or any(type(value) is not int or not 0 <= value <= 999 for value in region.values())
        or region['left'] >= region['right'] or region['top'] >= region['bottom']
    ):
        raise ValueError('region requires ordered left, top, right, bottom integers on the full image 0-999 grid')
    read = arguments.get('read', region is not None)
    if type(read) is not bool or read and region is None:
        raise ValueError('read must be boolean; read:true requires a region')
    mode = arguments.get('read_mode', 'detect')
    if mode not in ('detect', 'line') or 'read_mode' in arguments and not read:
        raise ValueError('read_mode must be detect or line and requires reading a region')
    return region, read, mode


def pixel_bounds(region: dict, width: int, height: int) -> tuple[int, int, int, int]:
    # Right/bottom are exclusive. Round outward to preserve edge glyphs.
    return (region['left'] * width // 999, region['top'] * height // 999,
            min(width, (region['right'] * width + 998) // 999),
            min(height, (region['bottom'] * height + 998) // 999))


def crop_png(png: bytes, bounds: tuple[int, int, int, int]) -> bytes:
    with Image.open(io.BytesIO(png)) as image:
        crop = image.crop(bounds)
        result = io.BytesIO()
        crop.save(result, 'PNG', compress_level=1)
        return result.getvalue()


class Reading:
    """One optional bounded read. The Harness owns the shared warm CPU reader."""
    def __init__(self, owner, png: bytes, source: dict, parent=None, *, mode="detect"):
        self.source = dict(source)
        self.mode = mode
        self.parent = parent
        self.stop = threading.Event()
        self.deadline = time.monotonic() + READ_SECONDS
        self.pool = self.future = None
        self.result = None
        self.closed = False
        if owner is None:
            self.result = self._unavailable('reader_unavailable')
            return
        from .reading import background_thread
        self.pool = ThreadPoolExecutor(max_workers=1, initializer=background_thread,
                                       thread_name_prefix='regional-reading')
        try:
            self.future = self.pool.submit(owner.read, png, source=self.source,
                recognition_only=mode == 'line', max_regions=12, deadline=self.deadline, cancelled=self.cancelled)
        except BaseException:
            self.close()
            raise

    def cancelled(self):
        return self.stop.is_set() or self.parent is not None and self.parent.is_set()

    def _unavailable(self, reason):
        return {'source': self.source, 'action_authorized': False, 'status': 'unavailable',
                'regions': [], 'coverage': {'scope': 'selected_native_region', 'recognized': 0},
                'partial': True, 'stop_reason': reason}

    def report(self, *, wait=False):
        if self.closed or self.parent is not None and self.parent.is_set():
            raise InterruptedError('regional reading cancelled')
        if self.result is not None:
            return self.result
        if self.stop.is_set():
            raise InterruptedError('regional reading cancelled')
        if not wait and not self.future.done():
            return None
        while self.result is None:
            if self.cancelled():
                raise InterruptedError('regional reading cancelled')
            try:
                self.result = self.future.result(timeout=min(0.05, max(0, self.deadline - time.monotonic())))
                if not isinstance(self.result, dict) or self.result.get('source') != self.source:
                    self.result = self._unavailable('source_mismatch')
            except FutureTimeout:
                if self.future.done():
                    self.result = self._unavailable('reader_failed')
                elif time.monotonic() >= self.deadline:
                    self.stop.set()
                    self.result = self._unavailable('deadline')
            except Exception:
                self.result = self._unavailable('reader_failed')
        self.result['reading_mode'] = self.mode
        return self.result

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.pool is not None:
            self.pool.shutdown(wait=True, cancel_futures=True)
        self.future = self.pool = None
        self.result = None
