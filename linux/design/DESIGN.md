# Desktop Recorder for Ubuntu 24.04: design spec for the Linux port

Branch `linux-port`, base `cb07dff`. Target: Ubuntu Desktop 24.04 LTS (GNOME 46). Wayland is the default session. The X11 session is optional. The code is Python 3.12 with GTK3 through PyGObject, and uses only apt packages.

This spec replaces the old full-screen Linux app in `linux/desktop_recorder/`. It is the only input for the coders. You do not need the three reports.

---

## 0. Rules for all coders

- Do not edit files outside the files that section 13 gives to you.
- Pure modules must not import `gi`, `Xlib` or `cairo` at module level. Section 13 marks each module "pure" or "GUI".
- Start every `subprocess.Popen` of FFmpeg on the GTK main thread. Section 6.1 tells why.
- Write LF line endings. The worktree has `core.autocrlf=true`. Owner C8 does the first step, before any other owner starts: the `.gitattributes` rules (section 15.4), `tests/linux_skip.py` (14.0) and the `tests/test_linux.py` cleanup (section 13).
- Do not change files in the repo root (`*.cs`, `build.cmd`), except the files named in section 13.
- Copy all user-visible text exactly as this spec gives it. All texts are in `messages.py` (section 13, C7) or in the module that section 13 names.
- Call the `Controller` and all GTK code on the GTK main thread only. Section 8.7 gives the thread rules.
- Every pure module must import on Windows Python 3.12 too. Do not use `fcntl`, `socket.AF_UNIX`, `ctypes.CDLL(None)`, `prctl`, `gi` or `Xlib` at module level. Use them inside functions, or guard them (6.1).
- Every test file uses `tests/linux_skip.py` (section 14.0) to skip a test that needs Linux, a display, `gi`, `Xlib`, `ffmpeg` or `AF_UNIX`. With env `DESKTOP_RECORDER_REQUIRE_GUI=1`, the same check fails the test.
- Unit-test command on the Windows dev PC (from the repo root, Git Bash): `PYTHONPATH=linux python -m unittest discover -s tests -p 'test_linux_*.py' -v`. All `test_linux_*.py` files must pass or skip there.

---

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Capture backend | The session type selects it. X11 uses FFmpeg `x11grab`. Wayland uses the ScreenCast portal, then GStreamer `pipewiresrc`, then raw frames on FFmpeg stdin. Env `DESKTOP_RECORDER_CAPTURE=x11\|wayland` overrides the choice (for tests). There is no settings key for it. |
| D2 | `capture_backend` key | Linux reads it with the Windows rule, keeps it, writes it, and never uses it. A Windows file then round-trips. |
| D3 | Linux-only keys | `record_audio`, `start_on_login`, `wayland_restore_token`, plus the new keys `wayland_region` and `wayland_frame`. The Linux-only keys come after the Windows keys. |
| D4 | Defaults | fps 10, `frame_rate_mode=changes`, quality 1 (Balanced), `show_pointer=1`, `encoder=auto` (NVENC, then x264), `chroma=yuv420`, `nvenc_cq=23`. These are the same as on Windows. |
| D5 | Dropped and duplicate frames | X11 fixed mode adds `-fps_mode cfr`, so a late capture becomes an FFmpeg `dup=`. Wayland counts late ticks itself (section 7.3). The status line uses one formula on all paths: real = max(0, frame − dup). |
| D6 | FFmpeg ends with the app | `prctl(PR_SET_PDEATHSIG, SIGTERM)` in `preexec_fn`, then a check of `getppid()`. Spawn on the main thread only. |
| D7 | Border at the screen edge | Linux has no exclude-from-capture API. A side that cannot be outside the region is not drawn. If the Stop button has no place outside the region, it is not shown. The Windows "inside the region" positions are not ported. |
| D8 | Selector | One pure state machine (`selector_model.py`) and one GTK view (`selector_gtk.py`) for both shells. The X11 shell is one override-redirect popup with a seat grab. The Wayland shell is one fullscreen window for each shared monitor, and shows a frozen frame from the stream. |
| D9 | Wayland coordinates | All Wayland region math uses stream pixels of one stream. The widget-to-image mapping is one pure function. Section 11.4 gives the formulas. |
| D10 | Wayland frame | Best effort: the border is drawn as override-redirect windows on XWayland (`DISPLAY`), in logical layout px, with a 1 px safety gap. There is no Stop button on Wayland. Key `wayland_frame=0` turns the border off. UNVERIFIED. |
| D11 | Hotkey | X11: `XGrabKey`, with an auto-repeat filter. Wayland: a GNOME custom keybinding that runs `desktop-recorder --toggle`. If no tray runs, `--toggle` starts the tray and opens the selector. |
| D12 | Encoders | `libx264 -preset veryfast`, as on Windows (not `medium`). NVENC argv is the same as on Windows. `bgr0` is the raw input format on both paths. |
| D13 | Save in Settings | Save never restarts a running recording. This is Windows decision 7. |
| D14 | Version | `__version__ = "2.1.0"`. Bran can change it. |
| D15 | Start notification (parity) | A start from the selector and a fallback retry always show "Recording started". A start at app launch (`start_saved_region`) shows it only when it has a note. This is the Windows rule (`StartSavedRegion(true, false)`). Every start, also a retry, writes the stderr line `Desktop Recorder: plan <backend> <encoder>`. This line is not a notification. Tests use it. |
| D16 | Fallback retry (parity) | Each retry takes a new folder snapshot and new stats, on both paths. The file of the failed start stays in the folder. It is not copied and not counted. This is the Windows rule (`RecordingSession.Start`). |
| D17 | Wayland retry pump | The retry calls `FramePump.restart(write)`. It keeps the latest frame and the crop, and sets the counters to zero. A new pump is not used, because a still screen sends no new frame. |
| D18 | Wayland first frame | After accept, the ticker starts only when a frame newer than the accept frame comes in, or after 500 ms. Thus frame 0 does not show the selector (7.2). |
| D19 | Threads | The `Controller` runs on the GTK main thread only. The socket thread, the hotkey thread, GStreamer and the FFmpeg reader send their events with `GLib.idle_add` (8.7). `Controller.toggle` returns at once and does long work in later idle callbacks. |
| D20 | Wayland stride | `frame_stride(size, width, height)` (7.1) gives the row stride from the buffer size. No `GstVideo` typelib is needed. A size that does not fit stops the recording with an error. |
| D21 | X11 whole screen | `plan_x11` sets `plan.region = None` when the even region equals `make_even(screen)`. "Whole screen" means `plan.region is None` everywhere: the whole-screen argv, the status text, and no frame. Space gives this case. |
| D22 | x11grab queue | `-thread_queue_size 128` for x11grab (not 1024). A stalled encoder then holds at most 128 raw frames. The pulse audio input keeps 1024. |
| D23 | Test skips | `tests/linux_skip.py` (14.0) is the one skip rule. CI sets `DESKTOP_RECORDER_REQUIRE_GUI=1`, so a missing package fails CI and does not give a green run with skipped tests. |
| D24 | Stats without FFmpeg progress (parity) | `wayland_stats` sets `has_progress = progress is not None`. With no stats line, the text is `"Frames: unknown. File size: ... MB."`, as on Windows. |
| D25 | Window list (parity) | The window list skips no window of the app by pid. The selector window does not exist yet when the list is read. The Settings dialog can be selected, as on Windows. |
| D26 | Clipboard | No change in this port. `clipboard.py` copies `text/uri-list` only. GNOME Wayland paste is UNVERIFIED (section 16). |
| D27 | Wayland border connection | The frame opens its XWayland connection when it shows. If GNOME starts XWayland on demand, the main thread can wait about 1 s. The pump thread does not wait, so no frame is lost. This delay is accepted and named in section 16. |
| D28 | Notifications | The stderr line is written first, always. libnotify loads lazily. Any error from it is caught. Env `DESKTOP_RECORDER_NOTIFY=stderr` skips libnotify (the GUI tests set it). |
| D29 | `--toggle` | The client starts a tray only when the socket is not reachable. A reachable tray that does not answer in 6 s gives exit 0 and no UI. The selector works the same when it opens from `--toggle`, the hotkey or the tray menu (8.6, 9.3). |

---

## 2. Platform model

| Item | X11 session | Wayland session (default) |
|---|---|---|
| Capture | `ffmpeg -f x11grab` on `$DISPLAY` | Portal `org.freedesktop.portal.ScreenCast` (interface version 5 on noble), GStreamer `pipewiresrc`, Python pump, `ffmpeg -f rawvideo -i pipe:0` |
| Region units | X screen px. These are physical px. The root window origin is 0,0. | Stream px of one shared monitor. The origin is the top-left corner of that stream. |
| Saved region key | `region` (same meaning as Windows) | `wayland_region` |
| GTK scale | Integer `S = Gdk.Display.get_default().get_monitor(0).get_scale_factor()`. Physical = logical × S. | Not used. The mapping uses image size ÷ widget allocation. |
| Frozen picture | `Gdk.pixbuf_get_from_window(root, ...)`, with an FFmpeg one-frame snapshot as the fallback | The latest frame of each stream, from the pump |
| Window detection | Yes (EWMH, with `XQueryTree` as the fallback) | No. GNOME blocks `org.gnome.Shell.Introspect` for normal apps. |
| Border | python-xlib override-redirect windows with an empty input shape | Same windows on XWayland, best effort (D10) |
| Stop button | GTK POPUP window | None. Stop with the hotkey or the tray menu. |
| Hotkey | `XGrabKey` (`hotkey_x11.py`) | GNOME custom keybinding (`gnome_hotkey.py`), then `--toggle` |
| Pointer | `-draw_mouse 1\|0` | Portal `cursor_mode` 2 (shown) or 1 (hidden) |

---

## 3. Shared contracts (exact code)

### 3.1 `Rect` (in `geometry.py`, owner C2; C1 imports it)

```python
@dataclass(frozen=True)
class Rect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    @property
    def right(self) -> int: return self.x + self.w     # exclusive
    @property
    def bottom(self) -> int: return self.y + self.h    # exclusive
    @property
    def is_empty(self) -> bool: return self.w <= 0 or self.h <= 0
    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom
    def intersect(self, other: "Rect") -> "Rect":
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        x1, y1 = min(self.right, other.right), min(self.bottom, other.bottom)
        if x1 <= x0 or y1 <= y0:
            return Rect()
        return Rect(x0, y0, x1 - x0, y1 - y0)
    def intersects(self, other: "Rect") -> bool:
        return not self.intersect(other).is_empty

EMPTY = Rect()
```

### 3.2 Other dataclasses

```python
# ffstats.py (C4)
@dataclass
class FfmpegProgress:
    frames: int = 0
    dup: int = 0
    drop: int = 0

@dataclass
class RecordingStats:
    has_progress: bool
    frames: int
    dup: int
    drop: int
    file_bytes: int

# ffmpeg_cmd.py (C3)
@dataclass(frozen=True)
class CapturePlan:
    backend: str             # "x11grab" or "pipewire"
    encoder: str             # "h264_nvenc" or "libx264"
    region: Rect | None      # x11grab: screen px, None = whole X screen. pipewire: crop in stream px, never None.
    width: int               # encoded width, even
    height: int              # encoded height, even
    notes: tuple[str, ...]   # user notes, in order

# ffstats.py (C4); wayland_pump.py imports it
@dataclass
class PumpCounters:
    received: int = 0     # buffers from the source
    superseded: int = 0   # buffers replaced before a tick used them (normal: the screen changes faster than fps)
    ticks: int = 0        # frames written to FFmpeg
    fresh: int = 0        # ticks that wrote a buffer for the first time
    repeats: int = 0      # ticks that wrote the same buffer again (still screen)
    late: int = 0         # ticks written 1 interval or more after their due time
    skipped: int = 0      # ticks not written because the writer was more than 2 s behind

# portal.py (C5)
@dataclass
class PortalStreamInfo:
    node_id: int
    position: tuple[int, int] | None   # logical compositor coordinates, or None
    size: tuple[int, int] | None       # logical size, or None
    source_type: int

@dataclass
class PortalSession:
    session: str
    fd: int                  # owned fd for the PipeWire remote
    restore_token: str
    streams: list[PortalStreamInfo]
```

---

## 4. settings.txt (`settings.py`, owner C1, pure)

### 4.1 Location and format

- Path: `$XDG_CONFIG_HOME/DesktopRecorder/settings.txt`, else `~/.config/DesktopRecorder/settings.txt`. This does not change.
- Write: UTF-8 without BOM, `\n` line ends, temp file `path + ".tmp"`, `fsync`, then `os.replace`. This does not change.
- Read (a change): `load_settings` catches `OSError`, `UnicodeDecodeError` and `ValueError` from the read or the parse, and then returns `Settings()`. The current code catches nothing. A missing file also gives `Settings()`.

### 4.2 Parse rules (port of `RecorderCore.ParseSettings`)

1. Change `\r\n` and `\r` to `\n`. Split on `\n`.
2. Skip a line when `line.strip()` is empty.
3. Set `eq = line.find("=")` on the raw line (not trimmed). If `eq < 1`, append `line.strip()` to `extra_lines`.
4. Else `key = line[:eq].strip()` and `val = line[eq+1:].strip()`.
5. A known key with a bad value is consumed and keeps the value from before. It does not go into `extra_lines`.
6. Drop `last_region_hotkey` and `stop_hotkey`. Do not keep them.
7. An unknown key goes to `extra_lines` as `key + "=" + val`.
8. After the loop, clamp and normalize all fields.
9. Integer values (`quality`, `split_minutes`, `nvenc_cq`, and each part of `region`, `last_region` and `wayland_region`) must match `re.fullmatch(r"\s*[+-]?[0-9]+\s*", val)` before `int()`. Else the value is bad (rule 5). Python `int()` alone accepts `_` and non-ASCII digits, and C# does not.

### 4.3 Keys in write order

| # | Key | Field (type) | Default | Parse rule |
|---|---|---|---|---|
| 1 | `folder` | `folder: str` | `~/Recordings` | Accept when not empty and has no CR or LF. |
| 2 | `fps` | `fps: float` | `10.0` | `float(val)`. NaN or ±inf gives 10. Clamp 0.2..60. Write `f"{fps:.3f}".rstrip("0").rstrip(".")`. |
| 3 | `quality` | `quality: int` | `1` | `int(val)`, clamp 0..2. |
| 4 | `split_minutes` | `split_minutes: int` | `30` | `int(val)`, clamp 0..1440. |
| 5 | `record_on_launch` | bool | `True` | Only `"1"` is true. |
| 6 | `copy_to_clipboard` | bool | `True` | Same. |
| 7 | `play_sounds` | bool | `True` | Same. |
| 8 | `show_pointer` | bool | `True` | Same. |
| 9 | `hotkey` | `hotkey_modifiers: int`, `hotkey_key: str` | `12`, `"D"` (`Win+Shift+D`) | `hotkey.try_set` (no change). |
| 10 | `capture_backend` | `capture_backend: str` | `"ddagrab"` | Accept only the exact `"ddagrab"` or `"gdigrab"`. Linux never uses it. |
| 11 | `encoder` | `encoder: str` | `"auto"` | Exact `"auto"`, `"h264_nvenc"`, `"libx264"`. |
| 12 | `chroma` | `chroma: str` | `"yuv420"` | Exact `"yuv420"`, `"yuv444"`. |
| 13 | `frame_rate_mode` | `frame_rate_mode: str` | `"changes"` | Exact `"fixed"`, `"changes"`. |
| 14 | `nvenc_cq` | `nvenc_cq: int` | `23` | `int(val)`, clamp 1..51. |
| 15 | `selector_crosshair` | bool | `False` | Only `"1"` is true. |
| 16 | `selector_magnifier` | bool | `True` | Same. |
| 17 | `selector_position` | bool | `True` | Same. |
| 18 | `region` | `region: Rect` | `Rect()` | Exactly 4 comma-separated ints (`int(part.strip())`), else no change. If w ≤ 0 or h ≤ 0, all four become 0. X screen px. |
| 19 | `last_region` | `last_region: Rect` | `Rect()` | Same rule. |
| 20 | `record_audio` | bool | `True` | Linux only. |
| 21 | `start_on_login` | bool | `False` | Linux only. The UI reads the real state from the autostart file. |
| 22 | `wayland_restore_token` | str | `""` | Linux only. Any value. |
| 23 | `wayland_region` | `wayland_region: tuple[int,int,int,int,int,int]` | `(0,0,0,0,0,0)` | Linux only. `MX,MY,X,Y,W,H`. MX,MY = the portal `position` of the monitor. X,Y,W,H = stream px. Exactly 6 ints, else no change. If W ≤ 0 or H ≤ 0, all six become 0. |
| 24 | `wayland_frame` | bool | `True` | Linux only. |
| — | extra lines | `extra_lines: list[str]` | `[]` | Written last, in their old order, each stripped. Empty lines are skipped. |

