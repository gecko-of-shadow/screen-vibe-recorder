"""Frame pump for the Wayland path (DESIGN.md 7).

The screen cast sends a frame only when the screen changes. FFmpeg reads raw
frames from stdin at a fixed rate. The pump keeps the latest frame and writes
it to FFmpeg on a fixed clock. A still screen gives repeats of the same frame.

Pure module: no gi, no Xlib, no cairo. It imports on Windows too.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Callable, Protocol

from .ffstats import PumpCounters
from .geometry import Rect

__all__ = [
    "Frame",
    "FramePump",
    "crop_rows",
    "frame_stride",
    "pipewire_source",
    "pipeline_description",
    "SKIP_AFTER",
    "WAIT_STEP",
]

SKIP_AFTER = 2.0     # s; a writer further behind than this skips ticks
WAIT_STEP = 0.01     # s; sleep step while the ticker waits for a frame
MAX_SLEEP = 0.05     # s; longest sleep in the tick phase
JOIN_TIMEOUT = 5.0   # s


class Frame(Protocol):
    width: int
    height: int
    stride: int
    seq: int  # 1, 2, 3 ... for each source buffer

    def crop(self, rect: Rect) -> bytes:
        """Return the BGRx rows of rect, packed (rect.w * 4 bytes for each row)."""


def crop_rows(data: bytes | memoryview, stride: int, rect: Rect) -> bytes:
    """Cut rect out of a BGRx picture with the given row stride."""
    if rect.is_empty or rect.x < 0 or rect.y < 0:
        raise ValueError(f"Bad crop rectangle {rect}.")
    row_bytes = rect.w * 4
    start_x = rect.x * 4
    if start_x + row_bytes > stride:
        raise ValueError(f"The crop rectangle {rect} is wider than the frame row ({stride} bytes).")
    view = memoryview(data)
    if view.ndim != 1 or view.itemsize != 1:
        view = view.cast("B")
    last_end = (rect.bottom - 1) * stride + start_x + row_bytes
    if last_end > len(view):
        raise ValueError(f"The crop rectangle {rect} is outside the frame data.")
    if start_x == 0 and row_bytes == stride:
        return bytes(view[rect.y * stride:rect.bottom * stride])
    out = bytearray(row_bytes * rect.h)
    pos = 0
    for y in range(rect.y, rect.bottom):
        begin = y * stride + start_x
        out[pos:pos + row_bytes] = view[begin:begin + row_bytes]
        pos += row_bytes
    return bytes(out)


def frame_stride(size: int, width: int, height: int) -> int | None:
    """Row stride in bytes from the buffer size (D20). None when the size does not fit."""
    if width <= 0 or height <= 0:
        return None
    packed = width * 4
    if size == packed * height:
        return packed
    if size % height == 0 and size // height >= packed:
        return size // height
    return None


def pipewire_source(fd: int, node_id: int) -> str:
    return f"pipewiresrc fd={fd} path={node_id} always-copy=true do-timestamp=true"


def pipeline_description(source: str) -> str:
    return (
        f"{source} ! videoconvert ! video/x-raw,format=BGRx ! "
        "appsink name=sink emit-signals=true sync=false max-buffers=0 drop=false"
    )


class FramePump:
    """Keeps the latest frame and writes it to FFmpeg at a fixed rate (7.2)."""

    def __init__(self, fps: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not fps > 0:
            raise ValueError("fps must be more than 0.")
        self.fps = float(fps)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._have_frame = threading.Condition(self._lock)
        self._slot: Frame | None = None
        self._slot_used = False
        self._crop: Rect | None = None
        self._counters = PumpCounters()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._write: Callable[[bytes], None] | None = None
        self.error: str | None = None

    # ------------------------------------------------------------ source side

    def offer(self, frame: Frame) -> None:
        """Any thread. Keep only the latest frame."""
        with self._lock:
            self._counters.received += 1
            if self._slot is not None and not self._slot_used:
                self._counters.superseded += 1
            self._slot = frame
            self._slot_used = False
            self._have_frame.notify_all()

    def latest(self) -> Frame | None:
        with self._lock:
            return self._slot

    def wait_first(self, timeout: float) -> Frame | None:
        """Wait (real time) until a frame is in the slot. Return it, or None after timeout."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            while self._slot is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._have_frame.wait(left)
            return self._slot

    def set_crop(self, rect: Rect) -> None:
        """Call before start(). The crop is in stream px."""
        with self._lock:
            self._crop = rect

    # ------------------------------------------------------------ ticker

    def start(self, write: Callable[[bytes], None], after_seq: int = 0,
              fresh_wait: float = 0.5) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("The frame pump is already running.")
        # Each run gets its own stop flag. A ticker that did not join in time
        # then cannot run again when a new start() begins.
        self._stop = threading.Event()
        self._write = write
        self._thread = threading.Thread(
            target=self._run,
            args=(write, after_seq, fresh_wait, self._stop),
            name="wayland-ticker",
            daemon=True,
        )
        self._thread.start()

    def restart(self, write: Callable[[bytes], None]) -> None:
        """Stop, set the counters to zero, and start again. Keep the latest frame and the crop (D17)."""
        self.stop()
        with self._lock:
            self._counters = PumpCounters()
            # The kept frame was not written by this run yet.
            self._slot_used = False
        self.error = None
        self.start(write)

    def stop(self) -> PumpCounters:
        """Stop the ticker and join it (5 s). Return the counters."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(JOIN_TIMEOUT)
        self._thread = None
        return self.counters()

    def counters(self) -> PumpCounters:
        with self._lock:
            c = self._counters
            return PumpCounters(
                received=c.received,
                superseded=c.superseded,
                ticks=c.ticks,
                fresh=c.fresh,
                repeats=c.repeats,
                late=c.late,
                skipped=c.skipped,
            )

    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _run(self, write: Callable[[bytes], None], after_seq: int, fresh_wait: float,
             stop: threading.Event) -> None:
        clock = self._clock
        sleep = self._sleep

        # Wait phase (D18): wait for a frame newer than after_seq, or fresh_wait s.
        start_time = clock()
        while not stop.is_set():
            f = self.latest()
            if f is None:
                sleep(WAIT_STEP)
                continue
            if f.seq > after_seq or clock() - start_time >= fresh_wait:
                break
            sleep(WAIT_STEP)
        if stop.is_set():
            return

        # Tick phase.
        t0 = clock()
        n = 0
        last_seq = 0
        interval = 1.0 / self.fps
        while not stop.is_set():
            due = t0 + n * interval
            now = clock()
            if now < due:
                sleep(min(due - now, MAX_SLEEP))
                continue
            behind = now - due
            if behind > SKIP_AFTER:
                k = math.floor(behind * self.fps)
                with self._lock:
                    self._counters.skipped += k
                n += k
                continue
            with self._lock:
                f = self._slot
                crop = self._crop
                if f is None:  # not possible after the wait phase; keep the ticker safe
                    n += 1
                    continue
                self._slot_used = True
                if f.seq != last_seq:
                    self._counters.fresh += 1
                    last_seq = f.seq
                else:
                    self._counters.repeats += 1
                if behind >= interval:
                    self._counters.late += 1
            try:
                rect = crop if crop is not None else Rect(0, 0, f.width, f.height)
                write(f.crop(rect))
            except Exception as exc:  # noqa: BLE001 - any write or crop error stops the pump
                self.error = str(exc) or type(exc).__name__
                break
            with self._lock:
                self._counters.ticks += 1
            n += 1
