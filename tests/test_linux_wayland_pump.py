"""Tests for wayland_pump.py (DESIGN.md 7 and 14.1). Pure: they run on any OS.

The pump gets a fake clock. The fake sleep moves the fake clock and then sleeps
a very short real time, so the ticker thread does not spin hard.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.geometry import Rect  # noqa: E402
from desktop_recorder.wayland_pump import (  # noqa: E402
    FramePump,
    crop_rows,
    frame_stride,
    pipeline_description,
    pipewire_source,
)


class FakeClock:
    def __init__(self) -> None:
        self._now = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        time.sleep(0.0002)


class FakeFrame:
    """A BGRx frame. Each pixel byte is the seq number, so a write shows which frame it came from."""

    def __init__(self, seq: int, width: int = 8, height: int = 6) -> None:
        self.seq = seq
        self.width = width
        self.height = height
        self.stride = width * 4
        self.data = bytes([seq % 256]) * (self.stride * height)

    def crop(self, rect: Rect) -> bytes:
        return crop_rows(self.data, self.stride, rect)


class StopWriting(Exception):
    pass


class Writer:
    """Records writes. Raises StopWriting on call limit+1, so the ticker ends at a known point.

    The pump counts fresh, repeats and late for a tick before it writes, and ticks
    only after the write. Thus the failed call adds to fresh, repeats or late, not to ticks.
    """

    def __init__(self, limit: int, on_write=None) -> None:
        self.limit = limit
        self.on_write = on_write
        self.items: list[bytes] = []
        self.done = threading.Event()

    def __call__(self, data: bytes) -> None:
        if len(self.items) >= self.limit:
            self.done.set()
            raise StopWriting("limit")
        self.items.append(data)
        if self.on_write is not None:
            self.on_write(len(self.items))


def run_until_done(test: unittest.TestCase, pump: FramePump, writer: Writer, timeout: float = 10.0):
    test.assertTrue(writer.done.wait(timeout), "the ticker did not reach the write limit")
    counters = pump.stop()
    return counters


class CropTests(unittest.TestCase):
    def test_crop_rows(self) -> None:
        width, height = 4, 3
        stride = width * 4
        data = bytes(range(stride * height))
        out = crop_rows(data, stride, Rect(1, 1, 2, 2))
        expected = data[1 * stride + 4:1 * stride + 12] + data[2 * stride + 4:2 * stride + 12]
        self.assertEqual(out, expected)
        self.assertEqual(crop_rows(data, stride, Rect(0, 0, 4, 3)), data)
        with self.assertRaises(ValueError):
            crop_rows(data, stride, Rect(3, 0, 2, 1))  # wider than the row
        with self.assertRaises(ValueError):
            crop_rows(data, stride, Rect(0, 2, 1, 2))  # below the data
        with self.assertRaises(ValueError):
            crop_rows(data, stride, Rect(0, 0, 0, 1))  # empty

    def test_crop_rows_padded_stride(self) -> None:
        width, height, stride = 1080, 4, 4400
        rows = []
        for y in range(height):
            row = bytes([y + 1]) * (width * 4) + bytes([0xEE]) * (stride - width * 4)
            rows.append(row)
        data = b"".join(rows)
        out = crop_rows(data, stride, Rect(0, 0, width, height))
        self.assertEqual(len(out), width * 4 * height)
        for y in range(height):
            part = out[y * width * 4:(y + 1) * width * 4]
            self.assertEqual(set(part), {y + 1}, f"row {y} is sheared")
        # The last row may end before the padding of the data ends.
        short = data[: (height - 1) * stride + width * 4]
        self.assertEqual(crop_rows(short, stride, Rect(0, 0, width, height)), out)

    def test_frame_stride(self) -> None:
        self.assertEqual(frame_stride(1080 * 4 * 720, 1080, 720), 1080 * 4)
        self.assertEqual(frame_stride(1100 * 4 * 720, 1080, 720), 4400)
        self.assertIsNone(frame_stride(1080 * 4 * 720 + 7, 1080, 720))
        self.assertIsNone(frame_stride(1000 * 4 * 720, 1080, 720))  # rows too short
        self.assertIsNone(frame_stride(100, 0, 0))

    def test_pipeline_strings(self) -> None:
        src = pipewire_source(42, 57)
        self.assertEqual(src, "pipewiresrc fd=42 path=57 always-copy=true do-timestamp=true")
        self.assertNotIn("target-object", src)
        self.assertNotIn("pipewire-serial", src)
        desc = pipeline_description(src)
        self.assertTrue(desc.startswith(src + " ! videoconvert ! video/x-raw,format=BGRx ! appsink name=sink"))
        self.assertIn("always-copy=true", desc)
        self.assertIn("max-buffers=0 drop=false", desc)
        self.assertIn("sync=false", desc)
        self.assertIn("emit-signals=true", desc)


class PumpTests(unittest.TestCase):
    def make(self, fps: float = 4.0) -> tuple[FramePump, FakeClock]:
        clock = FakeClock()
        pump = FramePump(fps, clock=clock, sleep=clock.sleep)
        self.addCleanup(pump.stop)
        return pump, clock

    def test_fresh_and_repeats(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(1))
        pump.set_crop(Rect(2, 1, 4, 2))

        def on_write(count: int) -> None:
            if count == 3:
                pump.offer(FakeFrame(2))

        writer = Writer(6, on_write)
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.ticks, 6)
        self.assertEqual(c.fresh, 2)
        self.assertEqual(c.repeats, 5)  # 4 written repeats + the failed call
        self.assertEqual(c.late, 0)
        self.assertEqual(c.skipped, 0)
        self.assertEqual([item[0] for item in writer.items], [1, 1, 1, 2, 2, 2])
        self.assertTrue(all(len(item) == 4 * 4 * 2 for item in writer.items))
        self.assertEqual(pump.error, "limit")

    def test_late_counts_when_write_blocks(self) -> None:
        # fps 4: interval 0.25 s. Each write takes 1.5 intervals (0.375 s) of fake time.
        # Tick k is 0.125*k s behind. It is late when that is 0.25 s or more: k >= 2.
        pump, clock = self.make(4.0)
        pump.offer(FakeFrame(1))
        writer = Writer(6, lambda _n: clock.advance(0.375))
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.ticks, 6)
        self.assertEqual(c.late, 5)  # ticks 2 to 5, and the failed call (tick 6)
        self.assertEqual(c.skipped, 0)

    def test_skip_after_2s(self) -> None:
        # fps 4. The first write blocks 2.55 s. Tick 1 is due at 0.25: 2.3 s behind.
        # floor(2.3 * 4) = 9 ticks are skipped. Tick 10 is due at 2.5: 0.05 s behind, not late.
        pump, clock = self.make(4.0)
        pump.offer(FakeFrame(1))

        def on_write(count: int) -> None:
            if count == 1:
                clock.advance(2.55)

        writer = Writer(3, on_write)
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.skipped, 9)
        self.assertEqual(c.ticks, 3)
        self.assertEqual(c.late, 0)

    def test_low_fps_late_write_does_not_spin(self) -> None:
        # fps 0.2: interval 5 s. The first write blocks 7.5 s. Tick 1 is due at 5: 2.5 s behind.
        # That is over 2 s but less than one interval, so it is written late, not skipped.
        # The old code computed k = floor(2.5 * 0.2) = 0 and looped with no sleep.
        pump, clock = self.make(0.2)
        pump.offer(FakeFrame(1))

        def on_write(count: int) -> None:
            if count == 1:
                clock.advance(7.5)

        writer = Writer(3, on_write)
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.skipped, 0)
        self.assertEqual(c.ticks, 3)
        self.assertEqual(c.late, 0)  # 2.5 s behind is less than one interval (5 s)

    def test_low_fps_skips_whole_intervals(self) -> None:
        # fps 0.2. The first write blocks 12 s. Tick 1 is due at 5: 7 s behind, more than
        # one interval. floor(7 * 0.2) = 1 tick is skipped. Tick 2 (due 10) is 2 s behind: written.
        pump, clock = self.make(0.2)
        pump.offer(FakeFrame(1))

        def on_write(count: int) -> None:
            if count == 1:
                clock.advance(12.0)

        writer = Writer(3, on_write)
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.skipped, 1)
        self.assertEqual(c.ticks, 3)

    def test_superseded(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(1))
        pump.offer(FakeFrame(2))  # frame 1 was never written

        def on_write(count: int) -> None:
            if count == 1:
                pump.offer(FakeFrame(3))  # replaced before a tick: superseded
                pump.offer(FakeFrame(4))

        writer = Writer(3, on_write)
        pump.start(writer)
        c = run_until_done(self, pump, writer)
        self.assertEqual(c.received, 4)
        self.assertEqual(c.superseded, 2)
        self.assertEqual([item[0] for item in writer.items], [2, 4, 4])

    def test_write_error_stops(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(1))
        calls = []

        def broken(data: bytes) -> None:
            calls.append(data)
            raise BrokenPipeError("pipe closed")

        pump.start(broken)
        deadline = time.monotonic() + 5
        while pump.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(pump.is_running())
        self.assertEqual(len(calls), 1)
        self.assertEqual(pump.error, "pipe closed")
        self.assertEqual(pump.counters().ticks, 0)

    def test_crop_error_stops(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(1))
        pump.set_crop(Rect(0, 0, 100, 100))  # outside the 8x6 frame
        writer = Writer(5)
        pump.start(writer)
        deadline = time.monotonic() + 5
        while pump.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(pump.is_running())
        self.assertEqual(writer.items, [])
        self.assertTrue(pump.error)

    def test_waits_for_fresh_frame(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(5))
        writer = Writer(2)
        pump.start(writer, after_seq=5, fresh_wait=1e9)
        time.sleep(0.2)
        self.assertEqual(writer.items, [])
        pump.offer(FakeFrame(6))
        c = run_until_done(self, pump, writer)
        self.assertEqual([item[0] for item in writer.items], [6, 6])
        self.assertEqual(c.fresh, 1)

    def test_fresh_wait_timeout(self) -> None:
        pump, clock = self.make()
        pump.offer(FakeFrame(5))
        seen: list[float] = []
        writer = Writer(1, lambda _n: seen.append(clock()))
        pump.start(writer, after_seq=5, fresh_wait=0.5)
        run_until_done(self, pump, writer)
        self.assertEqual(writer.items[0][0], 5)
        self.assertGreaterEqual(seen[0], 0.5)
        self.assertLess(seen[0], 0.6)

    def test_no_frame_writes_nothing(self) -> None:
        pump, clock = self.make()
        writer = Writer(1)
        pump.start(writer)
        time.sleep(0.2)
        self.assertGreater(clock(), 0.0)  # the wait loop ran
        c = pump.stop()
        self.assertEqual(writer.items, [])
        self.assertEqual(c.ticks, 0)
        self.assertIsNone(pump.error)
        self.assertFalse(pump.is_running())

    def test_restart_keeps_frame_zeroes_counters(self) -> None:
        pump, _clock = self.make()
        pump.offer(FakeFrame(1))
        pump.set_crop(Rect(0, 0, 2, 2))
        first = Writer(4)
        pump.start(first)
        c1 = run_until_done(self, pump, first)
        self.assertEqual(c1.ticks, 4)
        self.assertEqual(pump.error, "limit")

        second = Writer(3)
        pump.restart(second)  # still screen: no new frame is offered
        c2 = run_until_done(self, pump, second)
        self.assertEqual([item[0] for item in second.items], [1, 1, 1])
        self.assertTrue(all(len(item) == 2 * 2 * 4 for item in second.items))
        self.assertEqual(c2.ticks, 3)
        self.assertEqual(c2.fresh, 1)
        self.assertEqual(c2.repeats, 3)  # 2 written repeats + the failed call
        self.assertEqual(c2.received, 0)
        self.assertEqual(pump.latest().seq, 1)

    def test_wait_first(self) -> None:
        pump, _clock = self.make()
        self.assertIsNone(pump.wait_first(0.05))
        threading.Timer(0.05, lambda: pump.offer(FakeFrame(3))).start()
        frame = pump.wait_first(5.0)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.seq, 3)


if __name__ == "__main__":
    unittest.main()