- `Settings.hotkey_text` stays as a property.
- `region_text(r: Rect) -> str` returns `f"{r.x},{r.y},{r.w},{r.h}"`.

### 4.4 Public functions (signatures)

```python
DEFAULT_FPS = 10.0; MIN_FPS = 0.2; MAX_FPS = 60.0
def clamp_fps(value: float) -> float
def clamp_quality(value: int) -> int
def clamp_split(value: int) -> int
def clamp_cq(value: int) -> int                      # 1..51
def config_dir() -> str
def settings_path() -> str
def runtime_dir() -> str                             # see 8.4
def default_folder() -> str
def parse_settings(text: str, defaults: Settings | None = None) -> Settings
def serialize_settings(settings: Settings) -> str
def load_settings(path: str | None = None) -> Settings
def save_settings(settings: Settings, path: str | None = None) -> None
def copy_settings(s: Settings) -> Settings           # deep copy, extra_lines copied
```

---

## 5. FFmpeg argv, plan, probe and fallback (`ffmpeg_cmd.py`, `encoders.py`, owner C3, pure)

### 5.1 Derived values

| Name | Formula (Python) |
|---|---|
| `F` | `format_fps(fps)` = `f"{clamp_fps(fps):.3f}".rstrip("0").rstrip(".")` |
| `G` | `max(2, round(fps * 30))` |
| `L` | `max(0, min(40, round(fps * 2)))` |
| `T` | `max(1, min(16, math.ceil(fps)))` |
| `K` | `max(1, math.ceil(fps) - 1)` |
| `S` | `split_minutes * 60` |
| `STAMP` | `when.strftime("%Y-%m-%d_%H-%M-%S_") + f"{when.microsecond // 1000:03d}"` |
| `M` | `"1"` if `show_pointer` else `"0"` |
| `PIX` | `"yuv444p"` if `chroma == "yuv444"` else `"yuv420p"` |
| `CRF` | `(32, 27, 21)[quality]` |
| `CQ` | `clamp_cq(clamp_cq(nvenc_cq) + CRF - 27)`. The default gives 28 / 23 / 17. |

Python `round()` rounds half to even, like C# `Math.Round`.

### 5.2 Argv, in order

```python
def x11_argv(settings: Settings, plan: CapturePlan, when: datetime, display: str | None,
             audio_device: str | None, ffmpeg: str) -> list[str]
def wayland_argv(settings: Settings, plan: CapturePlan, when: datetime,
                 audio_device: str | None, ffmpeg: str) -> list[str]
```

- `ffmpeg_cmd.py` keeps `capture_backend() -> str` and `x11_target(display) -> str` with no change. It removes `wayland_ffmpeg_argv` and `wayland_pipeline`.
- Join the output path with `posixpath.join`, not `os.path.join`. The argv is for Linux, and the golden tests also run on Windows.

1. Head: `[ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y"]`
2. Video input:
   - X11 with a region: `["-thread_queue_size", "128", "-f", "x11grab", "-framerate", F, "-draw_mouse", M, "-video_size", f"{W}x{H}", "-i", f"{x11_target(display)}+{X},{Y}"]`
   - X11, whole screen: the same without `-video_size`, and `-i x11_target(display)`.
   - Wayland: `["-f", "rawvideo", "-pixel_format", "bgr0", "-video_size", f"{W}x{H}", "-framerate", F, "-i", "pipe:0"]`
   - `x11_target` does not change (`:1` gives `:1.0`).
3. Audio input, when `audio_device` is set: `["-thread_queue_size", "1024", "-f", "pulse", "-i", audio_device]`. Wayland also adds `"-shortest"`.
4. `-vf`, only when the list of parts is not empty. Join the parts with `,`:
   - `crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0` for X11 whole screen.
   - `format=PIX,mpdecimate=hi=256:lo=128:frac=0.33:max=K` when the mode is `changes` (the thresholds of Windows v2.0.1, HANDOFF 6.10).
5. Frame-rate mode, always: `["-fps_mode", "vfr"]` for `changes`, `["-fps_mode", "cfr"]` for `fixed`. This differs from Windows: see D5.
6. Encoder:
   - NVENC: `["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", CQ, "-b:v", "0"]`. For 4:4:4 add `["-profile:v", "high444p"]`, and also `["-rgb_mode", "yuv444"]` when the mode is `fixed`. Then `["-g", G]`. Do not add `-pix_fmt`.
   - x264: `["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", CRF, "-x264-params", f"rc-lookahead={L}", "-threads", T, "-g", G, "-pix_fmt", PIX]`
7. Audio codec, when there is audio: `["-c:a", "aac", "-b:a", "128k"]`
8. Output:
   - Split on: `["-force_key_frames", f"expr:gte(t,n_forced*{S})"]`, then `["-forced-idr", "1"]` (NVENC only), then `["-f", "segment", "-segment_time", S, "-segment_format", "mp4", "-segment_format_options", "movflags=+frag_keyframe+empty_moov:frag_duration=2000000:flush_packets=1", "-reset_timestamps", "1", posixpath.join(folder.replace("%", "%%"), f"desktop_{STAMP}_%03d.mp4")]`
   - Split off: `["-movflags", "+frag_keyframe+empty_moov", "-frag_duration", "2000000", "-flush_packets", "1", posixpath.join(folder, f"desktop_{STAMP}.mp4")]`

**Golden argv 1** (unit test). Settings: fps 10, quality 1, `fixed`, `yuv420`, `show_pointer=1`, split 0, folder `/home/me/Recordings`. Plan: x264, region `Rect(100,100,300,200)`. Display `:0`. Time 2026-11-14 10:20:30.456. No audio.

```
ffmpeg -hide_banner -loglevel error -stats -y -thread_queue_size 128 -f x11grab -framerate 10 -draw_mouse 1 -video_size 300x200 -i :0.0+100,100 -fps_mode cfr -c:v libx264 -preset veryfast -tune stillimage -crf 27 -x264-params rc-lookahead=20 -threads 10 -g 300 -pix_fmt yuv420p -movflags +frag_keyframe+empty_moov -frag_duration 2000000 -flush_packets 1 /home/me/Recordings/desktop_2026-11-14_10-20-30_456.mp4
```

**Golden strings** (substring checks on `" ".join(argv)`):

- X11 whole screen, `changes`, NVENC: ` -vf crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0,format=yuv420p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 -fps_mode vfr -c:v h264_nvenc -preset p4 -rc vbr -cq 23 -b:v 0 -g 300 `
- NVENC, 4:4:4, `fixed`: ` -profile:v high444p -rgb_mode yuv444 -g 300 `. In `changes` mode: ` -vf format=yuv444p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 ` and no `-rgb_mode`.
- NVENC, split 5 min: ` -force_key_frames expr:gte(t,n_forced*300) -forced-idr 1 -f segment -segment_time 300 -segment_format mp4 `
- Folder `/home/me/100%done`, split 1 → output ends with `/home/me/100%%done/desktop_..._%03d.mp4`. Split 0 → `/home/me/100%done/desktop_....mp4`.
- Wayland, 1120x892, `changes`, x264: contains ` -f rawvideo -pixel_format bgr0 -video_size 1120x892 -framerate 10 -i pipe:0 -vf format=yuv420p,mpdecimate=hi=256:lo=128:frac=0.33:max=9 -fps_mode vfr -c:v libx264 `
- Quality 0 / 2 → `-cq 28` / `-cq 17`. `nvenc_cq=50`, quality 0 → `-cq 51`.
- `show_pointer=0` → ` -draw_mouse 0 `.

### 5.3 Plan

```python
NVENC_MIN = (146, 50); NVENC_MAX = 4096
def make_even(r: Rect) -> Rect            # imported from geometry
def plan_x11(settings: Settings, region: Rect | None, screen: Rect, nvenc_ok: bool,
             force_x264: bool = False) -> CapturePlan
def plan_wayland(settings: Settings, crop: Rect, nvenc_ok: bool, force_x264: bool = False) -> CapturePlan
```

- `plan_x11`:
  - The caller passes `region=None` when no region is saved: `None if settings.region.is_empty else settings.region`. `Rect` has no `__bool__`, so never write `settings.region or None`.
  - With a region that is not empty, set `r = make_even(region.intersect(screen))`. If `r` is empty, use the whole screen and add the note `"The saved region is not on the screen now. Recording the whole desktop."`. Add this note only in this case.
  - If `r == make_even(screen)`, set `plan.region = None` (D21). Space in the selector gives this case.
  - With `plan.region is None` (no region, a region off the screen, or the whole screen), set width,height = `screen.w & ~1`, `screen.h & ~1`. No note is added for no region.
- Encoder choice:
  - `"libx264"` → x264.
  - `"h264_nvenc"` → NVENC unless `force_x264`.
  - `"auto"` → NVENC when `nvenc_ok and not force_x264`, else x264.
- NVENC size check on (width, height):
  - If w > 4096 or h > 4096, use x264 and add `f"NVENC cannot encode {w}x{h} (maximum 4096 px). libx264 records it."`.
  - If w < 146 or h < 50, use x264 and add `f"NVENC cannot encode {w}x{h} (too small). libx264 records it."`.
  - The check also applies to an explicit `h264_nvenc`.
- `plan_wayland`: `crop` is already even (from `accept_rect`). Backend `"pipewire"`. The same encoder rules apply.

### 5.4 Fallback after a failed start

```python
def choose_fallback(plan: CapturePlan, settings: Settings, error_text: str,
                    elapsed_ms: int) -> tuple[bool, str] | None
```

- Return `None` when `elapsed_ms > 10000`.
- Rule 1: the plan encoder is NVENC, `settings.encoder == "auto"`, and `error_text.lower()` contains `nvenc`, `nvcuda`, `cuda`, `nvencodeapi`, `no capable devices` or `openencodesessionex`. Return `(True, "NVENC failed. Recording again with libx264.")`. The caller also calls `NvencProbe.mark_unusable`.
- Rule 2 (Windows ddagrab → gdigrab) has no Linux equivalent. Do not port it.
- Rule 3: the plan encoder is NVENC and `settings.encoder == "auto"`. Return `(True, "FFmpeg failed with NVENC. Recording again with libx264.")`.
- Else return `None`.
- The retry plays no sound. It does not make a separate notification. The text `reason + "\nFFmpeg: " + first_error_line` goes into the normal start notification (8.2 step 5) as the first note. The retry always shows that notification (D15).
- The retry takes a new snapshot and new stats (D16).

### 5.5 NVENC probe (`encoders.py`)

```python
LIST_ARGS = ["-hide_banner", "-encoders"]
PROBE_ARGS = ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=10",
              "-frames:v", "5", "-c:v", "h264_nvenc", "-f", "null", "-"]
def encoder_listed(listing: str, name: str) -> bool   # a line whose 1st token starts with "V" and whose 2nd token == name
class NvencProbe:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None
    def usable(self, ffmpeg: str) -> bool        # cached per ffmpeg path; thread-safe (lock)
    def mark_unusable(self, ffmpeg: str) -> None # cache False until restart
    def warm_up(self, ffmpeg: str) -> None       # runs usable() on a daemon thread "nvenc-probe"
```

- Step 1: `runner([ffmpeg] + LIST_ARGS, capture_output=True, text=True, timeout=5)`.
- Step 2: `runner([ffmpeg] + PROBE_ARGS, capture_output=True, timeout=15)`. Return code 0 means usable.
- A timeout or an `OSError` means not usable.
- The probe runs only when `encoder == "auto"`.
- The tray calls `warm_up` at app start only when `record_on_launch` is false.
- The probe does not use PDEATHSIG. The timeout ends it.

---

## 6. FFmpeg process, stats and session files (`recording.py`, `ffstats.py`, owner C4, pure)

### 6.1 Spawn with PDEATHSIG

```python
# recording.py
# Resolved at import, before any fork. CDLL(None) raises on Windows, so guard it.
_libc = ctypes.CDLL(None, use_errno=True) if sys.platform.startswith("linux") else None
_PR_SET_PDEATHSIG = 1

def _child_setup(parent_pid: int) -> None:
    _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != parent_pid:
        os._exit(1)

def popen_with_pdeathsig(argv: list[str], **kwargs) -> subprocess.Popen:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("FFmpeg must start on the main thread.")
    if _libc is None:
        raise RuntimeError("FFmpeg start with PDEATHSIG needs Linux.")
    return subprocess.Popen(argv, preexec_fn=functools.partial(_child_setup, os.getpid()), **kwargs)
```

- Linux sends the signal when the **thread** that forked ends, not when the process ends. For this reason the spawn must happen on the main thread. The main thread lives as long as the app.
- FFmpeg handles SIGTERM. It closes the fragmented MP4. A file shorter than one fragment (2 s) has no readable length. This is the same limit as Windows.
- Named risk: Python documents `preexec_fn` as not safe when the process has other threads (hotkey, socket, probe, pump). The child calls only `prctl` and `getppid`, so the risk is low but not zero. The stdlib has no other way to set PDEATHSIG. Keep the code.
- The thread check comes before the platform check. Thus `test_spawn_off_main_thread_raises` runs on Windows too. Tests that start a process with `popen_with_pdeathsig` skip off Linux (14.0).

### 6.2 `FfmpegProcess`

```python
class FfmpegProcess:
    def __init__(self, argv: list[str], on_exit: Callable[[int, str], None] | None = None) -> None
    def start(self) -> str | None          # main thread. Returns an error text or None.
    pid: int | None
    started_at: float                      # time.monotonic() at start
    stopping: bool                         # True after request_stop()
    def write(self, data: bytes) -> None   # writes ALL bytes to stdin; raises BrokenPipeError / OSError
    def request_stop(self, fps: float, use_q: bool = True) -> None   # blocking; off the main thread
    def progress(self) -> FfmpegProgress | None   # last stats line, or None
    def error_text(self) -> str            # non-stats lines, at most 2000 chars, stripped
    def first_error_line(self) -> str      # first non-empty line of error_text(), or ""
    def is_running(self) -> bool
```

- `start` uses `popen_with_pdeathsig(argv, stdin=PIPE, stdout=DEVNULL, stderr=PIPE, bufsize=0)`.
  - On `OSError` it returns `f"Cannot start ffmpeg: {exc}"`.
  - Then it starts the daemon thread `ffmpeg-stderr`.
- `write`: with `bufsize=0`, `stdin` is an unbuffered `FileIO`, and one `write` call can write fewer bytes. Loop until all bytes are out: `mv = memoryview(data)`, then `while mv: n = stdin.write(mv); mv = mv[n:]` (treat `None` as 0). A lost byte would shift every later raw frame. `b"q"` uses the same loop.
- Reader thread:
  - Loop on `os.read(stderr_fd, 4096)`. Decode with `codecs.getincrementaldecoder("utf-8")(errors="replace")`, so a character split across two reads stays whole. Feed `LineSplitter`.
  - For each line: if `parse_progress(line)` gives a value, store it (the last one wins). Else append the line to the error text while the total is under 2000 chars.
  - At EOF, call `proc.wait()`, then `on_exit(returncode, error_text())`. `on_exit` runs on the reader thread. The caller marshals it with `GLib.idle_add` (8.7).
- `request_stop`:
  - With `use_q`, write `b"q"` with the `write` loop.
  - Without `use_q` (Wayland), close stdin.
  - Wait `min(15.0, 4.0 + 2.0 / max(0.2, fps))` s. Then `kill()` and wait 5 s.
  - Then join the reader thread (10 s) and close the pipes.
- The old `Recording` class is removed. `recording.py` keeps only the items above. The file stays.

### 6.3 Stats (`ffstats.py`)

```python
class LineSplitter:
    def feed(self, chunk: str) -> list[str]   # split on "\r" or "\n"; drop empty lines; cap each line at 8192 chars
    def flush(self) -> list[str]
def parse_progress(line: str) -> FfmpegProgress | None
def format_stats(stats: RecordingStats) -> str
def mb_text(file_bytes: int) -> str           # f"{file_bytes / 1048576:.2f}"
def snapshot(folder: str) -> set[str]         # paths of desktop_*.mp4 now in the folder
def session_files(folder: str, before: set[str]) -> list[str]   # new desktop_*.mp4 with size > 0, sorted by path.lower()
def total_bytes(paths: list[str]) -> int
def wayland_stats(progress: FfmpegProgress | None, pump: PumpCounters, file_bytes: int) -> RecordingStats
def x11_stats(progress: FfmpegProgress | None, file_bytes: int) -> RecordingStats
```

- `parse_progress` is a port of `TryParseProgress`:
  - The trimmed line must start with `frame=`.
  - Read `key=value` pairs. A value can start after spaces (`frame=  100`). The key is the text after the last space before `=`. The value ends at the next space.
  - `frame` must be all ASCII digits (`val.isascii() and val.isdigit()`), else return `None`. `str.isdigit()` alone is true for `"²"`, and then `int()` raises.
  - `dup` and `drop` count only when they are all ASCII digits (same check). Missing means 0.
