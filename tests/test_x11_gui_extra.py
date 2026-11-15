"""More Xvfb GUI tests for code that no test ran before (DESIGN.md 9.3, 12.1, 12.2).

- SettingsDialogTests: settings_dialog.SettingsDialog in a child process (Gtk on Xvfb).
- WaylandSelectorTests: the Wayland selector shell of selector_gtk.py with a synthetic
  frame, in a child process. The child uses the X11 GDK backend on Xvfb. There is no
  portal, no Mutter and no window manager, so the child sizes the window and gives it
  the keyboard focus itself (Mutter does this on a real Wayland session).
- X11SelectorArrowTests: arrow keys in the X11 selector, with the real app (like
  test_x11_gui.py).
- TrayMenuTests: the tray menu actions (ui.Tray) in a child process.

All GTK work runs in a child process ("--child <name>") with a watchdog. Dialog.run()
and the seat grab are nested loops, and a hang there must not stop the test run.
The child prints one line "RESULT <json>". The parent checks the values.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from pathlib import Path

THIS = Path(__file__).resolve()
ROOT = THIS.parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))

import linux_skip  # noqa: E402
import test_x11_gui as base  # noqa: E402  (module import: discover must not see X11GuiTests here)
from framecheck import PLAN_RE, STATS_RE, probe_size  # noqa: E402

CHILD_LIMIT_S = 90.0
RESULT_PREFIX = "RESULT "


# ================================================================ parent side


def _child_env(tmp: str, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    run = os.path.join(tmp, "run")
    cfg = os.path.join(tmp, "cfg")
    os.makedirs(run, mode=0o700, exist_ok=True)
    os.chmod(run, 0o700)
    os.makedirs(os.path.join(cfg, "DesktopRecorder"), exist_ok=True)
    env.update({
        "HOME": tmp,
        "XDG_CONFIG_HOME": cfg,
        "XDG_RUNTIME_DIR": run,
        "NO_AT_BRIDGE": "1",
        "PYTHONPATH": str(ROOT / "linux"),
        "DR_TEST_TMP": tmp,
    })
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("GDK_BACKEND", None)
    env.update(extra)
    return env


def _run_child(case: unittest.TestCase, name: str, env: dict[str, str],
               timeout: float = CHILD_LIMIT_S + 30) -> tuple[dict, str]:
    try:
        done = subprocess.run([sys.executable, str(THIS), "--child", name], env=env, cwd=str(ROOT),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        case.fail(f"child {name} did not end in {timeout} s. Stderr:\n{exc.stderr}")
    lines = [line for line in done.stdout.splitlines() if line.startswith(RESULT_PREFIX)]
    if not lines:
        case.fail(f"child {name} gave no result (exit {done.returncode}).\nStdout:\n{done.stdout}\n"
                  f"Stderr:\n{done.stderr}")
    result = json.loads(lines[-1][len(RESULT_PREFIX):])
    if "error" in result:
        case.fail(f"child {name} failed:\n{result['error']}\nStderr:\n{done.stderr}")
    return result, done.stderr


class _ChildCase(unittest.TestCase):
    """One temp folder for each test. Skip rules as in test_x11_gui.py (linux_skip)."""

    @classmethod
    def setUpClass(cls) -> None:
        linux_skip.need_linux()
        linux_skip.need_display()
        linux_skip.need_program("xdotool")
        linux_skip.need_module("Xlib")
        linux_skip.need_gi("Gtk", "3.0")
        linux_skip.need_module("cairo")

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="dr-extra-")

    def tearDown(self) -> None:
        try:
            subprocess.run(["xdotool", "mouseup", "1"], timeout=10, check=False)
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def child(self, name: str, **extra: str) -> tuple[dict, str]:
        return _run_child(self, name, _child_env(self.tmp, **extra))


# ---------------------------------------------------------------- a. Settings dialog


class SettingsDialogTests(_ChildCase):
    def test_fields_show_and_round_trip(self) -> None:
        from_messages = _messages()
        result, _err = self.child("settings_round_trip")
        start = result["initial"]
        self.assertEqual(start["title"], from_messages.SETTINGS_TITLE)
        self.assertEqual(start["fps"], 10.0)
        self.assertEqual(start["quality"], 1)
        self.assertEqual(start["split"], 30)
        self.assertEqual(start["mods"], [True, False, False, True])  # Win, Ctrl, Alt, Shift
        self.assertEqual(start["key"], "D")
        self.assertEqual([start["encoder"], start["chroma"], start["mode"]], [0, 0, 1])
        # login, record on launch, copy, sounds, hide pointer, audio
        self.assertEqual(start["checks"], [False, True, True, True, False, True])
        self.assertEqual(start["selector"], [False, True, True])
        self.assertIn(from_messages.CAPTURE_X11, start["labels"])
        self.assertTrue(start["no_wayland_frame"])

        got = result["saved"]
        self.assertEqual(got["folder"], os.path.join(self.tmp, "new out"))
        self.assertTrue(result["folder_made"])
        self.assertEqual(got["fps"], 4.5)
        self.assertEqual(got["quality"], 2)
        self.assertEqual(got["split_minutes"], 5)
        self.assertEqual(got["hotkey_modifiers"], 2 | 1)
        self.assertEqual(got["hotkey_key"], "F9")
        self.assertEqual(got["encoder"], "libx264")
        self.assertEqual(got["chroma"], "yuv444")
        self.assertEqual(got["frame_rate_mode"], "fixed")
        self.assertEqual([got["start_on_login"], got["record_on_launch"], got["copy_to_clipboard"],
                          got["play_sounds"], got["show_pointer"], got["record_audio"]],
                         [True, False, False, False, False, False])
        self.assertEqual([got["selector_crosshair"], got["selector_magnifier"], got["selector_position"]],
                         [True, False, False])
        # Save starts from a copy of the live values (12.2).
        self.assertEqual(got["region"], [10, 20, 300, 200])
        self.assertEqual(got["nvenc_cq"], 19)
        self.assertEqual(got["extra_lines"], ["future_key=1"])
        self.assertEqual(result["live_fps_after"], 10.0, "the dialog changed the live Settings object")
        self.assertEqual(result["warnings"], [])

    def test_wayland_backend_rows(self) -> None:
        msgs = _messages()
        result, _err = self.child("settings_wayland")
        self.assertIn(msgs.CAPTURE_WAYLAND, result["labels"])
        self.assertTrue(result["has_wayland_frame"])
        self.assertTrue(result["wayland_frame_start"])
        self.assertFalse(result["saved_wayland_frame"])

    def test_bad_hotkey_shows_text_and_loops(self) -> None:
        msgs = _messages()
        result, _err = self.child("settings_bad_hotkey")
        # No modifier, then Shift + a letter: both invalid (hotkey.is_valid). Then Shift+F5 is valid.
        self.assertEqual(result["warnings"], [msgs.HOTKEY_INVALID, msgs.HOTKEY_INVALID])
        self.assertEqual(result["saved"]["hotkey_modifiers"], 4)
        self.assertEqual(result["saved"]["hotkey_key"], "F5")

    def test_bad_folder_shows_text_and_loops(self) -> None:
        msgs = _messages()
        result, _err = self.child("settings_bad_folder")
        warnings = result["warnings"]
        self.assertEqual(len(warnings), 2, warnings)
        self.assertEqual(warnings[0], msgs.FOLDER_NOT_ABSOLUTE)
        self.assertTrue(warnings[1].startswith(msgs.FOLDER_CANNOT_CREATE), warnings[1])
        self.assertEqual(result["saved"]["folder"], os.path.join(self.tmp, "home out"))

    def test_bad_fps_is_clamped(self) -> None:
        # DESIGN.md 12.2 has no warning text for fps. The SpinButton range 0.2..60 clamps it.
        result, _err = self.child("settings_fps")
        self.assertEqual(result["after_zero"], 0.2)
        self.assertEqual(result["after_999"], 60.0)
        self.assertEqual(result["after_typed"], 0.2)
        self.assertEqual(result["saved"]["fps"], 0.2)
        self.assertEqual(result["warnings"], [])

    def test_cancel_and_exit_return_none(self) -> None:
        msgs = _messages()
        result, _err = self.child("settings_cancel_exit")
        self.assertIsNone(result["cancel"])
        self.assertIsNone(result["exit_in_warning"])
        self.assertEqual(result["exit_warnings"], [msgs.HOTKEY_INVALID])
        self.assertTrue(result["child_closed"])


# ---------------------------------------------------------------- b. Wayland selector shell


class WaylandSelectorTests(_ChildCase):
    def wl(self, name: str) -> dict:
        result, _err = self.child(name, DESKTOP_RECORDER_CAPTURE="wayland")
        self.assertTrue(result["sized"], f"the selector window did not get the size of the screen: {result}")
        self.assertIn("Esc", result["hint"] or "")
        return result

    def test_drag_same_size(self) -> None:
        r = self.wl("wl_drag_same")
        self.assertEqual(r["done"], [[0, [100, 100, 200, 150]]])
        self.assertEqual(r["left"], 0, "selector windows stay open after accept")

    def test_drag_scale_two(self) -> None:
        # The stream is 2x the window (a HiDPI monitor). A widget px is 2 stream px.
        r = self.wl("wl_drag_scale2")
        self.assertEqual(r["map"], [0.0, 0.0, float(r["screen"][0]), float(r["screen"][1])])
        # Widget (100,100) to (299,199) = stream (200,200) to (598,398), inclusive, then even.
        self.assertEqual(r["done"], [[0, [200, 200, 398, 198]]])

    def test_drag_letterbox(self) -> None:
        r = self.wl("wl_drag_letterbox")
        sw, sh = r["screen"]
        iw, ih = 1920, 1080
        s = min(sw / iw, sh / ih)
        dw, dh = iw * s, ih * s
        ox, oy = (sw - dw) / 2.0, (sh - dh) / 2.0
        for got, want in zip(r["map"], [ox, oy, dw, dh]):
            self.assertAlmostEqual(got, want, places=3)
        (x0, y0), (x1, y1) = r["points"]

        def to_image(p: float, o: float, d: float, size: int) -> int:
            return max(0, min(int(math.floor((p - o) * size / d)), size - 1))

        ax, ay = to_image(x0, ox, dw, iw), to_image(y0, oy, dh, ih)
        bx, by = to_image(x1, ox, dw, iw), to_image(y1, oy, dh, ih)
        w = (abs(bx - ax) + 1) & ~1
        h = (abs(by - ay) + 1) & ~1
        self.assertEqual(r["done"], [[0, [min(ax, bx), min(ay, by), w, h]]])

    def test_escape_cancels(self) -> None:
        r = self.wl("wl_escape")
        self.assertEqual(r["done"], [[None, None]])
        self.assertEqual(r["left"], 0)

    def test_right_click_cancels(self) -> None:
        # The cancel path when Esc does not reach the window (9.3, R3).
        r = self.wl("wl_right_click")
        self.assertEqual(r["done"], [[None, None]])
        self.assertEqual(r["left"], 0)

    def test_space_selects_whole_stream(self) -> None:
        r = self.wl("wl_space")
        self.assertEqual(r["done"], [[0, [0, 0, 1280, 720]]])

    def test_arrow_keys_move_model_cursor_only(self) -> None:
        r = self.wl("wl_arrows")
        x, y = r["start"]
        self.assertEqual(r["after_shift_down"], [x, y + 10])
        self.assertEqual(r["after_left"], [x - 1, y + 10])
        # Wayland apps cannot warp the pointer (9.3). The real pointer stays.
        self.assertEqual(r["pointer_after_keys"], r["pointer_before_keys"])
        # Drag 100,100 to 300,200, then Right, Right, Down, then Enter: corner at 302,201.
        self.assertEqual(r["done"], [[0, [100, 100, 202, 102]]])


# ---------------------------------------------------------------- c. X11 selector arrow keys


class X11SelectorArrowTests(base.X11GuiTests):
    """Uses the app, the pattern window and the helpers of test_x11_gui.py.

    load_tests (below) runs only the tests of this class, not the inherited ones.
    """

    def saved_region(self) -> tuple[int, ...] | None:
        path = os.path.join(self.cfg, "DesktopRecorder", "settings.txt")
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("region="):
                    return tuple(int(part) for part in line.strip().split("=", 1)[1].split(","))
        return None

    @staticmethod
    def pointer() -> tuple[int, int]:
        out = subprocess.run(["xdotool", "getmouselocation", "--shell"], stdout=subprocess.PIPE,
                             text=True, timeout=20, check=True).stdout
        values = dict(line.split("=", 1) for line in out.split() if "=" in line)
        return int(values["X"]), int(values["Y"]),

    def test_arrows_move_pointer_to_window_then_enter(self) -> None:
        # Pattern window: (100,100) 400x300. Start at (98,92), outside it. Only +2 px right and
        # +10 px down (Right, Right, Shift+Down) put the cursor inside. Enter accepts the hover
        # window (9.1). Without working arrow keys, Enter does nothing and no recording starts.
        self.start_app()
        base._xdotool("mousemove", "98", "92")
        self.open_selector()
        base._xdotool("key", "Right")
        base._xdotool("key", "Right")
        base._xdotool("key", "shift+Down")
        time.sleep(0.4)
        self.assertEqual(self.pointer(), (100, 102), "the selector did not warp the pointer")
        since = self.mark()
        base._xdotool("key", "Return")
        plan = self.expect(PLAN_RE, 10, since)
        self.assertEqual(plan.group(1), "x11grab")
        time.sleep(2)
        self.stop()
        self.assertEqual(self.saved_region(), (100, 100, 400, 300))
        self.assertEqual(probe_size(self.one_video()), (400, 300))

    def test_arrows_extend_drag_then_enter(self) -> None:
        # Drag 150,150 to 349,289 and hold the button. Right, Right, Down move the cursor to
        # 351,290. Enter accepts the selection: inclusive 202x141, made even: 202x140.
        # No Shift here: Shift+arrow during a drag applies the square rule (as on Windows).
        self.start_app()
        self.open_selector()
        base._xdotool("mousemove", "150", "150", "mousedown", "1", "mousemove", "349", "289")
        time.sleep(0.3)
        base._xdotool("key", "Right")
        base._xdotool("key", "Right")
        base._xdotool("key", "Down")
        time.sleep(0.4)
        self.assertEqual(self.pointer(), (351, 290), "the selector did not warp the pointer")
        since = self.mark()
        base._xdotool("key", "Return")
        base._xdotool("mouseup", "1")
        self.expect(PLAN_RE, 10, since)
        time.sleep(2)
        self.stop()
        self.assertEqual(self.saved_region(), (150, 150, 202, 140))
        self.assertEqual(probe_size(self.one_video()), (202, 140))


# ---------------------------------------------------------------- d. Tray menu


class TrayMenuTests(_ChildCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        for program in ("ffmpeg", "ffprobe"):
            linux_skip.need_program(program)

    def tray_env(self) -> dict[str, str]:
        out = os.path.join(self.tmp, "out")
        os.makedirs(out, exist_ok=True)
        env = _child_env(self.tmp, DESKTOP_RECORDER_TRAY="status", DESKTOP_RECORDER_NOTIFY="stderr",
                         DESKTOP_RECORDER_CAPTURE="x11", DR_TEST_OUT=out)
        values = {
            "folder": out,
            "fps": "10",
            "encoder": "libx264",
            "record_on_launch": "0",
            "copy_to_clipboard": "0",
            "play_sounds": "0",
            "record_audio": "0",
            "show_pointer": "0",
            "frame_rate_mode": "fixed",
        }
        path = os.path.join(env["XDG_CONFIG_HOME"], "DesktopRecorder", "settings.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        return env

    def test_menu_rows_and_exit(self) -> None:
        msgs = _messages()
        result, err = _run_child(self, "tray_menu", self.tray_env())
        self.assertIn(msgs.READY_LINE, err)
        labels = result["labels"]
        self.assertEqual(len(labels), 8, labels)
        self.assertEqual(labels[0], msgs.NOT_RECORDING)
        self.assertEqual(labels[2], "-")
        self.assertEqual(labels[3], msgs.MENU_SELECT + msgs.MENU_HOTKEY_GAP + "Win+Shift+D")
        self.assertEqual(labels[4:6], [msgs.MENU_OPEN_FOLDER, msgs.MENU_SETTINGS])
        self.assertEqual(labels[6:], ["-", msgs.MENU_EXIT])
        self.assertFalse(result["stats_visible"], "the stats row shows before the first stop")
        self.assertFalse(result["status_sensitive"])
        self.assertTrue(result["hotkey_active"])
        self.assertEqual(result["tooltip"], msgs.TOOLTIP_STOPPED)
        # Exit from the menu ends Gtk.main and releases the hotkey.
        self.assertTrue(result["main_ended"])
        self.assertTrue(result["quitting"])
        self.assertTrue(result["hotkey_none"])
        # libnotify path: no exception; the stderr line comes first (D28).
        self.assertIn(msgs.notify_line("Desktop Recorder", "extra-test body"), err)

    def test_toggle_item_records_and_stops(self) -> None:
        msgs = _messages()
        result, err = _run_child(self, "tray_toggle", self.tray_env())
        self.assertTrue(result["selector_opened"], err)
        self.assertTrue(result["recording"], err)
        self.assertTrue(result["toggle_recording"].startswith(msgs.MENU_STOP), result["toggle_recording"])
        self.assertEqual(result["status_recording"], msgs.recording_region("10", 200, 150))
        self.assertEqual(result["tooltip_recording"], msgs.TOOLTIP_RECORDING)
        self.assertTrue(result["stopped"], err)
        self.assertTrue(result["stats_visible"])
        self.assertTrue(result["stats"].startswith(msgs.LAST_RECORDING_PREFIX), result["stats"])
        self.assertRegex(result["stats"], STATS_RE)
        self.assertTrue(result["toggle_after"].startswith(msgs.MENU_SELECT), result["toggle_after"])
        files = sorted(Path(self.tmp, "out").glob("desktop_*.mp4"))
        self.assertEqual(len(files), 1, files)
        self.assertEqual(probe_size(str(files[0])), (200, 150))

    def test_settings_item_saves_and_new_hotkey_works(self) -> None:
        result, err = _run_child(self, "tray_settings", self.tray_env())
        self.assertTrue(result["icon_opened_dialog"], "StatusIcon activate did not open Settings")
        self.assertEqual(result["fps_after_cancel"], 10.0)
        self.assertTrue(result["item_opened_dialog"])
        self.assertEqual(result["live_fps"], 5.0)
        self.assertEqual(result["file_fps"], 5.0)
        self.assertEqual(result["file_hotkey"], [1 | 2, "F9"])
        self.assertTrue(result["hotkey_active"])
        self.assertTrue(result["toggle_label"].endswith("Ctrl+Alt+F9"), result["toggle_label"])
        self.assertTrue(result["new_hotkey_opened_selector"], err)
        self.assertEqual(result["state_after_escape"], "idle")
        self.assertEqual(result["messages"], [])

    def test_exit_while_settings_open(self) -> None:
        result, err = _run_child(self, "tray_exit_dialog", self.tray_env())
        self.assertTrue(result["dialog_seen"])
        self.assertTrue(result["main_ended"], err)
        self.assertTrue(result["quitting"])
        self.assertIsNone(result["dialog_after"])
        # Exit saves nothing (12.1): the fps typed in the open dialog is not in the file.
        self.assertEqual(result["file_fps"], 10.0)


def _messages():
    sys.path.insert(0, str(ROOT / "linux"))
    from desktop_recorder import messages

    return messages


def load_tests(loader: unittest.TestLoader, _tests, _pattern) -> unittest.TestSuite:
    """Only the tests that this file defines. X11SelectorArrowTests inherits 13 tests."""
    suite = unittest.TestSuite()
    for cls in (SettingsDialogTests, WaylandSelectorTests, X11SelectorArrowTests, TrayMenuTests):
        names = [name for name in loader.getTestCaseNames(cls) if name in cls.__dict__]
        suite.addTests(cls(name) for name in names)
    return suite


# ================================================================ child side


def _gtk():
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gdk, GLib, Gtk


def _pump(until=None, timeout: float = 5.0) -> bool:
    """Run GTK events. With `until`, stop when it is true (return True) or at the timeout."""
    _gdk, _glib, gtk = _gtk()
    end = time.monotonic() + timeout
    while True:
        while gtk.events_pending():
            gtk.main_iteration_do(False)
        if until is not None and until():
            return True
        if time.monotonic() >= end:
            return until is None
        time.sleep(0.01)


def _xdo(*args: str) -> str:
    """Run xdotool and keep GTK events flowing while it runs."""
    proc = subprocess.Popen(["xdotool", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    while proc.poll() is None:
        _pump(timeout=0.02)
    out, err = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"xdotool {args} failed: {err.decode('utf-8', 'replace')}")
    _pump(timeout=0.3)
    return out.decode("utf-8", "replace")


def _pointer() -> list[int]:
    values = dict(line.split("=", 1) for line in _xdo("getmouselocation", "--shell").split() if "=" in line)
    return [int(values["X"]), int(values["Y"])]


def _settings_dict(s) -> dict | None:
    if s is None:
        return None
    return {
        "folder": s.folder, "fps": s.fps, "quality": s.quality, "split_minutes": s.split_minutes,
        "hotkey_modifiers": s.hotkey_modifiers, "hotkey_key": s.hotkey_key, "encoder": s.encoder,
        "chroma": s.chroma, "frame_rate_mode": s.frame_rate_mode, "start_on_login": s.start_on_login,
        "record_on_launch": s.record_on_launch, "copy_to_clipboard": s.copy_to_clipboard,
        "play_sounds": s.play_sounds, "show_pointer": s.show_pointer, "record_audio": s.record_audio,
        "selector_crosshair": s.selector_crosshair, "selector_magnifier": s.selector_magnifier,
        "selector_position": s.selector_position, "region": [s.region.x, s.region.y, s.region.w, s.region.h],
        "nvenc_cq": s.nvenc_cq, "extra_lines": list(s.extra_lines), "wayland_frame": s.wayland_frame,
    }


class _Script:
    """Drives a dialog from a GLib timer, while its run() loop is active.

    get_dialog gives the Settings dialog (or None). get_children give open modal children
    (warnings, tray messages). Each child: record its text, then on_child(child) or OK.
    Each action runs once, when the dialog shows and no child is open.
    """

    def __init__(self, get_dialog, actions, get_children=(), on_child=None) -> None:
        _gdk, glib, _gtk_mod = _gtk()
        self.get_dialog = get_dialog
        self.actions = list(actions)
        self.get_children = list(get_children)
        self.on_child = on_child
        self.texts: list[str] = []
        self.seen_dialog = False
        self._seen: list = []  # the objects, not id(): a new dialog can reuse an old id
        self._done = False
        self.source = glib.timeout_add(60, self._tick)

    def _tick(self) -> bool:
        _gdk, _glib, gtk = _gtk()
        if self._done:
            return False
        for getter in self.get_children:
            child = getter()
            if child is None or any(child is old for old in self._seen):
                continue
            self._seen.append(child)
            text = child.get_property("text") if isinstance(child, gtk.MessageDialog) else type(child).__name__
            self.texts.append(text)
            if self.on_child is not None:
                self.on_child(child)
            else:
                child.response(gtk.ResponseType.OK)
            return True
        dialog = self.get_dialog()
        if dialog is not None and dialog.get_visible():
            self.seen_dialog = True
            if self.actions:
                self.actions.pop(0)()
        return True

    def stop(self) -> None:
        _gdk, glib, _gtk_mod = _gtk()
        self._done = True
        try:
            glib.source_remove(self.source)
        except Exception:
            pass


# ---------------------------------------------------------------- child: Settings dialog


def _labels(widget) -> list[str]:
    _gdk, _glib, gtk = _gtk()
    found: list[str] = []

    def walk(w) -> None:
        if isinstance(w, gtk.Label):
            found.append(w.get_text())
        if isinstance(w, gtk.Container):
            w.forall(walk)

    walk(widget)
    return found


def _set_key(dialog, name: str) -> None:
    for index, row in enumerate(dialog.key.get_model()):
        if row[0] == name:
            dialog.key.set_active(index)
            return
    raise AssertionError(f"key {name} is not in the list")


def _set_mods(dialog, win: bool, ctrl: bool, alt: bool, shift: bool) -> None:
    dialog.win.set_active(win)
    dialog.ctrl.set_active(ctrl)
    dialog.alt.set_active(alt)
    dialog.shift.set_active(shift)


def _base_settings(tmp: str):
    from desktop_recorder.geometry import Rect
    from desktop_recorder.settings import Settings

    s = Settings(folder=os.path.join(tmp, "start"))
    s.fps = 10.0
    s.quality = 1
    s.split_minutes = 30
    s.hotkey_modifiers = 8 | 4
    s.hotkey_key = "D"
    s.encoder = "auto"
    s.chroma = "yuv420"
    s.frame_rate_mode = "changes"
    s.start_on_login = False
    s.record_on_launch = True
    s.copy_to_clipboard = True
    s.play_sounds = True
    s.show_pointer = True
    s.record_audio = True
    s.selector_crosshair = False
    s.selector_magnifier = True
    s.selector_position = True
    s.region = Rect(10, 20, 300, 200)
    s.nvenc_cq = 19
    s.extra_lines = ["future_key=1"]
    return s


def _run_dialog(dialog, actions, on_child=None) -> tuple[object, _Script]:
    script = _Script(lambda: dialog, actions, [lambda: dialog._child], on_child)
    try:
        result = dialog.run_until_valid()
    finally:
        script.stop()
    return result, script


def _child_settings_round_trip() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    tmp = os.environ["DR_TEST_TMP"]
    live = _base_settings(tmp)
    dialog = SettingsDialog(live, "x11")
    initial = {
        "title": dialog.get_title(),
        "fps": dialog.fps.get_value(),
        "quality": dialog.quality.get_active(),
        "split": int(dialog.split.get_value()),
        "mods": [dialog.win.get_active(), dialog.ctrl.get_active(), dialog.alt.get_active(),
                 dialog.shift.get_active()],
        "key": dialog.key.get_active_text(),
        "encoder": dialog.encoder.get_active(),
        "chroma": dialog.chroma.get_active(),
        "mode": dialog.mode.get_active(),
        "checks": [dialog.startup.get_active(), dialog.record.get_active(), dialog.copy.get_active(),
                   dialog.sound.get_active(), dialog.hide_pointer.get_active(), dialog.audio.get_active()],
        "selector": [dialog.crosshair.get_active(), dialog.magnifier.get_active(), dialog.position.get_active()],
        "labels": _labels(dialog),
        "no_wayland_frame": dialog.wayland_frame is None,
    }
    new_folder = os.path.join(tmp, "new out")

    def edit() -> None:
        dialog.folder.set_text(f'  "{new_folder}/"  ')
        dialog.fps.set_value(4.5)
        dialog.quality.set_active(2)
        dialog.split.set_value(5)
        _set_mods(dialog, False, True, True, False)
        _set_key(dialog, "F9")
        dialog.encoder.set_active(2)
        dialog.chroma.set_active(1)
        dialog.mode.set_active(0)
        dialog.startup.set_active(True)
        dialog.record.set_active(False)
        dialog.copy.set_active(False)
        dialog.sound.set_active(False)
        dialog.hide_pointer.set_active(True)
        dialog.audio.set_active(False)
        dialog.crosshair.set_active(True)
        dialog.magnifier.set_active(False)
        dialog.position.set_active(False)
        dialog.response(gtk.ResponseType.OK)

    result, script = _run_dialog(dialog, [edit])
    dialog.destroy()
    return {"initial": initial, "saved": _settings_dict(result), "warnings": script.texts,
            "folder_made": os.path.isdir(new_folder), "live_fps_after": live.fps}


def _child_settings_wayland() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    live = _base_settings(os.environ["DR_TEST_TMP"])
    live.wayland_frame = True
    dialog = SettingsDialog(live, "wayland")
    out = {"labels": _labels(dialog), "has_wayland_frame": dialog.wayland_frame is not None}
    out["wayland_frame_start"] = bool(dialog.wayland_frame and dialog.wayland_frame.get_active())

    def edit() -> None:
        if dialog.wayland_frame is not None:
            dialog.wayland_frame.set_active(False)
        dialog.response(gtk.ResponseType.OK)

    result, _script = _run_dialog(dialog, [edit])
    dialog.destroy()
    out["saved_wayland_frame"] = None if result is None else result.wayland_frame
    return out


def _child_settings_bad_hotkey() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    dialog = SettingsDialog(_base_settings(os.environ["DR_TEST_TMP"]), "x11")

    def no_modifier() -> None:
        _set_mods(dialog, False, False, False, False)
        _set_key(dialog, "A")
        dialog.response(gtk.ResponseType.OK)

    def shift_letter() -> None:
        _set_mods(dialog, False, False, False, True)
        _set_key(dialog, "A")
        dialog.response(gtk.ResponseType.OK)

    def shift_f5() -> None:
        _set_key(dialog, "F5")
        dialog.response(gtk.ResponseType.OK)

    result, script = _run_dialog(dialog, [no_modifier, shift_letter, shift_f5])
    dialog.destroy()
    return {"warnings": script.texts, "saved": _settings_dict(result)}


def _child_settings_bad_folder() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    tmp = os.environ["DR_TEST_TMP"]
    blocker = os.path.join(tmp, "a file")
    with open(blocker, "w", encoding="utf-8") as handle:
        handle.write("x")
    dialog = SettingsDialog(_base_settings(tmp), "x11")

    def relative() -> None:
        dialog.folder.set_text("Recordings")
        dialog.response(gtk.ResponseType.OK)

    def under_file() -> None:
        dialog.folder.set_text(os.path.join(blocker, "sub"))
        dialog.response(gtk.ResponseType.OK)

    def home() -> None:
        dialog.folder.set_text("~/home out")  # HOME is the temp folder
        dialog.response(gtk.ResponseType.OK)

    result, script = _run_dialog(dialog, [relative, under_file, home])
    dialog.destroy()
    return {"warnings": script.texts, "saved": _settings_dict(result)}


def _child_settings_fps() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    dialog = SettingsDialog(_base_settings(os.environ["DR_TEST_TMP"]), "x11")
    out: dict = {}
    dialog.fps.set_value(0)
    out["after_zero"] = round(dialog.fps.get_value(), 3)
    dialog.fps.set_value(999)
    out["after_999"] = round(dialog.fps.get_value(), 3)
    dialog.fps.set_text("0.05")
    dialog.fps.update()
    out["after_typed"] = round(dialog.fps.get_value(), 3)

    def save() -> None:
        dialog.response(gtk.ResponseType.OK)

    result, script = _run_dialog(dialog, [save])
    dialog.destroy()
    saved = _settings_dict(result)
    if saved is not None:
        saved["fps"] = round(saved["fps"], 3)
    out.update({"saved": saved, "warnings": script.texts})
    return out


def _child_settings_cancel_exit() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder.settings_dialog import SettingsDialog

    tmp = os.environ["DR_TEST_TMP"]
    dialog = SettingsDialog(_base_settings(tmp), "x11")
    result, _script = _run_dialog(dialog, [lambda: dialog.response(gtk.ResponseType.CANCEL)])
    dialog.destroy()
    out: dict = {"cancel": _settings_dict(result)}

    # Exit while the hotkey warning is open: close_for_exit ends both nested loops.
    dialog = SettingsDialog(_base_settings(tmp), "x11")

    def bad() -> None:
        _set_mods(dialog, False, False, False, False)
        dialog.response(gtk.ResponseType.OK)

    result, script = _run_dialog(dialog, [bad], on_child=lambda _child: dialog.close_for_exit())
    out["exit_in_warning"] = _settings_dict(result)
    out["exit_warnings"] = script.texts
    out["child_closed"] = dialog._child is None
    dialog.destroy()
    return out


# ---------------------------------------------------------------- child: Wayland selector


class _FakeFrame:
    """A wayland_pump.Frame with one BGRx color."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.stride = width * 4
        self.seq = 1
        self.data = bytes((0x90, 0x60, 0x30, 0x00)) * (width * height)

    def crop(self, rect) -> bytes:
        from desktop_recorder.wayland_pump import crop_rows

        return crop_rows(self.data, self.stride, rect)


