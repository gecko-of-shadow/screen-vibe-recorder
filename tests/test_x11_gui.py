"""Xvfb GUI and integration tests for the X11 path (DESIGN.md 14.2).

These tests start the real app (python3 -m desktop_recorder) on an X display. They
drive it with xdotool and the --toggle command, and check the MP4 files with ffprobe.
Run them only in their own Xvfb (run-tests.sh and CI do this). They move the pointer
and grab the keyboard.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))

import linux_skip  # noqa: E402
from framecheck import (  # noqa: E402
    PLAN_RE,
    STATS_RE,
    count_frames,
    count_near,
    frame_rgb,
    near,
    pixel,
    probe_duration,
    probe_size,
    screen_rgb,
)

READY = "Desktop Recorder: ready"
SELECTOR_OPEN = "Desktop Recorder: selector open"
BORDER = (255, 64, 64)
GREEN = (0, 200, 0)
ACCENT = (64, 158, 255)
EDGE_NOTE = "The region touches the screen edge, so the red frame is not drawn on that side."


class LineLog:
    """Read the stderr of a process on a thread. Keep each line with its arrival time."""

    def __init__(self, stream, log_path: str | None) -> None:
        self.lines: list[tuple[float, str]] = []
        self._cond = threading.Condition()
        self._log = open(log_path, "a", encoding="utf-8") if log_path else None
        self._thread = threading.Thread(target=self._read, args=(stream,), daemon=True)
        self._thread.start()

    def _read(self, stream) -> None:
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            with self._cond:
                self.lines.append((time.monotonic(), line))
                self._cond.notify_all()
            if self._log:
                self._log.write(line + "\n")
                self._log.flush()
        with self._cond:
            self._cond.notify_all()

    def mark(self) -> int:
        with self._cond:
            return len(self.lines)

    def wait_for(self, pattern: str, timeout: float, since: int = 0) -> tuple[re.Match, float] | None:
        """Wait for a line (index >= since) that matches the regex. Return the match and its time."""
        regex = re.compile(pattern)
        end = time.monotonic() + timeout
        index = since
        with self._cond:
            while True:
                while index < len(self.lines):
                    stamp, line = self.lines[index]
                    index += 1
                    found = regex.search(line)
                    if found:
                        return found, stamp
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self._cond.wait(min(left, 0.2))

    def text(self) -> str:
        with self._cond:
            return "\n".join(line for _stamp, line in self.lines)

    def close(self) -> None:
        self._thread.join(5)
        if self._log:
            self._log.close()
            self._log = None


def _screen_size() -> tuple[int, int]:
    out = subprocess.run(["xdpyinfo"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
    found = re.search(r"dimensions:\s+(\d+)x(\d+) pixels", out)
    if not found:
        raise AssertionError("xdpyinfo gave no screen size")
    return int(found.group(1)), int(found.group(2))


def _xdotool(*args: str) -> None:
    subprocess.run(["xdotool", *args], check=True, timeout=20)


def _tree() -> str:
    return subprocess.run(["xwininfo", "-root", "-tree"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, timeout=20).stdout


def _alive(pid: int) -> bool:
    """True when the process exists and is not a zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            state = handle.read().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except OSError:
        return False


