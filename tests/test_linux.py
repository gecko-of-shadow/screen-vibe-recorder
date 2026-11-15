"""Linux rules that the new test_linux_*.py files do not cover: hotkey text, audio, sounds, clipboard, autostart, socket."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "linux"))
sys.path.insert(0, str(ROOT / "tests"))

import linux_skip  # noqa: E402
from desktop_recorder.audio import monitor_from_listing  # noqa: E402
from desktop_recorder.autostart import autostart_enabled, write_autostart  # noqa: E402
from desktop_recorder.clipboard import uri_list  # noqa: E402
from desktop_recorder.gnome_hotkey import PATH, update_gnome_shortcut  # noqa: E402
from desktop_recorder.hotkey import try_set  # noqa: E402
from desktop_recorder.single_instance import InstanceServer, send_command  # noqa: E402
from desktop_recorder.sounds import build_chime  # noqa: E402


class HotkeyTests(unittest.TestCase):
    def test_matches_windows_rules(self) -> None:
        self.assertEqual(try_set("Win+Shift+D", (0, "A")), (12, "D"))
        self.assertIsNone(try_set("Shift+A", (12, "D")))
        self.assertIsNone(try_set("Ctrl+Enter", (12, "D")))
        self.assertIsNone(try_set("Ctrl+13", (12, "D")))
        self.assertEqual(try_set("Ctrl+5", (12, "D")), (2, "5"))
        self.assertEqual(try_set("Shift+F1", (12, "D")), (4, "F1"))


class AudioTests(unittest.TestCase):
    def test_monitor_must_exist(self) -> None:
        listing = "10\talsa_output.pci.analog-stereo.monitor\tPipeWire\n"
        self.assertEqual(
            monitor_from_listing("alsa_output.pci.analog-stereo", listing),
            "alsa_output.pci.analog-stereo.monitor",
        )
        self.assertIsNone(monitor_from_listing("auto_null", listing))
        self.assertIsNone(monitor_from_listing("missing", listing))
        from desktop_recorder.audio import choose_monitor

        sinks = "35\tauto_null\tPipeWire\n41\tdr_speakers\tPipeWire\n"
        sources = "41\tdr_speakers.monitor\tPipeWire\n"
        self.assertEqual(choose_monitor("@DEFAULT_SINK@", sinks, sources), "dr_speakers.monitor")
        self.assertIsNone(choose_monitor("@DEFAULT_SINK@", "35\tauto_null\tPipeWire\n", "35\tauto_null.monitor\tPipeWire\n"))


class OtherTests(unittest.TestCase):
    def test_chime_and_autostart(self) -> None:
        wav = build_chime(660, 880)
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertIn(b"data", wav[:44])
        directory = tempfile.mkdtemp(prefix="dr-auto-")
        path = os.path.join(directory, "desktop-recorder.desktop")
        write_autostart("/usr/local/bin/desktop-recorder", True, path)
        self.assertTrue(autostart_enabled(path))
        write_autostart("/usr/local/bin/desktop-recorder", False, path)
        self.assertFalse(autostart_enabled(path))
        self.assertTrue(os.path.exists(path))

    def test_clipboard_uri_list(self) -> None:
        linux_skip.need_linux()  # POSIX paths
        text = uri_list(["/tmp/My Videos/desktop.mp4"])
        self.assertIn("file:///tmp/My%20Videos/desktop.mp4", text)

    def test_socket(self) -> None:
        linux_skip.need_af_unix()
        directory = tempfile.mkdtemp(prefix="dr-sock-")
        path = os.path.join(directory, "control.sock")
        seen = []

        def on_command(command: str) -> str:
            seen.append(command)
            return "STOPPED"

        server = InstanceServer(path, on_command)
        self.assertTrue(server.start())
        second = InstanceServer(path, on_command)
        self.assertFalse(second.start())
        self.assertEqual(send_command(path, "TOGGLE"), "STOPPED")
        self.assertEqual(seen, ["TOGGLE"])
        server.stop()
        # A stale socket is replaced.
        open(path, "w", encoding="utf-8").close()
        self.assertTrue(server.start())
        server.stop()

    def test_gnome_shortcut(self) -> None:
        class Result:
            def __init__(self, stdout: str, returncode: int = 0) -> None:
                self.stdout = stdout
                self.returncode = returncode

        calls = []

        def runner(args):
            calls.append(args)
            if args[1] == "get":
                return Result("@as []")
            return Result("")

        self.assertTrue(update_gnome_shortcut(12, "D", "/usr/bin/desktop-recorder --toggle", runner))
        flat = [" ".join(item) for item in calls]
        self.assertTrue(any(PATH in item and "custom-keybindings" in item for item in flat))
        self.assertTrue(any("<Super><Shift>d" in item for item in flat))
        self.assertTrue(any("/usr/bin/desktop-recorder --toggle" in item for item in flat))


if __name__ == "__main__":
    unittest.main()