- `format_stats`:
  - With progress: `f"Real frames: {max(0, frames - dup)} of {frames}. Duplicates: {dup}. Dropped: {drop}. File size: {mb} MB."`
  - Without progress: `f"Frames: unknown. File size: {mb} MB."`
- `x11_stats`: `has_progress = progress is not None`. The other fields come from the progress.
- `wayland_stats`:
  - `frames = progress.frames` if progress, else `pump.ticks`.
  - `dup = (progress.dup if progress else 0) + pump.late`.
  - `drop = (progress.drop if progress else 0) + pump.skipped`.
  - `has_progress = progress is not None` (D24). Without progress, `format_stats` gives `"Frames: unknown. File size: ... MB."`, as on Windows.

---

## 7. Wayland pump (`wayland_pump.py`, owner C5, pure)

### 7.1 Interfaces

```python
class Frame(Protocol):
    width: int; height: int; stride: int; seq: int      # seq: 1, 2, 3 ... per source buffer
    def crop(self, rect: Rect) -> bytes                 # BGRx rows of rect, packed (rect.w*4 per row)

def crop_rows(data: bytes | memoryview, stride: int, rect: Rect) -> bytes
def frame_stride(size: int, width: int, height: int) -> int | None
def pipewire_source(fd: int, node_id: int) -> str
def pipeline_description(source: str) -> str

class FramePump:
    def __init__(self, fps: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None
    def offer(self, frame: Frame) -> None             # any thread; keeps only the latest frame
    def latest(self) -> Frame | None
    def wait_first(self, timeout: float) -> Frame | None
    def set_crop(self, rect: Rect) -> None            # before start()
    def start(self, write: Callable[[bytes], None], after_seq: int = 0,
              fresh_wait: float = 0.5) -> None        # starts daemon thread "wayland-ticker"
    def restart(self, write: Callable[[bytes], None]) -> None   # stop(), zero the counters, start(write); keeps the latest frame and the crop
    def stop(self) -> PumpCounters                    # stops and joins (5 s); returns counters
    def counters(self) -> PumpCounters                # copy
    error: str | None                                  # set when write() raised
```

- `pipewire_source(fd, node)` returns `f"pipewiresrc fd={fd} path={node} always-copy=true do-timestamp=true"`. Do not use `pipewire-serial` or `target-object`. Noble has ScreenCast version 5.
- `pipeline_description(src)` returns `f"{src} ! videoconvert ! video/x-raw,format=BGRx ! appsink name=sink emit-signals=true sync=false max-buffers=0 drop=false"`. The appsink never drops. The callback takes each sample at once.
- `crop_rows`: for each row `y` in `rect.y .. rect.bottom-1`, take `data[y*stride + rect.x*4 : y*stride + (rect.x+rect.w)*4]`. Join the rows. Raise `ValueError` when the rect is outside `stride` or outside the data.
- `frame_stride(size, width, height)` (D20):
  - If `size == width*4*height`, return `width*4`.
  - Else if `height > 0`, `size % height == 0` and `size // height >= width*4`, return `size // height` (rows with padding).
  - Else return `None`. The caller then stops with `"Bad frame from the screen cast."`.
  - Reason: when Mutter already sends BGRx, `videoconvert` is passthrough, and the buffer can have a padded stride. `width*4` would then shear the rows with no error.

### 7.2 Ticker algorithm (exact)

```
# wait phase (D18)
start_time = clock()
loop until stop flag:
    f = latest frame
    if f is None: sleep(0.01); continue                       # no frame yet: write nothing
    if f.seq > after_seq or clock() - start_time >= fresh_wait: break
    sleep(0.01)
# tick phase
t0 = clock(); n = 0; last_seq = 0; interval = 1/fps
loop until stop flag:
    due = t0 + n*interval; now = clock()
    if now < due: sleep(min(due - now, 0.05)); continue
    behind = now - due
    if behind > 2.0:
        k = floor(behind * fps); skipped += k; n += k; continue
    f = latest frame
    if f.seq != last_seq: fresh += 1; last_seq = f.seq  else: repeats += 1
    if behind >= interval: late += 1
    write(f.crop(crop)); ticks += 1; n += 1
    on exception from write: error = str(exc); break
```

- `start(write, after_seq, fresh_wait)`: the controller passes `after_seq = latest().seq` at accept (11.3 step 5). The ticker then waits for a frame that comes after the selector closed. After `fresh_wait` s it uses the latest frame anyway. `restart` uses `after_seq=0`, so it starts at once with the kept frame.
- `restart(write)`: call `stop()`, set all counters to 0, clear `error`, then `start(write)`. The slot keeps the latest frame. A still screen sends no new frame, so a new pump would have no picture (D17).
- `offer`: `received += 1`. If the slot holds a frame that no tick used, `superseded += 1`. Then replace the slot. Use a lock.
- A blocking `write` makes the ticker late. Late ticks still write, so the video length stays equal to wall time. Late ticks show as duplicates. A gap over 2 s is skipped, and the video gets shorter. Skipped ticks show as dropped.
- A still screen gives repeats. Repeats are normal. They are not in the status line. In `changes` mode, `mpdecimate` removes them.

### 7.3 Status mapping

The status line uses `wayland_stats` (6.3). Limit, named in the README: in `changes` mode, late ticks are copies that `mpdecimate` removes, so "Real frames" can be too low by up to the late count.

---

## 8. Controller, hotkey and single instance

### 8.1 States (`capture.py`, owner C7, GUI)

| State | Meaning |
|---|---|
| `idle` | Nothing runs. |
| `portal` | Wayland only. The portal calls run, or the app waits for the first frame. |
| `selecting` | The selector is open. |
| `starting` | Selection accepted. FFmpeg is not running yet (about 60 ms on X11). |
| `recording` | FFmpeg runs. |
| `stopping` | The stop thread runs. |

| Event | idle | portal | selecting | starting | recording | stopping |
|---|---|---|---|---|---|---|
| Hotkey, tray toggle, socket `TOGGLE` | → `selecting` (X11) or → `portal` (Wayland), then open the selector in a later idle callback | ignore | ignore | ignore | stop | ignore |
| Selector accept | – | – | → starting | – | – | – |
| Selector cancel | – | – | → idle | – | – | – |
| FFmpeg exits by itself | – | – | – | – | fallback or → idle | (normal) → idle |
| Exit | quit | close portal, quit | close, quit | stop sync | stop sync | wait, quit |

- On X11 the seat grab blocks the passive hotkey grab while the selector is open. This matches "the hotkey does not cancel the selector".
- The portal nested main loop runs idle callbacks. The `portal` state guard stops a second start.
- `toggle` returns at once (D19). In `idle` it sets the new state, then schedules the work with `GLib.idle_add`: the X11 snapshot and selector, or the Wayland portal calls. Thus the socket reply is `SELECTING` and is not late, also when the GNOME share dialog is open. If the scheduled work fails, it notifies the error and sets the state to `idle`.
- The X11 selector opens the same way from every caller: the hotkey, the tray menu, a socket `TOGGLE` (from `--toggle`) and `ui.run(select=True)`. No path depends on a key that is still down or on a pointer motion (9.3).

```python
class ControllerUi(Protocol):
    def notify(self, title: str, body: str, timeout_ms: int) -> None
    def refresh(self) -> None
    def play(self, up: bool) -> None
    def present_token(self) -> str            # last activation token, may be ""

class Controller:
    state: str
    def __init__(self, ui: ControllerUi, get_settings: Callable[[], Settings],
                 save: Callable[[Settings], None], probe: NvencProbe, ffmpeg: str | None) -> None
    def toggle(self, activation_token: str = "") -> None
    def start_saved_region(self) -> None
    def stop(self, sound: bool = True) -> None      # async: frame closes and sound plays at once
    def stop_sync(self) -> None                     # for Exit and signals; no sound
    def status_text(self) -> str                    # tray row 1
    def last_stats_text(self) -> str | None         # "Last recording: ..." or None before the first stop
    def is_recording(self) -> bool
```

`status_text`:
- `idle`, `portal`, `selecting` and `stopping` give `"Not recording"`. While FFmpeg finishes the file, the tray shows the stopped state.
- `starting` and `recording` give `f"Recording at {F} fps, {W}x{H} region"`, where F is the fps of the current recording.
- An X11 recording with `plan.region is None` (D21) gives `f"Recording at {F} fps, whole desktop"`.

### 8.2 Start sequence (both paths)

1. Resolve FFmpeg: env `DESKTOP_RECORDER_FFMPEG`, else `shutil.which("ffmpeg")`. If there is none, notify `"ffmpeg was not found. Install it with: sudo apt install ffmpeg"`.
2. Check the folder:
   - An empty folder gives `"The recordings folder is empty."`.
   - If `os.makedirs` fails, notify `f"Cannot create the folder {folder}: {exc}"`.
3. Take `before = snapshot(folder)` and `when = datetime.now()`. A fallback retry also does this step again (D16).
4. Make the plan and the argv. Start `FfmpegProcess` on the main thread.
   - If `start()` returns an error, notify for 8000 ms with the error text cut to 250 chars, and set the state to `idle`.
5. On success:
   - Set the state to `recording`.
   - Write the stderr line `f"Desktop Recorder: plan {plan.backend} {plan.encoder}"` (D15). Write it at every start, also at a retry.
   - Show the frame: X11 when `plan.region is not None` (D21); Wayland when `wayland_frame=1`.
   - Play the start sound (unless this is a fallback retry).
   - Notify for 3000 ms with the text below. Show it for a selector start and for a retry. For a start at launch (`start_saved_region`), show it only when there is at least one note (D15).
   - Text: `f"Recording started ({plan.backend}, {plan.encoder})."`, then each note on a new line, in this order:
     1. The fallback note (5.4) or the saved-region note (11.3 step 8, 12.1).
     2. The plan notes (5.3).
     3. The audio note (step 6).
     4. The frame notes (10).
   - Cut the full body to 250 chars.
6. Audio: the tray probes the audio device at app start and after each Save, on a background thread. A start uses the cached device. Call `audio.probe_pulse(device, ffmpeg=path)` with the resolved FFmpeg path as a keyword.
   - When `record_audio` is on and `find_monitor()` found no device, record without audio and add the note `"System audio was not found, so this recording is silent."`.
   - When a device exists and `probe_pulse` returned False, record without audio and add the note `"System audio did not respond, so this recording is silent."`.
   - Both texts go into `messages.py`. They come from the current `capture.py`.

### 8.3 Stop sequence

1. Play the stop sound. Close the frame. Set the state to `stopping`. Refresh the tray.
2. Run the thread `ffmpeg-stop`:
   - X11: `proc.request_stop(fps, use_q=True)`.
   - Wayland: `pump.stop()`, then `proc.request_stop(fps, use_q=False)`.
3. Then `GLib.idle_add(finish_stop)`. `finish_stop` does these steps on the main thread:
   - Wayland: set the GStreamer pipeline to NULL, close the fd and close the portal session.
   - Make the stats and the stats text.
   - Copy the files to the clipboard.
   - Notify for 4000 ms:
     - One file: `"Video copied. Press Ctrl+V to paste it.\n" + stats`
     - More files: `f"{n} video files copied. Press Ctrl+V to paste them.\n" + stats`
     - Copy off, or no files: `"Recording stopped.\n" + stats`
     - Copy error: `stats + "\nCould not copy the video to the clipboard: " + msg`
   - Set the state to `idle`.
4. FFmpeg exits by itself while the state is `recording`:
   - Try `choose_fallback` first. A retry restarts FFmpeg from `GLib.idle_add`, on the main thread, with `force_x264=True`. The forced flag adds up across retries.
   - Else close the frame, refresh the tray, play the stop sound, make the stats, and update and show tray row 2. Then notify `"Desktop Recorder stopped"` for 8000 ms with `stats + "\n" + (error_text or "ffmpeg stopped.")`, cut to 250 chars. This is the Windows order (`recorder.Failed`).
5. `GLib.unix_signal_add` for SIGTERM, SIGINT and SIGHUP calls `quit()`. `quit()` calls `stop_sync()`. This is the equivalent of the Windows session end.

### 8.4 Single instance (`single_instance.py`, owner C7, pure)

- Socket path:
  - If `$XDG_RUNTIME_DIR` is set and is a folder: `$XDG_RUNTIME_DIR/desktop-recorder/control.sock`. Create the folder with mode 0700.
  - Else `config_dir()/control.sock`. Do not chmod `config_dir()`.
- Read limit: 512 bytes.
- Public pure functions: `parse_command(text: str) -> tuple[str, str]` (verb and token; strip the text, split on the first space), `is_reachable(path: str) -> bool` (the current `_reachable`, made public), `send_command(path, command, timeout: float = 6.0) -> str | None`. Use `socket.AF_UNIX` inside functions only.
- `InstanceServer(path, on_command, schedule: Callable[[Callable[[], None]], None] | None = None, wait: float = 5.0)`. The wait and the `BUSY` rule are in `single_instance.py`, so a unit test can check them:
  - For each command, the server thread makes a `threading.Event` and a reply box. It calls `schedule(job)`. `job` runs `on_command(text)`, stores the reply and sets the Event.
  - The server thread waits on the Event for `wait` s, then sends the reply. If the Event is not set in time, the reply is `BUSY`.
  - With `schedule=None`, the server thread runs `job` itself (the current behavior; `tests/test_linux.py` uses it).
  - The tray passes `schedule=lambda job: GLib.idle_add(lambda: (job(), False)[1])`. Thus `on_command` runs on the main thread. `single_instance.py` stays pure.
- The client timeout (6 s) is longer than the server wait (5 s).
- Commands and replies:

| Command | Reply |
|---|---|
| `TOGGLE` or `TOGGLE <token>` | The state after the action: `STOPPED` (idle), `SELECTING` (portal or selecting), `RECORDING` (starting or recording), `STOPPING` |
| `STATUS` | Same values. No action. |
| any, when the main thread is busy for 5 s | `BUSY` |

- A second app start shows the GTK dialog `"Desktop Recorder is already running. Look for its icon in the tray."`. This does not change.

### 8.5 Hotkey

- X11 (`hotkey_x11.py`, C7) keeps the current XGrabKey code. Add these changes:
  1. Call `XkbSetDetectableAutoRepeat(display, 1, None)` on the hotkey connection. Then handle `KeyRelease` (type 3) too. Accept a `KeyPress` only when the key is not down. A `KeyRelease` sets "not down". This is the equivalent of `MOD_NOREPEAT`.
     - Put this rule in a pure class in `hotkey_x11.py`: `class KeyRepeatFilter` with `def event(self, kind: int) -> bool` (kind 2 = press, 3 = release; True when the press must fire). `tests/test_linux_hotkey_x11.py` checks it (14.1). `hotkey_x11.py` must import on Windows (it loads `libX11` inside functions only).
     - The callback runs on the "x11-hotkey" thread. The tray passes a callback that only calls `GLib.idle_add(controller.toggle)` (8.7).
  2. Install the X error handler only during the grab and the `XSync`. Then restore the old handler with the return value of `XSetErrorHandler`.
  - If the grab fails, notify for 6000 ms `f"{hotkey} is used by another program, so that hotkey is off."`. After Save, also show a message dialog with the same text plus `" Pick a different hotkey in Settings."`.
- Wayland: `gnome_hotkey.update_gnome_shortcut` with the command `shlex.quote(command_path) + " --toggle"`. `gnome_hotkey` sends each value to `gsettings set` as a GVariant string literal, so a path with a space stays one argument.
  - `autostart.command_path()` uses `$DESKTOP_RECORDER_COMMAND` as one path (it is not split at spaces). The autostart `Exec` quotes the path as the Desktop Entry spec says.
  - If `command_path()` is empty, notify `"Install the program to enable the Wayland hotkey."`.
  - If gsettings fails, notify `"This Wayland session has no GNOME shortcut setting, so the hotkey is off. Use the tray menu."`.
- The tray toggle row shows `"    " + hotkey_text` only when the hotkey is active (X11 grab succeeded, or the gsettings write succeeded).

### 8.6 CLI (`__main__.py`, owner C7)