def _wl_open(image_w: int | None = None, image_h: int | None = None) -> dict:
    """Open the Wayland shell for one stream. Size the window to the monitor and focus it."""
    gdk, _glib, _gtk_mod = _gtk()
    from desktop_recorder import selector_gtk
    from desktop_recorder.portal import PortalStreamInfo
    from desktop_recorder.settings import Settings

    geom = gdk.Display.get_default().get_monitor(0).get_geometry()
    sw, sh = int(geom.width), int(geom.height)
    iw, ih = image_w or sw, image_h or sh
    info = PortalStreamInfo(node_id=7, position=(int(geom.x), int(geom.y)), size=(sw, sh), source_type=1)
    done: list = []

    def on_done(index, rect, _options) -> None:
        done.append([index, None if rect is None else [rect.x, rect.y, rect.w, rect.h]])

    settings = Settings(folder=os.path.join(os.environ["DR_TEST_TMP"], "out"))
    error = selector_gtk.open_wayland_selector([(info, _FakeFrame(iw, ih))], settings, "", on_done)
    if error is not None:
        raise AssertionError("open_wayland_selector failed: " + error)
    shells = [item for item in selector_gtk._active if isinstance(item, selector_gtk._WaylandSelector)]
    if len(shells) != 1 or len(shells[0].windows) != 1:
        raise AssertionError(f"expected one shell with one window, got {shells}")
    shell = shells[0]
    win = shell.windows[0]
    view = win.get_child()
    # No window manager on Xvfb: fullscreen_on_monitor can do nothing. Place the window here.
    win.move(int(geom.x), int(geom.y))
    win.resize(sw, sh)

    def ready() -> bool:
        gw = win.get_window()
        alloc = view.get_allocation()
        return gw is not None and gw.is_viewable() and (alloc.width, alloc.height) == (sw, sh)

    sized = _pump(ready, 5)
    gw = win.get_window()
    if not sized and gw is not None:
        # GTK can ignore resize() for a window in the fullscreen state. Do what a window
        # manager does: place the GdkWindow on the monitor.
        gw.move_resize(int(geom.x), int(geom.y), sw, sh)
        sized = _pump(ready, 5)
    if gw is not None:
        gw.focus(gdk.CURRENT_TIME)  # Mutter gives the focus on a real session (9.3, UNVERIFIED there)
    _pump(timeout=0.5)
    origin = gw.get_origin() if gw is not None else (0, 0)
    origin = list(origin)[-2:]
    m = view.draw_map()
    return {"shell": shell, "win": win, "view": view, "done": done, "sw": sw, "sh": sh, "origin": origin,
            "out": {"sized": sized, "screen": [sw, sh], "origin": origin, "hint": view.hint,
                    "map": [m.ox, m.oy, m.dw, m.dh]}}


