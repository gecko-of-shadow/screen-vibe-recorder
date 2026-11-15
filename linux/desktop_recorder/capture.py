"""The Controller: selector, FFmpeg start and stop, fallback and stats (DESIGN.md 8, 11.3).

GUI module. Call every Controller method on the GTK main thread only (8.7).
Other threads reach the Controller only through GLib.idle_add.
"""

from __future__ import annotations

import functools
import math
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from . import messages  # noqa: E402
from .audio import find_monitor, probe_pulse  # noqa: E402
from .clipboard import copy_files  # noqa: E402
from .encoders import NvencProbe  # noqa: E402
from .ffmpeg_cmd import (  # noqa: E402
    REASON_NVENC_FAILED,
    CapturePlan,
    capture_backend,
    choose_fallback,
    format_fps,
    plan_wayland,
    plan_x11,
    wayland_argv,
    x11_argv,
)
from .ffstats import (  # noqa: E402
    PumpCounters,
    format_stats,
    session_files,
    snapshot,
    total_bytes,
    wayland_stats,
    x11_stats,
)
from .geometry import Rect, accept_rect, stream_to_layout  # noqa: E402
from .recording import FfmpegProcess  # noqa: E402
from .selector_model import SelectorOptions  # noqa: E402
from .settings import ENCODER_AUTO, ZERO_WAYLAND_REGION, Settings, copy_settings  # noqa: E402

IDLE = "idle"
PORTAL = "portal"
SELECTING = "selecting"
STARTING = "starting"
RECORDING = "recording"
STOPPING = "stopping"

REPLY_OF_STATE = {
    IDLE: "STOPPED",
    PORTAL: "SELECTING",
    SELECTING: "SELECTING",
    STARTING: "RECORDING",
    RECORDING: "RECORDING",
    STOPPING: "STOPPING",
}

NOTE_LIMIT = 250
START_NOTICE_MS = 3000
STOP_NOTICE_MS = 4000
ERROR_NOTICE_MS = 8000
FIRST_FRAME_WAIT_S = 3.0
FIRST_FRAME_POLL_MS = 50
AUDIO_WAIT_S = 6.0
STOP_JOIN_S = 30.0


class ControllerUi(Protocol):
    def notify(self, title: str, body: str, timeout_ms: int) -> None: ...
    def refresh(self) -> None: ...
    def play(self, up: bool) -> None: ...
    def present_token(self) -> str: ...


