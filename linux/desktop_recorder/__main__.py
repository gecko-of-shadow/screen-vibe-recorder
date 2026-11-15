"""Command line: the tray, plus --select, --toggle, --check and --smoke (DESIGN.md 8.6).

Only pure modules load at module level. GTK (gi) loads only in the branches that
start a tray, so --help, --check, --smoke and --toggle with a running tray load no GTK.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from . import messages
from .ffmpeg_cmd import capture_backend


def _resolve_ffmpeg() -> str | None:
    forced = os.environ.get("DESKTOP_RECORDER_FFMPEG", "").strip()
    if forced:
        return forced
    return shutil.which("ffmpeg")


def _prepare_gdk_backend() -> None:
    """Set GDK_BACKEND before ui (and so Gtk) loads. A Wayland session also has XWayland."""
    if capture_backend() == "wayland" and os.environ.get("DISPLAY") and not os.environ.get("GDK_BACKEND"):
        os.environ["GDK_BACKEND"] = "wayland"


def _run_tray(select: bool = False, token: str = "", from_toggle: bool = False) -> int:
    _prepare_gdk_backend()
    from .ui import run

    return run(select=select, token=token, from_toggle=from_toggle)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _run_tray()
    command = args[0]
    if command in ("-h", "--help"):
        print(messages.HELP)
        return 0
    if command == "--select":
        return _run_tray(select=True)
    if command == "--toggle":
        return toggle()
    if command == "--check":
        return check()
    if command == "--smoke":
        try:
            seconds = float(args[1]) if len(args) > 1 else 1.5
        except ValueError:
            print(messages.HELP, file=sys.stderr)
            return 2
        return smoke(seconds)
    print(messages.HELP, file=sys.stderr)
    return 2


def _activation_token() -> str:
    return os.environ.get("XDG_ACTIVATION_TOKEN") or os.environ.get("DESKTOP_STARTUP_ID") or ""


def toggle() -> int:
    from .single_instance import CLIENT_TIMEOUT, is_reachable, send_command, socket_path

    token = _activation_token()
    path = socket_path()
    if not is_reachable(path):
        # No tray runs: this process becomes the tray and opens the selector.
        return _run_tray(select=True, token=token, from_toggle=True)
    command = "TOGGLE " + token if token else "TOGGLE"
    reply = send_command(path, command, CLIENT_TIMEOUT)
    if reply is None:
        print(messages.DID_NOT_ANSWER, file=sys.stderr)
        return 0
    print(reply)
    return 0


def check() -> int:
    from .audio import find_monitor
    from .encoders import NvencProbe

    ffmpeg = _resolve_ffmpeg()
    print("ffmpeg:", ffmpeg or "missing")
    print("backend:", capture_backend())
    print("display:", os.environ.get("DISPLAY", ""))
    print("wayland:", os.environ.get("WAYLAND_DISPLAY", ""))
    print("audio:", find_monitor() or "none")
    usable = bool(ffmpeg) and NvencProbe().usable(ffmpeg or "")
    print("nvenc:", "usable" if usable else "not usable")
    return 0 if ffmpeg else 1


def _probe_video(path: str) -> tuple[int, int, float] | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        print("ffprobe was not found.", file=sys.stderr)
        return None
    done = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "default=nw=1", path],
        check=False, capture_output=True, text=True,
    )
    if done.returncode != 0:
        print(done.stderr.strip(), file=sys.stderr)
        return None
    values: dict[str, str] = {}
    for line in done.stdout.splitlines():
        key, _sep, value = line.partition("=")
        values.setdefault(key.strip(), value.strip())
    try:
        return int(values["width"]), int(values["height"]), float(values["duration"])
    except (KeyError, ValueError):
        return None


def smoke(seconds: float) -> int:
    """X11 only: record Rect(0,0,320,240) with x264 in fixed mode, then check the file."""
    from .ffmpeg_cmd import BACKEND_X11, CapturePlan, x11_argv
    from .ffstats import format_stats, session_files, snapshot, total_bytes, x11_stats
    from .geometry import Rect
    from .recording import FfmpegProcess
    from .settings import ENCODER_X264, MODE_FIXED, Settings

    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg:
        print(messages.FFMPEG_MISSING, file=sys.stderr)
        return 1
    folder = tempfile.mkdtemp(prefix="desktop-recorder-smoke-")
    settings = Settings(
        folder=folder,
        fps=10,
        split_minutes=0,
        record_audio=False,
        record_on_launch=False,
        play_sounds=False,
        copy_to_clipboard=False,
        encoder=ENCODER_X264,
        frame_rate_mode=MODE_FIXED,
    )
    # Build the plan directly: plan_x11 would make a region equal to a 320x240 screen "whole screen" (D21).
    plan = CapturePlan(BACKEND_X11, ENCODER_X264, Rect(0, 0, 320, 240), 320, 240, ())
    before = snapshot(folder)
    argv = x11_argv(settings, plan, datetime.now(), os.environ.get("DISPLAY"), None, ffmpeg)
    proc = FfmpegProcess(argv)
    error = proc.start()
    if error:
        print(error, file=sys.stderr)
        return 1
    time.sleep(max(0.5, seconds))
    proc.request_stop(settings.fps, use_q=True)
    files = session_files(folder, before)
    print(format_stats(x11_stats(proc.progress(), total_bytes(files))))
    if not files:
        print("Recording produced no file. " + proc.error_text(), file=sys.stderr)
        return 1
    print(files[0])
    probed = _probe_video(files[0])
    if probed is None:
        return 1
    width, height, duration = probed
    print(f"width={width} height={height} duration={duration:.3f}")
    if width != 320 or height != 240 or duration < 0.2:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
