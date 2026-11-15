# Inventory of the current Linux port (worktree `G:/CLAUDE CODE/svr-linux-port`, branch `linux-port`, HEAD cb07dff)

Checked: I read every file in the task list in full. I also checked the line endings with `git ls-files --eol` and the CI runs with `gh run list`. Not checked: nothing ran on Ubuntu. Every claim about runtime behaviour on Ubuntu is UNVERIFIED unless a CI result covers it.

## 1. Module map (`linux/desktop_recorder/`)

| File | Job | Public items | Imports gi? |
|---|---|---|---|
| `__init__.py` | Version | `__version__ = "1.1.0"` (:3). This is stale: the tarball README says 2.0.0. | No |
| `__main__.py` | CLI entry | `main(argv)`, `check()`, `toggle()`, `smoke(seconds)`, `HELP`. No args runs `ui.run()`. `-h/--help`, `--check`, `--toggle`, `--smoke SEC` (default 1.5). | Only through a lazy `from .ui import run` (:31) |
| `settings.py` | settings.txt | `DEFAULT_FPS=2.0`, `MIN_FPS=0.2`, `MAX_FPS=60.0`, `clamp_fps/quality/split`, `config_dir()` (`$XDG_CONFIG_HOME` or `~/.config` + `/DesktopRecorder`), `settings_path()`, `default_folder()` (`~/Recordings`), `@dataclass Settings`, `parse_settings`, `serialize_settings`, `load_settings`, `save_settings` (tmp file + fsync + `os.replace`) | No |
| `hotkey.py` | Hotkey text rules (copy of Windows) | `parse_key`, `is_valid`, `try_set`, `text_of`, `gtk_accelerator` | No |
| `ffmpeg_cmd.py` | ffmpeg argv and GStreamer pipeline text | `CRF=(32,27,21)`, `format_fps`, `fps_fraction`, `stamp_of`, `x11_target`, `capture_backend`, `_encoder`, `x11_argv`, `wayland_ffmpeg_argv`, `wayland_pipeline` | No |
| `recording.py` | One ffmpeg process for X11 (state machine idle/recording/stopping) | `Recording` (`is_active`, `start(argv, folder, fps)`, `stop()`, `session_files()`, `on_failed`), `_snapshot`, `_finish`, `_close_pipes` | No |
| `capture.py` | Chooses X11 or Wayland | `Capture` (`is_active`, `start(settings, display, ffmpeg)`, `stop()`, `session_files()`, `mode`, `warning`) | Only through a lazy import of `portal` |
| `portal.py` | xdg-desktop-portal ScreenCast | `PortalError`, `@dataclass PortalStream(session,node_id,serial,fd,restore_token,width,height)`, `PortalTransport` (Protocol), `ScreenCast.open(restore_token)` (pure), `GioTransport` (gi Gio/GLib, imported inside `__init__`) | `GioTransport` only (lazy) |
| `wayland.py` | PipeWire → GStreamer appsink → ffmpeg stdin | `WaylandCapture` (`active`, `start`, `stop`, `session_files`, `error`) | Gst (lazy, inside `start`/`stop`) |
| `audio.py` | Monitor source through pactl | `monitor_from_listing`, `choose_monitor`, `probe_pulse`, `find_monitor` | No |
| `autostart.py` | XDG autostart file | `autostart_path` (`~/.config/autostart/desktop-recorder.desktop`), `write_autostart(command, enabled, path)`, `autostart_enabled` | No |
| `clipboard.py` | text/uri-list copy | `uri_list`, `copy_files` (`wl-copy -t text/uri-list` if `WAYLAND_DISPLAY`, else `xclip -selection clipboard -t text/uri-list`, else wl-copy) | No |
| `sounds.py` | Two-tone chime | `build_chime`, `play(up)` (uses `paplay` / `pw-play` / `aplay` on a temp wav), `wav_duration_samples` | No |
| `hotkey_x11.py` | XGrabKey via ctypes `libX11.so.6` | `x_modifiers`, `keysym_for`, `X11Hotkey(display, modifiers, key, callback)` with `.start()`, `.stop()`, `.registered` | No (ctypes) |
| `gnome_hotkey.py` | GNOME custom keybinding through `gsettings` | `SCHEMA`, `BINDING`, `PATH`, `update_gnome_shortcut(mods, key, command, runner)` | No |
| `single_instance.py` | Unix socket | `InstanceServer(path, on_command)` with `.start()` / `.stop()`, `send_command(path, cmd)` | No |
| `ui.py` | Tray, menu, Settings dialog | `run()`, `Tray`, `SettingsDialog`, `QUALITY`, `_use_appindicator`, `_indicator`, `_write_icon` (pycairo), `_command_path`, `threading_is_main` | Yes, at module top: `gi.require_version("Gtk","3.0")` (:11). Lazy: Notify 0.7, AyatanaAppIndicator3 0.1. |

