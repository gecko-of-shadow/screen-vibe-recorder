"""Tests for ffstats.py and recording.py (DESIGN.md 6 and 14.1).

The pure tests run on any OS. Tests that start a process need Linux.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

try:
    import linux_skip  # noqa: E402
except ImportError:  # tests/linux_skip.py (owner C8) is not there yet: same rule, local copy.
    import types

    linux_skip = types.ModuleType("linux_skip")
    linux_skip.REQUIRE = os.environ.get("DESKTOP_RECORDER_REQUIRE_GUI") == "1"
    linux_skip.IS_LINUX = sys.platform.startswith("linux")

    def _need(ok: bool, reason: str) -> None:
        if ok:
            return
        if linux_skip.REQUIRE:
            raise AssertionError("Required for this test: " + reason)
        raise unittest.SkipTest(reason)

    def _need_linux() -> None:
        _need(linux_skip.IS_LINUX, "Linux")

    def _need_program(name: str) -> str:
        path = shutil.which(name)
        _need(path is not None, name)
        return path or ""

    linux_skip.need = _need
    linux_skip.need_linux = _need_linux
    linux_skip.need_program = _need_program

from desktop_recorder.ffstats import (  # noqa: E402
    MAX_LINE,
    FfmpegProgress,
    LineSplitter,
    PumpCounters,
    RecordingStats,
    format_stats,
    mb_text,
    parse_progress,
    session_files,
    snapshot,
    total_bytes,
    wayland_stats,
    x11_stats,
)
from desktop_recorder.recording import FfmpegProcess, popen_with_pdeathsig, write_all  # noqa: E402

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FAKE_STATS = os.path.join(TESTS_DIR, "fake_ffmpeg_stats.py")

WINDOWS_SAMPLE = (
    "frame=  100 fps= 10 q=23.0 size=     256KiB time=00:00:10.00 "
    "bitrate= 209.7kbits/s dup=3 drop=1 speed=1.0x"
)


class LineSplitterTests(unittest.TestCase):
    def test_line_splitter_cr(self) -> None:
        s = LineSplitter()
        self.assertEqual(s.feed("a\rb\nc"), ["a", "b"])
        self.assertEqual(s.flush(), ["c"])
        self.assertEqual(s.flush(), [])

    def test_split_across_chunks_and_empty_lines(self) -> None:
        s = LineSplitter()
        self.assertEqual(s.feed("fra"), [])
        self.assertEqual(s.feed("me=1\r"), ["frame=1"])
        self.assertEqual(s.feed("\n\n\rx\r\n"), ["x"])
        self.assertEqual(s.flush(), [])

    def test_cap_8192(self) -> None:
        s = LineSplitter()
        lines = s.feed("x" * 10000 + "\nshort\n")
        self.assertEqual([len(line) for line in lines], [MAX_LINE, 5])
        # A long line with no line end stays bounded too.
        for _ in range(10):
            self.assertEqual(s.feed("y" * 5000), [])
        tail = s.flush()
        self.assertEqual(len(tail), 1)
        self.assertEqual(len(tail[0]), MAX_LINE)


class ParseProgressTests(unittest.TestCase):
    def test_parse_progress(self) -> None:
        self.assertEqual(parse_progress(WINDOWS_SAMPLE), FfmpegProgress(100, 3, 1))
        self.assertEqual(parse_progress("frame=  100 fps=10"), FfmpegProgress(100, 0, 0))
        self.assertEqual(
            parse_progress(
                "frame=   10 fps=0.0 q=-1.0 Lsize=N/A time=00:00:00.80 bitrate=N/A speed=64.3x elapsed=0:00:00.01    "
            ),
            FfmpegProgress(10, 0, 0),
        )
        self.assertEqual(
            parse_progress("frame=5 fps=5 q=23.0 size=0KiB time=00:00:01.00 bitrate=N/A drop=7 speed=1x"),
            FfmpegProgress(5, 0, 7),
        )
        self.assertIsNone(parse_progress("frame=N/A fps=0"))
        self.assertIsNone(parse_progress("frame=² fps=0"))
        self.assertEqual(parse_progress("frame=7 dup=² drop=1"), FfmpegProgress(7, 0, 1))
        self.assertIsNone(parse_progress("[x11grab @ 0x0] Stream #0"))
        self.assertIsNone(parse_progress("Error opening input: frame=1"))
        self.assertIsNone(parse_progress(""))
        self.assertIsNone(parse_progress("frame="))
        self.assertEqual(parse_progress("  frame=3 dup=1\r"), FfmpegProgress(3, 1, 0))


class FormatStatsTests(unittest.TestCase):
    def test_format_stats(self) -> None:
        size = int(0.05 * 1048576)
        with_progress = RecordingStats(True, 83, 0, 0, size)
        self.assertEqual(
            format_stats(with_progress),
            "Real frames: 83 of 83. Duplicates: 0. Dropped: 0. File size: 0.05 MB.",
        )
        self.assertEqual(
            format_stats(RecordingStats(True, 10, 12, 2, size)),
            "Real frames: 0 of 10. Duplicates: 12. Dropped: 2. File size: 0.05 MB.",
        )
        self.assertEqual(format_stats(RecordingStats(False, 0, 0, 0, size)), "Frames: unknown. File size: 0.05 MB.")
        self.assertEqual(mb_text(0), "0.00")
        self.assertEqual(mb_text(3 * 1048576), "3.00")

    def test_x11_stats(self) -> None:
        s = x11_stats(FfmpegProgress(42, 3, 2), 7)
        self.assertEqual(s, RecordingStats(True, 42, 3, 2, 7))
        s = x11_stats(None, 7)
        self.assertFalse(s.has_progress)
        self.assertEqual(s.file_bytes, 7)

    def test_wayland_stats_formula(self) -> None:
        pump = PumpCounters(received=50, superseded=5, ticks=40, fresh=30, repeats=10, late=4, skipped=6)
        s = wayland_stats(FfmpegProgress(38, 1, 2), pump, 1048576)
        self.assertEqual(s, RecordingStats(True, 38, 1 + 4, 2 + 6, 1048576))
        self.assertEqual(format_stats(s), "Real frames: 33 of 38. Duplicates: 5. Dropped: 8. File size: 1.00 MB.")
        s = wayland_stats(None, pump, 1048576)
        self.assertFalse(s.has_progress)
        self.assertEqual((s.frames, s.dup, s.drop), (40, 4, 6))
        self.assertTrue(format_stats(s).startswith("Frames: unknown."))


class SessionFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp(prefix="dr-ffproc-")

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def _write(self, name: str, data: bytes) -> str:
        path = os.path.join(self.folder, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_session_files_skip_old_and_empty(self) -> None:
        old = self._write("desktop_2026-01-01_00-00-00_000.mp4", b"old")
        before = snapshot(self.folder)
        self.assertEqual(before, {old})
        self._write("desktop_2026-11-14_10-00-00_000.mp4", b"")
        b = self._write("desktop_2026-11-14_10-20-30_456_001.mp4", b"12345")
        c = self._write("desktop_2026-11-14_10-20-30_456_000.mp4", b"123")
        self._write("other.mp4", b"x")
        self._write("desktop_x.mkv", b"x")
        os.mkdir(os.path.join(self.folder, "desktop_dir.mp4"))
        found = session_files(self.folder, before)
        self.assertEqual(found, [c, b])
        self.assertEqual(total_bytes(found), 8)
        self.assertEqual(total_bytes(found + [os.path.join(self.folder, "missing.mp4")]), 8)

    def test_missing_folder(self) -> None:
        missing = os.path.join(self.folder, "none")
        self.assertEqual(snapshot(missing), set())
        self.assertEqual(session_files(missing, set()), [])


class _ShortWriter:
    """Fake stdin: takes at most 3 bytes per call, and returns None once."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.calls = 0

    def write(self, chunk: memoryview) -> int | None:
        self.calls += 1
        if self.calls == 2:
            return None
        part = bytes(chunk[:3])
        self.data.extend(part)
        return len(part)