def _log(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _cut(text: str) -> str:
    return text[:NOTE_LIMIT]


def _guarded(method):
    """Scheduled start work: an exception notifies the error and sets the state to idle (8.1)."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: {method.__name__} failed: {exc!r}")
            self._recover(str(exc) or exc.__class__.__name__)
            return False

    return wrapper


def resolve_ffmpeg() -> str | None:
    """Env DESKTOP_RECORDER_FFMPEG, else ffmpeg on PATH."""
    forced = os.environ.get("DESKTOP_RECORDER_FFMPEG", "").strip()
    if forced:
        return forced
    return shutil.which("ffmpeg")


def _close_fd(fd: int | None) -> None:
    if fd is None or fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


# ---------------------------------------------------------------- Wayland state


@dataclass
class _Stream:
    info: Any            # portal.PortalStreamInfo
    pump: Any            # wayland_pump.FramePump
    gst: Any             # wayland.GstStream
    fd: int              # our dup of the PipeWire fd
    stopped: bool = False

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        try:
            self.pump.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.gst.stop()
        except Exception:  # noqa: BLE001
            pass
        _close_fd(self.fd)
        self.fd = -1


@dataclass
class _Cast:
    """One portal session and its GStreamer streams."""
    transport: Any
    portal: Any          # portal.PortalSession
    purpose: str         # "select" or "launch"
    token: str
    streams: list[_Stream] = field(default_factory=list)
    infos: list[Any] = field(default_factory=list)   # all streams of the session
    timer: int | None = None
    deadline: float = 0.0
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.timer is not None:
            try:
                GLib.source_remove(self.timer)
            except Exception:  # noqa: BLE001
                pass
            self.timer = None
        for stream in self.streams:
            stream.stop()
        _close_fd(getattr(self.portal, "fd", None))
        try:
            self.transport.close_session(self.portal.session)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- one recording


@dataclass
class _Session:
    kind: str                       # "x11" or "wayland"
    settings: Settings              # copy at start: folder, fps, encoder
    plan: CapturePlan
    proc: FfmpegProcess
    before: set[str]
    ffmpeg: str
    requested: Rect | None = None   # X11: the region asked for (None = no saved region)
    cast: _Cast | None = None       # Wayland
    stream: _Stream | None = None   # Wayland: the recorded stream
    frame: Any = None               # frame_x11.RecordingFrame
    counters: PumpCounters | None = None
    stop_thread: threading.Thread | None = None
    error_text: str | None = None   # Wayland stream error that stopped the recording
    finished: bool = False


class Controller:
    def __init__(self, ui: ControllerUi, get_settings: Callable[[], Settings],
                 save: Callable[[Settings], None], probe: NvencProbe, ffmpeg: str | None) -> None:
        self.ui = ui
        self.get_settings = get_settings
        self.save = save
        self.probe = probe
        self.ffmpeg = ffmpeg
        self.state = IDLE
        self.session: _Session | None = None
        self.cast: _Cast | None = None
        self._last_stats: str | None = None
        self._quitting = False
        self._audio_lock = threading.Lock()
        self._audio_thread: threading.Thread | None = None
        self._audio_result: tuple[str | None, bool] | None = None   # (device, responds)
        self._audio_generation = 0

    # ------------------------------------------------------------ small helpers

    def backend(self) -> str:
        return capture_backend()

    def _ffmpeg(self) -> str | None:
        return self.ffmpeg or resolve_ffmpeg()

    def _set_state(self, state: str) -> None:
        self.state = state
        try:
            self.ui.refresh()
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: tray refresh failed: {exc}")

    def _notify(self, title: str, body: str, timeout_ms: int) -> None:
        try:
            self.ui.notify(title, body, timeout_ms)
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: notification failed: {exc}")

    def _error(self, text: str) -> None:
        self._notify(messages.APP_TITLE, _cut(text), ERROR_NOTICE_MS)

    def _play(self, up: bool) -> None:
        if not self.get_settings().play_sounds:
            return
        try:
            self.ui.play(up)
        except Exception:  # noqa: BLE001
            pass

    def _save_live(self) -> None:
        try:
            self.save(self.get_settings())
        except Exception as exc:  # noqa: BLE001
            self._notify(messages.APP_TITLE, _cut(messages.CANNOT_SAVE_SETTINGS + str(exc)), 6000)

    def _save_options(self, options: SelectorOptions | None) -> None:
        """Keys C, M and P change these options. Save them when they changed, also on cancel."""
        if options is None:
            return
        s = self.get_settings()
        if (s.selector_crosshair == options.crosshair and s.selector_magnifier == options.magnifier
                and s.selector_position == options.position):
            return
        s.selector_crosshair = bool(options.crosshair)
        s.selector_magnifier = bool(options.magnifier)
        s.selector_position = bool(options.position)
        self._save_live()

    def _check_folder(self, folder: str) -> str | None:
        if not folder or not folder.strip():
            return messages.FOLDER_EMPTY
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            return messages.folder_error(folder, exc)
        return None

    def _recover(self, text: str) -> None:
        """Clean up after a failed start step."""
        if self.state not in (PORTAL, SELECTING, STARTING, RECORDING):
            return
        session = self.session
        if self.state == RECORDING and session is not None and not session.finished:
            # FFmpeg runs: stop it normally, and show the error with the stats.
            session.error_text = text
            self.stop(sound=False)
            return
        if session is not None and not session.finished and session.proc.is_running():
            session.finished = True
            self._close_frame(session)
            threading.Thread(target=self._stop_worker, args=(session, False), name="ffmpeg-stop",
                             daemon=True).start()
        cast = self.cast
        if cast is not None:
            cast.close()
            self.cast = None
        self._start_failed(text)

    def _nvenc_ok(self, settings: Settings, ffmpeg: str, force_x264: bool) -> bool:
        # The probe runs only for "auto" (5.5).
        if force_x264 or settings.encoder != ENCODER_AUTO:
            return False
        try:
            return self.probe.usable(ffmpeg)
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ audio (8.2 step 6)

    def refresh_audio(self) -> None:
        """Find and probe the audio device on a background thread. The tray calls this at
        app start and after each Save."""
        settings = self.get_settings()
        ffmpeg = self._ffmpeg()
        with self._audio_lock:
            self._audio_generation += 1
            generation = self._audio_generation
            if not settings.record_audio or not ffmpeg:
                self._audio_result = None
                self._audio_thread = None
                return

        def work() -> None:
            device = None
            responds = False
            try:
                device = find_monitor()
                if device:
                    responds = probe_pulse(device, ffmpeg=ffmpeg)
            except Exception:  # noqa: BLE001
                device, responds = None, False
            with self._audio_lock:
                if generation == self._audio_generation:
                    self._audio_result = (device, responds)

        thread = threading.Thread(target=work, name="audio-probe", daemon=True)
        with self._audio_lock:
            self._audio_thread = thread
        thread.start()

    def _audio_for(self, settings: Settings) -> tuple[str | None, str | None]:
        """Return (device or None, note or None) for a start. Uses the cached probe."""
        if not settings.record_audio:
            return None, None
        with self._audio_lock:
            thread = self._audio_thread
            result = self._audio_result
        if result is None and thread is None:
            self.refresh_audio()
            with self._audio_lock:
                thread = self._audio_thread
        if result is None and thread is not None:
            thread.join(AUDIO_WAIT_S)
            with self._audio_lock:
                result = self._audio_result
        if result is None:
            return None, messages.AUDIO_NO_RESPONSE
        device, responds = result
        if not device:
            return None, messages.AUDIO_NOT_FOUND
        if not responds:
            return None, messages.AUDIO_NO_RESPONSE
        return device, None

    # ------------------------------------------------------------ public API

    def is_recording(self) -> bool:
        return self.state in (STARTING, RECORDING)

    def reply_word(self) -> str:
        """The socket reply for the current state (8.4)."""
        return REPLY_OF_STATE.get(self.state, "STOPPED")

    def status_text(self) -> str:
        session = self.session
        if self.state not in (STARTING, RECORDING) or session is None:
            return messages.NOT_RECORDING
        fps_text = format_fps(session.settings.fps)
        if session.plan.region is None:
            return messages.recording_whole(fps_text)
        return messages.recording_region(fps_text, session.plan.width, session.plan.height)

    def last_stats_text(self) -> str | None:
        if self._last_stats is None:
            return None
        return messages.LAST_RECORDING_PREFIX + self._last_stats

    def toggle(self, activation_token: str = "") -> None:
        """Returns at once. The work runs in later idle callbacks (D19)."""
        if self.state == RECORDING:
            self.stop()
            return
        if self.state != IDLE:
            return
        token = activation_token or ""
        if self.backend() == "wayland":
            self._set_state(PORTAL)
            GLib.idle_add(self._wayland_begin, "select", token)
        else:
            self._set_state(SELECTING)
            GLib.idle_add(self._x11_open_selector)

    @_guarded
    def start_saved_region(self) -> None:
        """Start at app launch with the saved region, without the selector."""
        if self.state != IDLE:
            return
        if self.backend() == "wayland":
            self._set_state(PORTAL)
            GLib.idle_add(self._wayland_begin, "launch", "")
            return
        s = self.get_settings()
        region = None if s.region.is_empty else s.region
        self._x11_start(region, sound=True, notice=False, first_note=None, force_x264=False, retry=False)

    # ------------------------------------------------------------ X11 path

    def _x11_open_selector(self) -> bool:
        if self.state != SELECTING:
            return False
        try:
            from .selector_gtk import open_x11_selector

            error = open_x11_selector(self.get_settings(), os.environ.get("DISPLAY"), self._x11_selected)
        except Exception as exc:  # noqa: BLE001
            error = str(exc) or exc.__class__.__name__
        if error:
            self._set_state(IDLE)
            self._error(messages.SELECTOR_FAILED + error)
        return False

    @_guarded
    def _x11_selected(self, rect: Rect | None, options: SelectorOptions) -> None:
        self._save_options(options)
        if self.state != SELECTING or self._quitting:
            return
        if rect is None:
            self._set_state(IDLE)
            return
        s = self.get_settings()
        s.region = rect
        s.last_region = rect
        self._save_live()
        self._x11_start(rect, sound=True, notice=True, first_note=None, force_x264=False, retry=False)

    @staticmethod
    def _x11_screen() -> tuple[Rect, list[Rect], list[Rect], int]:
        """X screen, monitors and work areas in physical px, and the GTK scale S."""
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        first = display.get_monitor(0) if display is not None else None
        scale = max(1, int(first.get_scale_factor())) if first is not None else 1
        root = Gdk.get_default_root_window()
        screen = Rect(0, 0, int(root.get_width()) * scale, int(root.get_height()) * scale)
        monitors: list[Rect] = []
        work_areas: list[Rect] = []
        if display is not None:
            for index in range(display.get_n_monitors()):
                mon = display.get_monitor(index)
                if mon is None:
                    continue
                g = mon.get_geometry()
                w = mon.get_workarea()
                monitors.append(Rect(g.x * scale, g.y * scale, g.width * scale, g.height * scale))
                work_areas.append(Rect(w.x * scale, w.y * scale, w.width * scale, w.height * scale))
        if not monitors:
            monitors = [screen]
            work_areas = [screen]
        return screen, monitors, work_areas, scale

    @_guarded
    def _x11_start(self, region: Rect | None, sound: bool, notice: bool, first_note: str | None,
                   force_x264: bool, retry: bool) -> None:
        self._set_state(STARTING)
        settings = copy_settings(self.get_settings())
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            self._start_failed(messages.FFMPEG_MISSING)
            return
        problem = self._check_folder(settings.folder)
        if problem:
            self._start_failed(problem)
            return
        before = snapshot(settings.folder)
        when = datetime.now()
        try:
            screen, monitors, work_areas, scale = self._x11_screen()
        except Exception as exc:  # noqa: BLE001
            self._start_failed(str(exc))
            return
        plan = plan_x11(settings, region, screen, self._nvenc_ok(settings, ffmpeg, force_x264), force_x264)
        audio_device, audio_note = self._audio_for(settings)
        display = os.environ.get("DISPLAY")
        argv = x11_argv(settings, plan, when, display, audio_device, ffmpeg)
        session = _Session("x11", settings, plan, FfmpegProcess(argv), before, ffmpeg, requested=region)
        session.proc.on_exit = functools.partial(self._exit_from_thread, session)
        error = session.proc.start()
        if error:
            self._start_failed(error)
            return
        self.session = session
        self._set_state(RECORDING)
        _log(messages.plan_line(plan.backend, plan.encoder))
        frame_notes: list[str] = []
        if plan.region is not None:
            frame_notes = self._show_x11_frame(session, plan.region, monitors, work_areas, scale, display)
        if sound and not retry:
            self._play(True)
        self._start_notice(plan, notice, [first_note, *plan.notes, audio_note, *frame_notes])

    def _show_x11_frame(self, session: _Session, region: Rect, monitors: list[Rect], work_areas: list[Rect],
                        scale: int, display: str | None) -> list[str]:
        try:
            from .frame_x11 import RecordingFrame

            frame = RecordingFrame(display)
            session.frame = frame
            return list(frame.show(region, monitors, work_areas, float(scale), scale,
                                   self.get_settings().hotkey_text, self._stop_clicked, 0))
        except Exception as exc:  # noqa: BLE001 - the recording goes on without the frame
            _log(f"Desktop Recorder: cannot show the recording frame: {exc}")
            self._close_frame(session)
            return []

    def _stop_clicked(self) -> None:
        # The click comes from the Stop button. Stop after its event handler ends.
        GLib.idle_add(self._stop_idle)

    def _stop_idle(self) -> bool:
        self.stop()
        return False

    def _start_failed(self, text: str) -> None:
        self._set_state(IDLE)
        self._error(text)

    def _start_notice(self, plan: CapturePlan, notice: bool, notes: list[str | None]) -> None:
        kept = [note for note in notes if note]
        if not notice and not kept:
            return
        body = "\n".join([messages.recording_started(plan.backend, plan.encoder), *kept])
        self._notify(messages.APP_TITLE, _cut(body), START_NOTICE_MS)

    @staticmethod
    def _close_frame(session: _Session | None) -> None:
        if session is None or session.frame is None:
            return
        frame = session.frame
        session.frame = None
        try:
            frame.close()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------ Wayland path (11.3)

    @_guarded
    def _wayland_begin(self, purpose: str, token: str) -> bool:
        if self.state != PORTAL:
            return False
        settings = self.get_settings()
        if not self._ffmpeg():
            self._start_failed(messages.FFMPEG_MISSING)
            return False
        try:
            from .portal import GioTransport, PortalError, ScreenCast

            transport = GioTransport()
            portal = ScreenCast(transport).open(settings.wayland_restore_token, settings.show_pointer)
        except Exception as exc:  # noqa: BLE001 - PortalError and D-Bus errors
            if self.state == PORTAL:
                self._start_failed(str(exc) or exc.__class__.__name__)
            return False
        cast = _Cast(transport, portal, purpose, token, infos=list(portal.streams))
        # The portal dialog runs a nested main loop. Exit can come during it.
        if self._quitting or self.state != PORTAL:
            cast.close()
            return False
        if portal.restore_token and portal.restore_token != settings.wayland_restore_token:
            settings.wayland_restore_token = portal.restore_token
            self._save_live()
        self.cast = cast
        try:
            from .wayland import GstStream
            from .wayland_pump import FramePump, pipewire_source
        except Exception as exc:  # noqa: BLE001
            self._cast_failed(cast, str(exc))
            return False
        first_error = None
        for info in portal.streams:
            fd = -1
            try:
                fd = os.dup(portal.fd)
                pump = FramePump(settings.fps)
                stream = _Stream(info, pump, None, fd)
                stream.gst = GstStream(pipewire_source(fd, info.node_id), pump,
                                       functools.partial(self._stream_error_soon, cast, stream))
                error = stream.gst.start()
            except Exception as exc:  # noqa: BLE001
                error = str(exc) or exc.__class__.__name__
            if error:
                _close_fd(fd)
                first_error = first_error or error
                continue
            cast.streams.append(stream)
        if not cast.streams:
            self._cast_failed(cast, first_error or messages.NO_PICTURE)
            return False
        cast.deadline = time.monotonic() + FIRST_FRAME_WAIT_S
        cast.timer = GLib.timeout_add(FIRST_FRAME_POLL_MS, self._wayland_poll, cast)
        return False

    def _cast_failed(self, cast: _Cast, text: str) -> None:
        cast.close()
        if self.cast is cast:
            self.cast = None
        self._start_failed(text)

    @_guarded
    def _wayland_poll(self, cast: _Cast) -> bool:
        if cast is not self.cast or cast.closed or self.state != PORTAL:
            cast.timer = None
            return False
        have = [s for s in cast.streams if s.pump.latest() is not None]
        if len(have) < len(cast.streams) and time.monotonic() < cast.deadline:
            return True
        cast.timer = None
        if not have:
            self._cast_failed(cast, messages.NO_PICTURE)
            return False
        for stream in cast.streams:
            if stream not in have:
                stream.stop()
        cast.streams = have
        if cast.purpose == "launch":
            self._wayland_launch(cast)
        else:
            self._wayland_open_selector(cast)
        return False

    def _wayland_open_selector(self, cast: _Cast) -> None:
        frames = [(s.info, s.pump.latest()) for s in cast.streams]
        # Set the state first: on_done must see "selecting", also if it comes at once.
        self._set_state(SELECTING)
        try:
            from .selector_gtk import open_wayland_selector

            error = open_wayland_selector(frames, self.get_settings(), cast.token,
                                          functools.partial(self._wayland_selected, cast))
        except Exception as exc:  # noqa: BLE001
            error = str(exc) or exc.__class__.__name__
        if error and cast is self.cast and self.state == SELECTING:
            self._cast_failed(cast, messages.SELECTOR_FAILED + error)

    @_guarded
    def _wayland_selected(self, cast: _Cast, index: int | None, crop: Rect | None,
                          options: SelectorOptions) -> None:
        self._save_options(options)
        if cast is not self.cast or self.state != SELECTING or self._quitting:
            if cast is not self.cast:
                cast.close()
            return
        if index is None or crop is None or not (0 <= index < len(cast.streams)):
            cast.close()
            self.cast = None
            self._set_state(IDLE)
            return
        chosen = cast.streams[index]
        latest = chosen.pump.latest()
        accept_seq = latest.seq if latest is not None else 0
        self._keep_only(cast, chosen)
        pos = chosen.info.position or (0, 0)
        s = self.get_settings()
        s.wayland_region = (int(pos[0]), int(pos[1]), crop.x, crop.y, crop.w, crop.h)
        self._save_live()
        self._wayland_start(cast, chosen, crop, after_seq=accept_seq, sound=True, notice=True,
                            first_note=None, force_x264=False, retry=False)

    @staticmethod
    def _keep_only(cast: _Cast, chosen: _Stream) -> None:
        for stream in cast.streams:
            if stream is not chosen:
                stream.stop()
        cast.streams = [chosen]

    @_guarded
    def _wayland_launch(self, cast: _Cast) -> None:
        """record_on_launch: no selector. Use the saved region, else the whole of stream 0."""
        saved = tuple(self.get_settings().wayland_region)
        first = cast.streams[0]
        chosen = first
        note = None
        crop = None
        if saved != ZERO_WAYLAND_REGION:
            mx, my, x, y, w, h = saved
            for stream in cast.streams:
                if tuple(stream.info.position or (0, 0)) == (mx, my):
                    frame = stream.pump.latest()
                    crop = accept_rect(Rect(x, y, w, h), Rect(0, 0, frame.width, frame.height))
                    chosen = stream
                    break
            if crop is None:
                chosen = first
                note = messages.SAVED_REGION_OFF_SCREEN
        if crop is None:
            frame = chosen.pump.latest()
            bounds = Rect(0, 0, frame.width, frame.height)
            crop = accept_rect(bounds, bounds)
        if crop is None:
            self._cast_failed(cast, messages.NO_PICTURE)
            return
        self._keep_only(cast, chosen)
        self._wayland_start(cast, chosen, crop, after_seq=0, sound=True, notice=False,
                            first_note=note, force_x264=False, retry=False)

    @_guarded
    def _wayland_start(self, cast: _Cast, chosen: _Stream, crop: Rect, after_seq: int, sound: bool,
                       notice: bool, first_note: str | None, force_x264: bool, retry: bool) -> None:
        self._set_state(STARTING)
        settings = copy_settings(self.get_settings())
        ffmpeg = self._ffmpeg()
        problem = messages.FFMPEG_MISSING if not ffmpeg else self._check_folder(settings.folder)
        if problem:
            self._cast_failed(cast, problem)
            return
        before = snapshot(settings.folder)
        when = datetime.now()
        plan = plan_wayland(settings, crop, self._nvenc_ok(settings, ffmpeg, force_x264), force_x264)
        audio_device, audio_note = self._audio_for(settings)
        argv = wayland_argv(settings, plan, when, audio_device, ffmpeg)
        session = _Session("wayland", settings, plan, FfmpegProcess(argv), before, ffmpeg,
                           cast=cast, stream=chosen)
        session.proc.on_exit = functools.partial(self._exit_from_thread, session)
        error = session.proc.start()
        if error:
            self._cast_failed(cast, error)
            return
        pump = chosen.pump
        pump.fps = float(settings.fps)
        if retry:
            pump.restart(session.proc.write)
        else:
            pump.set_crop(crop)
            pump.start(session.proc.write, after_seq=after_seq)
        self.session = session
        self._set_state(RECORDING)
        _log(messages.plan_line(plan.backend, plan.encoder))
        frame_notes = self._show_wayland_frame(session, cast, chosen, crop, settings)
        if sound and not retry:
            self._play(True)
        self._start_notice(plan, notice, [first_note, *plan.notes, audio_note, *frame_notes])

    def _show_wayland_frame(self, session: _Session, cast: _Cast, chosen: _Stream, crop: Rect,
                            settings: Settings) -> list[str]:
        hotkey_text = self.get_settings().hotkey_text
        display = os.environ.get("DISPLAY")
        if not settings.wayland_frame or not display:
            # No frame, so nothing else says that there is no Stop button.
            return [messages.wayland_no_stop_note(hotkey_text)]
        frame_img = chosen.pump.latest()
        iw = frame_img.width if frame_img is not None else crop.right
        ih = frame_img.height if frame_img is not None else crop.bottom
        pos = tuple(chosen.info.position or (0, 0))
        # The spec asks for the selector window size when the portal gives no size.
        # The selector API does not give it, so use the stream size (scale 1).
        logical = tuple(chosen.info.size or (iw, ih))
        lx, ly, lw, lh = stream_to_layout(crop, pos, logical, (iw, ih))
        x0, y0 = math.floor(lx), math.floor(ly)
        x1, y1 = math.ceil(lx + lw), math.ceil(ly + lh)
        region = Rect(x0, y0, x1 - x0, y1 - y0)
        monitors: list[Rect] = []
        for info in cast.infos:
            if info.size is None and info is not chosen.info:
                continue
            ipos = tuple(info.position or (0, 0))
            isize = tuple(info.size or logical)
            monitors.append(Rect(int(ipos[0]), int(ipos[1]), int(isize[0]), int(isize[1])))
        try:
            from .frame_x11 import RecordingFrame

            frame = RecordingFrame(display)
            session.frame = frame
            return list(frame.show(region, monitors, list(monitors), 1.0, 1, hotkey_text, None, 1))
        except Exception as exc:  # noqa: BLE001 - the recording goes on without the frame
            _log(f"Desktop Recorder: cannot show the recording frame: {exc}")
            self._close_frame(session)
            return [messages.wayland_no_stop_note(hotkey_text)]

    def _stream_error_soon(self, cast: _Cast, stream: _Stream, text: str) -> None:
        # GstStream calls this on the main thread already. idle_add keeps the order safe anyway.
        GLib.idle_add(self._stream_error, cast, stream, text)

    def _stream_error(self, cast: _Cast, stream: _Stream, text: str) -> bool:
        session = self.session
        if (self.state == RECORDING and session is not None and session.stream is stream
                and session.cast is cast):
            session.error_text = text
            self.stop()
            return False
        # Before the recording: the stream gives no frame, and the poll drops it.
        _log(f"Desktop Recorder: screen cast error: {text}")
        return False

    # ------------------------------------------------------------ FFmpeg exit and fallback (8.3 step 4)

    def _exit_from_thread(self, session: _Session, code: int, text: str) -> None:
        # Runs on the "ffmpeg-stderr" thread.
        GLib.idle_add(self._ffmpeg_exited, session, code, text)

    @_guarded
    def _ffmpeg_exited(self, session: _Session, code: int, text: str) -> bool:
        if session is not self.session or self.state != RECORDING or session.proc.stopping:
            return False
        elapsed_ms = int((time.monotonic() - session.proc.started_at) * 1000)
        choice = choose_fallback(session.plan, session.settings, text, elapsed_ms)
        if choice is not None:
            _force, reason = choice
            if reason == REASON_NVENC_FAILED:
                self.probe.mark_unusable(session.ffmpeg)
            note = reason + messages.FFMPEG_LINE_PREFIX + session.proc.first_error_line()
            self._close_frame(session)
            if session.kind == "x11":
                self._x11_start(session.requested, sound=False, notice=True, first_note=note,
                                force_x264=True, retry=True)
            elif session.cast is not None and session.stream is not None and session.plan.region is not None:
                self._wayland_start(session.cast, session.stream, session.plan.region, after_seq=0,
                                    sound=False, notice=True, first_note=note, force_x264=True, retry=True)
            return False
        # No fallback: the recording failed.
        session.finished = True
        self._close_frame(session)
        if session.kind == "wayland":
            if session.stream is not None:
                session.counters = session.stream.pump.stop()
            if session.cast is not None:
                session.cast.close()
                if self.cast is session.cast:
                    self.cast = None
        self._set_state(IDLE)
        self._play(False)
        stats = self._make_stats(session)
        self._last_stats = stats
        try:
            self.ui.refresh()
        except Exception:  # noqa: BLE001
            pass
        body = stats + "\n" + (text or messages.FFMPEG_STOPPED)
        self._notify(messages.STOPPED_TITLE, _cut(body), ERROR_NOTICE_MS)
        return False

    def _make_stats(self, session: _Session) -> str:
        try:
            files = session_files(session.settings.folder, session.before)
            size = total_bytes(files)
            progress = session.proc.progress()
            if session.kind == "wayland":
                counters = session.counters
                if counters is None and session.stream is not None:
                    counters = session.stream.pump.counters()
                stats = wayland_stats(progress, counters or PumpCounters(), size)
            else:
                stats = x11_stats(progress, size)
            return format_stats(stats)
        except Exception:  # noqa: BLE001
            return messages.NO_STATS

    # ------------------------------------------------------------ stop (8.3)

    def stop(self, sound: bool = True) -> None:
        """Async stop. The frame closes and the sound plays at once."""
        if self.state != RECORDING or self.session is None:
            return
        session = self.session
        if sound:
            self._play(False)
        self._close_frame(session)
        self._set_state(STOPPING)
        thread = threading.Thread(target=self._stop_worker, args=(session, True), name="ffmpeg-stop",
                                  daemon=True)
        session.stop_thread = thread
        thread.start()

    def _stop_worker(self, session: _Session, schedule_finish: bool) -> None:
        try:
            if session.kind == "wayland":
                if session.stream is not None:
                    session.counters = session.stream.pump.stop()
                session.proc.request_stop(session.settings.fps, use_q=False)
            else:
                session.proc.request_stop(session.settings.fps, use_q=True)
        except Exception as exc:  # noqa: BLE001
            _log(f"Desktop Recorder: stop failed: {exc}")
        if schedule_finish:
            GLib.idle_add(self._finish_stop, session)

    def _finish_stop(self, session: _Session) -> bool:
        if session.finished:
            return False
        session.finished = True
        if session.kind == "wayland" and session.cast is not None:
            session.cast.close()
            if self.cast is session.cast:
                self.cast = None
        stats = self._make_stats(session)
        self._last_stats = stats
        title = messages.APP_TITLE
        timeout = STOP_NOTICE_MS
        body = messages.RECORDING_STOPPED + stats
        files: list[str] = []
        if self.get_settings().copy_to_clipboard:
            try:
                files = session_files(session.settings.folder, session.before)
            except Exception:  # noqa: BLE001
                files = []
        if files:
            try:
                copy_files(files)
                lead = messages.VIDEO_COPIED_ONE if len(files) == 1 else messages.videos_copied(len(files))
                body = lead + stats
            except Exception as exc:  # noqa: BLE001
                body = stats + messages.COPY_FAILED + str(exc)
        if session.error_text:
            title = messages.STOPPED_TITLE
            body = stats + "\n" + session.error_text
            timeout = ERROR_NOTICE_MS
        if self.session is session:
            self._set_state(IDLE)
        self._notify(title, _cut(body), timeout)
        return False

    def stop_sync(self) -> None:
        """For Exit and signals. No sound. Blocks until FFmpeg has finished the file."""
        self._quitting = True
        session = self.session
        if self.state in (RECORDING, STARTING) and session is not None and not session.finished:
            self._close_frame(session)
            self.state = STOPPING
            self._stop_worker(session, False)
            self._finish_stop(session)
        elif self.state == STOPPING and session is not None:
            thread = session.stop_thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(STOP_JOIN_S)
            self._finish_stop(session)
        cast = self.cast
        if cast is not None:
            cast.close()
            self.cast = None
        self.state = IDLE