All other modules are pure Python. The tests import only the pure modules (and `hotkey_x11`). They never import `ui.py` or `wayland.py`.

## 2. Settings keys (`settings.py`)

Linux keys and defaults (dataclass at :54-68, serialize order at :180-192):

| Key | Default |
|---|---|
| `folder` | `~/Recordings` |
| `fps` | 2.0 (range 0.2 to 60) |
| `quality` | 1 (range 0 to 2) |
| `split_minutes` | 30 (range 0 to 1440) |
| `record_on_launch` | 1 |
| `copy_to_clipboard` | 1 |
| `play_sounds` | 1 |
| `hotkey` | `Win+Shift+D` (mods `4\|8`, key `"D"` as a string) |
| `record_audio` | 1 |
| `start_on_login` | 0 |
| `wayland_restore_token` | `""` |

Unknown lines are kept in `extra_lines`. The file is written with `\n` line endings.

Differences from Windows (`RecorderCore.cs:10-40`, `:469-491`):

1. Default `fps`: Linux 2, Windows 10 (`DefaultFps = 10`, :134).
2. Linux has no `show_pointer` (Windows default 1). `-draw_mouse 1` is hard-coded (`ffmpeg_cmd.py:127`).
3. Linux has no `capture_backend` (Windows: `ddagrab` or `gdigrab`, default `ddagrab`).
4. Linux has no `encoder` (Windows: `auto`, `h264_nvenc` or `libx264`, default `auto`).
5. Linux has no `chroma` (Windows: `yuv420` or `yuv444`, default `yuv420`).
6. Linux has no `frame_rate_mode` (Windows: `fixed` or `changes`, default `changes`).
7. Linux has no `nvenc_cq` (Windows default 23). Quality maps to `NvencCqForQuality`, which gives 28/23/17.
8. Linux has no `region` or `last_region` (`x,y,w,h`, 0 = whole desktop).
9. Linux has no `selector_crosshair` (0), `selector_magnifier` (1) or `selector_position` (1).
10. Windows reads and drops `last_region_hotkey` and `stop_hotkey`. Linux keeps them as extra lines.
11. Windows has no `record_audio`, `start_on_login` or `wayland_restore_token`. Windows keeps them as ExtraLines. Windows stores "start with Windows" outside the file.
12. Line endings: Windows writes `\r\n`, Linux writes `\n`. Both parsers accept both.
13. Lines with no `=`: Windows `eq < 1` also treats a line that starts with `=` as an extra line. Linux uses `"=" not in line` (:114).
14. Hotkey key type: Windows uses an int VK. Linux uses a string such as `"D"` or `"F1"`. The text form is the same.

## 3. Capture flow

### Backend choice

`capture_backend()` (`ffmpeg_cmd.py:41-48`) works in this order:
1. `DESKTOP_RECORDER_CAPTURE=x11|wayland` forces the backend.
2. Otherwise, if `WAYLAND_DISPLAY` is set or `XDG_SESSION_TYPE=wayland`, the backend is `wayland`.
3. Otherwise the backend is `x11`.

`ui.run()` sets `GDK_BACKEND=wayland` when the backend is wayland and `DISPLAY` is set (:33-36).

