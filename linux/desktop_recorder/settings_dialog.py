"""The Settings dialog (DESIGN.md 12.2). GUI module: GTK 3."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from . import messages  # noqa: E402
from .hotkey import is_valid, parse_key  # noqa: E402
from .settings import (  # noqa: E402
    CHROMA_420,
    CHROMA_444,
    ENCODER_AUTO,
    ENCODER_NVENC,
    ENCODER_X264,
    MAX_FPS,
    MIN_FPS,
    MODE_CHANGES,
    MODE_FIXED,
    Settings,
    clamp_fps,
    clamp_quality,
    clamp_split,
    copy_settings,
)

ENCODER_VALUES = (ENCODER_AUTO, ENCODER_NVENC, ENCODER_X264)
CHROMA_VALUES = (CHROMA_420, CHROMA_444)
MODE_VALUES = (MODE_FIXED, MODE_CHANGES)


def _keys() -> list[str]:
    keys = [chr(code) for code in range(ord("A"), ord("Z") + 1)]
    keys += list("0123456789")
    keys += ["F" + str(n) for n in range(1, 13)]
    return keys


def _index(values: tuple[str, ...], value: str) -> int:
    try:
        return values.index(value)
    except ValueError:
        return 0


def _label(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.set_line_wrap(True)
    return label


def normalize_folder(text: str) -> tuple[str | None, str | None]:
    """Return (folder, None), or (None, error text). Makes the folder."""
    folder = (text or "").strip()
    if len(folder) >= 2 and folder[0] == folder[-1] and folder[0] in "\"'":
        folder = folder[1:-1].strip()
    folder = os.path.expanduser(folder)
    if not os.path.isabs(folder):
        return None, messages.FOLDER_NOT_ABSOLUTE
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return None, messages.FOLDER_CANNOT_CREATE + str(exc)
    if folder != "/":
        folder = folder.rstrip("/") or "/"
    return folder, None


class SettingsDialog(Gtk.Dialog):
    """current is the live Settings object. Save reads it again, because the selector
    can save a region while the dialog is open."""

    def __init__(self, current: Settings, backend: str) -> None:
        super().__init__(title=messages.SETTINGS_TITLE)
        self.current = current
        self.backend = backend
        # Exit sets _closing. _child is the open folder chooser or warning, if any.
        self._closing = False
        self._child: Gtk.Dialog | None = None
        self.set_resizable(False)
        self.add_button(messages.BUTTON_CANCEL, Gtk.ResponseType.CANCEL)
        save = self.add_button(messages.BUTTON_SAVE, Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        save.grab_default()

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        self.get_content_area().add(grid)
        row = 0

        # 1 Folder
        self.folder = Gtk.Entry()
        self.folder.set_text(current.folder)
        self.folder.set_hexpand(True)
        self.folder.set_activates_default(True)
        browse = Gtk.Button(label=messages.BUTTON_BROWSE)
        browse.connect("clicked", self._browse)
        grid.attach(_label(messages.LABEL_FOLDER), 0, row, 2, 1)
        row += 1
        folder_box = Gtk.Box(spacing=6)
        folder_box.pack_start(self.folder, True, True, 0)
        folder_box.pack_start(browse, False, False, 0)
        grid.attach(folder_box, 0, row, 2, 1)
        row += 1

        # 2 fps
        self.fps = Gtk.SpinButton.new_with_range(MIN_FPS, MAX_FPS, 1)
        self.fps.set_digits(1)
        self.fps.set_value(current.fps)
        row = self._row(grid, row, messages.LABEL_FPS, self.fps)

        # 3 Quality
        self.quality = self._combo(messages.QUALITY_NAMES, clamp_quality(current.quality))
        row = self._row(grid, row, messages.LABEL_QUALITY, self.quality)

        # 4 Split
        self.split = Gtk.SpinButton.new_with_range(0, 1440, 1)
        self.split.set_digits(0)
        self.split.set_value(current.split_minutes)
        row = self._row(grid, row, messages.LABEL_SPLIT, self.split)

        # 5 Hotkey
        self.win = Gtk.CheckButton(label=messages.CHECK_WIN)
        self.ctrl = Gtk.CheckButton(label=messages.CHECK_CTRL)
        self.alt = Gtk.CheckButton(label=messages.CHECK_ALT)
        self.shift = Gtk.CheckButton(label=messages.CHECK_SHIFT)
        self.win.set_active(bool(current.hotkey_modifiers & 8))
        self.ctrl.set_active(bool(current.hotkey_modifiers & 2))
        self.alt.set_active(bool(current.hotkey_modifiers & 1))
        self.shift.set_active(bool(current.hotkey_modifiers & 4))
        self.key = Gtk.ComboBoxText()
        for name in _keys():
            self.key.append_text(name)
        self._select_key(current.hotkey_key)
        mods = Gtk.Box(spacing=6)
        for widget in (self.win, self.ctrl, self.alt, self.shift, self.key):
            mods.pack_start(widget, False, False, 0)
        row = self._row(grid, row, messages.LABEL_HOTKEY, mods)

        # 6 Capture (read-only)
        capture = messages.CAPTURE_WAYLAND if backend == "wayland" else messages.CAPTURE_X11
        row = self._row(grid, row, messages.LABEL_CAPTURE, _label(capture))

        # 7 to 9 Encoder, chroma, mode
        self.encoder = self._combo(messages.ENCODER_NAMES, _index(ENCODER_VALUES, current.encoder))
        row = self._row(grid, row, messages.LABEL_ENCODER, self.encoder)
        self.chroma = self._combo(messages.CHROMA_NAMES, _index(CHROMA_VALUES, current.chroma))
        row = self._row(grid, row, messages.LABEL_CHROMA, self.chroma)
        self.mode = self._combo(messages.MODE_NAMES, _index(MODE_VALUES, current.frame_rate_mode))
        row = self._row(grid, row, messages.LABEL_MODE, self.mode)

        # 10 to 16 Check boxes
        self.startup = self._check(messages.CHECK_LOGIN, current.start_on_login)
        self.record = self._check(messages.CHECK_RECORD_ON_LAUNCH, current.record_on_launch)
        self.copy = self._check(messages.CHECK_COPY, current.copy_to_clipboard)
        self.sound = self._check(messages.CHECK_SOUNDS, current.play_sounds)
        self.hide_pointer = self._check(messages.CHECK_HIDE_POINTER, not current.show_pointer)
        self.audio = self._check(messages.CHECK_AUDIO, current.record_audio)
        checks = [self.startup, self.record, self.copy, self.sound, self.hide_pointer, self.audio]
        self.wayland_frame: Gtk.CheckButton | None = None
        if backend == "wayland":
            self.wayland_frame = self._check(messages.CHECK_WAYLAND_FRAME, current.wayland_frame)
            checks.append(self.wayland_frame)
        for widget in checks:
            grid.attach(widget, 0, row, 2, 1)
            row += 1

        # 17 Selector options
        self.crosshair = self._check(messages.CHECK_CROSSHAIR, current.selector_crosshair)
        self.magnifier = self._check(messages.CHECK_MAGNIFIER, current.selector_magnifier)
        self.position = self._check(messages.CHECK_POSITION, current.selector_position)
        selector = Gtk.Box(spacing=6)
        for widget in (self.crosshair, self.magnifier, self.position):
            selector.pack_start(widget, False, False, 0)
        row = self._row(grid, row, messages.LABEL_SELECTOR, selector)

        self.show_all()

    # ------------------------------------------------------------ build helpers

    @staticmethod
    def _row(grid: Gtk.Grid, row: int, text: str, widget: Gtk.Widget) -> int:
        grid.attach(_label(text), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)
        return row + 1

    @staticmethod
    def _combo(names: tuple[str, ...], active: int) -> Gtk.ComboBoxText:
        combo = Gtk.ComboBoxText()
        for name in names:
            combo.append_text(name)
        combo.set_active(max(0, min(len(names) - 1, active)))
        return combo

    @staticmethod
    def _check(text: str, active: bool) -> Gtk.CheckButton:
        check = Gtk.CheckButton(label=text)
        check.set_active(bool(active))
        return check

    def _select_key(self, name: str) -> None:
        model = self.key.get_model()
        for index, row in enumerate(model):
            if row[0] == name:
                self.key.set_active(index)
                return
        self.key.append_text(name)
        self.key.set_active(len(model) - 1)

    def _browse(self, _button: Gtk.Button) -> None:
        chooser = Gtk.FileChooserDialog(
            title=messages.FOLDER_CHOOSER_TITLE,
            parent=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_button(messages.BUTTON_CANCEL, Gtk.ResponseType.CANCEL)
        chooser.add_button(messages.BUTTON_SELECT, Gtk.ResponseType.OK)
        start = os.path.expanduser(self.folder.get_text().strip())
        if os.path.isdir(start):
            chooser.set_current_folder(start)
        self._child = chooser
        try:
            if chooser.run() == Gtk.ResponseType.OK and not self._closing:
                self.folder.set_text(chooser.get_filename() or "")
        finally:
            self._child = None
            chooser.destroy()

    # ------------------------------------------------------------ result

    def _modifiers(self) -> int:
        return ((8 if self.win.get_active() else 0)
                | (2 if self.ctrl.get_active() else 0)
                | (1 if self.alt.get_active() else 0)
                | (4 if self.shift.get_active() else 0))

    def _warn(self, text: str) -> None:
        message = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        self._child = message
        try:
            message.run()
        finally:
            self._child = None
            message.destroy()

    def _validated(self) -> Settings | None:
        # Commit typed text first. A SpinButton updates its value only on Enter, focus-out
        # or an arrow click, so Save from the keyboard can read the old value.
        self.fps.update()
        self.split.update()
        modifiers = self._modifiers()
        key = parse_key(self.key.get_active_text() or "")
        if not is_valid(modifiers, key):
            self._warn(messages.HOTKEY_INVALID)
            return None
        folder, error = normalize_folder(self.folder.get_text())
        if folder is None:
            self._warn(error or messages.FOLDER_NOT_ABSOLUTE)
            return None
        # Start from the live values at Save time. This keeps capture_backend, nvenc_cq,
        # region, last_region, wayland_region, wayland_restore_token and extra_lines.
        result = copy_settings(self.current)
        result.folder = folder
        result.fps = clamp_fps(float(self.fps.get_value()))
        result.quality = clamp_quality(self.quality.get_active())
        result.split_minutes = clamp_split(int(self.split.get_value()))
        result.hotkey_modifiers = modifiers
        result.hotkey_key = key or result.hotkey_key
        result.encoder = ENCODER_VALUES[max(0, self.encoder.get_active())]
        result.chroma = CHROMA_VALUES[max(0, self.chroma.get_active())]
        result.frame_rate_mode = MODE_VALUES[max(0, self.mode.get_active())]
        result.start_on_login = self.startup.get_active()
        result.record_on_launch = self.record.get_active()
        result.copy_to_clipboard = self.copy.get_active()
        result.play_sounds = self.sound.get_active()
        result.show_pointer = not self.hide_pointer.get_active()
        result.record_audio = self.audio.get_active()
        if self.wayland_frame is not None:
            result.wayland_frame = self.wayland_frame.get_active()
        result.selector_crosshair = self.crosshair.get_active()
        result.selector_magnifier = self.magnifier.get_active()
        result.selector_position = self.position.get_active()
        return result

    def close_for_exit(self) -> None:
        """Exit: end each nested run() loop. Then run_until_valid() returns None.

        Gtk.main_quit() does not end the loop of Gtk.Dialog.run(), so the tray calls this.
        """
        self._closing = True
        if self._child is not None:
            self._child.response(Gtk.ResponseType.CANCEL)
        self.response(Gtk.ResponseType.CANCEL)

    def run_until_valid(self) -> Settings | None:
        """Loop until Save gives valid values. Return None for Cancel or Exit."""
        while not self._closing:
            response = self.run()
            if response != Gtk.ResponseType.OK or self._closing:
                return None
            result = self._validated()
            if self._closing:
                return None
            if result is not None:
                return result
        return None