class X11GuiTests(unittest.TestCase):
    pattern: subprocess.Popen | None = None
    display = ""
    screen = (0, 0)
    artifacts: str | None = None

    @classmethod
    def setUpClass(cls) -> None:
        linux_skip.need_linux()
        cls.display = linux_skip.need_display()
        for program in ("ffmpeg", "ffprobe", "xdotool", "xwininfo", "xdpyinfo", "xset"):
            linux_skip.need_program(program)
        linux_skip.need_module("Xlib")
        linux_skip.need_gi("Gtk", "3.0")
        cls.screen = _screen_size()
        base = os.environ.get("RUNNER_TEMP")
        if base:
            cls.artifacts = os.path.join(base, "dr-tests")
            os.makedirs(cls.artifacts, exist_ok=True)
        cls.pattern = subprocess.Popen(
            [sys.executable, str(TESTS / "x11_pattern.py"), cls.display],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        line = cls.pattern.stdout.readline().decode("utf-8", "replace")
        if not line.startswith("pattern ready"):
            err = cls.pattern.stderr.read().decode("utf-8", "replace") if cls.pattern.poll() is not None else ""
            raise AssertionError("The pattern window did not start: " + line + err)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.pattern is not None:
            cls.pattern.terminate()
            try:
                cls.pattern.wait(5)
            except subprocess.TimeoutExpired:
                cls.pattern.kill()
                cls.pattern.wait(5)
            cls.pattern = None

    # ------------------------------------------------------------ set up one app

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="dr-gui-")
        self.out = os.path.join(self.tmp, "out")
        self.cfg = os.path.join(self.tmp, "cfg")
        run = os.path.join(self.tmp, "run")
        os.makedirs(self.out)
        os.makedirs(os.path.join(self.cfg, "DesktopRecorder"))
        os.makedirs(run, mode=0o700)
        os.chmod(run, 0o700)
        self.env = dict(os.environ)
        self.env.update({
            "XDG_CONFIG_HOME": self.cfg,
            "XDG_RUNTIME_DIR": run,
            "DESKTOP_RECORDER_TRAY": "status",
            "DESKTOP_RECORDER_NOTIFY": "stderr",
            "NO_AT_BRIDGE": "1",
            "PYTHONPATH": str(ROOT / "linux"),
            "DESKTOP_RECORDER_CAPTURE": "x11",
        })
        self.env.pop("WAYLAND_DISPLAY", None)
        self.env.pop("GDK_BACKEND", None)
        self.socket = os.path.join(run, "desktop-recorder", "control.sock")
        self.app: subprocess.Popen | None = None
        self.log: LineLog | None = None
        self.write_settings()

    def tearDown(self) -> None:
        self.end_app()
        try:
            _xdotool("mouseup", "1")
        except Exception:
            pass
        if self.artifacts:
            dest = os.path.join(self.artifacts, self.id().rsplit(".", 1)[-1])
            os.makedirs(dest, exist_ok=True)
            for path in glob.glob(os.path.join(self.out, "*.mp4")):
                shutil.copy2(path, dest)
            settings = os.path.join(self.cfg, "DesktopRecorder", "settings.txt")
            if os.path.exists(settings):
                shutil.copy2(settings, dest)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_settings(self, **overrides: str) -> None:
        values = {
            "folder": self.out,
            "fps": "10",
            "encoder": "libx264",
            "record_on_launch": "0",
            "copy_to_clipboard": "0",
            "play_sounds": "0",
            "record_audio": "0",
            "show_pointer": "0",
            "frame_rate_mode": "fixed",
        }
        values.update(overrides)
        path = os.path.join(self.cfg, "DesktopRecorder", "settings.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")

    def log_path(self) -> str | None:
        if not self.artifacts:
            return None
        return os.path.join(self.artifacts, self.id().rsplit(".", 1)[-1] + ".log")

    def start_app(self, *args: str, wait_ready: bool = True) -> None:
        self.app = subprocess.Popen(
            [sys.executable, "-m", "desktop_recorder", *args],
            env=self.env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        self.log = LineLog(self.app.stderr, self.log_path())
        if wait_ready:
            self.expect(READY, 10)

    def end_app(self) -> None:
        if self.app is None:
            return
        if self.app.poll() is None:
            self.app.send_signal(signal.SIGTERM)
            try:
                self.app.wait(20)
            except subprocess.TimeoutExpired:
                self.app.kill()
                self.app.wait(5)
        if self.log:
            self.log.close()
        self.app = None

    # ------------------------------------------------------------ helpers (R1)

    def expect(self, pattern: str, timeout: float, since: int = 0) -> re.Match:
        assert self.log is not None
        found = self.log.wait_for(pattern, timeout, since)
        if found is None:
            self.fail(f"No stderr line matched {pattern!r} in {timeout} s. Stderr:\n" + self.log.text())
        return found[0]

    def expect_timed(self, pattern: str, timeout: float, since: int = 0) -> tuple[re.Match, float]:
        assert self.log is not None
        found = self.log.wait_for(pattern, timeout, since)
        if found is None:
            self.fail(f"No stderr line matched {pattern!r} in {timeout} s. Stderr:\n" + self.log.text())
        return found

    def toggle(self) -> str:
        done = subprocess.run(
            [sys.executable, "-m", "desktop_recorder", "--toggle"],
            env=self.env, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30,
        )
        return done.stdout.strip()

    def status(self) -> str | None:
        sys.path.insert(0, str(ROOT / "linux"))
        from desktop_recorder.single_instance import send_command

        return send_command(self.socket, "STATUS")

    def mark(self) -> int:
        assert self.log is not None
        return self.log.mark()

    def wait_selector(self, since: int) -> None:
        self.expect(re.escape(SELECTOR_OPEN), 5, since)

    def open_selector(self) -> None:
        since = self.mark()
        self.assertEqual(self.toggle(), "SELECTING")
        self.wait_selector(since)

    def stop(self) -> re.Match:
        since = self.mark()
        self.assertIn(self.toggle(), ("STOPPING", "STOPPED"))
        return self.expect(STATS_RE, 15, since)

    def drag(self, x0: int, y0: int, x1: int, y1: int) -> None:
        _xdotool("mousemove", str(x0), str(y0), "mousedown", "1",
                 "mousemove", str(x1), str(y1), "mouseup", "1")

    def videos(self) -> list[str]:
        return sorted(glob.glob(os.path.join(self.out, "desktop_*.mp4")))

    def one_video(self) -> str:
        files = self.videos()
        self.assertEqual(len(files), 1, f"expected one MP4, got {files}")
        return files[0]

    def no_border_in(self, path: str, frames: list[int]) -> None:
        for index in frames:
            w, h, data = frame_rgb(path, index)
            self.assertEqual(count_near(w, h, data, BORDER), 0, f"border color in frame {index}")

    # ------------------------------------------------------------ tests

    def test_drag_records_region(self) -> None:
        self.start_app()
        self.open_selector()
        since = self.mark()
        self.drag(150, 150, 349, 299)
        time.sleep(3)
        sw, _sh, screen = screen_rgb(self.display)
        stats = self.stop()
        path = self.one_video()
        self.assertEqual(probe_size(path), (200, 150))
        n = count_frames(path)
        last = n - 1
        for index in (0, last):
            w, h, data = frame_rgb(path, index)
            self.assertTrue(near(pixel(w, data, 45, 45), GREEN), f"green block in frame {index}: {pixel(w, data, 45, 45)}")
        self.no_border_in(path, [0, last])
        self.assertTrue(near(pixel(sw, screen, 148, 200), BORDER), pixel(sw, screen, 148, 200))
        self.assertTrue(near(pixel(sw, screen, 350, 200), BORDER), pixel(sw, screen, 350, 200))
        real, frames = int(stats.group(1)), int(stats.group(2))
        self.assertEqual(frames, n)
        self.assertGreaterEqual(n, 25)
        self.assertGreaterEqual(real, 0.9 * n)
        self.expect(re.escape("Recording started (x11grab, libx264)."), 1, since)
        plan = self.expect(PLAN_RE, 1, since)
        self.assertEqual((plan.group(1), plan.group(2)), ("x11grab", "libx264"))

    def test_hotkey_opens_selector(self) -> None:
        self.start_app()
        since = self.mark()
        _xdotool("key", "super+shift+d")
        self.wait_selector(since)
        _xdotool("key", "Escape")
        time.sleep(1)
        self.assertEqual(self.status(), "STOPPED")

    def test_click_window_selects_it(self) -> None:
        self.start_app()
        self.open_selector()
        _xdotool("mousemove", "300", "250", "click", "1")
        time.sleep(2)
        self.stop()
        self.assertEqual(probe_size(self.one_video()), (400, 300))

    def test_space_whole_screen_changes_mode(self) -> None:
        self.write_settings(frame_rate_mode="changes")
        self.start_app()
        self.open_selector()
        since = self.mark()
        _xdotool("key", "space")
        _plan, plan_time = self.expect_timed(PLAN_RE, 10, since)
        time.sleep(4)
        tree = _tree()
        stop_time = time.monotonic()
        self.stop()
        width = stop_time - plan_time
        path = self.one_video()
        sw, sh = self.screen
        self.assertEqual(probe_size(path), (sw & ~1, sh & ~1))
        self.assertNotIn('"Recording frame"', tree)
        self.assertNotIn('"Stop recording"', tree)
        n = count_frames(path)
        self.assertGreaterEqual(n, 3)
        self.assertLessEqual(n, 12)
        # W starts at the plan line, before x11grab gives its first frame. mpdecimate can
        # cut up to 1 s at the end. Allow that cut plus up to 1.5 s for the FFmpeg start.
        self.assertGreaterEqual(probe_duration(path), width - 2.5)

    def test_escape_cancels(self) -> None:
        self.start_app()
        self.open_selector()
        _xdotool("key", "Escape")
        time.sleep(1)
        self.assertEqual(self.videos(), [])
        self.assertEqual(self.status(), "STOPPED")

    def test_selector_dim_and_magnifier(self) -> None:
        self.start_app()
        self.open_selector()
        _xdotool("mousemove", "800", "600")
        time.sleep(0.3)
        sw, _sh, screen = screen_rgb(self.display)
        _xdotool("key", "Escape")
        white = pixel(sw, screen, 300, 280)
        self.assertTrue(near(white, (135, 135, 135), 12), f"dimmed white block: {white}")
        for x in (830, 900):
            seen = pixel(sw, screen, x, 624)
            self.assertTrue(near(seen, ACCENT, 24), f"magnifier border at ({x},624): {seen}")

    def test_edge_region_omits_border(self) -> None:
        self.start_app()
        self.open_selector()
        since = self.mark()
        self.drag(0, 0, 199, 149)
        time.sleep(2)
        tree = _tree()
        self.stop()
        self.assertEqual(tree.count('"Recording frame"'), 2, tree)
        self.expect(re.escape(EDGE_NOTE), 1, since)
        path = self.one_video()
        self.no_border_in(path, [0, count_frames(path) - 1])
        stop_line = [line for line in tree.splitlines() if '"Stop recording"' in line]
        self.assertTrue(stop_line, tree)
        found = re.search(r"\d+x\d+\+(-?\d+)\+(-?\d+)\s+\+(-?\d+)\+(-?\d+)", stop_line[0])
        self.assertIsNotNone(found, stop_line[0])
        self.assertGreaterEqual(int(found.group(4)), 150, "the Stop button is not below the region")

    def test_stop_button_click(self) -> None:
        self.start_app()
        self.open_selector()
        self.drag(300, 200, 599, 399)
        time.sleep(2)
        info = subprocess.run(["xwininfo", "-name", "Stop recording"], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, timeout=20)
        self.assertEqual(info.returncode, 0, info.stderr)
        values = {}
        for key in ("Absolute upper-left X", "Absolute upper-left Y", "Width", "Height"):
            found = re.search(re.escape(key) + r":\s+(-?\d+)", info.stdout)
            self.assertIsNotNone(found, info.stdout)
            values[key] = int(found.group(1))
        cx = values["Absolute upper-left X"] + values["Width"] // 2
        cy = values["Absolute upper-left Y"] + values["Height"] // 2
        since = self.mark()
        _xdotool("mousemove", str(cx), str(cy), "click", "1")
        self.expect(STATS_RE, 15, since)
        time.sleep(0.5)
        self.assertNotIn('"Recording frame"', _tree())

    def test_kill_app_ends_ffmpeg(self) -> None:
        self.start_app()
        self.open_selector()
        self.drag(300, 200, 599, 399)
        time.sleep(3)
        found = subprocess.run(["pgrep", "-f", self.out], stdout=subprocess.PIPE, text=True)
        pids = [int(item) for item in found.stdout.split()]
        self.assertTrue(pids, "no FFmpeg process found")
        assert self.app is not None
        self.app.kill()
        self.app.wait(5)
        end = time.monotonic() + 3
        while time.monotonic() < end and any(_alive(pid) for pid in pids):
            time.sleep(0.1)
        self.assertFalse(any(_alive(pid) for pid in pids), "FFmpeg still runs after the app was killed")
        path = self.one_video()
        self.assertGreater(probe_duration(path), 0)

    def test_record_on_launch_saved_region(self) -> None:
        self.write_settings(record_on_launch="1", region="100,100,401,301")
        self.start_app(wait_ready=False)
        plan = self.expect(PLAN_RE, 10)
        self.assertEqual((plan.group(1), plan.group(2)), ("x11grab", "libx264"))
        self.expect(READY, 10)
        time.sleep(2)
        self.stop()
        self.assertEqual(probe_size(self.one_video()), (400, 300))
        assert self.log is not None
        self.assertNotIn("Recording started", self.log.text())

    def test_auto_encoder_falls_back_to_x264(self) -> None:
        self.write_settings(encoder="auto", record_on_launch="1", region="100,100,401,301")
        self.start_app(wait_ready=False)
        plan = self.expect(PLAN_RE, 30)
        self.assertEqual((plan.group(1), plan.group(2)), ("x11grab", "libx264"))
        self.expect(READY, 30)
        time.sleep(1)
        self.stop()

    def test_toggle_cli_replies(self) -> None:
        self.start_app()
        since = self.mark()
        self.assertEqual(self.toggle(), "SELECTING")
        self.wait_selector(since)
        _xdotool("key", "space")
        time.sleep(2)
        since = self.mark()
        self.assertIn(self.toggle(), ("STOPPING", "STOPPED"))
        self.expect(STATS_RE, 15, since)
        self.assertEqual(len(self.videos()), 1)

    def test_toggle_starts_tray_when_none(self) -> None:
        self.start_app("--toggle", wait_ready=False)
        self.expect(READY, 10)
        self.wait_selector(0)
        _xdotool("key", "Escape")
        time.sleep(1)
        named = subprocess.run(["xwininfo", "-name", "Desktop Recorder"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=20)
        self.assertNotEqual(named.returncode, 0, 'a window named "Desktop Recorder" exists')
        self.assertEqual(self.status(), "STOPPED")
        assert self.app is not None
        self.app.send_signal(signal.SIGTERM)
        self.app.wait(15)


if __name__ == "__main__":
    unittest.main()