### Common start (`capture.py:28-52`)

1. Find ffmpeg with `shutil.which`.
2. If `record_audio` is on, `find_monitor()` runs `pactl get-default-sink`, `pactl list short sources` and `pactl list short sinks`. It returns `<sink>.monitor`.
3. `probe_pulse()` runs `ffmpeg -hide_banner -loglevel error -f pulse -i DEV -t 0.2 -f null -` with a 2 s timeout. If the probe fails, the recording has no audio and `warning` is set.
4. `when = datetime.now()`.

### X11

The argv comes from `x11_argv` (:112-135):

```
ffmpeg -hide_banner -loglevel error -nostats -y -thread_queue_size 1024 -f x11grab -framerate <fps> -draw_mouse 1 -i <DISPLAY normalized to :N.0>
  [-thread_queue_size 1024 -f pulse -i <monitor>]
  -vf crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0 -c:v libx264 -preset medium -tune stillimage -crf <32|27|21>
  -x264-params rc-lookahead=<clamp(round(fps*2),0,40)> -threads <ceil(fps) 1..16> -g <max(2,round(fps*30))> -pix_fmt yuv420p
  [-c:a aac -b:a 128k]
  split>0:  -force_key_frames expr:gte(t,n_forced*<sec>) -f segment -segment_time <sec> -segment_format mp4
            -segment_format_options movflags=+frag_keyframe+empty_moov:frag_duration=2000000:flush_packets=1
            -reset_timestamps 1 <folder with % doubled>/desktop_<stamp>_%03d.mp4
  split=0:  -movflags +frag_keyframe+empty_moov -frag_duration 2000000 -flush_packets 1 <folder>/desktop_<stamp>.mp4
```

- The stamp format is `%Y-%m-%d_%H-%M-%S_mmm`.
- There is no `-video_size` and no offset, so ffmpeg records the whole X screen.
- There is no NVENC, no mpdecimate and no `-stats`.

`Recording.start` (`recording.py:32-63`) works as follows:
1. It creates the folder.
2. It takes a snapshot of the existing `desktop_*.mp4` files.
3. It runs `Popen(argv, stdin=PIPE, stderr=PIPE, stdout=DEVNULL)`.
4. A thread named `ffmpeg-stderr` keeps at most about 2000 characters of stderr.
5. If ffmpeg exits while the state is "recording", the thread calls `on_failed(stderr text)`. The UI wires this callback for X11 only (`ui.py:56`).

Stop (`_finish`, :164-186):
1. It writes `b"q"` to stdin.
2. It waits `min(15, 4 + 2/fps)` s.
3. If ffmpeg is still running, it calls `kill()` and waits 5 s.
4. The watcher join is 10 s. A second `stop()` during "stopping" waits on `_idle` for 20 s.

`stop()` runs on the GTK thread, so the UI blocks during the stop.

### Wayland

1. `GioTransport()` gets the session bus. `ScreenCast(transport).open(settings.wayland_restore_token)` (`portal.py:47-87`) makes these calls:
   - `CreateSession {session_handle_token:"dr<16 hex>", handle_token}`
   - `SelectSources(session, {types:u 1 (monitors), multiple:b true, cursor_mode:u 2 (embedded), persist_mode:u 2, [restore_token:s]})`
   - `Start(session, "", {})`
   - Each call waits for the `org.freedesktop.portal.Request.Response` signal on `/org/freedesktop/portal/desktop/request/<sender>/<token>`. A nested `GLib.MainLoop` runs with a 120 s timeout (:122-166). A response code other than 0 raises "Screen sharing was cancelled."
   - `streams[0]` gives `node_id`, `pipewire-serial` and `size`. The other streams are ignored, although `multiple` is true.
   - `OpenPipeWireRemote(session, {})` uses `call_with_unix_fd_list_sync`. The code calls `os.dup` on the fd and then closes the original.
   - The restore token is `started["restore_token"]`, else the old token.
