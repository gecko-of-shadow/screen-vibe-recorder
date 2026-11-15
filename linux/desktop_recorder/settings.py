"""settings.txt, same keys as the Windows build, plus Linux-only lines.

This module is pure: it does not import gi, Xlib or cairo.
The parse rules are a port of RecorderCore.ParseSettings (Windows).
"""

from __future__ import annotations

import copy
import math
import os
import re
from dataclasses import dataclass, field

from .geometry import Rect
from .hotkey import text_of, try_set

DEFAULT_FPS = 10.0
MIN_FPS = 0.2
MAX_FPS = 60.0

BACKEND_DDAGRAB = "ddagrab"
BACKEND_GDIGRAB = "gdigrab"
ENCODER_AUTO = "auto"
ENCODER_NVENC = "h264_nvenc"
ENCODER_X264 = "libx264"
CHROMA_420 = "yuv420"
CHROMA_444 = "yuv444"
MODE_FIXED = "fixed"
MODE_CHANGES = "changes"

_BACKENDS = (BACKEND_DDAGRAB, BACKEND_GDIGRAB)
_ENCODERS = (ENCODER_AUTO, ENCODER_NVENC, ENCODER_X264)
_CHROMAS = (CHROMA_420, CHROMA_444)
_MODES = (MODE_FIXED, MODE_CHANGES)

# Same as C# int.TryParse with NumberStyles.Integer: ASCII digits, optional sign, spaces.
# Python int() alone also accepts "_" and non-ASCII digits.
_INT_RE = re.compile(r"\s*[+-]?[0-9]+\s*")

# Old keys from Windows. Read them and drop them.
_DROPPED_KEYS = ("last_region_hotkey", "stop_hotkey")

ZERO_WAYLAND_REGION = (0, 0, 0, 0, 0, 0)


def clamp_fps(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        return DEFAULT_FPS
    if value < MIN_FPS:
        return MIN_FPS
    if value > MAX_FPS:
        return MAX_FPS
    return value


def clamp_quality(value: int) -> int:
    if value < 0:
        return 0
    if value > 2:
        return 2
    return value


def clamp_split(value: int) -> int:
    if value < 0:
        return 0
    if value > 1440:
        return 1440
    return value


def clamp_cq(value: int) -> int:
    """NVENC reads CQ 0 as "automatic", so the range starts at 1."""
    if value < 1:
        return 1
    if value > 51:
        return 51
    return value


def normalize_backend(value: str) -> str:
    return BACKEND_GDIGRAB if value == BACKEND_GDIGRAB else BACKEND_DDAGRAB


def normalize_encoder(value: str) -> str:
    return value if value in (ENCODER_NVENC, ENCODER_X264) else ENCODER_AUTO


def normalize_chroma(value: str) -> str:
    return CHROMA_444 if value == CHROMA_444 else CHROMA_420


def normalize_mode(value: str) -> str:
    return MODE_CHANGES if value == MODE_CHANGES else MODE_FIXED


def normalize_region(r: Rect) -> Rect:
    if r.w > 0 and r.h > 0:
        return r
    return Rect()


def normalize_wayland_region(values: tuple[int, ...]) -> tuple[int, int, int, int, int, int]:
    if len(values) != 6 or values[4] <= 0 or values[5] <= 0:
        return ZERO_WAYLAND_REGION
    return (values[0], values[1], values[2], values[3], values[4], values[5])


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "DesktopRecorder")


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.txt")