| Args | Behavior |
|---|---|
| none | `ui.run(select=False)` |
| `--select` | `ui.run(select=True)`: tray, `record_on_launch` ignored, open the selector when ready |
| `--toggle` | Read the token from `XDG_ACTIVATION_TOKEN`, else `DESKTOP_STARTUP_ID`, else `""`. If `is_reachable(path)` is False, run `ui.run(select=True, token=token, from_toggle=True)` in this process. This process becomes the tray and passes the token to `controller.toggle(token)`. Else send `TOGGLE <token>` (`TOGGLE` when the token is empty), print the reply to stdout, and exit 0. If the reachable tray gives no reply in 6 s, print `"Desktop Recorder did not answer."` to stderr and exit 0. This path never shows a dialog or starts a second tray (D29). Race: when two `--toggle` starts both find no tray, the one whose `InstanceServer.start()` returns False sends `TOGGLE <token>` to the winner once, prints the reply, and exits 0. It shows no "already running" dialog. |
| `--check` | Print `ffmpeg:`, `backend:`, `display:`, `wayland:`, `audio:`, `nvenc: usable\|not usable`. Exit 0 when FFmpeg exists. |
| `--smoke SEC` | X11: record `Rect(0,0,320,240)` with x264 and `fixed` for SEC s. Require ffprobe width 320, height 240 and a duration of at least 0.2 s. |
| `-h`, `--help` | Print HELP with the lines above. |

- `ui.run` signature: `run(select: bool = False, token: str = "", from_toggle: bool = False) -> int`. With `from_toggle=True`, a lost socket race does the race rule above, not the dialog.
- Imports: `__main__.py` imports only pure modules at module level. It imports `ui` (and so `gi`) only in the branches that start a tray. `--check`, `--smoke`, `--help` and `--toggle` with a running tray never load GTK.
- `GDK_BACKEND` (a change): `__main__.py` sets `GDK_BACKEND=wayland` before it imports `ui`, when `capture_backend() == "wayland"`, `DISPLAY` is set and `GDK_BACKEND` is not set. The current code sets it in `ui.run()`, after `ui.py` already imported `Gtk`, so it has no effect.
- `--smoke` and `--check` use only `recording`, `ffmpeg_cmd`, `encoders`, `ffstats`, `settings` and `audio`. `--smoke` starts FFmpeg on the main thread of the CLI process.
- After the hotkey is installed and the tray is ready, `ui.run` writes the line `Desktop Recorder: ready` to stderr. The GUI tests wait for it.
- Every notification is also written to stderr as one line: `title + ": " + body.replace("\n", " | ")`. The stderr line comes first, always (D28).

### 8.7 Threads (D19)

| Thread | Calls into the app with |
|---|---|
| Socket server (`desktop-recorder-socket`) | `GLib.idle_add` + `threading.Event`, 5 s (8.4) |
| X11 hotkey (`x11-hotkey`) | `GLib.idle_add(controller.toggle)` |
| FFmpeg reader (`ffmpeg-stderr`) | `on_exit` → `GLib.idle_add` |
| FFmpeg stop (`ffmpeg-stop`) | `GLib.idle_add(finish_stop)` |
| GStreamer streaming thread | `pump.offer` only (it has a lock); `on_error` → `GLib.idle_add` |
| Pump ticker (`wayland-ticker`) | `FfmpegProcess.write` only |
| NVENC probe (`nvenc-probe`), audio probe | Store the result under a lock. No GTK. |

- Only the main thread calls `Controller` methods, GTK, `Gdk`, `Notify` and `popen_with_pdeathsig`.

---

## 9. Region selector

### 9.1 Pure model (`selector_model.py`, owner C2)

```python
@dataclass
class SelectorOptions:
    crosshair: bool
    magnifier: bool
    position: bool

@dataclass
class Outcome:
    kind: str                 # "none" | "redraw" | "accept" | "cancel" | "warp"
    rect: Rect | None = None  # for "accept": clipped and even
    dx: int = 0
    dy: int = 0

class SelectorModel:
    def __init__(self, bounds: Rect, monitors: list[Rect], windows: list[Rect],
                 options: SelectorOptions) -> None
    cursor: tuple[int, int]
    selection: Rect | None
    hover: Rect | None
    mode: str                 # "hover" | "pending" | "creating"
    options: SelectorOptions  # C, M, P change it; the shell saves it on close
    def press(self, x: int, y: int, button: int) -> Outcome
    def motion(self, x: int, y: int, shift: bool, ctrl: bool) -> Outcome
    def release(self, x: int, y: int, button: int) -> Outcome
    def key(self, name: str, shift: bool, ctrl: bool) -> Outcome
```

All coordinates are image px. `windows` is in top-to-bottom order. It is empty on Wayland.

| Input | Rule |
|---|---|
| motion in `hover` | Set the cursor. `hover` = the first window that contains the cursor, else None. Return redraw. |
| press 1 | Set the cursor to (x,y). Compute `hover` again at (x,y), with the same rule as motion in `hover`. Set mode `pending`, anchor = (x,y). Keep `prev = selection`. |
| motion in `pending` | If `abs(dx) > 3` or `abs(dy) > 3`, set mode `creating`, and in the same call apply the "motion in `creating`" rule to this point (Ctrl is ignored on this move). Thus a drag with only one motion event (as `xdotool` sends) has a selection at release. Return redraw. |
| motion in `creating` | With Ctrl, move the anchor by the mouse delta. With Shift, use the point `geometry.square_point(anchor, cursor)`. `selection = inclusive_rect(anchor, point).intersect(bounds)`. No hover. |
| release 1 in `creating` | `r = accept_rect(selection, bounds)`. If `r` is not None, return accept. Else return to `hover`. |
| release 1 in `pending` | If `hover` is set, return accept with `accept_rect(hover, bounds)`. Else return to `hover` and do nothing. |
| press 3 | In `pending` or `creating`: `selection = prev` and mode `hover`; the selector stays open (Windows: any `mode != None`). Else, with a selection: clear it. Else return cancel. Right-click is also the cancel path when Esc does not reach a Wayland selector (9.3). |
| `Escape` | cancel |
| `Return`, `KP_Enter` | Accept the selection. Else accept `hover`. Else none. |
| `space` | accept `accept_rect(bounds, bounds)` |
| `grave`, `asciitilde` | accept `accept_rect(monitor_at(cursor) or bounds, bounds)` |
| `c`, `m`, `p` (any case) | Toggle crosshair, magnifier or position. Return redraw. |
| `Left`, `Right`, `Up`, `Down` | warp by 1 px (Shift: 10 px). The cursor stays inside the bounds. |

- Not ported: the resize handles and the double-click accept. The Windows app flow never reaches them (`Show(null)`).
- The shell calls `model.motion(px, py, False, False)` once when it opens, with the pointer position from `seat.get_pointer().get_position()` (X11) or the widget pointer position (Wayland, when known). Thus `hover` is set also when no motion event comes, for example when the pointer is already in place or moved before the window mapped.

### 9.2 Geometry (`geometry.py`, owner C2)

```python
def inclusive_rect(ax: int, ay: int, bx: int, by: int) -> Rect      # Rect(min, min, |dx|+1, |dy|+1)
def square_point(ax: int, ay: int, bx: int, by: int) -> tuple[int, int]   # side = max(|dx|,|dy|); sign 0 -> +
def make_even(r: Rect) -> Rect          # w & ~1, h & ~1; EMPTY if w < 2 or h < 2
def accept_rect(r: Rect | None, bounds: Rect) -> Rect | None   # intersect, make_even, None if empty
def monitor_at(px: int, py: int, monitors: list[Rect]) -> Rect | None
def is_on_monitors(r: Rect, monitors: list[Rect]) -> bool       # sum of intersect areas == area > 0
def border_thickness(scale: float) -> int                       # max(2, round(2 * scale))
@dataclass
class BorderLayout:
    sides: list[Rect | None]     # top, bottom, left, right; None = not drawn
    outer: Rect
    omitted: list[str]           # names from "top", "bottom", "left", "right"
def border_layout(region: Rect, t: int, monitors: list[Rect], gap: int = 0) -> BorderLayout
def stop_rect(region: Rect, outer: Rect, monitor: Rect, work_area: Rect,
              monitors: list[Rect], scale: float) -> Rect | None
def label_rect(target: Rect, box_w: int, box_h: int, bounds: Rect) -> Rect
def magnifier_rect(cx: int, cy: int, box_w: int, box_h: int, monitor: Rect) -> Rect
@dataclass(frozen=True)
class DrawMap:
    ox: float; oy: float; dw: float; dh: float; iw: int; ih: int
def fit_image(widget_w: float, widget_h: float, iw: int, ih: int) -> DrawMap
def widget_to_image(px: float, py: float, m: DrawMap) -> tuple[int, int]
def image_to_widget(ix: float, iy: float, m: DrawMap) -> tuple[float, float]
def stream_to_layout(r: Rect, position: tuple[int, int], logical: tuple[int, int],
                     stream: tuple[int, int]) -> tuple[float, float, float, float]
```

- `border_layout` (port of `ComputeBorderRects`, plus the gap `g`; with `g=0` it gives the Windows rects):
  1. Test each side with its strip before any corner extension. A side is present when `is_on_monitors(strip, monitors)`:
     - top strip: `Rect(x, y-g-t, w, t)`
     - bottom strip: `Rect(x, bottom+g, w, t)`
     - left strip: `Rect(x-g-t, y, t, h)`
     - right strip: `Rect(right+g, y, t, h)`
  2. `outer` = the region grown by `g+t` on each present side only: left edge `x - (g+t if left else 0)`, top edge `y - (g+t if top else 0)`, right edge `right + (g+t if right else 0)`, bottom edge `bottom + (g+t if bottom else 0)`.
  3. Sides (a missing side is `None`, and its name goes into `omitted`):
     - top: `Rect(outer.x, y-g-t, outer.w, t)`
     - bottom: `Rect(outer.x, bottom+g, outer.w, t)`
     - left: `Rect(x-g-t, y0, t, y1-y0)`, with `y0 = y-g if top else y` and `y1 = bottom+g if bottom else bottom`
     - right: `Rect(right+g, y0, t, y1-y0)`, same `y0` and `y1`
  4. Thus the top and bottom sides always span `outer` from left to right, as on Windows. Each end grows only when that side (left or right) is present. With `g > 0`, the left and right sides also cover the gap at the corners.
  - Linux never draws inside the region.
- `stop_rect`: port of `ComputeStopRect` steps 1 to 3 only.
  - `w = round(84*scale)`, `h = round(28*scale)`, `gap = round(4*scale)`.
  - Step 1: below the outer edge, centered, clamped to the work area.
  - Step 2: above the outer edge.
  - Step 3: top center of another monitor that does not touch the region.
  - Else return `None`.
- `label_rect`: `y = target.y - box_h - 8`. If `y < bounds.y`, set `y = target.y + 8`. Then clamp the box to the bounds. `x = target.x`, clamped.
- `magnifier_rect`: the box goes to (cx+24, cy+24). If it leaves the monitor on an axis, flip it to `c - 24 - box` on that axis. Then clamp it to the monitor.
- `fit_image`:
  - If `abs(widget_w/widget_h - iw/ih) <= 0.01 * iw/ih`, return `DrawMap(0, 0, widget_w, widget_h, iw, ih)`.
  - Else letterbox: `s = min(widget_w/iw, widget_h/ih)`, `dw = iw*s`, `dh = ih*s`, centered.
- `widget_to_image`: `ix = floor((px - ox) * iw / dw)`, clamped to `0..iw-1`. Use the same rule for y.
- `stream_to_layout`: `sx = stream_w / logical_w`, `sy = stream_h / logical_h`. The result is `(pos_x + r.x/sx, pos_y + r.y/sy, r.w/sx, r.h/sy)` in logical px.

### 9.3 View and shells (`selector_gtk.py`, owner C6, GUI)

```python
class SelectorView(Gtk.DrawingArea):
    def __init__(self, image: GdkPixbuf.Pixbuf, model: SelectorModel, monitor_rects: list[Rect],
                 coord_origin: tuple[int, int], on_outcome: Callable[[Outcome], None]) -> None
def open_x11_selector(settings: Settings, display_name: str | None,
                      on_done: Callable[[Rect | None, SelectorOptions], None]) -> str | None
def open_wayland_selector(frames: list[tuple[PortalStreamInfo, Frame]], settings: Settings,
                          token: str,
                          on_done: Callable[[int | None, Rect | None, SelectorOptions], None]) -> str | None
```

- `open_x11_selector` and `open_wayland_selector` return an error text, or None.
- `on_done` for Wayland gets `(stream_index, crop)`.
- The controller notifies `"The region selector failed: " + text` on error, or when a selector call raises.

**Drawing.** All drawing is in image px. Cairo uses `DrawMap` scale and offset with `cairo.FILTER_NEAREST`.

| Item | Spec |
|---|---|
| Background | The image. Over it, black at alpha 120/255. |
| Bright area | The selection, else `hover`. Draw the image again, clipped to it. |
| Lines | Draw every frame and line as filled whole-pixel rectangles (`rectangle` + `fill`), not as strokes. Set `cairo.ANTIALIAS_NONE` for them. A 1 px stroke at whole coordinates covers two pixels at half alpha. |
| Hover frame | 2 px, accent (64,158,255), just outside the rect |
| Selection frame | 1 px, accent, just outside the rect |
| Crosshair | When on: white at alpha 170/255, 1 px, a full row and column through the cursor |
| Size label | `f"{W} x {H}"` (even values) plus, when position is on, `f"   at {X}, {Y}"` (three spaces). Font "Sans" 12 px × scale. Box: text + 10 × text + 4, text at +5,+2. Background (20,20,20) at alpha 220/255. White text. Place with `label_rect`. |
| Magnifier | When on: source 10×10 px at (cursor − 5), clipped to the image. Zoom 8 times, nearest neighbor (80×80). Box width `max(80, width("-00000, -00000") + 8)`, height `80 + font height + 4`. Place the box with `magnifier_rect`. Black background on the full box. Zoom area: `x = box.x + (box.w - 80) // 2`, `y = box.y`, 80×80 (centered on the width). Center pixel cell at `(zoom.x + 40, zoom.y + 40)`, 8×8: black 1 px square just outside the cell, white 1 px square on the inner edge of the cell. Caption `f"{x}, {y}"`, white, at `(box.x + 4, zoom.y + 80 + 2)`. 1 px accent border on the inner edge of the box: `(box.x, box.y, box.w, box.h)`. These are the Windows offsets (`RegionSelector.DrawMagnifier`). |

X and Y in the label and the caption are X screen px on X11. On Wayland they are stream px.

**X11 shell.**

1. Snapshot:
   - Take `root = Gdk.get_default_root_window()`. Set `pw = root.get_width()*S` and `ph = root.get_height()*S`.
   - Call `Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())`.
   - If the result is None or its size is not `pw×ph`, run `[ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-i", target, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]` on the main thread. Build the pixbuf from the bytes.
   - If both fail, use a black image.
2. Windows: `x11_windows.list_windows(display_name)` (section 9.4). Monitors and work areas: `Gdk.Monitor.get_geometry()` and `get_workarea()`, × S.
3. The window is `Gtk.Window(type=Gtk.WindowType.POPUP)` with title `"Select region"`, `move(0,0)` and `resize(root logical size)`. A POPUP window is override-redirect, so it needs no window manager. Set the cursor `Gdk.Cursor.new_from_name(display, "crosshair")`.
4. After `show_all()`, call `seat.grab(gdk_window, Gdk.SeatCapabilities.ALL, False, cursor, None, None, None)`. If the result is not `SUCCESS`, retry every 50 ms for up to 1000 ms. If the grab still fails, close and return `"cannot grab the keyboard and mouse."`. The retry also covers a hotkey that is still down. A start from `--toggle` or the tray menu has no key down and grabs at once.
5. After the grab, read the pointer with `seat.get_pointer().get_position()` (logical px), map it to image px (step 6), and call `model.motion(...)` once (9.1). Then redraw. This sets `hover` and the magnifier without a motion event.
6. Event px to image px: `widget_to_image` with `DrawMap(0, 0, logical_w, logical_h, pw, ph)`.
7. After steps 4 and 5, write the stderr line `Desktop Recorder: selector open`. The GUI tests wait for this line before they send keys or clicks, because a mapped window does not prove that the grab is done.
8. To warp, use python-xlib `root.warp_pointer(x, y)` in physical px, then `display.sync()`. Then update the model cursor.
9. On accept or cancel:
   - Ungrab. Destroy the window. Call `Gdk.Display.get_default().flush()` and `sync()`.
   - Then call `on_done` from `GLib.timeout_add(60, ...)`. The compositor must remove the selector before the first capture. UNVERIFIED on GNOME X11. Test 14.2 checks frame 0 on Xvfb.

**Wayland shell.**

- Make one `Gtk.Window(Gtk.WindowType.TOPLEVEL)` for each matched stream. Set `decorated=False`, title `"Select region"`, and `fullscreen_on_monitor(screen, monitor_index)`. If the token is not empty, call `set_startup_id(token)`. Then call `present()`. After all windows are shown, write the stderr line `Desktop Recorder: selector open`.
- Match a stream to a `Gdk.Monitor`:
  1. Prefer `stream.position == (geometry.x, geometry.y)`.
  2. Else, if there is one stream and one monitor, match them.
  3. Else open one window for stream 0 on `display.get_primary_monitor()`. GTK3 on Wayland can return None for it; then use `display.get_monitor(0)`. The image is letterboxed by `fit_image`.