2. `capture._start_wayland` copies the new token into the in-memory `settings` object (:65-66). **No code saves it to disk.** `save_settings` is called only from `show_settings` (`ui.py:182`). Thus each new app start shows the share dialog again, unless the user saved Settings in that run.
3. The pipeline text comes from `wayland_pipeline` (`ffmpeg_cmd.py:171-181`):
   `pipewiresrc fd=<fd> path=<node> do-timestamp=true [target-object=<serial>] ! videoconvert ! videorate ! video/x-raw,format=BGRA,framerate=<n>/<d> ! appsink name=sink emit-signals=true sync=false max-buffers=2 drop=true`
   - The fps is a fraction in tenths, so 0.2 becomes `1/5`.
   - `videorate` makes a constant rate: it duplicates frames when PipeWire sends nothing (PipeWire sends on damage) and drops extra frames.
4. The `new-sample` callback (on a GStreamer thread) does this:
   - It reads width and height from the caps.
   - It copies the buffer with `bytes(info.data)`. The code assumes that stride = width × 4.
   - `_ensure_encoder` starts ffmpeg on the first frame with `wayland_ffmpeg_argv`:
     `ffmpeg -hide_banner -loglevel error -nostats -y -f rawvideo -pixel_format bgra -video_size WxH -framerate <fps> -i pipe:0 [-thread_queue_size 1024 -f pulse -i DEV -shortest]` + the same `_encoder` tail.
   - `Popen(stdin=PIPE, stderr=PIPE, stdout=DEVNULL)`. **Nothing reads stderr.**
5. Frame dropping happens in three places:
   - appsink `max-buffers=2 drop=true`.
   - The Python `queue.Queue(maxsize=2)`. `_offer` calls `put(timeout=0.05)` and drops the frame silently on `queue.Full`.
   - Thread `wayland-frames` writes the frames to ffmpeg stdin.
   - ffmpeg sets timestamps from the frame count (`-framerate`), so each drop makes the video shorter. No code counts drops.
6. A GStreamer bus ERROR sets `self.error` and calls `self.stop()`. The UI is not refreshed and gets no notification. An ffmpeg crash on Wayland is silent: the pump thread ends and `_started` stays True.
7. Stop (`wayland.py:151-190`, then `capture.stop`):
   - The pipeline goes to NULL.
   - The code drains the queue and puts `None`.
   - The pump closes stdin and joins (5 s).
   - `proc.wait(8)`, else kill and wait 5 s.
   - The code closes the PipeWire fd.
   - `GioTransport().close_session(session)` calls `org.freedesktop.portal.Session.Close` with a 5 s timeout.

### If the app is killed

- No code uses `prctl(PR_SET_PDEATHSIG)`, `preexec_fn`, `start_new_session`, a signal handler or `atexit`. A grep for these returned nothing.
- X11: ffmpeg gets EOF on stdin. EOF is not `q`. ffmpeg very probably keeps recording until it writes to the broken stderr pipe, and with `-loglevel error -nostats` that is rare. This is the same failure as Windows bug 5. UNVERIFIED on Linux.
- Wayland: ffmpeg gets EOF on `pipe:0` and finishes the file. The GStreamer pipeline dies with the process. The portal session ends when the D-Bus connection closes. UNVERIFIED.

## 4. Hotkey and single instance

`Tray._install_hotkey` (`ui.py:239-273`) runs at start and after each Settings save.

**X11** (`hotkey_x11.py`):
- The code calls `XInitThreads`, then `XSetErrorHandler`. This replaces the error handler for the whole process, so it can interfere with GDK. This is a fragile spot.
- It calls `XOpenDisplay(DISPLAY)` and `XKeysymToKeycode`.
- `XGrabKey` runs on the root window with the base mask OR each of `{0, LockMask, Mod2Mask, Lock|Mod2}`, then `XSync`. If the error handler fired, the grab failed.
- The mask mapping is Alt→Mod1 (8), Ctrl→Control (4), Shift→Shift (1), Win→Mod4 (64).
- The F-key keysym is `0xFFBE + n - 1`.
- A thread `select()`s on the X fd with a 0.2 s timeout. Each KeyPress runs the callback `GLib.idle_add(self.toggle)`.
- Auto-repeat is not filtered, so a held key can toggle many times.
- If the grab fails, the user gets a notification: "<hotkey> is used by another program, so the hotkey is off."