def _wl_finish(state: dict) -> dict:
    from desktop_recorder import selector_gtk

    _pump(lambda: bool(state["done"]), 3)
    _pump(timeout=0.3)
    out = state["out"]
    out["done"] = [list(item) for item in state["done"]]  # a copy: the cleanup below can add to it
    out["left"] = len(state["shell"].windows)
    out["still_active"] = state["shell"] in selector_gtk._active
    if not state["done"]:
        state["shell"]._finish(None, None)
    return out


def _drag(state: dict, x0: int, y0: int, x1: int, y1: int) -> None:
    ox, oy = state["origin"]
    _xdo("mousemove", str(ox + x0), str(oy + y0), "mousedown", "1",
         "mousemove", str(ox + x1), str(oy + y1), "mouseup", "1")


def _child_wl_drag_same() -> dict:
    state = _wl_open()
    _drag(state, 100, 100, 299, 249)
    return _wl_finish(state)


def _child_wl_drag_scale2() -> dict:
    gdk, _glib, _gtk_mod = _gtk()
    geom = gdk.Display.get_default().get_monitor(0).get_geometry()
    state = _wl_open(int(geom.width) * 2, int(geom.height) * 2)
    _drag(state, 100, 100, 299, 199)
    return _wl_finish(state)


def _child_wl_drag_letterbox() -> dict:
    state = _wl_open(1920, 1080)
    ox, oy = state["out"]["map"][0], state["out"]["map"][1]
    p0 = (int(round(ox)) + 100, int(round(oy)) + 100)
    p1 = (int(round(ox)) + 301, int(round(oy)) + 301)
    _drag(state, p0[0], p0[1], p1[0], p1[1])
    out = _wl_finish(state)
    out["points"] = [list(p0), list(p1)]
    return out


