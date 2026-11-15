"""GStreamer pump to real FFmpeg, without a portal (DESIGN.md 14.3).

Needs Linux, gi Gst 1.0, ffmpeg and ffprobe. No display is needed.
The source is videotestsrc in place of pipewiresrc.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

try:
    import linux_skip  # noqa: E402
except ImportError:  # tests/linux_skip.py (owner C8) is not there yet: same rule, local copy.
    import importlib
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

    def _need_gi(namespace: str, version: str):
        try:
            import gi

            gi.require_version(namespace, version)
            return importlib.import_module("gi.repository." + namespace)
        except Exception as exc:  # noqa: BLE001
            _need(False, f"gi {namespace} {version} ({exc})")

    linux_skip.need = _need
    linux_skip.need_linux = _need_linux
    linux_skip.need_program = _need_program
    linux_skip.need_gi = _need_gi

from desktop_recorder.ffmpeg_cmd import plan_wayland, wayland_argv  # noqa: E402
from desktop_recorder.ffstats import session_files, snapshot  # noqa: E402
from desktop_recorder.geometry import Rect  # noqa: E402
from desktop_recorder.recording import FfmpegProcess  # noqa: E402
from desktop_recorder.settings import Settings  # noqa: E402
from desktop_recorder.wayland import GstStream  # noqa: E402
from desktop_recorder.wayland_pump import FramePump  # noqa: E402

FPS = 10.0
LIVE_SOURCE = "videotestsrc is-live=true pattern=smpte ! video/x-raw,width=640,height=480,framerate=30/1"
STILL_SOURCE = "videotestsrc num-buffers=1 pattern=smpte ! video/x-raw,width=640,height=480,framerate=30/1"
CROP = Rect(10, 10, 320, 240)


class GstPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        linux_skip.need_linux()
        cls.Gst = linux_skip.need_gi("Gst", "1.0")
        cls.GLib = linux_skip.need_gi("GLib", "2.0")
        cls.ffmpeg = linux_skip.need_program("ffmpeg")
        cls.ffprobe = linux_skip.need_program("ffprobe")
        cls.Gst.init(None)
        if cls.Gst.ElementFactory.find("videotestsrc") is None:
            linux_skip.need(False, "GStreamer videotestsrc (gstreamer1.0-plugins-base)")

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="dr-gst-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.errors: list[str] = []

    # ------------------------------------------------------------ helpers

    def spin(self, seconds: float) -> None:
        """Run the default GLib main context, so idle callbacks and bus messages run."""
        context = self.GLib.MainContext.default()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while context.iteration(False):
                pass
            time.sleep(0.01)

    def probe(self, path: str) -> tuple[int, int, int, float]:
        """Width, height, decoded frame count and duration (s) of the first video stream."""
        out = subprocess.run(
            [self.ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,nb_read_frames", "-of", "default=nw=1", path],
            capture_output=True, text=True, timeout=60,
        ).stdout
        values = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        width = int(values.get("width", "0"))
        height = int(values.get("height", "0"))
        frames = int(values.get("nb_read_frames", "0") or 0)
        return width, height, frames, self.duration(path)

    def duration(self, path: str) -> float:
        out = subprocess.run(
            [self.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        try:
            return float(out)
        except ValueError:
            pass
        # Fallback: the last packet time plus one frame.
        out = subprocess.run(
            [self.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        ).stdout
        times = [float(t) for t in out.split() if t.replace(".", "", 1).isdigit()]
        return (max(times) + 1.0 / FPS) if times else 0.0

    def record(self, source: str, mode: str, seconds: float = 3.0):
        """Record the crop of source for the given seconds. Return (path, counters, proc)."""
        settings = Settings(folder=self.tmp, fps=FPS, encoder="libx264", frame_rate_mode=mode,
                            split_minutes=0, show_pointer=False, record_audio=False)
        pump = FramePump(FPS)
        self.addCleanup(pump.stop)
        stream = GstStream(source, pump, self.errors.append)
        error = stream.start()
        self.assertIsNone(error, error)
        self.addCleanup(stream.stop)
        first = None
        end = time.monotonic() + 5
        while first is None and time.monotonic() < end:
            self.spin(0.05)
            first = pump.latest()
        self.assertIsNotNone(first, "no frame from GStreamer in 5 s")
        self.assertEqual((first.width, first.height), (640, 480))

        pump.set_crop(CROP)
        plan = plan_wayland(settings, CROP, nvenc_ok=False)
        self.assertEqual(plan.encoder, "libx264")
        before = snapshot(self.tmp)
        argv = wayland_argv(settings, plan, datetime.now(), None, self.ffmpeg)
        proc = FfmpegProcess(argv)
        start_error = proc.start()
        self.assertIsNone(start_error, start_error)
        pump.start(proc.write)
        self.spin(seconds)
        counters = pump.stop()
        proc.request_stop(FPS, use_q=False)
        stream.stop()
        self.assertIsNone(pump.error, pump.error)
        self.assertEqual(self.errors, [])
        files = session_files(self.tmp, before)
        self.assertEqual(len(files), 1, f"files: {files}; ffmpeg: {proc.error_text()}")
        return files[0], counters, proc

    # ------------------------------------------------------------ tests

    def test_pump_to_ffmpeg_fixed(self) -> None:
        path, counters, proc = self.record(LIVE_SOURCE, "fixed")
        width, height, frames, _duration = self.probe(path)
        self.assertEqual((width, height), (320, 240))
        self.assertGreaterEqual(frames, 27)
        self.assertEqual(counters.skipped, 0)
        self.assertGreater(counters.fresh, 0)
        self.assertIsNotNone(proc.progress(), "no FFmpeg stats line was parsed")

    def test_still_source_keeps_length(self) -> None:
        path, counters, _proc = self.record(STILL_SOURCE, "fixed")
        _w, _h, _frames, duration = self.probe(path)
        self.assertGreaterEqual(duration, 2.8)
        self.assertGreater(counters.repeats, 20)
        self.assertEqual(counters.fresh, 1)

    def test_still_source_changes_mode(self) -> None:
        path, _counters, _proc = self.record(STILL_SOURCE, "changes")
        _w, _h, frames, duration = self.probe(path)
        self.assertLessEqual(frames, 6)
        self.assertGreaterEqual(duration, 1.8)


if __name__ == "__main__":
    unittest.main()