- Each window has its own `SelectorModel` with `bounds = Rect(0, 0, iw, ih)`, `monitors = [bounds]` and `windows = []`.
- The image is the frame of that stream: BGRx bytes, changed to an RGB pixbuf with `GdkPixbuf.Pixbuf.new_from_bytes`.
- Arrow keys move the model cursor only. Wayland apps cannot warp the pointer. Name this limit.
- Accept in window i → `on_done(i, rect, options)`. Esc in any window cancels all windows.
- UNVERIFIED: GNOME gives keyboard focus to the new fullscreen window. If it does not, the mouse still works and Esc does not. Right-click cancels with no keyboard (press 3, 9.1).
- Each Wayland selector window draws a one-line hint at its top center: `"Esc or right-click: cancel"`. Use the size-label style (font, box, colors). The hint is in `messages.py`. The X11 selector draws no hint (as on Windows).
- UNVERIFIED: that the GNOME custom keybinding sets `XDG_ACTIVATION_TOKEN` or `DESKTOP_STARTUP_ID`. With no token, focus depends on Mutter alone.

### 9.4 X11 window list (`x11_windows.py`, owner C6; pure core and lazy Xlib)

```python
@dataclass
class XWin:
    xid: int
    x: int; y: int; w: int; h: int              # client area in root coordinates
    frame_extents: tuple[int, int, int, int] | None   # _NET_FRAME_EXTENTS (l, r, t, b)
    gtk_extents: tuple[int, int, int, int] | None     # _GTK_FRAME_EXTENTS (l, r, t, b)
    types: list[str]                            # _NET_WM_WINDOW_TYPE atom names
    states: list[str]                           # _NET_WM_STATE atom names
    viewable: bool
    override_redirect: bool
    pid: int | None                             # _NET_WM_PID
SKIP_TYPES = {"_NET_WM_WINDOW_TYPE_DOCK", "_NET_WM_WINDOW_TYPE_DESKTOP", "_NET_WM_WINDOW_TYPE_TOOLBAR",
              "_NET_WM_WINDOW_TYPE_MENU", "_NET_WM_WINDOW_TYPE_UTILITY", "_NET_WM_WINDOW_TYPE_SPLASH",
              "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU", "_NET_WM_WINDOW_TYPE_POPUP_MENU",
              "_NET_WM_WINDOW_TYPE_TOOLTIP", "_NET_WM_WINDOW_TYPE_NOTIFICATION"}
def window_rect(win: XWin) -> Rect
def visible_rects(bottom_to_top: list[XWin], screen: Rect) -> list[Rect]   # top-to-bottom
def list_windows(display_name: str | None) -> list[Rect]
```

- `window_rect` applies both extents, in this order:
  1. Start with `Rect(x, y, w, h)`.
  2. If `frame_extents (l,r,t,b)` is set, grow: `Rect(x-l, y-t, w+l+r, h+t+b)`.
  3. Then, if `gtk_extents (l,r,t,b)` is set, shrink the result: `Rect(x+l, y+t, w-l-r, h-t-b)`.
  - Mutter sets `_NET_FRAME_EXTENTS = 0,0,0,0` and `_GTK_FRAME_EXTENTS` on the same client-side-decorated window. With an "else" rule, the shadow would stay in the hover rect. Windows fixed the same problem with `DWMWA_EXTENDED_FRAME_BOUNDS`.
- `visible_rects` skips these windows: not viewable, `override_redirect`, `_NET_WM_STATE_HIDDEN` in the states, a type in `SKIP_TYPES`, and a rect smaller than 2×2 after `intersect(screen)`. Return the clipped rects, top first. It does not skip by pid (D25). The selector window does not exist when the list is read, and the frame and Stop windows are override-redirect.
- `list_windows` (python-xlib, imported in the function):
  - Use `_NET_CLIENT_LIST_STACKING` on the root window when it is present (EWMH window manager).
  - Else use `root.query_tree().children`, which is in bottom-to-top order (no window manager, as on Xvfb).
  - Get the position with exactly `t = root.translate_coords(win, 0, 0)`, then `(t.x, t.y)`. In python-xlib, `a.translate_coords(src, x, y)` converts from `src` to `a`, so `win.translate_coords(root, 0, 0)` gives the negative values. Get the size with `win.get_geometry()`.
  - Catch every `Xlib.error.XError` for each window and skip that window.
  - All values are physical px.

---

## 10. Recording frame (`frame_x11.py`, owner C6, GUI)

```python
class RecordingFrame:
    def __init__(self, display_name: str | None) -> None
    def show(self, region: Rect, monitors: list[Rect], work_areas: list[Rect], scale: float,
             gdk_scale: int, hotkey_text: str, on_stop: Callable[[], None] | None,
             gap: int = 0) -> list[str]      # returns notes for the start notification
    def close(self) -> None                  # idempotent
```

- Border: four python-xlib windows from `border_layout(region, border_thickness(scale), monitors, gap)`.
  - Each window has `override_redirect=True` and a background pixel allocated for (255,64,64).
  - Set `WM_NAME` to `"Recording frame"`.
  - Set an empty input shape: `win.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])`. If the constant is missing, use the kind value 2.
  - Map each window. Call `display.flush()`.
  - A `GLib.timeout_add(1000)` timer restacks the windows with `configure(stack_mode=X.Above)` while they show.
  - The windows are opaque. Xvfb has no compositor, so do not use RGBA.
- If any side is in `omitted`, add the note `"The region touches the screen edge, so the red frame is not drawn on that side."`.
- Stop button (only when `on_stop` is not None):
  - Compute `stop_rect(...)` in physical px. If the result is `None`, show no button. Add the note `f"There is no room for the Stop button. Press {hotkey_text} or use the tray menu to stop."`.
  - Else use a `Gtk.Window(type=POPUP)` with title `"Stop recording"`. Set the position in logical px: x = `rect.x // gdk_scale`. y = `ceil(rect.y / gdk_scale)` when the button is below the region, else `rect.y // gdk_scale`. Set the size with `ceil`.
  - Look: background (32,32,32), hover (64,64,64), 1 px edge (255,64,64), red square of size `max(6, h//3)` at x = `h//3` and centered on the height. The text `"Stop"` is "Sans Bold" 13 px × scale, white, centered in the space to the right of the square.
  - Use the cursor `"pointer"`. A left button press calls `on_stop()`. A POPUP window does not take the focus.
- X11 call values: `scale = float(S)` and `gdk_scale = S` (S from section 2), `gap=0`, `on_stop=controller.stop`. Windows uses the DPI scale of the monitor at the region center; GTK3 on X11 has one integer scale for the screen.
- The controller shows no frame when `plan.region is None` (D21: no region, a saved region off the screen, or Space). The frame shows only after `FfmpegProcess.start()` succeeds. If `show` raises, the recording continues without the frame. Log the error to stderr.
- Wayland (D10): the controller calls `RecordingFrame(os.environ["DISPLAY"]).show(...)` only when `wayland_frame=1` and `DISPLAY` is set.
  - The region is `stream_to_layout(...)`, with the outer edges rounded outward to whole logical px.
  - Use `gap=1`, `scale=1.0`, `gdk_scale=1`, `on_stop=None`. Monitors are the stream position and logical size rects.
  - Always add the note `f"GNOME on Wayland does not let apps put a Stop button on the screen. Press {hotkey_text} or use the tray menu to stop."`.
  - UNVERIFIED: that Mutter shows XWayland override-redirect windows above Wayland windows at these coordinates. If a Bran test shows the border inside the video, set the default of `wayland_frame` to 0.
  - The frame opens its python-xlib connection in `show` (D27). If GNOME starts XWayland on demand, this can block the main thread for about 1 s. The pump ticker runs on its own thread, so the video loses no frame.

---

## 11. Wayland capture

### 11.1 Portal (`portal.py`, owner C5)

```python
class PortalTransport(Protocol):
    def request(self, method: str, options: dict[str, Any]) -> dict[str, Any]
    def open_pipewire(self, session: str) -> int
    def close_session(self, session: str) -> None
    def get_property(self, name: str) -> Any       # org.freedesktop.portal.ScreenCast property; None on error
class ScreenCast:
    def __init__(self, transport: PortalTransport) -> None
    def open(self, restore_token: str = "", show_pointer: bool = True) -> PortalSession
```

1. Call `CreateSession {session_handle_token: "dr" + 16 hex}`.
2. Read `version = get_property("version") or 0` and `modes = get_property("AvailableCursorModes") or 0`.
3. Call `SelectSources` with `types=1` and `multiple=True`.
   - `cursor_mode`: the wanted mode is 2 when `show_pointer`, else 1. If `modes & wanted`, send the wanted mode. Else if `modes & 2`, send 2. Else omit the key.
   - When `version >= 4`, add `persist_mode=2` and `restore_token` (if the token is not empty).
4. Call `Start(session, "", {})`. A response code other than 0 raises `PortalError("Screen sharing was cancelled.")`.
5. Read every stream: `node_id`, `position`, `size`, `source_type`. With zero streams, close the session and raise `PortalError("No screen was shared.")`.
6. Get the fd from `OpenPipeWireRemote`.
7. Return `PortalSession`. `restore_token` is the new token, else the old token.

`GioTransport` changes:
- `get_property` calls `org.freedesktop.DBus.Properties.Get("org.freedesktop.portal.ScreenCast", name)` with a 5 s timeout.
- `_call` keeps the id from `GLib.timeout_add` and calls `GLib.source_remove(id)` after `loop.run()` when the timeout did not fire.

### 11.2 GStreamer stream (`wayland.py`, owner C5, GUI)

```python
class GstFrame:          # implements wayland_pump.Frame
    def __init__(self, sample, seq: int, stride: int) -> None    # width, height from caps; stride from frame_stride (7.1)
    def crop(self, rect: Rect) -> bytes             # buffer.extract_dup(0, size) then crop_rows with self.stride
class GstStream:
    def __init__(self, source: str, pump: FramePump, on_error: Callable[[str], None]) -> None
    def start(self) -> str | None
    def stop(self) -> None                           # main thread: set_state(NULL)
```

- `start`:
  - Import `Gst`. If this fails, return `"Wayland capture needs GStreamer PipeWire support. Install gir1.2-gstreamer-1.0, gstreamer1.0-plugins-base and gstreamer1.0-pipewire. "` + the error.
  - Call `Gst.init(None)`, then `Gst.parse_launch(pipeline_description(source))`. If the parse raises, return the error text. The caller closes the dup'ed fd.
- `new-sample` handler:
  - Call `pull-sample`.
  - Set `stride = frame_stride(buffer.get_size(), width, height)` (D20). If it is `None`, call `on_error("Bad frame from the screen cast.")` and return `OK`.
  - Call `pump.offer(GstFrame(sample, seq, stride))`. Return `OK`. The handler never blocks.
- When the first frame has a size, the stream keeps that size. A later frame with another size calls `on_error("The shared screen changed size, so the recording stopped.")`.
- Bus `ERROR` messages call `on_error(str(err))`.
- `on_error` is marshalled with `GLib.idle_add` to the controller, which stops the recording and notifies `"Desktop Recorder stopped"`.

### 11.3 Wayland flow (controller)

1. `toggle` in `idle`: set the state to `portal` and return (D19). A later `GLib.idle_add` callback calls `ScreenCast(GioTransport()).open(settings.wayland_restore_token, settings.show_pointer)`.
   - Save the new token to disk at once with `save_settings`.
   - On `PortalError`, notify the text and set the state to `idle`.
2. For each stream: create `FramePump(fps)` and `GstStream(pipewire_source(os.dup(fd), node_id), pump, on_error)`. Start the stream.
3. Poll `pump.latest()` every 50 ms with `GLib.timeout_add`, for up to 3000 ms.
   - If no stream has a frame, notify `"The screen cast sent no picture in 3 seconds. Try again."`. Clean up, and set the state to `idle`.
   - Use only the streams that have a frame.
4. Call `open_wayland_selector(...)`. Set the state to `selecting`.
5. On accept `(i, crop)`:
   - Store `accept_seq = pump_i.latest().seq`. This frame can still show the selector (P6). Then destroy all selector windows.
   - Stop the other streams.
   - Save `wayland_region = (pos_x, pos_y, crop.x, crop.y, crop.w, crop.h)`. A stream without `position` gives (0, 0).
   - Call `pump_i.set_crop(crop)`. Make `plan_wayland`. Start `FfmpegProcess` on the main thread.
   - Call `pump_i.start(proc.write, after_seq=accept_seq)` (D18). Show the frame (D10). Set the state to `recording`.
6. On cancel: stop all streams, close the fd, close the session, and save the selector options.
7. Fallback retry (5.4): take a new snapshot and new stats (D16). Start a new `FfmpegProcess` with x264. Then call `pump_i.restart(proc.write)` (D17). The `GstStream` and the latest frame stay. The new file gets a new stamp. The failed file is not copied or counted.
8. `record_on_launch` (`start_saved_region`):
   - Open the portal with the saved token. The GNOME dialog shows when the token does not work.
   - If `wayland_region` is all zeros (no saved region), record the whole of stream 0: `accept_rect(Rect(0,0,iw,ih), Rect(0,0,iw,ih))`. Add no note.
   - Else find the stream with `position == (MX, MY)`. Use `accept_rect(Rect(X,Y,W,H), Rect(0,0,iw,ih))`.
   - If no stream matches or that rect is empty, record the whole of stream 0 and add the note `"The saved region is not on the screen now. Recording the whole desktop."`.
   - No selector was shown, so call `pump.start(proc.write)` with `after_seq=0`.

### 11.4 Coordinate mapping (exact)

- Stream image size `(iw, ih)` comes from the caps of the first frame. These are stream px. On Mutter 46 with scaled stage views they are physical px (UNVERIFIED on noble).
- Selector widget px to image px: `widget_to_image(px, py, fit_image(alloc_w, alloc_h, iw, ih))`.
- The crop is in image px = stream px. FFmpeg gets exactly W×H. The picture is never scaled.
- Border layout px: `stream_to_layout(crop, position, size, (iw, ih))`. `size` is the logical size from the portal. If `size` is None, use `(alloc_w, alloc_h)` of the selector window.
- A region cannot span two monitors. Each selector window covers one stream. This is the same rule as ddagrab on Windows.

---

## 12. Tray, Settings, notifications, sounds, clipboard, autostart

### 12.1 Tray (`ui.py`, owner C7, GUI)

```python
def run(select: bool = False, token: str = "", from_toggle: bool = False) -> int
class Tray:      # implements ControllerUi
```

- `GDK_BACKEND=wayland` moves to `__main__.py` (8.6). It must be set before any import of `ui`, because `ui.py` imports `Gtk` at module level. `ui.run` does not set it.
- Every hotkey callback and every socket command reaches the controller through `GLib.idle_add` (8.4, 8.7).
- Menu, in this order:

| # | Item | Text |
|---|---|---|
| 1 | Status, disabled | `controller.status_text()` |
| 2 | Stats, disabled, hidden until the first stop | `"Last recording: " + stats` (or `"No stats."` if the stats call raises) |
| 3 | Separator | |
| 4 | Toggle | `"Select region and record"` or `"Stop recording"`, plus `"    " + hotkey_text` when the hotkey is active |
| 5 | `Open recordings folder` | `os.makedirs`, then `xdg-open` |
| 6 | `Settings...` | |
| 7 | Separator | |
| 8 | `Exit` | |

- Exit (and SIGTERM, SIGINT, SIGHUP) closes each open dialog first: the Settings dialog, its folder chooser or warning, and a tray warning. `Gtk.main_quit()` does not end the loop of `Gtk.Dialog.run()`. After Exit, the code saves nothing, installs no hotkey and shows no new dialog.
- Tooltip: `"Desktop Recorder: recording"` or `"Desktop Recorder: stopped"`.
- Tray type: AyatanaAppIndicator3 first, `Gtk.StatusIcon` as the fallback. The `_use_appindicator` rules do not change.
  - `StatusIcon`: the `activate` signal opens Settings (the Windows double-click). `popup-menu` opens the menu.
  - AppIndicator has no click event. The status rows are in the menu.
- Icons (`icons.py`, C7):
  - `draw_tray_icon(size: int, recording: bool) -> cairo.ImageSurface` is a port of `TrayIcons.Draw` with the same formulas and colors:
    - Idle: brackets, ring and dot in (175,220,235).
    - Recording: top brackets (225,120,255), bottom brackets (80,195,255), ring (205,175,255), dot (255,40,90).
    - Round caps. `k = size/16`.
  - Write `config_dir()/icons/desktop-recorder-idle.png` and `config_dir()/icons/desktop-recorder-recording.png` at 64 px at each app start.