def _child_wl_escape() -> dict:
    state = _wl_open()
    ox, oy = state["origin"]
    _xdo("mousemove", str(ox + 400), str(oy + 300))
    _xdo("key", "Escape")
    return _wl_finish(state)


def _child_wl_right_click() -> dict:
    state = _wl_open()
    ox, oy = state["origin"]
    _xdo("mousemove", str(ox + 400), str(oy + 300), "click", "3")
    return _wl_finish(state)


def _child_wl_space() -> dict:
    state = _wl_open(1280, 720)
    ox, oy = state["origin"]
    _xdo("mousemove", str(ox + 400), str(oy + 300))
    _xdo("key", "space")
    return _wl_finish(state)


def _child_wl_arrows() -> dict:
    state = _wl_open()
    view = state["view"]
    ox, oy = state["origin"]
    _xdo("mousemove", str(ox + 500), str(oy + 300))
    _pump(lambda: tuple(view.model.cursor) == (500, 300), 2)
    out_extra: dict = {"start": list(view.model.cursor)}
    out_extra["pointer_before_keys"] = _pointer()
    _xdo("key", "shift+Down")
    out_extra["after_shift_down"] = list(view.model.cursor)
    _xdo("key", "Left")
    out_extra["after_left"] = list(view.model.cursor)
    out_extra["pointer_after_keys"] = _pointer()
    _xdo("mousemove", str(ox + 100), str(oy + 100), "mousedown", "1", "mousemove", str(ox + 300), str(oy + 200))
    _xdo("key", "Right")
    _xdo("key", "Right")
    _xdo("key", "Down")
    _xdo("key", "Return")
    _xdo("mouseup", "1")
    out = _wl_finish(state)
    out.update(out_extra)
    return out