**Wayland**:
- `_command_path()` returns `$DESKTOP_RECORDER_COMMAND` (if its first word exists) or `~/.local/bin/desktop-recorder`. If neither exists, the user gets the notification "Install the program to enable the Wayland hotkey."
- `update_gnome_shortcut` makes these calls:
  - `gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings`
  - It adds the path `/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/desktop-recorder/` to the list if it is missing.
  - `gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:<PATH> name "Desktop Recorder"`
  - Then `binding <Super><Shift>d` and `command "<cmd> --toggle"`.
- The code never removes the shortcut.
- `--toggle` when no tray is running prints "Desktop Recorder is not running." and exits 1. It does not start the tray.

**Single instance** (`single_instance.py`):
- The socket is `~/.config/DesktopRecorder/control.sock`, not in `$XDG_RUNTIME_DIR`. The code sets the directory to mode 0700 and the socket to 0600.
- `start()` probes with a connect. A live socket means another instance runs, and `start()` returns False. A stale file is unlinked.
- The protocol is a single line of at most 64 bytes. The only command is `TOGGLE`. The reply is `RECORDING` or `STOPPED`.
- The server thread marshals the command to GTK with `GLib.idle_add` and waits 5 s.
- A second app start shows a GTK MessageDialog: "Desktop Recorder is already running. Look for its icon in the tray."

## 5. Tray and Settings

**Tray type** (`_use_appindicator`, `ui.py:284-291`):
- `DESKTOP_RECORDER_TRAY=appindicator|status` forces the type.
- Otherwise the app uses AppIndicator when the backend is wayland or when `GNOME` is in `XDG_CURRENT_DESKTOP`.
- AppIndicator is `AyatanaAppIndicator3 0.1`, id `desktop-recorder`, category APPLICATION_STATUS. If AppIndicator is not available, the app uses `Gtk.StatusIcon` (left click toggles, right click opens the menu).

**Icons**: pycairo draws two 32×32 PNGs into the config dir, `icon-off.png` (grey) and `icon-on.png` (red with a white dot). Bran's icon set is not used.

**Menu**:
- "Not recording" / "Recording at N fps" (disabled)
- separator
- "Start recording" / "Stop recording" + 4 spaces + the hotkey text (X11 only, when the grab worked)
- "Open recordings folder" (`xdg-open`)
- "Settings..."
- separator
- "Exit"

There is no status line with frame counts, because nothing parses `-stats`.

**Notifications**: libnotify `Notify 0.7`. If libnotify is not available, the text goes to stderr.

**Settings dialog** (`ui.py:351-524`), title "Desktop Recorder settings", buttons Cancel and Save:

| Field | Widget |
|---|---|
| Folder | Entry + "Browse..." (a SELECT_FOLDER chooser) |
| "Frames per second (0.2 to 60):" | SpinButton, step 0.1, 1 digit |
| "Quality:" | Combo with the 3 `QUALITY` strings |
| "New file every (minutes, 0 = never):" | SpinButton 0 to 1440 |
| "Hotkey:" | Check boxes Win/Ctrl/Alt/Shift + key combo (A-Z, 0-9, F1-F12) |
| Check boxes | "Start Desktop Recorder when I log in", "Start recording when Desktop Recorder starts", "Copy the video to the clipboard when recording stops", "Play a sound when recording starts and stops", "Record system audio (what you hear)" |

Save writes the settings, writes the autostart file and installs the hotkey again. **Save during a recording stops it and starts a new file** (:188-190). Windows removed this behaviour (bug 4).

**Start**: `record_on_launch` (default 1) starts a full-screen recording at once through `GLib.idle_add`.

**After stop**: the app copies `session_files()` as a uri-list and shows "Video copied. Paste it into a folder or a chat."

## 6. Tests and CI