- Notifications (D28):
  - First write the stderr line (8.6). Always.
  - Then, unless env `DESKTOP_RECORDER_NOTIFY=stderr` is set, use libnotify `Notify 0.7` with `set_timeout(timeout_ms)`. Import `Notify` lazily on the first call. Catch `ImportError`, `ValueError` and `GLib.Error` from the import, `Notify.init` and `show()`. After the first failure, use stderr only.
  - Titles: `"Desktop Recorder"`, except `"Desktop Recorder stopped"`.
- Start:
  - With `select=True`, call `controller.toggle(token)` after `ready`.
  - Else with `record_on_launch`, call `controller.start_saved_region()` from `GLib.idle_add`.
  - On X11 this uses `plan_x11(region=None if settings.region.is_empty else settings.region, ...)` (5.3). There is no selector. The start sound plays. The start notification shows only with a note (D15).
- NVENC `warm_up` runs at start when `record_on_launch` is false and `encoder == "auto"`.

### 12.2 Settings dialog (`settings_dialog.py`, owner C7, GUI)

```python
class SettingsDialog(Gtk.Dialog):
    def __init__(self, current: Settings, backend: str) -> None
    def run_until_valid(self) -> Settings | None   # None = Cancel
```

- Title `"Desktop Recorder settings"`. Buttons `Cancel` and `Save` (default).
- `run_until_valid` loops on `self.run()`. Cancel returns None. Save validates. A failed check shows a message and loops. Remove the `do_response` override.

| # | Label | Widget |
|---|---|---|
| 1 | `Save recordings to:` | Entry + `Browse...` |
| 2 | `Frames per second (0.2 to 60). Lower = smaller files:` | SpinButton 0.2..60, step 1, 1 digit |
| 3 | `Quality:` | `Smallest files (text still readable)`, `Balanced (recommended)`, `Sharpest text (bigger files)` |
| 4 | `Start a new file every (minutes, 0 = never):` | SpinButton 0..1440 |
| 5 | `Hotkey:` | Check boxes `Win`, `Ctrl`, `Alt`, `Shift` + key list (A–Z, 0–9, F1–F12, plus the current key if missing) |
| 6 | `Capture:` | Read-only label: `x11grab (X11 session)` or `PipeWire screen cast (Wayland session)` |
| 7 | `Encoder:` | `Auto: NVENC, else x264 (recommended)`, `NVIDIA NVENC (h264_nvenc)`, `x264 on the CPU (libx264)` |
| 8 | `Color detail (chroma):` | `4:2:0 (plays everywhere)`, `4:4:4 (sharper colored text)` |
| 9 | `Frame-rate mode:` | `Fixed frame rate`, `Changes only (drops still frames)` |
| 10 | check | `Start Desktop Recorder when I log in` |
| 11 | check | `Start recording (saved region) when Desktop Recorder starts` |
| 12 | check | `Copy the video to the clipboard when recording stops` |
| 13 | check | `Play a sound when recording starts and stops` |
| 14 | check | `Hide the mouse pointer in the video` (inverse of `show_pointer`) |
| 15 | check | `Record system audio (what you hear)` |
| 16 | check (Wayland only) | `Show a red frame around the region (Wayland, experimental)` |
| 17 | `Region selector:` | `Crosshair`, `Magnifier`, `Position` |

- Validation:
  - Hotkey: `hotkey.is_valid(mods, parse_key(key))`, else show `"For the hotkey, tick at least one of Win, Ctrl, Alt and pick a key. Shift alone works only with F1 to F12."`.
  - Folder: trim it, strip outer quotes and `expanduser`. If it is not absolute, show `"Give a full folder path, such as /home/you/Recordings."`. If `os.makedirs` fails, show `"Cannot create that folder: " + msg`. Remove a trailing `/`, except for `/`.
- Save:
  - Start from `copy_settings(live)`. This keeps `capture_backend`, `nvenc_cq`, `region`, `last_region`, `wayland_region`, `wayland_restore_token` and `extra_lines`. Read the live values again at Save time, because the selector can save while the dialog is open.
  - Write the file and the autostart file. Install the hotkey again. Probe the audio again.
  - **Do not touch a running recording.** The new settings apply to the next recording.
- The selector writes `region = last_region = picked` (X11) or `wayland_region` (Wayland) before FFmpeg starts. It writes the C/M/P options when they changed, also on cancel.

### 12.3 Other modules (small changes, owner C7)

- `sounds.py`: no change. Spawn `paplay` without PDEATHSIG.
- `clipboard.py`: no change (D26). It copies `text/uri-list` only. `x-special/gnome-copied-files` is not added in this port.
- `autostart.py`: no change.
- `audio.py`: change `probe_pulse(device: str, timeout: float = 2.0)` to `probe_pulse(device: str, timeout: float = 2.0, ffmpeg: str = "ffmpeg")`. Keep `timeout` second, so old positional calls still work. Callers always pass `ffmpeg=` as a keyword.
- `gnome_hotkey.py`: no change.
- `hotkey.py`: no change.
- `__init__.py`: `__version__ = "2.1.0"`.

---

## 13. File-by-file plan and owners

The interfaces are in sections 3 to 12. Each coder owns only the files in their row. "pure" means no `gi`, `Xlib` or `cairo` at module level.

| Owner | Files (N = new, C = changed) | Kind | Depends on |
|---|---|---|---|
| C1 | `linux/desktop_recorder/settings.py` (C); `tests/test_linux_settings.py` (N) | pure | `geometry.Rect` (copy of 3.1) |
| C2 | `geometry.py` (N), `selector_model.py` (N); `tests/test_linux_geometry.py` (N), `tests/test_linux_selector_model.py` (N) | pure | – |
| C3 | `ffmpeg_cmd.py` (C, rewrite), `encoders.py` (N); `tests/test_linux_argv.py` (N), `tests/test_linux_encoders.py` (N) | pure | C1, C2 |
| C4 | `recording.py` (C, rewrite), `ffstats.py` (N); `tests/test_linux_ffproc.py` (N), `tests/test_pdeathsig.py` (N) | pure | C2 |
| C5 | `wayland_pump.py` (N), `portal.py` (C), `wayland.py` (C, rewrite); `tests/test_linux_wayland_pump.py` (N), `tests/test_linux_portal.py` (N), `tests/test_gst_pipeline.py` (N) | pump and portal pure; wayland GUI | C2, C3, C4 |
| C6 | `x11_windows.py` (N), `selector_gtk.py` (N), `frame_x11.py` (N); `tests/test_linux_x11_windows.py` (N) | GUI (x11_windows core pure) | C2 |
| C7 | `capture.py` (C, rewrite: `Controller`), `ui.py` (C, rewrite), `settings_dialog.py` (N), `icons.py` (N), `messages.py` (N), `single_instance.py` (C), `hotkey_x11.py` (C), `__main__.py` (C), `audio.py` (C), `__init__.py` (C); `tests/test_linux_instance.py` (N), `tests/test_linux_hotkey_x11.py` (N) | GUI (`single_instance` pure; `hotkey_x11` imports on Windows) | all |
| C8 | `.gitattributes` (C), `tests/linux_skip.py` (N), `tests/test_linux.py` (C), `tests/test_x11_gui.py` (N), `tests/x11_pattern.py` (N), `tests/framecheck.py` (N), `tests/test_x11_session.py` (C), `run-tests.sh` (C), `.github/workflows/build.yml` (C), `.github/workflows/release.yml` (C), `packaging/make-linux-tarball.sh` (C), `packaging/linux/desktop-recorder` (C), `packaging/linux/README.txt` (C), `packaging/linux/desktop-recorder.png` (N), `build-linux.sh` (C), `README.md` Linux section (C) | tests, CI, docs | all |

- Each file is in exactly one row. Files that are in no row do not change: `hotkey.py`, `gnome_hotkey.py`, `sounds.py`, `clipboard.py`, `autostart.py`, `tests/fake_ffmpeg.py` (`CoreTests.cs` uses it), `tests/fake_ffmpeg_stats.py`, `tests/CoreTests.cs`, and everything in the repo root.
- `messages.py` holds every UI text of sections 8, 9.3 (the Wayland hint), 10, 11 and 12 as constants or format functions. FFmpeg plan notes and fallback reasons stay in `ffmpeg_cmd.py`. Portal errors stay in `portal.py`.
- C8's first step holds `.gitattributes`, `tests/linux_skip.py` (14.0) and the `tests/test_linux.py` cleanup. It must be done before any other owner starts, because every test file imports `linux_skip`. If the work is committed, it is the first commit.
- `tests/test_linux.py` (C8, first step):
  - Remove the classes `SettingsTests`, `ArgumentTests`, `PortalTests` and `RecordingTests`. The new `test_linux_*.py` files cover them.
  - Remove the module-level imports that only those classes use: `ffmpeg_cmd` (`capture_backend`, `wayland_ffmpeg_argv`, `wayland_pipeline`, `x11_argv`, `x11_target`), `portal` (`PortalError`, `ScreenCast`), `recording` (`Recording`), and `settings` (`Settings`, `parse_settings`, `serialize_settings`).
  - Keep `HotkeyTests`, `AudioTests` and `OtherTests`. Their imports name only items that stay: `audio.monitor_from_listing`, `audio.choose_monitor`, `autostart.autostart_enabled`, `autostart.write_autostart`, `clipboard.uri_list`, `gnome_hotkey.PATH`, `gnome_hotkey.update_gnome_shortcut`, `hotkey.try_set`, `single_instance.InstanceServer`, `single_instance.send_command`, `sounds.build_chime`. C7 keeps these names.
  - In `OtherTests`, split the socket part into its own test, and guard it with `linux_skip` (needs `AF_UNIX`). Guard the `uri_list` check with `linux_skip` (needs POSIX paths). Thus `test_linux.py` passes or skips on Windows too.
  - After this first step, no later merge breaks an import in `test_linux.py`.
- `tests/fake_ffmpeg_stats.py` (exists, no change) is the fake for `FfmpegProcess` tests. It writes stats lines with `\r`, the error line `real warning line`, and after `q` or stdin EOF the final line `frame=   42 ... dup=3 drop=2`. With `--fail` it writes `boom: capture failed` and exits 1.
- Order: C8's first step (`.gitattributes`, `tests/linux_skip.py`, `tests/test_linux.py`) → C2 → C1 → C3, C4 → C5, C6 → C7 → rest of C8.

---

## 14. Tests

### 14.0 Skip rule (`tests/linux_skip.py`, owner C8, first step)

Exact code. Every owner calls these functions the same way, in `setUp`, `setUpClass` or a test method. They take no `TestCase`, so they also work in `setUpClass`.

```python
"""One skip rule for all Linux tests. DESKTOP_RECORDER_REQUIRE_GUI=1 turns a skip into a failure."""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess
import sys
import unittest
from typing import Any

REQUIRE = os.environ.get("DESKTOP_RECORDER_REQUIRE_GUI") == "1"
IS_LINUX = sys.platform.startswith("linux")


def need(ok: bool, reason: str) -> None:
    if ok:
        return
    if REQUIRE:
        raise AssertionError("Required for this test: " + reason)
    raise unittest.SkipTest(reason)


def need_linux() -> None:
    need(IS_LINUX, "Linux")


def need_af_unix() -> None:
    need(hasattr(socket, "AF_UNIX"), "AF_UNIX sockets")


def need_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # ImportError, or a broken binding
        need(False, f"{name} ({exc})")


def need_gi(namespace: str, version: str) -> Any:
    try:
        import gi

        gi.require_version(namespace, version)
        return importlib.import_module("gi.repository." + namespace)
    except Exception as exc:
        need(False, f"gi {namespace} {version} ({exc})")


def need_program(name: str) -> str:
    path = shutil.which(name)
    need(path is not None, name)
    return path or ""


def need_display() -> str:
    display = os.environ.get("DISPLAY", "")
    ok = False
    if display and shutil.which("xdpyinfo"):
        ok = subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    need(ok, "an X display (DISPLAY and xdpyinfo)")
    return display
```

- Test files import it as `import linux_skip` (`discover -s tests` puts `tests/` on `sys.path`). The name does not match `test_*.py`, so discover does not load it as a test.
- `unittest` treats `SkipTest` from `setUpClass` as a skip of the class, and `AssertionError` as an error. Both are what D23 wants.
- Never import `gi`, `Xlib`, `fcntl` or a Linux-only module at the top of a test file. Use the helpers.
- Use: `need_linux()` for `popen_with_pdeathsig`, `/proc` and `prctl`; `need_af_unix()` for sockets; `need_gi(...)` for GTK and GStreamer; `need_module("Xlib")`; `need_program(...)` for `ffmpeg`, `ffprobe`, `xdotool`, `xwininfo`, `xdpyinfo`, `xset`; `need_display()` for X tests.
- CI sets `DESKTOP_RECORDER_REQUIRE_GUI=1` on every test step (D23). Then a missing package fails the run.
- On the Windows dev PC, `PYTHONPATH=linux python -m unittest discover -s tests -p 'test_linux_*.py' -v` must end with OK (skips allowed).

### 14.1 Unit tests (pure, no display, run anywhere)

