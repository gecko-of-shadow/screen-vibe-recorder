"""FFmpeg argument lists, the capture plan and the fallback rule (spec section 5).

This module is pure: it does not import gi, Xlib or cairo.
The rules are a port of RecorderCore.PlanCapture, BuildCaptureArguments
and ChooseFallback (Windows). The argv is for Linux, so paths use "/".
"""

from __future__ import annotations

import math
import os
import posixpath
from dataclasses import dataclass
from datetime import datetime

from .geometry import Rect, make_even
from .settings import (
    CHROMA_444,
    ENCODER_AUTO,
    ENCODER_NVENC,
    ENCODER_X264,
    MODE_CHANGES,
    Settings,
    clamp_cq,
    clamp_fps,
    clamp_quality,
    clamp_split,
)

CRF = (32, 27, 21)

BACKEND_X11 = "x11grab"
BACKEND_PIPEWIRE = "pipewire"

# NVENC H.264 frame size limits (same values as RecorderCore.cs).
NVENC_MIN = (146, 50)
NVENC_MAX = 4096

NOTE_REGION_OFF_SCREEN = "The saved region is not on the screen now. Recording the whole desktop."
REASON_NVENC_FAILED = "NVENC failed. Recording again with libx264."
REASON_FFMPEG_FAILED_NVENC = "FFmpeg failed with NVENC. Recording again with libx264."

# Text marks of an NVENC error in the FFmpeg output (RecorderCore.LooksLikeNvencError).
_NVENC_ERROR_MARKS = ("nvenc", "nvcuda", "cuda", "nvencodeapi", "no capable devices", "openencodesessionex")

# A fallback is only for a start that fails soon (ms).
FALLBACK_WINDOW_MS = 10000


@dataclass(frozen=True)
class CapturePlan:
    backend: str             # "x11grab" or "pipewire"
    encoder: str             # "h264_nvenc" or "libx264"
    region: Rect | None      # x11grab: screen px, None = whole X screen. pipewire: crop in stream px, never None.
    width: int               # encoded width, even
    height: int              # encoded height, even
    notes: tuple[str, ...]   # user notes, in order


# ---------------------------------------------------------------- derived values (5.1)


def format_fps(fps: float) -> str:
    text = f"{clamp_fps(fps):.3f}".rstrip("0").rstrip(".")
    return text or "0"


def stamp_of(when: datetime) -> str:
    return when.strftime("%Y-%m-%d_%H-%M-%S_") + f"{when.microsecond // 1000:03d}"


def gop_of(fps: float) -> int:
    return max(2, round(clamp_fps(fps) * 30))


def lookahead_of(fps: float) -> int:
    return max(0, min(40, round(clamp_fps(fps) * 2)))


def threads_of(fps: float) -> int:
    return max(1, min(16, math.ceil(clamp_fps(fps))))


def mpdecimate_max(fps: float) -> int:
    """The longest run of dropped frames. The file then keeps one frame each second at least."""
    return max(1, math.ceil(clamp_fps(fps)) - 1)


def pix_fmt_of(settings: Settings) -> str:
    return "yuv444p" if settings.chroma == CHROMA_444 else "yuv420p"


def crf_of(settings: Settings) -> int:
    return CRF[clamp_quality(settings.quality)]


def nvenc_cq_of(settings: Settings) -> int:
    """The CQ for the quality level. nvenc_cq is the "Balanced" value. Default: 28 / 23 / 17."""
    return clamp_cq(clamp_cq(settings.nvenc_cq) + crf_of(settings) - CRF[1])


# ---------------------------------------------------------------- session helpers (no change)


def x11_target(display: str | None) -> str:
    text = (display or ":0").strip()
    if text.startswith("unix:"):
        text = text[5:]
    _head, sep, tail = text.rpartition(":")
    if sep and tail and "." not in tail:
        return text + ".0"
    return text


def capture_backend() -> str:
    forced = os.environ.get("DESKTOP_RECORDER_CAPTURE", "").strip().lower()
    if forced in ("x11", "wayland"):
        return forced
    session = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if os.environ.get("WAYLAND_DISPLAY") or session == "wayland":
        return "wayland"
    return "x11"


