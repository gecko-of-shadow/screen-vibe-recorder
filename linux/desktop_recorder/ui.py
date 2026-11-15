"""GTK tray (DESIGN.md 12.1). It implements ControllerUi for capture.Controller.

GDK_BACKEND is set in __main__.py before this module loads, because Gtk loads here.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import messages, sounds  # noqa: E402
from .autostart import autostart_command, autostart_enabled, command_path, write_autostart  # noqa: E402
from .capture import Controller, resolve_ffmpeg  # noqa: E402
from .encoders import NvencProbe  # noqa: E402
from .ffmpeg_cmd import capture_backend  # noqa: E402
from .gnome_hotkey import update_gnome_shortcut  # noqa: E402
from .hotkey_x11 import X11Hotkey  # noqa: E402
from .settings import ENCODER_AUTO, Settings, config_dir, copy_settings, load_settings, save_settings  # noqa: E402
from .single_instance import InstanceServer, parse_command, send_command, socket_path  # noqa: E402

HOTKEY_NOTICE_MS = 6000


def _log(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def run(select: bool = False, token: str = "", from_toggle: bool = False) -> int:
    tray = Tray()
    if not tray.owned:
        if from_toggle:
            # Lost the start race to another --toggle: send it our TOGGLE once (D29).
            reply = send_command(socket_path(), "TOGGLE " + token if token else "TOGGLE")
            if reply is None:
                _log(messages.DID_NOT_ANSWER)
            else:
                print(reply)
            return 0
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=messages.ALREADY_RUNNING,
        )
        dialog.set_title(messages.APP_TITLE)
        dialog.run()
        dialog.destroy()
        return 0
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signum, tray.on_signal)
    tray.begin(select, token)
    Gtk.main()
    return 0


class Tray:
    def __init__(self) -> None:
        self.settings: Settings = load_settings()
        self.settings.start_on_login = autostart_enabled()
        self.backend = capture_backend()
        self.server = InstanceServer(socket_path(), self._command, schedule=_schedule_on_main)
        self.owned = self.server.start()
        if not self.owned:
            return
        self.token = ""
        self.hotkey: X11Hotkey | None = None
        self.hotkey_active = False
        self._dialog = None
        # Exit and a session signal set this flag. Then the code after a nested dialog
        # loop does nothing (no save, no new hotkey, no new message).
        self._quitting = False
        self._message_dialog = None
        self._notify_failed = os.environ.get("DESKTOP_RECORDER_NOTIFY", "").strip().lower() == "stderr"
        self._notify_module = None
        self.probe = NvencProbe()
        self.controller = Controller(self, lambda: self.settings, self._save_quietly, self.probe, None)
        self._icon_paths = self._write_icons()
        self._build_menu()

    # ------------------------------------------------------------ start and stop

    def begin(self, select: bool, token: str) -> None:
        self.token = token or ""
        self._install_hotkey(after_save=False)
        self.controller.refresh_audio()
        self.refresh()
        ffmpeg = resolve_ffmpeg()
        if not self.settings.record_on_launch and self.settings.encoder == ENCODER_AUTO and ffmpeg:
            self.probe.warm_up(ffmpeg)
        _log(messages.READY_LINE)
        if select:
            GLib.idle_add(self._toggle_once, self.token)
        elif self.settings.record_on_launch:
            GLib.idle_add(self._start_saved_once)

    def _toggle_once(self, token: str) -> bool:
        if not self._quitting:
            self.controller.toggle(token)
        return False

    def _start_saved_once(self) -> bool:
        if not self._quitting:
            self.controller.start_saved_region()
        return False

    def on_signal(self, *_args) -> bool:
        self.quit()
        return False

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        # Gtk.main_quit() does not end the nested loop of Gtk.Dialog.run(). Close each
        # open dialog, so that its run() returns and the outer Gtk.main() can end.
        if self._message_dialog is not None:
            self._message_dialog.response(Gtk.ResponseType.CANCEL)
        if self._dialog is not None:
            self._dialog.close_for_exit()
        try:
            self.controller.stop_sync()
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: stop at exit failed: {exc}")
        if self.hotkey is not None:
            self.hotkey.stop()
            self.hotkey = None
        self.server.stop()
        if self._icon is not None:
            self._icon.set_visible(False)
        Gtk.main_quit()

    # ------------------------------------------------------------ menu

    def _write_icons(self) -> tuple[str, str]:
        from . import icons

        try:
            return icons.write_icons(config_dir())
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: cannot write the tray icons: {exc}")
            return icons.icon_path(config_dir(), False), icons.icon_path(config_dir(), True)

    def _build_menu(self) -> None:
        self.menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label=messages.NOT_RECORDING)
        self.status_item.set_sensitive(False)
        self.stats_item = Gtk.MenuItem(label="")
        self.stats_item.set_sensitive(False)
        self.toggle_item = Gtk.MenuItem(label=messages.MENU_SELECT)
        self.toggle_item.connect("activate", lambda *_a: self._menu_toggle())
        folder_item = Gtk.MenuItem(label=messages.MENU_OPEN_FOLDER)
        folder_item.connect("activate", lambda *_a: self.open_folder())
        settings_item = Gtk.MenuItem(label=messages.MENU_SETTINGS)
        settings_item.connect("activate", lambda *_a: self.show_settings())
        quit_item = Gtk.MenuItem(label=messages.MENU_EXIT)
        quit_item.connect("activate", lambda *_a: self.quit())
        for item in (
            self.status_item,
            self.stats_item,
            Gtk.SeparatorMenuItem(),
            self.toggle_item,
            folder_item,
            settings_item,
            Gtk.SeparatorMenuItem(),
            quit_item,
        ):
            self.menu.append(item)
        self.menu.show_all()
        self.stats_item.hide()
        self._icon = None
        self._indicator = None
        if _use_appindicator():
            self._indicator = _indicator(self.menu, self._icon_paths[0])
        if self._indicator is None:
            self._icon = Gtk.StatusIcon()
            self._icon.connect("popup-menu", self._popup)
            # The Windows double-click: open Settings.
            self._icon.connect("activate", lambda *_a: self.show_settings())
            self._icon.set_visible(True)

    def _popup(self, _icon, button, time) -> None:
        self.menu.popup(None, None, None, None, button, time)

    def _menu_toggle(self) -> None:
        # Let the menu close before the selector grabs the keyboard and the mouse.
        GLib.idle_add(self._toggle_once, "")

    def open_folder(self) -> None:
        folder = self.settings.folder
        try:
            os.makedirs(folder, exist_ok=True)
            subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.notify(messages.APP_TITLE, (messages.CANNOT_OPEN_FOLDER + str(exc))[:250], 6000)

    # ------------------------------------------------------------ ControllerUi

    def refresh(self) -> None:
        if not self.owned:
            return
        recording = self.controller.is_recording()
        self.status_item.set_label(self.controller.status_text())
        try:
            stats = self.controller.last_stats_text()
        except Exception:  # noqa: BLE001
            stats = messages.LAST_RECORDING_PREFIX + messages.NO_STATS
        if stats is None:
            self.stats_item.hide()
        else:
            self.stats_item.set_label(stats)
            self.stats_item.show()
        label = messages.MENU_STOP if recording else messages.MENU_SELECT
        if self.hotkey_active:
            label += messages.MENU_HOTKEY_GAP + self.settings.hotkey_text
        self.toggle_item.set_label(label)
        tooltip = messages.TOOLTIP_RECORDING if recording else messages.TOOLTIP_STOPPED
        path = self._icon_paths[1] if recording else self._icon_paths[0]
        if self._icon is not None:
            if os.path.exists(path):
                self._icon.set_from_file(path)
            self._icon.set_tooltip_text(tooltip)
        if self._indicator is not None:
            self._indicator.set_icon_full(path, tooltip)
            try:
                self._indicator.set_title(tooltip)
            except Exception:  # noqa: BLE001
                pass

    def play(self, up: bool) -> None:
        sounds.play(up)

    def present_token(self) -> str:
        return self.token

    def notify(self, title: str, body: str, timeout_ms: int) -> None:
        # The stderr line comes first, always (D28). Tests read it.
        _log(messages.notify_line(title, body))
        if self._notify_failed:
            return
        try:
            notify = self._notify_module
            if notify is None:
                gi.require_version("Notify", "0.7")
                from gi.repository import Notify as notify

                if not notify.is_initted():
                    notify.init(messages.APP_TITLE)
                self._notify_module = notify
            note = notify.Notification.new(title, body, None)
            note.set_timeout(int(timeout_ms))
            note.show()
        except (ImportError, ValueError, GLib.Error) as exc:
            self._notify_failed = True
            _log(f"Desktop Recorder: notifications are off: {exc}")
        except Exception as exc:  # noqa: BLE001
            self._notify_failed = True
            _log(f"Desktop Recorder: notifications are off: {exc}")

    # ------------------------------------------------------------ socket

    def _command(self, text: str) -> str:
        """Runs on the main thread (InstanceServer schedule)."""
        verb, token = parse_command(text)
        if verb == "TOGGLE" and not self._quitting:
            if token:
                self.token = token
            self.controller.toggle(token)
        return self.controller.reply_word()

    # ------------------------------------------------------------ hotkey (8.5)

    def _hotkey_pressed(self) -> bool:
        if not self._quitting:
            self.controller.toggle("")
        return False

    def _install_hotkey(self, after_save: bool) -> None:
        if self._quitting:
            return
        if self.hotkey is not None:
            self.hotkey.stop()
            self.hotkey = None
        self.hotkey_active = False
        if self.backend == "x11":
            hotkey = X11Hotkey(
                os.environ.get("DISPLAY"),
                self.settings.hotkey_modifiers,
                self.settings.hotkey_key,
                lambda: GLib.idle_add(self._hotkey_pressed),
            )
            self.hotkey = hotkey
            if hotkey.start():
                self.hotkey_active = True
                return
            text = messages.hotkey_in_use(self.settings.hotkey_text)
            self.notify(messages.APP_TITLE, text, HOTKEY_NOTICE_MS)
            if after_save:
                self._message(text + messages.HOTKEY_PICK_OTHER)
            return
        command = command_path()
        if not command:
            self.notify(messages.APP_TITLE, messages.WAYLAND_HOTKEY_NEEDS_INSTALL, HOTKEY_NOTICE_MS)
            return

        def runner(args):
            return subprocess.run(args, capture_output=True, text=True, check=False, timeout=5)

        try:
            ok = update_gnome_shortcut(self.settings.hotkey_modifiers, self.settings.hotkey_key,
                                       shlex.quote(command) + " --toggle", runner)
        except Exception:  # noqa: BLE001 - a gsettings timeout
            ok = False
        if ok:
            self.hotkey_active = True
        else:
            self.notify(messages.APP_TITLE, messages.WAYLAND_NO_SHORTCUT, HOTKEY_NOTICE_MS)

    def _message(self, text: str) -> None:
        if self._quitting:
            return
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=text,
        )
        dialog.set_title(messages.APP_TITLE)
        self._message_dialog = dialog
        try:
            dialog.run()
        finally:
            self._message_dialog = None
            dialog.destroy()

    # ------------------------------------------------------------ settings

    def _save_quietly(self, settings: Settings) -> None:
        """The controller saves the live settings here (region, token, selector options)."""
        if settings is not self.settings:
            self.settings = settings
        save_settings(self.settings)

    def show_settings(self) -> None:
        if self._dialog is not None:
            self._dialog.present()
            return
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings, self.backend)
        self._dialog = dialog
        try:
            result = dialog.run_until_valid()
        finally:
            dialog.destroy()
            self._dialog = None
        if self._quitting or result is None:
            return
        # Keep values that the controller saved while the dialog was open (region, token).
        live = self.settings
        result.region = live.region
        result.last_region = live.last_region
        result.wayland_region = tuple(live.wayland_region)
        result.wayland_restore_token = live.wayland_restore_token
        self.settings = copy_settings(result)
        try:
            save_settings(self.settings)
            write_autostart(autostart_command(), self.settings.start_on_login)
        except Exception as exc:  # noqa: BLE001
            self._message(messages.CANNOT_SAVE_SETTINGS + str(exc))
        if self._quitting:
            return
        # Save never restarts a running recording (D13). New values apply to the next recording.
        self._install_hotkey(after_save=True)
        if self._quitting:
            return
        self.controller.refresh_audio()
        self.refresh()


def _schedule_on_main(job) -> None:
    def run_job() -> bool:
        job()
        return False

    GLib.idle_add(run_job)


def _use_appindicator() -> bool:
    choice = os.environ.get("DESKTOP_RECORDER_TRAY", "").strip().lower()
    if choice == "appindicator":
        return True
    if choice == "status":
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return capture_backend() == "wayland" or "GNOME" in desktop.split(":")


def _indicator(menu, icon_path):
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3 as AppIndicator
    except (ImportError, ValueError):
        return None
    indicator = AppIndicator.Indicator.new(
        "desktop-recorder",
        icon_path,
        AppIndicator.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    indicator.set_menu(menu)
    return indicator