| File | Tests (name: check) |
|---|---|
| `test_linux_settings.py` | `test_defaults`: fps 10, `changes`, quality 1, `show_pointer` True, `encoder` auto, `nvenc_cq` 23. `test_nan_fps_gives_10`. `test_bad_known_value_keeps_old_and_is_not_extra` (`encoder=h264_vaapi`, `capture_backend=x11grab`). `test_dropped_keys` (`stop_hotkey`, `last_region_hotkey`). `test_eq_rule` (`=x` and `noequals` become extras). `test_region_rules` (3 parts → no change; `1,2,0,5` → zeros). `test_wayland_region_six_ints`. `test_write_order_matches_windows` (the first 19 keys in table order, then 5 Linux keys, then extras). `test_round_trip`. `test_windows_crlf_file_parses`. `test_int_rule_ascii_only` (`quality=1_0`, `quality=١`, `nvenc_cq=2_3` keep the old value and are not extras; `quality= +2 ` gives 2). `test_load_bad_file_gives_defaults` (invalid UTF-8 bytes; a folder in place of the file). |
| `test_linux_geometry.py` | `test_inclusive_drag` (440,172 → 1421,601 = 982×430). `test_make_even_shrinks` (301×201 → 300×200; 1×5 → empty). `test_square_point`. `test_border_outside` (region 100,100,200,100, t=2: top = Rect(98,98,204,2)). `test_border_edge_omits_side` (region `Rect(0,0,200,100)`, t=2, monitor `Rect(0,0,1280,800)`: top and left None, omitted `["top","left"]`, outer `Rect(0,0,202,102)`, bottom `Rect(0,100,202,2)`, right `Rect(200,0,2,100)`). `test_border_gap` (region `Rect(100,100,200,100)`, t=2, g=1: top `Rect(97,97,206,2)`, left `Rect(97,99,2,102)`). `test_border_one_side_corner` (right side omitted: top spans from `outer.x` to the region right edge, as on Windows). `test_stop_below_above_other_none` (4 cases; the full-monitor region gives None). `test_label_flip` (target at y=5 → label at y+8). `test_magnifier_flip`. `test_fit_and_map` (1920×1080 image in a 1536×864 widget: px 767.5 → 959; letterbox offset). `test_stream_to_layout` (scale 1.25). |
| `test_linux_selector_model.py` | `test_drag_accepts_on_release`. `test_one_motion_drag_accepts` (press 150,150; one motion to 349,299; release → accept `Rect(150,150,200,150)`). `test_small_move_is_click`. `test_click_selects_hover_window`. `test_press_sets_hover_without_motion` (no motion before press; press and release on a window → accept that window). `test_click_without_window_does_nothing`. `test_shift_square`. `test_ctrl_moves_anchor_not_on_first_move`. `test_right_click_rules` (4 cases: in `creating` → back to `prev`, stays open; in `pending` → back to `prev`, stays open; with a selection → cleared; else → cancel). `test_escape_enter_space_tilde`. `test_arrows_warp_1_and_10`. `test_cmp_toggle_options`. `test_accept_is_even_and_clipped`. `test_tiny_drag_not_accepted` (stays open). |
| `test_linux_argv.py` | Golden argv 1 (also on Windows: the path uses `/`). All golden strings in 5.2. `test_plan_nvenc_limits` (4097 wide, 140 wide). `test_plan_auto_without_nvenc_is_x264`. `test_plan_region_offscreen_note`. `test_plan_no_region_no_note` (`region=None` → whole screen, no note). `test_plan_full_screen_region_is_none` (region = screen → `plan.region is None`, D21). `test_x11grab_queue_128`. `test_fallback_rules` (1, 3, explicit nvenc → None, elapsed 10001 → None). `test_no_nostats`. |
| `test_linux_encoders.py` | `test_encoder_listed` (` V....D h264_nvenc ...` true; ` A..... h264_nvenc` false). `test_probe_two_steps_and_cache` (fake runner counts calls). `test_mark_unusable`. `test_timeout_is_false`. |
| `test_linux_ffproc.py` | `test_line_splitter_cr` (`"a\rb\nc"` → a, b; then c on flush). `test_cap_8192`. `test_parse_progress` (the Windows sample line; `frame=  100`; no dup → 0; `frame=N/A` → None; `frame=²` → None; `dup=²` → 0). `test_format_stats` (both forms, `0.05 MB`). `test_write_loops_on_short_writes` (a fake stdin whose `write` takes at most 3 bytes per call; all bytes arrive in order; no process needed). `test_ffmpeg_process_stats_via_fake` (`need_linux`; argv `[sys.executable, "tests/fake_ffmpeg_stats.py", out]`; after `request_stop`: frames 42, dup 3, drop 2; error text is `real warning line` and has no stats line). `test_failure_calls_on_exit` (`need_linux`; `--fail` → code 1, error text contains `boom: capture failed`). `test_session_files_skip_old_and_empty`. `test_wayland_stats_formula` (with progress; and without progress → `has_progress` False, `Frames: unknown.`). `test_spawn_off_main_thread_raises` (runs on Windows too). |
| `test_pdeathsig.py` | `need_linux` and `need_program("sleep")`. `test_child_dies_with_parent`: a helper Python parent (`python3 -c ...`, run with `PYTHONPATH=linux`) uses `popen_with_pdeathsig(["sleep","60"])`, prints the child pid, and sleeps. The test sends SIGKILL to the parent. Within 2 s, `os.kill(child, 0)` raises `ProcessLookupError` (after `waitpid`, or a check of `/proc/<pid>/stat` for state Z). |
| `test_linux_wayland_pump.py` | Fake clock and fake frames. `test_crop_rows`. `test_fresh_and_repeats`. `test_late_counts_when_write_blocks` (fake write advances the clock by 1.5 intervals). `test_skip_after_2s`. `test_superseded`. `test_write_error_stops`. `test_pipeline_strings` (`always-copy=true`, `max-buffers=0 drop=false`, no `target-object`). `test_waits_for_fresh_frame` (`after_seq=5`: no write until a frame with seq 6 is offered). `test_fresh_wait_timeout` (no newer frame: the first write comes after 0.5 s of fake clock, with the old frame). `test_no_frame_writes_nothing`. `test_restart_keeps_frame_zeroes_counters` (still screen: after `restart`, ticks continue with the kept frame; `fresh` and `ticks` start at 0). `test_frame_stride` (exact size → `w*4`; padded rows `size = 1100*4*h` for `w=1080` → 4400; size that does not divide → None). `test_crop_rows_padded_stride` (stride 4400, width 1080: rows do not shear). |
| `test_linux_portal.py` | Fake transport. `test_call_order`. `test_cursor_mode_shown_hidden_and_fallback` (modes 1, 2, 3, 0). `test_version_3_omits_persist`. `test_all_streams_read` (2 streams with positions). `test_zero_streams_closes`. `test_token_in_out`. |
| `test_linux_x11_windows.py` | `test_frame_extents_added`. `test_gtk_extents_subtracted`. `test_both_extents` (frame `0,0,0,0` and GTK `10,10,8,12` on a 400×300 client at 100,100 → `Rect(110,108,380,280)`). `test_skip_rules` (hidden, dock, override-redirect, unviewable, 1 px). `test_own_pid_not_skipped` (D25). `test_order_top_first`. |
| `test_linux_instance.py` | `test_runtime_dir_path`. `test_parse_command` (`"TOGGLE"` → `("TOGGLE","")`; `"TOGGLE abc"` → `("TOGGLE","abc")`; `" STATUS\n"` → `("STATUS","")`). The socket tests call `need_af_unix`: `test_toggle_token_command`, `test_status_command`, `test_512_byte_limit`, `test_busy_reply_after_wait` (`schedule` that never runs the job, `wait=0.2` → reply `BUSY`), `test_schedule_runs_job` (`schedule` that runs the job on another thread → the real reply), `test_is_reachable_false_for_stale_file`. |
| `test_linux_hotkey_x11.py` | `test_repeat_filter` (press, press, press, release, press → True, False, False, –, True). `test_release_without_press`. Runs on Windows (pure class). |

### 14.2 Xvfb GUI and integration tests (`tests/test_x11_gui.py`, C8)

- Checks in `setUpClass` (14.0): `need_display`, `need_program` for `ffmpeg`, `ffprobe`, `xdotool`, `xwininfo`, `xdpyinfo` and `xset`, `need_module("Xlib")`, `need_gi("Gtk", "3.0")`.
- Screen size: read it once from `xdpyinfo` (`dimensions:` line). CI and `run-tests.sh` use 1280×800. Tests use the read size, not a fixed value.
- Common setup:
  - Make a temp folder T. Set `XDG_CONFIG_HOME=T/cfg`, `XDG_RUNTIME_DIR=T/run` (mode 0700), `DESKTOP_RECORDER_TRAY=status`, `DESKTOP_RECORDER_NOTIFY=stderr`, `NO_AT_BRIDGE=1` and `PYTHONPATH=linux`. Every `--toggle` call uses the same env, so it finds the same socket.
  - Write `settings.txt` with `folder=T/out`, `fps=10`, `encoder=libx264`, `record_on_launch=0`, `copy_to_clipboard=0`, `play_sounds=0`, `record_audio=0`, `show_pointer=0`, `frame_rate_mode=fixed`, unless a test says otherwise.
  - Start `tests/x11_pattern.py`. It uses python-xlib to make a normal top-level window at (100,100), 400×300, name `dr-pattern`. The background is (40,40,40), with blocks of 100×100 px: green (0,200,0) at (120,120), blue (0,0,200) at (280,120), yellow (255,255,0) at (120,260), white (255,255,255) at (280,260), all in root px. Draw the pattern once into a pixmap and set it as the window `background_pixmap` (P14). The X server then repaints the blocks with no client round trip when the selector closes. Xvfb has no window manager, so the position is exact.
  - Start the app with `python3 -m desktop_recorder`. Wait for `Desktop Recorder: ready` on stderr (10 s).
  - Save all MP4s and logs to `$RUNNER_TEMP/dr-tests` when the env var is set.
- Helpers in `tests/test_x11_gui.py` (R1):
  - `toggle() -> str`: run `python3 -m desktop_recorder --toggle` with the test env. Return its stdout, stripped.
  - `wait_selector()`: wait for a new stderr line `Desktop Recorder: selector open` (5 s). The line comes after the seat grab and the first hover (9.3 X11 shell step 7). A mapped window alone does not prove that keys and clicks reach the selector.
  - `open_selector()`: `assert toggle() == "SELECTING"`, then `wait_selector()`. All tests open the selector with this helper, except `test_hotkey_opens_selector`.
  - `stop()`: `assert toggle() in ("STOPPING", "STOPPED")`. Then wait for `STATS_RE` on stderr (15 s).
- `tests/framecheck.py` (helpers):

```python
def frame_rgb(path: str, index: int) -> tuple[int, int, bytes]   # ffmpeg -i path -vf select=eq(n\,index) -frames:v 1 -f rawvideo -pix_fmt rgb24 -
def screen_rgb(display: str) -> tuple[int, int, bytes]           # x11grab 1 frame, rgb24
def pixel(w: int, data: bytes, x: int, y: int) -> tuple[int, int, int]
def near(a: tuple[int, int, int], b: tuple[int, int, int], tol: int = 24) -> bool
def count_frames(path: str) -> int                               # ffprobe -count_frames nb_read_frames
def probe_size(path: str) -> tuple[int, int]
def probe_duration(path: str) -> float                           # ffprobe format duration
STATS_RE = r"Real frames: (\d+) of (\d+)\. Duplicates: (\d+)\. Dropped: (\d+)\. File size: [0-9.]+ MB\."
PLAN_RE = r"Desktop Recorder: plan (\S+) (\S+)"
```

- `STATS_RE` has no `Last recording: ` prefix (P1). That prefix is only in tray row 2. The stop notification on stderr is `Desktop Recorder: Recording stopped. | Real frames: ...`.

| Test | Steps | Pass |
|---|---|---|
| `test_drag_records_region` | `open_selector()`. `xdotool mousemove 150 150 mousedown 1 mousemove 349 299 mouseup 1`. Wait 3 s. `screen_rgb` while recording. `stop()`. | Size 200×150. Frame 0 and the last frame: green block center (in video coords 20..69) is near (0,200,0); not dimmed. No pixel in any checked frame is near (255,64,64). Screen during recording: (148,200) and (350,200) near (255,64,64). Stats N == `count_frames`, N ≥ 25, real ≥ 0.9·N. Stderr has `Recording started (x11grab, libx264).`, and `PLAN_RE` gives `x11grab libx264`. |
| `test_hotkey_opens_selector` | The only hotkey test. `xdotool key super+shift+d`. `wait_selector()`. `xdotool key Escape`. | The selector opens. Socket `STATUS` → `STOPPED`. If `super+shift+d` does not reach `Mod4` on Xvfb, only this test fails. |
| `test_click_window_selects_it` | `open_selector()`. `xdotool mousemove 300 250 click 1`. Wait 2 s. `stop()`. | Size 400×300 (pattern window, `XQueryTree` path). |
| `test_space_whole_screen_changes_mode` | `frame_rate_mode=changes`. `open_selector()`, `xdotool key space`. Wait 4 s (still screen). `stop()`. Measure W = time from the `PLAN_RE` line to the stop `--toggle`. | Size = the screen size with even sides. `xwininfo -root -tree` has no `"Recording frame"` and no `"Stop recording"` (D21). 3 ≤ frames ≤ 12. Duration ≥ W − 2.5 s (`mpdecimate` can cut up to 1 s at the end; W starts before the first x11grab frame, so allow up to 1.5 s for the FFmpeg start on a loaded runner). |
| `test_escape_cancels` | `open_selector()`. `xdotool key Escape`. Wait 1 s. | No new MP4. Socket `STATUS` → `STOPPED`. |
| `test_selector_dim_and_magnifier` | `open_selector()`. `xdotool mousemove 800 600`. Wait 0.3 s. `screen_rgb`. Then Escape. | White block pixel (300,280) ≈ 135 ±12 (dimmed). On the magnifier border row y=624, the pixels at x=830 and x=900 are near (64,158,255) (`near`, tol 24). The box starts at 824 and is at least 80 px wide. The size label is not checked. |
| `test_edge_region_omits_border` | `open_selector()`. Drag 0,0 → 199,149. Wait 2 s. `xwininfo -root -tree`. `stop()`. | 2 `"Recording frame"` windows. Stderr has the edge note. No border-colored pixel in the video. A `"Stop recording"` window exists below the region. |
| `test_stop_button_click` | `open_selector()`. Drag a region. Read the `"Stop recording"` geometry with `xwininfo -name "Stop recording"`. Click its center. | `STATS_RE` appears on stderr. The frame windows are gone. |
| `test_kill_app_ends_ffmpeg` | `open_selector()`, drag a region, record 3 s. Find the FFmpeg pid with `pgrep -f T/out`. Send SIGKILL to the app. | FFmpeg is gone in 3 s. ffprobe reads the file. |
| `test_record_on_launch_saved_region` | `record_on_launch=1`, `region=100,100,401,301`. Start the app. Wait for `PLAN_RE` (10 s). Wait 2 s. `stop()`. | Size 400×300. `PLAN_RE` gives `x11grab libx264`. Stderr has no `Recording started` line (D15: a launch start with no note). |
| `test_auto_encoder_falls_back_to_x264` | `encoder=auto`, `record_on_launch=1`, region as above. Wait for `PLAN_RE` (30 s: the NVENC probe runs first). `stop()`. | `PLAN_RE` gives `x11grab libx264`. CI has no NVIDIA GPU. |
| `test_toggle_cli_replies` | `toggle()` → reply 1. `wait_selector()`. `xdotool key space`. Wait 2 s. `toggle()` → reply 2. | Reply 1 is `SELECTING`. Reply 2 is `STOPPING` or `STOPPED`. A file is made. |
| `test_toggle_starts_tray_when_none` | Do not start the app. Run `python3 -m desktop_recorder --toggle` in the background as the app process. Wait for `Desktop Recorder: ready` (10 s), then `wait_selector()` on the stderr of that process. `xdotool key Escape`. | The selector opens. No window named `"Desktop Recorder"` (the "already running" dialog) exists. Socket `STATUS` → `STOPPED`. Then end the process with SIGTERM. |

`tests/test_x11_session.py` keeps `test_hotkey_grab`. It adds `test_hotkey_no_repeat`: run `xset r on` first, then `xdotool keydown ctrl+shift+F12`, wait 1 s, then `keyup`. The callback runs exactly once. Xvfb auto-repeat for XTEST keys is UNVERIFIED, so this test can pass with no repeat. `test_linux_hotkey_x11.py` checks the filter itself (P16). Change `test_smoke_recording` to the new `--smoke`. The file uses `linux_skip` (14.0).

### 14.3 GStreamer path without a portal (`tests/test_gst_pipeline.py`, C5)

- Checks (14.0): `need_linux`, `need_gi("Gst", "1.0")`, `need_program` for `ffmpeg` and `ffprobe`. No display is needed.
- `test_pump_to_ffmpeg_fixed`:
  - Source `videotestsrc is-live=true pattern=smpte ! video/x-raw,width=640,height=480,framerate=30/1`.
  - `GstStream` + `FramePump(10)`. Wait for the first frame. Crop `Rect(10,10,320,240)`.
  - Use `wayland_argv` with the x264 plan in `fixed` mode, and real FFmpeg. `pump.start(proc.write)` (`after_seq=0`). Run for 3 s, then stop.
  - Pass: size 320×240, frames ≥ 27, `skipped == 0`, `fresh > 0`, and the stats parse.
- `test_still_source_keeps_length`:
  - Source `videotestsrc num-buffers=1 ...`. One frame, then nothing.
  - Pass: in `fixed` mode the duration is ≥ 2.8 s, and `repeats` > 20.
  - With `changes` mode: frames ≤ 6 and duration ≥ 1.8 s. `mpdecimate` with `max=9` keeps 1 frame in 10, so the file can end up to 1 s before the stop (P4).

### 14.4 CI (`.github/workflows/build.yml`, job `linux`, `ubuntu-24.04`)

- Triggers: `push` on branches `[main, linux-port]`, and `pull_request`.
- Job env: `DESKTOP_RECORDER_REQUIRE_GUI: "1"` (D23).
- apt: `mono-devel libmono-system-windows-forms4.0-cil libmono-system-drawing4.0-cil python3 python3-gi python3-gi-cairo python3-xlib gir1.2-gtk-3.0 gir1.2-gstreamer-1.0 gir1.2-notify-0.7 gstreamer1.0-plugins-base ffmpeg xvfb xdotool x11-utils x11-xserver-utils dbus`
  - `x11-utils` gives `xwininfo` and `xdpyinfo`. `x11-xserver-utils` gives `xset`. `dbus` gives `dbus-run-session` (UNVERIFIED on noble: the binary can be in `dbus-daemon`, which `dbus` pulls in).
- Steps, with the working directory at the repo root. Each line is one exact command:
  1. `Unit tests`:
     - `env -u DISPLAY PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_linux*.py' -v`
     - `PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_pdeathsig.py' -v`
     - `PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_gst_pipeline.py' -v`
  2. `Core tests (Mono)`: the existing `mcs` and `mono` lines.
  3. `GUI tests`: `dbus-run-session -- xvfb-run -a -s "-screen 0 1280x800x24" env PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_x11*.py' -v`
  4. `actions/upload-artifact@v4` with `if: failure()`, name `linux-test-output`, path `${{ runner.temp }}/dr-tests`.
- The pattern `test_linux*.py` also loads `tests/test_linux.py`. Its imports must work after every merge (section 13).
- `run-tests.sh` runs the same groups with the same command lines, in the same order:
  - It does not set `DESKTOP_RECORDER_REQUIRE_GUI`, so a missing package skips.
  - It always runs the GUI group under its own `xvfb-run -a -s "-screen 0 1280x800x24"` (with `dbus-run-session --` when it exists). It never uses the live `DISPLAY`, so the tests do not move the real pointer or grab keys on Bran's desktop (P13).
  - If `xvfb-run` is missing, it prints `GUI tests skipped: xvfb-run is missing.` and goes on.
  - Remove the current `DISPLAY=:1` detection.
- `release.yml`, job `linux`:
  - Add an apt step: `sudo apt-get update` and `sudo apt-get install -y ffmpeg python3-gi python3-xlib`.
  - Then the three unit-test commands of step 1, before the tarball.
  - Then run `desktop-recorder --help` and `desktop-recorder --check`. `--check` exits 0 because the apt step installs `ffmpeg`. Both load no GTK (8.6).
  - The release job does not set `DESKTOP_RECORDER_REQUIRE_GUI`. It installs no GStreamer, so `test_gst_pipeline.py` skips there. `build.yml` runs the full set.