# ---------------------------------------------------------------- argv (5.2)


def _head(ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y"]


def _audio_input(audio_device: str | None) -> list[str]:
    if not audio_device:
        return []
    return ["-thread_queue_size", "1024", "-f", "pulse", "-i", audio_device]


def _tail(settings: Settings, plan: CapturePlan, when: datetime, audio: bool, vf: list[str]) -> list[str]:
    """Filters, frame-rate mode, encoder, audio codec and output (5.2 steps 4 to 8)."""
    fps = clamp_fps(settings.fps)
    changes = settings.frame_rate_mode == MODE_CHANGES
    chroma444 = settings.chroma == CHROMA_444
    nvenc = plan.encoder == ENCODER_NVENC
    pix = pix_fmt_of(settings)
    gop = str(gop_of(fps))
    args: list[str] = []

    parts = list(vf)
    if changes:
        # mpdecimate needs a YUV input. Convert once to the target chroma.
        parts.append(f"format={pix}")
        # hi=256, lo=128 (defaults 768, 320), as in the Windows app v2.0.1. The defaults
        # dropped one-character look-alike changes (x.y to x,y) that stayed less than 1 s.
        parts.append(f"mpdecimate=hi=256:lo=128:frac=0.33:max={mpdecimate_max(fps)}")
    if parts:
        args += ["-vf", ",".join(parts)]

    # Always set the mode. In "fixed" mode a late capture becomes an FFmpeg dup= (D5).
    args += ["-fps_mode", "vfr" if changes else "cfr"]

    if nvenc:
        args += ["-c:v", ENCODER_NVENC, "-preset", "p4", "-rc", "vbr",
                 "-cq", str(nvenc_cq_of(settings)), "-b:v", "0"]
        if chroma444:
            args += ["-profile:v", "high444p"]
            if not changes:
                # The input is RGB. NVENC converts it to 4:2:0 unless rgb_mode says 4:4:4.
                args += ["-rgb_mode", "yuv444"]
        args += ["-g", gop]
    else:
        args += ["-c:v", ENCODER_X264, "-preset", "veryfast", "-tune", "stillimage",
                 "-crf", str(crf_of(settings)),
                 "-x264-params", f"rc-lookahead={lookahead_of(fps)}",
                 "-threads", str(threads_of(fps)),
                 "-g", gop,
                 "-pix_fmt", pix]

    if audio:
        args += ["-c:a", "aac", "-b:a", "128k"]

    split = clamp_split(settings.split_minutes)
    stamp = stamp_of(when)
    if split > 0:
        seconds = split * 60
        args += ["-force_key_frames", f"expr:gte(t,n_forced*{seconds})"]
        if nvenc:
            # A new segment must start on an IDR frame to play alone.
            args += ["-forced-idr", "1"]
        args += [
            "-f", "segment",
            "-segment_time", str(seconds),
            "-segment_format", "mp4",
            "-segment_format_options",
            "movflags=+frag_keyframe+empty_moov:frag_duration=2000000:flush_packets=1",
            "-reset_timestamps", "1",
            # The segment muxer reads "%" as a format token, so double it in the folder.
            posixpath.join(settings.folder.replace("%", "%%"), f"desktop_{stamp}_%03d.mp4"),
        ]
    else:
        args += [
            "-movflags", "+frag_keyframe+empty_moov",
            "-frag_duration", "2000000",
            "-flush_packets", "1",
            posixpath.join(settings.folder, f"desktop_{stamp}.mp4"),
        ]
    return args


def x11_argv(settings: Settings, plan: CapturePlan, when: datetime, display: str | None,
             audio_device: str | None, ffmpeg: str = "ffmpeg") -> list[str]:
    fps_text = format_fps(settings.fps)
    mouse = "1" if settings.show_pointer else "0"
    target = x11_target(display)
    args = _head(ffmpeg)
    args += ["-thread_queue_size", "128", "-f", "x11grab", "-framerate", fps_text, "-draw_mouse", mouse]
    vf: list[str] = []
    if plan.region is None:
        args += ["-i", target]
        vf.append("crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0")
    else:
        args += ["-video_size", f"{plan.width}x{plan.height}",
                 "-i", f"{target}+{plan.region.x},{plan.region.y}"]
    args += _audio_input(audio_device)
    args += _tail(settings, plan, when, bool(audio_device), vf)
    return args


def wayland_argv(settings: Settings, plan: CapturePlan, when: datetime,
                 audio_device: str | None, ffmpeg: str = "ffmpeg") -> list[str]:
    args = _head(ffmpeg)
    args += ["-f", "rawvideo", "-pixel_format", "bgr0", "-video_size", f"{plan.width}x{plan.height}",
             "-framerate", format_fps(settings.fps), "-i", "pipe:0"]
    if audio_device:
        args += _audio_input(audio_device) + ["-shortest"]
    args += _tail(settings, plan, when, bool(audio_device), [])
    return args


# ---------------------------------------------------------------- plan (5.3)


def _resolve_encoder(settings: Settings, nvenc_ok: bool, force_x264: bool) -> str:
    if force_x264:
        return ENCODER_X264
    if settings.encoder == ENCODER_X264:
        return ENCODER_X264
    if settings.encoder == ENCODER_NVENC:
        return ENCODER_NVENC
    return ENCODER_NVENC if nvenc_ok else ENCODER_X264


def _nvenc_size_note(width: int, height: int) -> str | None:
    """None when NVENC can encode the size, else the note that says why libx264 records it."""
    if width > NVENC_MAX or height > NVENC_MAX:
        return f"NVENC cannot encode {width}x{height} (maximum {NVENC_MAX} px). libx264 records it."
    if width < NVENC_MIN[0] or height < NVENC_MIN[1]:
        return f"NVENC cannot encode {width}x{height} (too small). libx264 records it."
    return None


def _finish(backend: str, encoder: str, region: Rect | None, width: int, height: int,
            notes: list[str]) -> CapturePlan:
    if encoder == ENCODER_NVENC:
        why = _nvenc_size_note(width, height)
        if why is not None:
            encoder = ENCODER_X264
            notes.append(why)
    return CapturePlan(backend, encoder, region, width, height, tuple(notes))


def plan_x11(settings: Settings, region: Rect | None, screen: Rect, nvenc_ok: bool,
             force_x264: bool = False) -> CapturePlan:
    encoder = _resolve_encoder(settings, nvenc_ok, force_x264)
    notes: list[str] = []
    plan_region: Rect | None = None
    if region is not None and not region.is_empty:
        r = make_even(region.intersect(screen))
        if r.is_empty:
            notes.append(NOTE_REGION_OFF_SCREEN)
        elif r != make_even(screen):
            plan_region = r
        # Else the region is the whole screen (D21): plan_region stays None.
    if plan_region is None:
        width, height = screen.w & ~1, screen.h & ~1
    else:
        width, height = plan_region.w, plan_region.h
    return _finish(BACKEND_X11, encoder, plan_region, width, height, notes)


def plan_wayland(settings: Settings, crop: Rect, nvenc_ok: bool, force_x264: bool = False) -> CapturePlan:
    encoder = _resolve_encoder(settings, nvenc_ok, force_x264)
    return _finish(BACKEND_PIPEWIRE, encoder, crop, crop.w, crop.h, [])


# ---------------------------------------------------------------- fallback (5.4)


def looks_like_nvenc_error(text: str) -> bool:
    low = (text or "").lower()
    return any(mark in low for mark in _NVENC_ERROR_MARKS)


def choose_fallback(plan: CapturePlan, settings: Settings, error_text: str,
                    elapsed_ms: int) -> tuple[bool, str] | None:
    """Returns (force_x264, reason) for a retry, or None when no fallback is left."""
    if elapsed_ms > FALLBACK_WINDOW_MS:
        return None
    nvenc_auto = plan.encoder == ENCODER_NVENC and settings.encoder == ENCODER_AUTO
    if not nvenc_auto:
        return None
    # Rule 1. The caller also calls NvencProbe.mark_unusable.
    if looks_like_nvenc_error(error_text):
        return (True, REASON_NVENC_FAILED)
    # Rule 2 (ddagrab to gdigrab) has no Linux equivalent. Rule 3:
    return (True, REASON_FFMPEG_FAILED_NVENC)