# ---------------------------------------------------------------- child: tray


def _tray():
    from desktop_recorder import ui

    tray = ui.Tray()
    if not tray.owned:
        raise AssertionError("the tray did not get the control socket")
    tray.begin(False, "")
    return tray


def _menu_items(tray) -> list:
    return list(tray.menu.get_children())


def _label_of(item) -> str:
    _gdk, _glib, gtk = _gtk()
    if isinstance(item, gtk.SeparatorMenuItem):
        return "-"
    return item.get_label() or ""


def _item(tray, text: str):
    for item in _menu_items(tray):
        if _label_of(item) == text:
            return item
    raise AssertionError(f"no menu item {text!r}")


def _run_main(start, limit: float = 30.0) -> bool:
    """Run Gtk.main, call start() from idle. True when main ended before the limit."""
    _gdk, glib, gtk = _gtk()
    timed_out = [False]

    def stop() -> bool:
        timed_out[0] = True
        gtk.main_quit()
        return False

    guard = glib.timeout_add(int(limit * 1000), stop)

    def first() -> bool:
        start()
        return False

    glib.idle_add(first)
    gtk.main()
    if not timed_out[0]:
        glib.source_remove(guard)
    return not timed_out[0]


def _shutdown(tray) -> bool:
    if tray._quitting:
        return True
    return _run_main(tray.quit, 30)