---

## 15. Packaging and docs (owner C8)

### 15.1 apt line (launcher, README.txt, README.md)

```
sudo apt install ffmpeg python3 python3-gi python3-gi-cairo python3-xlib gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-pipewire pipewire pipewire-pulse wireplumber pulseaudio-utils xdg-desktop-portal xdg-desktop-portal-gnome xclip wl-clipboard
```

- The launcher check changes from `import gi` to `import gi, Xlib`. Removed: `xdg-desktop-portal-gtk` (GNOME does not need it). Added: `python3-xlib` and `gir1.2-gstreamer-1.0`.
- `gnome-shell-extension-appindicator` is on Ubuntu Desktop by default. Name it in the README for other desktops.

### 15.2 Tarball (`packaging/make-linux-tarball.sh`)

- The default version comes from `linux/desktop_recorder/__init__.py`. Parse it with `sed -n 's/^__version__ = "\(.*\)"/\1/p'`.
- Contents: `desktop_recorder/*.py`, `desktop-recorder` (mode 755), `README.txt`, `desktop-recorder.png` (256×256), and `desktop-recorder.desktop`. The script writes the `.desktop` file with `Exec=desktop-recorder` and `Icon=desktop-recorder`.
- The launcher gets `--install-menu`. This writes `~/.local/share/applications/desktop-recorder.desktop` with the absolute Exec path and `Icon=<here>/desktop-recorder.png`.
- `packaging/linux/desktop-recorder.png` is a one-time conversion: `ffmpeg -i packaging/icon/app-icon-source.jpg -vf scale=256:256 packaging/linux/desktop-recorder.png`. Commit the PNG.
- `build-linux.sh --install` uses the same PNG for `Icon=`.

### 15.3 README text changes

- `README.md` Linux section: replace "earlier tray recorder… no region selector" with these items:
  - The start flow: the hotkey opens the selector; drag and release starts; the same hotkey stops.
  - The keys: Esc, Enter, Space, `~`, C, M, P, arrows, Shift and Ctrl.
  - The two session types and their limits (section 16).
  - The settings table with the Linux keys.
  - The apt line.
  - The test commands.
  - The frame-rate rule from HANDOFF 6.8.
  - The `changes` mode note: `mpdecimate` keeps at least one frame each second, so the file can end up to 1 s before the stop on a still screen.
  - `run-tests.sh` runs the GUI tests in its own Xvfb, never on the live desktop.
- `packaging/linux/README.txt`: the same start and stop text, short. Add the Wayland note: "The first recording shows the GNOME screen-share dialog. Pick the screen and allow 'Remember'."

### 15.4 `.gitattributes` (add these lines)

```
*.py text eol=lf
*.sh text eol=lf
linux/** text eol=lf
packaging/linux/* text eol=lf
packaging/linux/*.png binary
```

---

## 16. Limits and UNVERIFIED items after a CI run on Xvfb

CI checks the X11 path on Xvfb only (no window manager, no compositor, no GPU). It checks the GStreamer pump with `videotestsrc`. These items stay UNVERIFIED until a run on a real Ubuntu 24.04 PC:

| Item | Why it is not checked in CI |
|---|---|
| GNOME Wayland: portal dialog, `persist_mode=2` restore with no dialog, `AvailableCursorModes`, stream px = physical px with fractional scaling, the first frame on a still screen, match of `position` to `Gdk.Monitor` | CI has no Wayland session or portal. |
| `pipewiresrc fd= path= always-copy=true` on PipeWire 1.0.5, and the BGRx negotiation | CI has no PipeWire session. |
| Wayland border on XWayland (D10) is above other windows and outside the region | The behavior of Mutter. If it fails, set `wayland_frame=0` as the default. |
| Wayland selector keyboard focus, `set_startup_id` with the activation token | GNOME focus rules. |
| GNOME custom keybinding `<Super><Shift>d` works and is free on GNOME 46 | CI has no GNOME. |
| NVENC: `h264_nvenc` in the noble FFmpeg build, `bgr0` input, `-rgb_mode yuv444`, the probe | CI has no NVIDIA GPU. Driver 530.41.03 or later is needed. |
| Real tray: AppIndicator menu and icons in the GNOME top bar, libnotify timeouts | CI has no tray or notification server. |
| GNOME X11 session: compositor removes the selector before frame 0 (60 ms delay), override-redirect border stays on top, HiDPI with `S=2` | Xvfb has no compositor and scale 1. |
| X11 window detection with a real window manager (`_NET_FRAME_EXTENTS`, `_GTK_FRAME_EXTENTS`) | Xvfb has no window manager. Unit tests cover the math only. Optional: add `openbox` to CI (package and section not checked). |
| `python3-xlib` `shape.SK.Input` constant name | Fallback value 2 is in the code. |
| Python crop cost at 4K or 60 fps on Wayland | Only 640×480 is tested. Option: move the crop to `videocrop` later. |
| `xdotool key super+shift+d` reaches `Mod4` on the Xvfb keymap | All other GUI tests open the selector with `--toggle`. If it fails, only `test_hotkey_opens_selector` fails. |
| Clipboard on GNOME Wayland: `wl-copy -t text/uri-list` without focus (GNOME 46 has no wlr-data-control), and whether Nautilus and browsers paste a `text/uri-list` file without `x-special/gnome-copied-files` (D26) | CI has no Wayland session. |
| XWayland start on demand: the first python-xlib `Display()` for the Wayland border can block the main thread for about 1 s (D27) | CI has no GNOME. |
| GTK3 on Wayland: `get_primary_monitor()` can return None (fallback `get_monitor(0)`, 9.3) | CI has no Wayland session. |
| The GNOME custom keybinding sets `XDG_ACTIVATION_TOKEN` or `DESKTOP_STARTUP_ID` for `--toggle` | CI has no GNOME. Right-click still cancels without focus. |
| Mutter sets `_NET_FRAME_EXTENTS = 0,0,0,0` together with `_GTK_FRAME_EXTENTS` on CSD windows (9.4) | Xvfb has no window manager. `window_rect` handles both orders of values. |
| `FileIO.write` short writes on Ubuntu pipes | The `write` loop (6.2) handles them. The unit test uses a fake stdin. |
| Padded stride from `pipewiresrc` / `videoconvert` passthrough (D20) | CI has no PipeWire. The unit test uses a fake padded buffer. |
| Xvfb auto-repeat for XTEST keys (`test_hotkey_no_repeat`) | The test can pass with no repeat. The pure filter test covers the rule. |
| apt names: `dbus-run-session` from `dbus` on noble, `xset` from `x11-xserver-utils` | Not checked with `apt-file`. The first CI run shows it. |
| `preexec_fn` with other threads running (6.1) | A named Python limit. No stdlib option. |
| `xwininfo -name "Stop recording"` finds the GTK POPUP window by its title (GTK sets `WM_NAME` on override-redirect windows) | Not run yet. The first Xvfb CI run shows it. The selector tests use the stderr line, not `xwininfo`. |

Named platform limits (in the README):
- Wayland has no window detection, no Stop button on the screen, and arrow keys do not move the real pointer.
- A Wayland region stays on one monitor.
- Linux has no exclude-from-capture: the frame side or the Stop button is not drawn when it cannot be outside the region.
- In `changes` mode, late captures can make "Real frames" too low (7.3). On X11 in `changes` mode, a late capture is not counted.
- In `changes` mode, the file can end up to 1 s before the stop on a still screen (`mpdecimate` keeps 1 frame each second).
- On Wayland, Esc can fail when GNOME does not give focus to the selector. Right-click cancels.

---

## 17. Change log v2

Sources: `critique-parity.md` (items 1 to 26), `critique-platform.md` (P1 to P16, R1 to R9), and three extra items from the task (E1 to E3). One line for each change.

- 1: `plan_x11` gets `region=None` when no region is saved (`is_empty`, not `or None`); the off-screen note only for a non-empty region that clips to empty (5.3, 12.1).
- 2: New 8.7 thread table (D19). Socket and hotkey events reach the controller only through `GLib.idle_add`; socket waits on an Event for 5 s (8.4).
- 3: `window_rect` grows by `_NET_FRAME_EXTENTS`, then shrinks by `_GTK_FRAME_EXTENTS` (9.4); new `test_both_extents`.
- 4: `GDK_BACKEND=wayland` moves to `__main__.py`, before the `ui` import (8.6, 12.1).
- 5: `FfmpegProcess.write` loops until all bytes are written, also for `b"q"` (6.2); new `test_write_loops_on_short_writes`.
- 6: D15: launch start notifies only with a note (Windows parity); stderr line `Desktop Recorder: plan <backend> <encoder>` at every start; launch tests use it.
- 7: The fallback reason is the first note of the normal start notification, not a separate one (5.4, 8.2).
- 8: FFmpeg stop by itself and a start error notify for 8000 ms; tray row 2 and the tray update first (8.2, 8.3).
- 9: D16: each retry takes a new snapshot and new stats, on both paths (5.4, 8.2, 11.3).
- 10: Wayland launch with no saved region records stream 0 with no note (11.3 step 8).
- 11: Right-click in `pending` or `creating` reverts the drag and keeps the selector open (9.1); test has 4 cases.
- 12: `border_layout` tests sides on un-extended strips, computes `outer` first, top and bottom span `outer` (Windows corner rule) (9.2); new border tests.
- 13: D17: `FramePump.restart(write)` for the Wayland retry; it keeps the latest frame and zeroes the counters (7.1, 11.3).
- 14: The two audio warnings go into `messages.py` and the start notification as notes (8.2 step 6).
- 15: `probe_pulse(device, timeout=2.0, ffmpeg="ffmpeg")`; callers pass `ffmpeg=` as a keyword (12.3).
- 16: `load_settings` catching errors is named a change; it catches `OSError`, `UnicodeDecodeError`, `ValueError` (4.1).
- 17: ASCII-only digit checks in `parse_progress` and a regex check before `int()` in the settings parser (4.2 rule 9, 6.3).
- 18: X11 frame uses `scale=float(S)` and `gdk_scale=S` (10).
- 19: `test_toggle_cli_replies` expects `SELECTING`, then `STOPPING` or `STOPPED` (14.2).
- 20: CI unit step has one exact command for each group (14.4).
- 21: D28: stderr line first, lazy `Notify` with caught errors, `gir1.2-notify-0.7` in CI apt (12.1, 14.4).
- 22: Wayland golden string says "contains" (5.2).
- 23: `test_linux_ffproc.py` reuses `tests/fake_ffmpeg_stats.py` (42/3/2, `boom: capture failed`); `fake_ffmpeg.py` leaves the C4 row and does not change (13, 14.1).
- 24: Selector lines are filled whole-pixel rectangles; magnifier zoom, center cell, caption and border offsets from Windows (9.3).
- 25: D25: `visible_rects` drops the `own_pid` skip and parameter (9.4); new `test_own_pid_not_skipped`.
- 26: D24: `wayland_stats` uses `has_progress = progress is not None` (6.3); test covers both cases.
- P1: `STATS_RE` has no `Last recording: ` prefix (14.2).
- P2: The motion that starts `creating` also applies the creating rule, so a one-motion drag accepts (9.1); new `test_one_motion_drag_accepts`.
- P3: `press` sets the cursor and `hover`; the shells call `motion` once at open with the pointer position; tests wait for the "Select region" window (9.1, 9.3, 14.2).
- P4: `changes` mode duration checks use W − 2.5 s (X11) and 1.8 s (GStreamer); README names the up-to-1-s cut (14.2, 14.3, 15.3, 16).
- P5: D29: `--toggle` starts a tray only when the socket is not reachable; 6 s client timeout; timeout gives exit 0 and no UI; server replies `BUSY` after 5 s (8.4, 8.6).
- P6: D18: the ticker waits for a frame newer than the accept frame, or 500 ms (7.1, 7.2, 11.3); new pump tests.
- P7: D20: `frame_stride` gives the stride from the buffer size, option (b) (7.1, 11.2); new stride tests.
- P8: Exact call `root.translate_coords(win, 0, 0)` (9.4).
- P9: D23: `DESKTOP_RECORDER_REQUIRE_GUI=1` in CI turns each skip into a failure (14.0, 14.4).
- P10: Resolved without a second owner: C8's first step removes the four old classes and their imports from `tests/test_linux.py`, so no later merge breaks it (13).
- P11: GUI step runs under `dbus-run-session`; env `DESKTOP_RECORDER_NOTIFY=stderr` skips libnotify in tests (12.1, 14.2, 14.4).
- P12: `release.yml` gets an apt step; `__main__.py` imports GUI modules lazily, so `--check` and `--help` load no GTK (8.6, 14.4).
- P13: `run-tests.sh` always runs the GUI group in its own Xvfb; tests read the screen size from `xdpyinfo` (14.2, 14.4).
- P14: `x11_pattern.py` sets the pattern as `background_pixmap` (14.2).
- P15: Magnifier check uses `near` with tol 24 at two pixels of the border row (14.2).
- P16: Pure `KeyRepeatFilter` in `hotkey_x11.py` with `tests/test_linux_hotkey_x11.py` (C7); `xset r on` in the X test (8.5, 14.2).
- R1: All GUI tests open the selector with `--toggle`; one test (`test_hotkey_opens_selector`) uses the hotkey (14.2).
- R2: Wayland selector falls back to `display.get_monitor(0)` when there is no primary monitor (9.3).
- R3: Right-click is the cancel path without focus; Wayland selector draws `"Esc or right-click: cancel"`; token source UNVERIFIED (9.1, 9.3, 16).
- R4: D27: the border XWayland connect delay is accepted and named (10, 16).
- R5: D22: `-thread_queue_size 128` for x11grab; Golden argv 1 updated (5.2).
- R6: D26: clipboard does not change; GNOME Wayland paste added to section 16.
- R7: `preexec_fn` thread risk named in 6.1 and section 16.
- R8: Same fix as 20 (14.4).
- R9: D21: "whole screen" is `plan.region is None`; `plan_x11` sets it when the region equals `make_even(screen)`; status, frame and test use it (5.3, 8.1, 10).
- E1: The selector works the same from `--toggle`, the hotkey, the tray and `ui.run(select=True)`; `toggle` returns at once; `ui.run(select, token)`; new `test_toggle_starts_tray_when_none` (8.1, 8.6, 9.3, 14.2).
- E2: `tests/test_linux.py` is C8's alone; its kept imports are listed; its socket and `uri_list` checks skip on Windows (13).
- E3: Section 13 table: `tests/linux_skip.py` and `tests/test_linux.py` to C8 (first step), `tests/test_linux_hotkey_x11.py` to C7, `tests/fake_ffmpeg.py` removed from C4; the unchanged files are listed.
- Also: Windows dev PC rules in section 0 and 14.0: guarded `ctypes.CDLL(None)` and PDEATHSIG spawn (6.1), `posixpath.join` for the output path (5.2), and one skip helper.
- Also: the old "Checked in this session" block is replaced by the lines below.
- Also: `tests/linux_skip.py` has exact code in 14.0; the helpers take no `TestCase` and raise `SkipTest` or `AssertionError`, so they work in `setUpClass`.
- Also: C8's part one is a "first step" that runs before any other owner starts (it may be a commit or not) (0, 13).
- Also: `PumpCounters` moves to `ffstats.py` (C4); `wayland_pump.py` imports it; C4 no longer depends on C5 (3.2, 13).
- Also: `InstanceServer` gets `schedule` and `wait`; the `BUSY` rule is in `single_instance.py` and has unit tests (8.4, 14.1).
- Also: the selector writes `Desktop Recorder: selector open` after the grab and the first hover; GUI tests wait for it with `wait_selector()` (9.3, 14.2).
- Also: `ui.run(..., from_toggle=True)`: a lost socket race on the `--toggle` path sends `TOGGLE` to the winner and exits 0 with no dialog (8.6, 12.1).
- Also: X11 shell steps renumbered 1 to 9 (9.3).

Checked (v2 edit): the critique claims against `DesktopRecorder.cs` (start notification, `StartSavedRegion`, `recorder.Failed`, `TryFallback`), `RecordingFrame.ComputeBorderRects`, `RegionSelector.cs` (right-click, `DrawMagnifier`), `RecordingSession.Start`, and the Linux files `tests/test_linux.py`, `tests/fake_ffmpeg*.py`, `single_instance.py`, `__main__.py`, `ui.py`, `hotkey_x11.py`, `clipboard.py`, `audio.py`, `capture.py`. On this Windows PC: `socket.AF_UNIX` is missing, `ctypes.CDLL(None)` raises `TypeError`, `fcntl` is missing, and `hotkey_x11`, `single_instance` and `audio` import.

Not checked: no code was built or run on Linux. The apt names `dbus` and `x11-xserver-utils`, and all items in section 16, stay UNVERIFIED.