**`tests/test_linux.py`** (pure, no display needed):

| Test | What it checks |
|---|---|
| `HotkeyTests` | `try_set` follows the Windows rules |
| `SettingsTests` | NaN fps → 2, quality clamp 9→2, an invalid hotkey keeps the default, the Linux keys round-trip, `extra_lines` are kept |
| `ArgumentTests` | x11grab argv, `:1`→`:1.0`, the segment pattern and the `%%` escape, Wayland raw argv (`bgra`, `pipe:0`, `-shortest`), backend choice from the env vars, pipeline text (`fd=`, `path=`, `target-object=`, `framerate=2/1` and `1/5`) |
| `AudioTests` | Monitor choice |
| `PortalTests` | A fake transport gets the call order CreateSession, SelectSources, Start, OpenPipeWireRemote; the SelectSources options; the restore token in and out; zero streams → `PortalError` and the session is closed |
| `RecordingTests` | With `fake_ffmpeg.py`: a failure calls `on_failed` with "boom: bad input"; a second start is refused; `session_files` skips the old files; `--slow` stop overlap |
| `OtherTests` | Chime WAV header, uri-list encoding, autostart enable and disable, socket single-instance, stale socket, `TOGGLE` reply, gsettings argv |

**`tests/test_x11_session.py`** is skipped unless `DISPLAY` is set, ffmpeg and ffprobe exist, and `xdpyinfo` succeeds:
- `test_hotkey_grab` grabs Ctrl+Shift+F12 and sends `xdotool key ctrl+shift+F12`. It expects the callback within 2 s. It skips if xdotool is missing.
- `test_smoke_recording` runs `smoke(1.2)`. That is a real x11grab + libx264 recording at 2 fps, and ffprobe must report a duration of at least 0.2 s.

**Fake ffmpeg**:
- `fake_ffmpeg.py` writes `x` to the last argument (`%03d`→`000`). `--fail` writes "boom: bad input" to stderr and exits 1. Otherwise it reads stdin until `q` or EOF; `--slow` then sleeps 0.8 s; then it appends `ok`.
- `fake_ffmpeg_stats.py` is used only by the C# `tests/CoreTests.cs` (:814). It writes `frame=` stats lines that end in `\r`, with `dup=1`, then a final line with `dup=3 drop=2`.

**`run-tests.sh`**:
1. If `DISPLAY` is empty and `:1` answers, it uses `:1`.
2. `mcs -sdk:4.5 ... tests/CoreTests.cs RecorderCore.cs RecordingSession.cs`, then `mono`.
3. `PYTHONPATH=linux python3 -m unittest discover -s tests -v`.

**CI** (`.github/workflows/build.yml` job `linux`, `ubuntu-24.04`):
- It runs on push to `main` and on pull requests only. A push to `linux-port` without a PR does not run it.
- apt list: `mono-devel libmono-system-windows-forms4.0-cil libmono-system-drawing4.0-cil python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 ffmpeg xvfb xdotool x11-utils`.
- Command: `xvfb-run -a ./run-tests.sh`.
- The last Build runs on main passed (cb07dff, febdccc, d96cbc3).
- CI installs no GStreamer, no AppIndicator, no libnotify and no portal. `ui.py`, `wayland.py` and `GioTransport` are never imported in CI.

## 7. Packaging

**`packaging/make-linux-tarball.sh [version=1.0.0] [out_dir=repo root]`**:
- It makes `desktop-recorder-<ver>-linux-x86_64.tar.gz`.
- Contents: `desktop_recorder/*.py` (with `__pycache__` and `.pyc` removed), `desktop-recorder` (made executable) and `README.txt`.
- It adds no `.desktop` file and no icon.

**`packaging/linux/desktop-recorder`**:
- It sets `DESKTOP_RECORDER_COMMAND=$here/desktop-recorder` and `PYTHONPATH=$here`.
- With no args, if `import gi` fails, it prints the apt line and exits 1.
- Otherwise it runs `exec python3 -m desktop_recorder "$@"`.