def _x11_selector_open() -> bool:
    from desktop_recorder import selector_gtk

    return any(isinstance(item, selector_gtk._X11Selector) for item in selector_gtk._active)


def _child_tray_menu() -> dict:
    from desktop_recorder import messages

    tray = _tray()
    items = _menu_items(tray)
    out = {
        "labels": [_label_of(item) for item in items],
        "stats_visible": tray.stats_item.get_visible(),
        "status_sensitive": tray.status_item.get_sensitive(),
        "hotkey_active": tray.hotkey_active,
        "tooltip": tray._icon.get_tooltip_text() if tray._icon is not None else None,
    }
    # The libnotify path (D28). The stderr line comes first. A missing notification
    # service must not raise.
    tray._notify_failed = False
    tray.notify(messages.APP_TITLE, "extra-test body", 1000)
    exit_item = _item(tray, messages.MENU_EXIT)
    out["main_ended"] = _run_main(exit_item.activate, 30)
    out["quitting"] = tray._quitting
    out["hotkey_none"] = tray.hotkey is None
    return out


def _child_tray_toggle() -> dict:
    from desktop_recorder import capture

    tray = _tray()
    out: dict = {}
    try:
        tray.toggle_item.activate()
        out["selector_opened"] = _pump(_x11_selector_open, 10)
        _pump(timeout=0.3)
        _xdo("mousemove", "150", "150", "mousedown", "1", "mousemove", "349", "299", "mouseup", "1")
        out["recording"] = _pump(lambda: tray.controller.state == capture.RECORDING, 15)
        out["toggle_recording"] = tray.toggle_item.get_label()
        out["status_recording"] = tray.status_item.get_label()
        out["tooltip_recording"] = tray._icon.get_tooltip_text() if tray._icon is not None else None
        _pump(timeout=2.5)
        tray.toggle_item.activate()
        out["stopped"] = _pump(lambda: tray.controller.state == capture.IDLE and tray.stats_item.get_visible(), 30)
        out["stats_visible"] = tray.stats_item.get_visible()
        out["stats"] = tray.stats_item.get_label()
        out["toggle_after"] = tray.toggle_item.get_label()
    finally:
        out["shutdown"] = _shutdown(tray)
    return out