def runtime_dir() -> str:
    """Folder for the control socket (8.4). This function only gives the path.

    The caller (InstanceServer) makes the folder. Do not chmod config_dir().
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or ""
    if base and os.path.isdir(base):
        return os.path.join(base, "desktop-recorder")
    return config_dir()


def default_folder() -> str:
    return os.path.join(os.path.expanduser("~"), "Recordings")


def region_text(r: Rect) -> str:
    return f"{r.x},{r.y},{r.w},{r.h}"


@dataclass
class Settings:
    folder: str = ""
    fps: float = DEFAULT_FPS
    quality: int = 1
    split_minutes: int = 30
    record_on_launch: bool = True
    copy_to_clipboard: bool = True
    play_sounds: bool = True
    show_pointer: bool = True
    hotkey_modifiers: int = 4 | 8
    hotkey_key: str = "D"
    capture_backend: str = BACKEND_DDAGRAB
    encoder: str = ENCODER_AUTO
    chroma: str = CHROMA_420
    frame_rate_mode: str = MODE_CHANGES
    nvenc_cq: int = 23
    selector_crosshair: bool = False
    selector_magnifier: bool = True
    selector_position: bool = True
    region: Rect = field(default_factory=Rect)
    last_region: Rect = field(default_factory=Rect)
    record_audio: bool = True
    start_on_login: bool = False
    wayland_restore_token: str = ""
    wayland_region: tuple[int, int, int, int, int, int] = ZERO_WAYLAND_REGION
    wayland_frame: bool = True
    extra_lines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.folder:
            self.folder = default_folder()

    @property
    def hotkey_text(self) -> str:
        return text_of(self.hotkey_modifiers, self.hotkey_key)


def copy_settings(s: Settings) -> Settings:
    """Deep copy. extra_lines is a new list."""
    return copy.deepcopy(s)


def _parse_int(val: str) -> int | None:
    if not _INT_RE.fullmatch(val):
        return None
    return int(val)


def _parse_ints(val: str, count: int) -> tuple[int, ...] | None:
    parts = val.split(",")
    if len(parts) != count:
        return None
    numbers = []
    for part in parts:
        number = _parse_int(part.strip())
        if number is None:
            return None
        numbers.append(number)
    return tuple(numbers)


def _parse_rect(val: str, old: Rect) -> Rect:
    numbers = _parse_ints(val, 4)
    if numbers is None:
        return old
    return Rect(numbers[0], numbers[1], numbers[2], numbers[3])


def _apply(s: Settings, key: str, val: str) -> bool:
    """Apply one known key. Return False for an unknown key.

    A known key with a bad value keeps the value from before.
    """
    if key == "folder":
        if val and "\n" not in val and "\r" not in val:
            s.folder = val
        return True
    if key == "fps":
        try:
            s.fps = float(val)
        except ValueError:
            pass
        return True
    if key in ("quality", "split_minutes", "nvenc_cq"):
        number = _parse_int(val)
        if number is not None:
            setattr(s, key, number)
        return True
    if key in (
        "record_on_launch",
        "copy_to_clipboard",
        "play_sounds",
        "show_pointer",
        "selector_crosshair",
        "selector_magnifier",
        "selector_position",
        "record_audio",
        "start_on_login",
        "wayland_frame",
    ):
        setattr(s, key, val == "1")
        return True
    if key == "hotkey":
        updated = try_set(val, (s.hotkey_modifiers, s.hotkey_key))
        if updated is not None:
            s.hotkey_modifiers, s.hotkey_key = updated
        return True
    if key == "capture_backend":
        if val in _BACKENDS:
            s.capture_backend = val
        return True
    if key == "encoder":
        if val in _ENCODERS:
            s.encoder = val
        return True
    if key == "chroma":
        if val in _CHROMAS:
            s.chroma = val
        return True
    if key == "frame_rate_mode":
        if val in _MODES:
            s.frame_rate_mode = val
        return True
    if key == "region":
        s.region = _parse_rect(val, s.region)
        return True
    if key == "last_region":
        s.last_region = _parse_rect(val, s.last_region)
        return True
    if key == "wayland_restore_token":
        s.wayland_restore_token = val
        return True
    if key == "wayland_region":
        numbers = _parse_ints(val, 6)
        if numbers is not None:
            s.wayland_region = normalize_wayland_region(numbers)
        return True
    if key in _DROPPED_KEYS:
        return True
    return False


def _normalize(s: Settings) -> None:
    s.fps = clamp_fps(s.fps)
    s.quality = clamp_quality(s.quality)
    s.split_minutes = clamp_split(s.split_minutes)
    s.capture_backend = normalize_backend(s.capture_backend)
    s.encoder = normalize_encoder(s.encoder)
    s.chroma = normalize_chroma(s.chroma)
    s.frame_rate_mode = normalize_mode(s.frame_rate_mode)
    s.nvenc_cq = clamp_cq(s.nvenc_cq)
    s.region = normalize_region(s.region)
    s.last_region = normalize_region(s.last_region)
    s.wayland_region = normalize_wayland_region(tuple(s.wayland_region))


def parse_settings(text: str, defaults: Settings | None = None) -> Settings:
    result = copy_settings(defaults) if defaults is not None else Settings()
    # As on Windows: the extra lines of the defaults are not kept.
    result.extra_lines = []
    if text is None:
        text = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not line.strip():
            continue
        eq = line.find("=")
        if eq < 1:
            result.extra_lines.append(line.strip())
            continue
        key = line[:eq].strip()
        val = line[eq + 1 :].strip()
        if not _apply(result, key, val):
            result.extra_lines.append(key + "=" + val)
    _normalize(result)
    return result


def _flag(value: bool) -> str:
    return "1" if value else "0"


def serialize_settings(settings: Settings) -> str:
    s = settings
    fps_text = f"{clamp_fps(s.fps):.3f}".rstrip("0").rstrip(".")
    wayland = normalize_wayland_region(tuple(s.wayland_region))
    lines = [
        "folder=" + (s.folder or ""),
        "fps=" + fps_text,
        "quality=" + str(clamp_quality(s.quality)),
        "split_minutes=" + str(clamp_split(s.split_minutes)),
        "record_on_launch=" + _flag(s.record_on_launch),
        "copy_to_clipboard=" + _flag(s.copy_to_clipboard),
        "play_sounds=" + _flag(s.play_sounds),
        "show_pointer=" + _flag(s.show_pointer),
        "hotkey=" + s.hotkey_text,
        "capture_backend=" + normalize_backend(s.capture_backend),
        "encoder=" + normalize_encoder(s.encoder),
        "chroma=" + normalize_chroma(s.chroma),
        "frame_rate_mode=" + normalize_mode(s.frame_rate_mode),
        "nvenc_cq=" + str(clamp_cq(s.nvenc_cq)),
        "selector_crosshair=" + _flag(s.selector_crosshair),
        "selector_magnifier=" + _flag(s.selector_magnifier),
        "selector_position=" + _flag(s.selector_position),
        "region=" + region_text(normalize_region(s.region)),
        "last_region=" + region_text(normalize_region(s.last_region)),
        "record_audio=" + _flag(s.record_audio),
        "start_on_login=" + _flag(s.start_on_login),
        "wayland_restore_token=" + (s.wayland_restore_token or ""),
        "wayland_region=" + ",".join(str(n) for n in wayland),
        "wayland_frame=" + _flag(s.wayland_frame),
    ]
    for extra in s.extra_lines or []:
        if extra is None:
            continue
        line = extra.strip()
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"


def load_settings(path: str | None = None) -> Settings:
    """Read the file. A missing or bad file gives the defaults. A BOM is ignored, as on Windows."""
    target = path or settings_path()
    try:
        if not os.path.exists(target):
            return Settings()
        with open(target, "r", encoding="utf-8-sig", newline="") as handle:
            return parse_settings(handle.read())
    except (OSError, UnicodeDecodeError, ValueError):
        return Settings()


def save_settings(settings: Settings, path: str | None = None) -> None:
    """UTF-8 without BOM, LF line ends, temp file, fsync, then replace."""
    target = path or settings_path()
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(serialize_settings(settings))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
