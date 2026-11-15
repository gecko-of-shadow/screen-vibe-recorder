"""Live X11 checks: the hotkey grab, the auto-repeat filter and the --smoke recording.

Run them on Xvfb (run-tests.sh and CI do this). They grab keys on the display.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))
sys.path.insert(0, str(ROOT / "tests"))

import linux_skip  # noqa: E402


class X11SessionTests(unittest.TestCase):
    display = ""

    @classmethod
    def setUpClass(cls) -> None:
        linux_skip.need_linux()
        cls.display = linux_skip.need_display()
        for program in ("ffmpeg", "ffprobe", "xdotool", "xset"):
            linux_skip.need_program(program)

    def _hotkey(self, modifiers: int, key: str, callback):
        from desktop_recorder.hotkey_x11 import X11Hotkey

        return X11Hotkey(self.display, modifiers, key, callback)

    def test_hotkey_grab(self) -> None:
        hits = threading.Event()
        grab = self._hotkey(2 | 4, "F12", hits.set)
        try:
            self.assertTrue(grab.start(), "X11 did not accept Ctrl+Shift+F12")
            subprocess.run(["xdotool", "key", "ctrl+shift+F12"], check=False)
            self.assertTrue(hits.wait(2), "hotkey was not delivered")
        finally:
            grab.stop()

    def test_hotkey_no_repeat(self) -> None:
        # Xvfb auto-repeat for XTEST keys is UNVERIFIED. This test can pass with no repeat.
        # tests/test_linux_hotkey_x11.py checks the filter rule itself.
        count = [0]
        lock = threading.Lock()
        first = threading.Event()

        def hit() -> None:
            with lock:
                count[0] += 1
            first.set()

        subprocess.run(["xset", "r", "on"], check=False)
        grab = self._hotkey(2 | 4, "F12", hit)
        try:
            self.assertTrue(grab.start(), "X11 did not accept Ctrl+Shift+F12")
            subprocess.run(["xdotool", "keydown", "ctrl+shift+F12"], check=False)
            time.sleep(1)
            subprocess.run(["xdotool", "keyup", "ctrl+shift+F12"], check=False)
            self.assertTrue(first.wait(2), "hotkey was not delivered")
            time.sleep(0.5)
            with lock:
                self.assertEqual(count[0], 1)
        finally:
            grab.stop()

    def test_smoke_recording(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "linux")
        done = subprocess.run(
            [sys.executable, "-m", "desktop_recorder", "--smoke", "1.2"],
            env=env, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