**apt list** (README.txt:15-20, the same in the launcher and in README.md:218-223):
`ffmpeg python3 python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 gstreamer1.0-plugins-base gstreamer1.0-pipewire pipewire pipewire-pulse wireplumber pulseaudio-utils xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-gtk xclip wl-clipboard`.
- `gir1.2-gstreamer-1.0` is not in the list, and `from gi.repository import Gst` needs it. A default Ubuntu Desktop probably has it already. UNVERIFIED.

**`build-linux.sh`**:
- It runs `compileall`.
- `--install` copies the files to `$PREFIX` (default `~/.local`) `/share/desktop-recorder/desktop_recorder/`.
- It writes the wrapper `~/.local/bin/desktop-recorder` (it sets `DESKTOP_RECORDER_COMMAND` and `PYTHONPATH`).
- It writes `~/.local/share/applications/desktop-recorder.desktop` with `Icon=media-record`.

**`release.yml`** runs on a `v*` tag:
- Job `linux` (ubuntu-24.04) builds the tarball into `$RUNNER_TEMP`, copies it to `dist/`, runs `tar -t`, extracts it and runs `desktop-recorder --help`. It runs no unit tests. It uploads the artifact `linux-portable`.
- Job `publish` merges the `*-portable` artifacts and runs `gh release upload --clobber` or `gh release create`.
- The last Release run (v2.0.0, d96cbc3) failed. I did not check why. HANDOFF says febdccc fixed the Windows zip script.

**README.md:211-243**: says the Linux build "is the earlier tray recorder… no region selector". It gives the install steps and the test apt list `mono-devel libmono-system-windows-forms4.0-cil libmono-system-drawing4.0-cil x11-utils xdotool`.

## 8. Bugs, fragile spots, gaps

**Line endings and orphan ffmpeg**

1. **CRLF.** `core.autocrlf=true` on this PC. All Linux `.py`, `.sh` and `packaging/linux/desktop-recorder` files are `i/lf w/crlf`. `.gitattributes` has only `*.cmd eol=crlf` and `test/** eol=lf`. CI checkouts get LF, so CI is safe. But a tarball built or copied from this Windows worktree gets `#!/bin/sh\r` and `set -eu\r`, and the shell scripts fail. Fix: add `*.sh text eol=lf`, `*.py text eol=lf`, `linux/** text eol=lf` and `packaging/linux/* text eol=lf`.
2. **Orphan ffmpeg on kill (X11).** No `PR_SET_PDEATHSIG`. See section 3.

**Missing features** (all features named in the task):

3. No region selector, no border, no Stop button.
4. No `show_pointer`. `draw_mouse 1` and portal `cursor_mode 2` are fixed.
5. No NVENC: `libx264 -preset medium` only. No 4:4:4, no `changes` mode (mpdecimate + vfr), no `-stats`, no status line.
6. Default fps is 2, not 10.
7. Old hotkey semantics: the hotkey toggles a full-screen recording; it does not open a selector.

**Wayland capture**

8. The restore token is never saved to disk (see section 3). The share dialog comes back after each app restart.
9. Wayland failures are silent. `on_failed` is wired only for X11 (`ui.py:56`). Nothing reads ffmpeg stderr: it is a PIPE, so a full pipe can block ffmpeg (low risk with `-loglevel error`). `WaylandCapture.active` stays True after an ffmpeg crash.
10. Frames are dropped silently in three places (appsink, the Python queue, the `put` timeout of 0.05 s). Timestamps come from the frame count, so a drop makes the video shorter. `videorate` adds duplicates. The real-frame, duplicate and drop counts cannot be measured now.
11. A stride other than width × 4, or a size change in the middle of the stream, gives a corrupt raw feed (`wayland.py:70-80`). UNVERIFIED.
12. `portal._call` runs a nested `GLib.MainLoop` on the GTK thread for up to 120 s. Idle callbacks still run during that time, so a `TOGGLE` from the socket can enter `start_recording` again. `GLib.timeout_add(120000, …)` is never removed (`portal.py:157`).
13. The fd leaks when `Gst.parse_launch` raises: `_stream` is set after the parse (`wayland.py:54-58`), so `stop()` does not close the fd. `parse_launch` exceptions (for example, no `pipewiresrc`) become "Wayland screen capture failed: …".
14. `multiple: True` but only `streams[0]` is used.
15. `wayland_pipeline` uses `path=` (deprecated in newer pipewiresrc) together with `target-object`.