class WriteTests(unittest.TestCase):
    def test_write_loops_on_short_writes(self) -> None:
        payload = bytes(range(256)) * 3
        fake = _ShortWriter()
        write_all(fake, payload)
        self.assertEqual(bytes(fake.data), payload)

        proc = FfmpegProcess(["ffmpeg"])
        fake = _ShortWriter()
        proc._stdin = fake
        proc.write(payload)
        proc.write(b"q")
        self.assertEqual(bytes(fake.data), payload + b"q")

    def test_write_before_start_raises(self) -> None:
        proc = FfmpegProcess(["ffmpeg"])
        with self.assertRaises(BrokenPipeError):
            proc.write(b"abc")
        # A stop before a start does nothing.
        proc.request_stop(10.0)
        self.assertTrue(proc.stopping)
        self.assertFalse(proc.is_running())
        self.assertIsNone(proc.progress())
        self.assertEqual(proc.error_text(), "")
        self.assertEqual(proc.first_error_line(), "")

    def test_spawn_off_main_thread_raises(self) -> None:
        box: dict[str, BaseException] = {}

        def run() -> None:
            try:
                popen_with_pdeathsig([sys.executable, "-c", "pass"])
            except BaseException as exc:  # noqa: BLE001
                box["exc"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(10)
        self.assertIsInstance(box.get("exc"), RuntimeError)
        self.assertIn("main thread", str(box["exc"]))


class FfmpegProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        linux_skip.need_linux()
        self.folder = tempfile.mkdtemp(prefix="dr-ffproc-")
        self.out = os.path.join(self.folder, "desktop_test.mp4")
        self.exits: list[tuple[int, str]] = []
        self.exited = threading.Event()

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def _on_exit(self, code: int, text: str) -> None:
        self.exits.append((code, text))
        self.exited.set()

    def test_ffmpeg_process_stats_via_fake(self) -> None:
        proc = FfmpegProcess([sys.executable, FAKE_STATS, self.out], on_exit=self._on_exit)
        self.assertIsNone(proc.start())
        self.assertIsNotNone(proc.pid)
        self.assertGreater(proc.started_at, 0.0)
        proc.request_stop(10.0)
        self.assertTrue(proc.stopping)
        self.assertTrue(self.exited.wait(10))
        self.assertEqual(proc.progress(), FfmpegProgress(42, 3, 2))
        self.assertEqual(proc.error_text(), "real warning line")
        self.assertNotIn("frame=", proc.error_text())
        self.assertEqual(proc.first_error_line(), "real warning line")
        self.assertEqual(self.exits[0][0], 0)
        self.assertFalse(proc.is_running())
        self.assertTrue(os.path.isfile(self.out))

    def test_failure_calls_on_exit(self) -> None:
        proc = FfmpegProcess([sys.executable, FAKE_STATS, "--fail", self.out], on_exit=self._on_exit)
        self.assertIsNone(proc.start())
        self.assertTrue(self.exited.wait(10))
        code, text = self.exits[0]
        self.assertEqual(code, 1)
        self.assertIn("boom: capture failed", text)
        self.assertNotIn("frame=", text)
        self.assertEqual(proc.progress(), FfmpegProgress(10, 1, 0))
        self.assertEqual(proc.first_error_line(), "real warning line")
        proc.request_stop(10.0)
        self.assertFalse(proc.is_running())

    def test_start_error_text(self) -> None:
        missing = os.path.join(self.folder, "no-such-ffmpeg")
        proc = FfmpegProcess([missing, "-version"])
        error = proc.start()
        self.assertIsNotNone(error)
        self.assertTrue(error.startswith("Cannot start ffmpeg: "))
        self.assertFalse(proc.is_running())


if __name__ == "__main__":
    unittest.main()