def _child_tray_settings() -> dict:
    _gdk, _glib, gtk = _gtk()
    from desktop_recorder import capture, messages
    from desktop_recorder.settings import load_settings

    tray = _tray()
    out: dict = {}
    try:
        def children():
            return [lambda: tray._dialog._child if tray._dialog is not None else None,
                    lambda: tray._message_dialog]

        # 1. StatusIcon activate (the Windows double-click) opens Settings. Cancel.
        script = _Script(lambda: tray._dialog, [lambda: tray._dialog.response(gtk.ResponseType.CANCEL)],
                         children())
        try:
            if tray._icon is not None:
                tray._icon.emit("activate")
        finally:
            script.stop()
        out["icon_opened_dialog"] = script.seen_dialog
        out["fps_after_cancel"] = tray.settings.fps
        texts = list(script.texts)

        # 2. Settings... from the menu. Save fps 5 and the hotkey Ctrl+Alt+F9.
        def edit() -> None:
            dialog = tray._dialog
            dialog.fps.set_value(5)
            _set_mods(dialog, False, True, True, False)
            _set_key(dialog, "F9")
            dialog.response(gtk.ResponseType.OK)

        script = _Script(lambda: tray._dialog, [edit], children())
        try:
            _item(tray, messages.MENU_SETTINGS).activate()
        finally:
            script.stop()
        texts += script.texts
        out["item_opened_dialog"] = script.seen_dialog
        out["messages"] = texts
        out["live_fps"] = tray.settings.fps
        saved = load_settings()
        out["file_fps"] = saved.fps
        out["file_hotkey"] = [saved.hotkey_modifiers, saved.hotkey_key]
        out["hotkey_active"] = tray.hotkey_active
        out["toggle_label"] = tray.toggle_item.get_label()

        # 3. The new hotkey opens the selector. Esc closes it.
        _xdo("key", "ctrl+alt+F9")
        out["new_hotkey_opened_selector"] = _pump(_x11_selector_open, 10)
        _pump(timeout=0.3)
        _xdo("key", "Escape")
        _pump(lambda: tray.controller.state == capture.IDLE, 5)
        out["state_after_escape"] = tray.controller.state
    finally:
        out["shutdown"] = _shutdown(tray)
    return out