**UI, settings and processes**

16. `SettingsDialog.do_response` override (`ui.py:488-514`): with `dialog.run()`, the run loop also listens to the `response` signal, so an early `return` probably does not keep the dialog open. `result()` then checks the hotkey a second time. A relative folder becomes `os.path.abspath` of the cwd. UNVERIFIED.
17. Save in Settings restarts a running recording (`ui.py:188-190`). This conflicts with Windows decision 7.
18. Dead code at `ui.py:399-401`.
19. Stop runs on the GTK thread and can block for up to about 15 s (X11) or 18 s (Wayland).
20. `probe_pulse` uses the literal `"ffmpeg"`, not the resolved path (`audio.py:42`).
21. The socket is in `~/.config` (not `$XDG_RUNTIME_DIR`), and `chmod 0700` changes the config dir. Small race between `_reachable` and `bind`.
22. `XSetErrorHandler` replaces the handler for the whole process, and KeyPress auto-repeat is not filtered.
23. The GNOME shortcut is never removed. If the tarball folder moves, the shortcut points to a dead path. `--toggle` with no tray running does nothing visible (exit 1).

**Tests, CI, packaging and docs**

24. Test gaps: no test imports `ui.py` or `wayland.py`, and `GioTransport` is never run. CI has no GStreamer, no portal, no AppIndicator and no Notify. CI does not run on the `linux-port` branch without a PR. The release job runs only `--help`.
25. Version text does not match: `__version__` 1.1.0, the tarball README says 2.0.0, and the `make-linux-tarball.sh` default is 1.0.0.
26. `run-tests.sh` compiles only `RecorderCore.cs` and `RecordingSession.cs` with Mono. That works now (main CI is green). It breaks if `CoreTests.cs` starts to use `NativeMethods.cs`, `RegionSelector.cs` or `RecordingFrame.cs`.
27. The Ubuntu 24.04 ffmpeg 6.1 has no PipeWire input (`portal.py:3-4`). `ddagrab` and `gdigrab` do not exist on Linux, and `kmsgrab` needs extra rights. The Linux equivalents of the Windows backends are `x11grab` on X11 (with `-video_size WxH -i :0.0+X,Y` for a region) and the portal + GStreamer path on Wayland (crop in GStreamer `videocrop` or in the ffmpeg `crop`).
28. A freeze-frame selector on Wayland needs a screenshot. The `org.freedesktop.portal.Screenshot` portal is in `xdg-desktop-portal`. Its interactive and permission behaviour on GNOME 46 is UNVERIFIED.
29. NVENC on Ubuntu: the Ubuntu `ffmpeg` package lists `h264_nvenc`, but NVENC needs the NVIDIA proprietary driver (`libnvidia-encode`). It cannot run on GitHub runners. The `libx264` fallback must be the path that CI tests.

Files referenced (all under `G:/CLAUDE CODE/svr-linux-port/`):
- `linux/desktop_recorder/{__init__,__main__,settings,hotkey,ffmpeg_cmd,recording,capture,portal,wayland,audio,autostart,clipboard,sounds,hotkey_x11,gnome_hotkey,single_instance,ui}.py`
- `tests/test_linux.py`, `tests/test_x11_session.py`, `tests/fake_ffmpeg.py`, `tests/fake_ffmpeg_stats.py`
- `run-tests.sh`, `build-linux.sh`, `packaging/make-linux-tarball.sh`, `packaging/linux/README.txt`, `packaging/linux/desktop-recorder`
- `.github/workflows/build.yml`, `.github/workflows/release.yml`, `README.md`, `.gitattributes`, `RecorderCore.cs`