def _child_tray_exit_dialog() -> dict:
    from desktop_recorder import messages
    from desktop_recorder.settings import load_settings

    tray = _tray()
    exit_item = _item(tray, messages.MENU_EXIT)
    settings_item = _item(tray, messages.MENU_SETTINGS)

    def edit_then_exit() -> None:
        tray._dialog.fps.set_value(7)
        exit_item.activate()

    script = _Script(lambda: tray._dialog, [edit_then_exit],
                     [lambda: tray._dialog._child if tray._dialog is not None else None])
    try:
        ended = _run_main(settings_item.activate, 30)
    finally:
        script.stop()
    return {"dialog_seen": script.seen_dialog, "main_ended": ended, "quitting": tray._quitting,
            "dialog_after": None if tray._dialog is None else "open", "file_fps": load_settings().fps}


_CHILDREN = {
    "settings_round_trip": _child_settings_round_trip,
    "settings_wayland": _child_settings_wayland,
    "settings_bad_hotkey": _child_settings_bad_hotkey,
    "settings_bad_folder": _child_settings_bad_folder,
    "settings_fps": _child_settings_fps,
    "settings_cancel_exit": _child_settings_cancel_exit,
    "wl_drag_same": _child_wl_drag_same,
    "wl_drag_scale2": _child_wl_drag_scale2,
    "wl_drag_letterbox": _child_wl_drag_letterbox,
    "wl_escape": _child_wl_escape,
    "wl_right_click": _child_wl_right_click,
    "wl_space": _child_wl_space,
    "wl_arrows": _child_wl_arrows,
    "tray_menu": _child_tray_menu,
    "tray_toggle": _child_tray_toggle,
    "tray_settings": _child_tray_settings,
    "tray_exit_dialog": _child_tray_exit_dialog,
}


def _emit(result: dict) -> None:
    sys.stdout.write(RESULT_PREFIX + json.dumps(result, default=str) + "\n")
    sys.stdout.flush()


def _child_main(name: str) -> None:
    def watchdog() -> None:
        _emit({"error": f"watchdog: child {name} ran more than {CHILD_LIMIT_S} s"})
        os._exit(3)

    timer = threading.Timer(CHILD_LIMIT_S, watchdog)
    timer.daemon = True
    timer.start()
    sys.path.insert(0, str(ROOT / "linux"))
    try:
        result = _CHILDREN[name]()
    except BaseException:  # noqa: BLE001 - report every failure to the parent
        result = {"error": traceback.format_exc()}
    _emit(result)
    sys.stderr.flush()
    # Skip the GTK and thread teardown. A stuck thread must not keep the child alive.
    os._exit(0)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        _child_main(sys.argv[2])
    unittest.main()
