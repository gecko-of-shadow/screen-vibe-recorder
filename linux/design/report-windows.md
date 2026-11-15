# Feature inventory of the new Windows app, for the Linux port

Worktree: `G:/CLAUDE CODE/svr-linux-port`, branch `linux-port`, HEAD `cb07dff`. I read all the files that the task names, `NativeMethods.cs` lines 225–300, and `linux/desktop_recorder/settings.py`. I did not edit, build or run anything.

## 1. settings.txt keys

**File location**
- Windows: `%APPDATA%\DesktopRecorder\settings.txt` (`DesktopRecorder.cs:90`).
- Linux today: `$XDG_CONFIG_HOME/DesktopRecorder/settings.txt` (`linux/desktop_recorder/settings.py:41-47`).

**How the app writes the file**
- `RecorderCore.AtomicWrite` (`RecorderCore.cs:547`) writes UTF-8 with no BOM to `path + ".tmp"`. Then it calls `File.Replace`. If that fails, it copies the file and deletes the temp file.
- Each line ends with `\r\n`.

**How the app reads the file (`ParseSettings`, `RecorderCore.cs:329-359`)**
- Line endings: `\r\n` and `\r` become `\n`.
- Blank lines (after trim) are skipped.
- A line with no `=`, or with `=` at position 0 (`eq < 1`), is kept as an extra line, trimmed.
- For other lines, the key is the text before the first `=`, trimmed. The value is the rest, trimmed.
- A known key with a bad value is consumed and keeps the value from before. It is NOT kept as an extra line.
- An unknown key is kept as `key + "=" + val`, with both parts trimmed.
- After the parse, the app clamps and normalizes every field.
- When the app saves, it writes the extra lines at the end, in their old order (`RecorderCore.cs:492-502`).
- A load error gives the defaults (`DesktopRecorder.cs:175`).

**Key order and rules (`SerializeSettings`, `RecorderCore.cs:469-491`)**

| Key | Type | Default | Parse / clamp |
|---|---|---|---|
| `folder` | string | `%USERPROFILE%\Recordings` (`DesktopRecorder.cs:82`) | Accepted if not empty and has no CR or LF. |
| `fps` | double | `10` (`RecorderCore.cs:134`) | Invariant float. NaN or ±Inf becomes 10. Clamp 0.2..60. Written with format `0.###`. |
| `quality` | int | `1` | Clamp 0..2 (0 = Smallest, 1 = Balanced, 2 = Sharpest). |
| `split_minutes` | int | `30` | Clamp 0..1440. 0 = one file. |
| `record_on_launch` | bool | `1` | Only the exact text `"1"` is true. Anything else is false. |
| `copy_to_clipboard` | bool | `1` | Same rule. |
| `play_sounds` | bool | `1` | Same rule. |
| `show_pointer` | bool | `1` | Same rule. |
| `hotkey` | text | `Win+Shift+D` | See the hotkey rules below. |
| `capture_backend` | enum | `ddagrab` | Only `ddagrab` or `gdigrab`. Anything else keeps the value from before. |
| `encoder` | enum | `auto` | Only `auto`, `h264_nvenc` or `libx264`. |
| `chroma` | enum | `yuv420` | Only `yuv420` or `yuv444`. |
| `frame_rate_mode` | enum | `changes` | Only `fixed` or `changes`. |
| `nvenc_cq` | int | `23` | Clamp 1..51. Not shown in the dialog. |
| `selector_crosshair` | bool | `0` | |
| `selector_magnifier` | bool | `1` | |
| `selector_position` | bool | `1` | |
| `region` | `x,y,w,h` | `0,0,0,0` | Exactly 4 invariant ints, else no change. If w ≤ 0 or h ≤ 0, all four become 0. Physical px, virtual-screen coordinates. |
| `last_region` | `x,y,w,h` | `0,0,0,0` | Same rules. Written but never read by the app flow. |
| `last_region_hotkey`, `stop_hotkey` | none | none | Read and dropped. Not kept as extras (`RecorderCore.cs:441`). |

**Hotkey rules**
- Split the text on `+`. Each part is trimmed. An empty part makes the whole text invalid.
- Modifier names are case-insensitive: `Win` = 8, `Ctrl` = 2, `Alt` = 1, `Shift` = 4.
- Exactly one key is allowed: A–Z (lowercase is accepted), 0–9, `D0`–`D9`, or `F1`–`F24`.
- Valid only when the modifiers are not 0 and the key is set, and (Win, Ctrl or Alt is present, or the key is F1–F24).
- An invalid text keeps the old hotkey.
- Write order: `Win+Ctrl+Alt+Shift+KEY` (`RecorderCore.cs:241-327`).

**Not in the file on Windows**
- "Start with Windows" is stored in the registry: `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `DesktopRecorder` = `"<exe path>"` (`DesktopRecorder.cs:225-242`).

## 2. FFmpeg argv (`BuildCaptureArguments`, `RecorderCore.cs:830-1016`)

### Derived values

| Name | Formula |
|---|---|
| `F` | `fps.ToString("0.###")` after the clamp |
| `G` (GOP) | `max(2, round(fps*30))` |
| `L` (x264 lookahead) | `clamp(round(fps*2), 0, 40)` |
| `T` (x264 threads) | `clamp(ceil(fps), 1, 16)` |
| `K` (mpdecimate max) | `max(1, ceil(fps) - 1)` |
| `S` (split seconds) | `split_minutes * 60` |
| `STAMP` | local time, `yyyy-MM-dd_HH-mm-ss_fff` |
| `M` (pointer) | `1` when `show_pointer`, else `0` |
| `PIX` | `yuv444p` for 4:4:4, else `yuv420p` |
| `CRF` | `{32, 27, 21}[quality]` |
| `CQ` | `clamp(clamp(nvenc_cq, 1, 51) + CRF[q] - 27, 1, 51)`. With the default 23, this gives 28 / 23 / 17. |

C# `Math.Round` rounds half to even. Python `round()` does the same.

### Argv in order

1. Always: `-hide_banner -loglevel error -stats -y`

2. Input, one of:
   - **ddagrab:** `-f lavfi -i ddagrab=output_idx=N:framerate=F:draw_mouse=M:offset_x=X:offset_y=Y:video_size=WxH`. X and Y are relative to the monitor.
   - **gdigrab, region:** `-f gdigrab -framerate F -draw_mouse M -offset_x X -offset_y Y -video_size WxH -i desktop`. X and Y are virtual-screen coordinates.
   - **gdigrab, whole desktop:** `-f gdigrab -framerate F -draw_mouse M -i desktop`

3. `-vf <chain>`, only when the chain is not empty. The parts join with commas, in this order:
   - `hwdownload,format=bgra`, when the backend is ddagrab AND (the encoder is x264 OR the mode is changes).
   - `crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0`, when the backend is gdigrab and the whole desktop is recorded.
   - `format=PIX,mpdecimate=max=K`, when the mode is changes.

4. `-fps_mode vfr`, when the mode is changes.

5. Encoder, one of:
   - **NVENC:** `-c:v h264_nvenc -preset p4 -rc vbr -cq CQ -b:v 0`. For 4:4:4, add `-profile:v high444p`. Also add `-rgb_mode yuv444`, but only when the mode is fixed. Then `-g G`. NVENC has no `-pix_fmt`.
   - **x264:** `-c:v libx264 -preset veryfast -tune stillimage -crf CRF -x264-params rc-lookahead=L -threads T -g G -pix_fmt PIX`

6. Output, one of:
   - **Split on:** `-force_key_frames expr:gte(t,n_forced*S)`, then `-forced-idr 1` (NVENC only), then `-f segment -segment_time S -segment_format mp4 -segment_format_options movflags=+frag_keyframe+empty_moov:frag_duration=2000000:flush_packets=1 -reset_timestamps 1 <folder with % doubled>\desktop_STAMP_%03d.mp4`
   - **Split off:** `-movflags +frag_keyframe+empty_moov -frag_duration 2000000 -flush_packets 1 <folder>\desktop_STAMP.mp4`. `%` is not doubled here.
   - The path join adds no separator when the folder already ends in `\` or `/`.

### Exact strings that the unit tests check (`tests/CoreTests.cs:515-631`)

- ddagrab with fixed mode and NVENC has no `-vf` and no `-pix_fmt`.
- ddagrab with changes mode: `hwdownload,format=bgra,format=yuv420p,mpdecimate=max=9`.
- gdigrab, whole desktop, changes mode: `crop=trunc(iw/2)*2:trunc(ih/2)*2:0:0,format=yuv420p,mpdecimate=max=9`.
- NVENC with split: ` -force_key_frames expr:gte(t,n_forced*300) -forced-idr 1 -f segment -segment_time 300 -segment_format mp4 `.
- gdigrab region: ` -f gdigrab -framerate 10 -draw_mouse 1 -offset_x -500 -offset_y 20 -video_size 300x200 -i desktop `.

### Plan rules (`PlanCapture` / `PlanGeometry`, `RecorderCore.cs:708-806`)

- The app calls `MakeEven` first. It shrinks an odd width or height by 1 px and never grows it. A result under 2 px means "no region".
- **ddagrab with a region:** the region must be fully inside one monitor that has a DXGI index ≥ 0. Then `OffsetX/Y = region - monitor origin`.
- **Notes when ddagrab cannot run.** In each case, the app records with gdigrab and shows the note:
  - Region not inside one monitor: `"The region is not inside one monitor. gdigrab records it."`
  - Monitor with no DXGI output: `"ddagrab cannot record this monitor (no DXGI output on its GPU). gdigrab records it."`
  - No region and 0 monitors: `"No monitor data. gdigrab records the whole desktop."`
  - No region, 1 monitor not found: `"ddagrab cannot find this monitor. gdigrab records the whole desktop."`
  - No region and 2 or more monitors: `"ddagrab records one monitor only. gdigrab records the whole desktop."`
- **ddagrab with no region and 1 monitor:** the app records that monitor at `w & ~1` × `h & ~1`.
- **Encoder choice:** `auto` uses NVENC if the probe passed, else x264. An explicit `h264_nvenc` or `libx264` is used as set, with no probe.
- **NVENC size limits:** from 146×50 to 4096×4096. For a whole-desktop recording, the app checks the bounding box of all monitors. Outside the limits, the app uses x264 (also for an explicit NVENC setting) and adds one of these notes:
  - `"NVENC cannot encode WxH (maximum 4096 px). libx264 records it."`
  - `"NVENC cannot encode WxH (too small). libx264 records it."`

### NVENC probe (`DesktopRecorder.cs:275-301`, `RecorderCore.cs:1035-1053`)

- The probe runs only when the encoder setting is `auto`.
- Step 1: `ffmpeg -hide_banner -encoders`, timeout 5 s. A line passes when its first token starts with `V` and its second token is `h264_nvenc`.
- Step 2: `ffmpeg -hide_banner -loglevel error -f lavfi -i color=c=black:s=256x256:r=10 -frames:v 5 -c:v h264_nvenc -f null -`, timeout 15 s. Exit code 0 means NVENC works.
- The result is cached for each ffmpeg path.
- `WarmUp` runs the probe on a background thread at app start, but only when `record_on_launch` is false. When it is true, the first start runs the probe in line.
- `MarkNvencUnusable` sets the cache to false until the app restarts.

### Fallback after a failed start (`ChooseFallback`, `RecorderCore.cs:652-680`; `TryFallback`, `DesktopRecorder.cs:538-553`)

- This applies only when FFmpeg exits by itself within 10000 ms of the start.
- **Rule 1.** The encoder is NVENC, the setting is `auto`, and the error text contains `nvenc`, `nvcuda`, `cuda`, `nvencodeapi`, `no capable devices` or `openencodesessionex` (case-insensitive). Then the app records again with x264 and calls `MarkNvencUnusable`. Reason: `"NVENC failed. Recording again with libx264."`
- **Rule 2.** Else, if the backend was ddagrab, the app records again with gdigrab. Reason: `"ddagrab failed. Recording again with gdigrab."`
- **Rule 3.** Else, if the encoder is NVENC from `auto`, the app records again with x264. Reason: `"FFmpeg failed with NVENC. Recording again with libx264."`
- The forced flags add up across retries.
- The restart plays no sound. Its balloon text is `reason + "\nFFmpeg: " + <first error line>`.

### FFmpeg not found

- Search order: next to the exe, then `%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe`, then PATH. On Linux the name is `ffmpeg` and the PATH separator is `:`.
- Message: `"ffmpeg.exe was not found. Run this in PowerShell: winget install -e --id Gyan.FFmpeg. Or put ffmpeg.exe next to DesktopRecorder.exe."`

## 3. Status line

**Reading stderr (`RecordingSession.cs:252-305`)**
- The app reads stderr in raw blocks and splits lines on `\r` OR `\n`. FFmpeg ends each stats line with a lone `\r`.
- Each line is capped at 8192 characters.

**Parsing (`TryParseProgress`, `RecorderCore.cs:1106-1139`)**
- A stats line is a trimmed line that starts with `frame=`.
- The parser reads `key=value` pairs separated by spaces. A value can start after spaces, as in `frame=  100`.
- `frame` must be an integer (`NumberStyles.None`), or the line is not a stats line.
- `dup` and `drop` count only when they are integers. When they are missing, they are 0. This FFmpeg build omits them when they are 0.
- The values are cumulative. The last stats line wins.
- Stats lines never go into the error text. The error text is capped at 2000 characters.
- A generation counter stops a late stats line from an old process from changing the new stats.

**File size**
- The sum of the session files.
- A session file matches `desktop_*.mp4` in the folder, was not in the snapshot taken before the start, and has a size above 0.
- The list is sorted case-insensitively.

**Text (`FormatStats`, `RecorderCore.cs:1142-1155`)**
- `MB = bytes / 1048576`, format `0.00`.
- With stats: `"Real frames: {max(0, frame - dup)} of {frame}. Duplicates: {dup}. Dropped: {drop}. File size: {MB} MB."`
- With no stats line: `"Frames: unknown. File size: {MB} MB."`
- The tray item shows `"Last recording: " + text`. The item is hidden until the first stop. If the stats call throws, the text is `"No stats."`.

## 4. Region selector (`RegionSelector.cs`)

**Window and screenshot**
- One borderless topmost form covers the whole virtual screen. Title: `"Select region"`. Cursor: cross. No taskbar entry.
- `SetWindowPos` sets the exact physical bounds.
- The app takes the screenshot before the form shows. If the capture fails, the background is black.
- The screenshot is frozen.
- The form ignores `WM_DPICHANGED`.

**Dimming**
- Black at alpha 120 over the screenshot. Checked on Bran's PC: pixel value 31 became 16.
- The bright area is the selection. With no selection, it is the window under the cursor.

**Window detection (`WindowList.Get`, lines 99-118)**
- The app makes one `EnumWindows` snapshot when the selector opens, in Z-order, top first.
- It skips: the selector itself, windows that are not visible, minimized windows, `WS_EX_TOOLWINDOW` windows, and cloaked windows.
- Bounds come from `DWMWA_EXTENDED_FRAME_BOUNDS`, with `GetWindowRect` as the fallback. Bounds are clipped to the virtual screen. Windows smaller than 2 px are skipped.
- The first window that contains the cursor wins.
- There is no hover while the user drags, moves or resizes.
- Child-control detection (`ChildWindowFromPointEx`) is NOT implemented.

**Mouse**
- A left press starts `Pending`.
- A move of more than 3 px on either axis starts `Creating`, with the press point as the anchor.
- The rectangle is inclusive: `FromLTRB(min, min, max+1, max+1)`, clipped to the screen. A drag from 440,172 to 1421,601 gives 982×430.
- Shift keeps a square with side `max(|dx|, |dy|)`.
- Ctrl moves the anchor by the mouse delta. Ctrl is ignored on the move that crosses the 3 px threshold.
- Release after `Creating`, with a selection of at least 2×2: accept at once.
- Release while `Pending` (a click), with a window under the cursor: select that window and accept at once.
- Release while `Pending` with no window under the cursor: nothing happens.
- A double-click inside a selection accepts it.
- Right-click during a drag: go back to the selection from before the press.
- Right-click with a selection: clear the selection.
- Right-click with no selection: cancel the selector.
- The move and resize code (8 handles, 8 px) runs only when the app gives a preselected region. The app calls `Show(null)` (`DesktopRecorder.cs:617`), so this code does not run in the app.

**Keys (`ProcessCmdKey`, lines 282-347)**

| Key | Result |
|---|---|
| Esc | Cancel. |
| Enter | Accept the selection. With no selection, accept the window under the cursor. With neither, nothing. |
| Space | Select the whole virtual screen and accept. |
| `~` (`Keys.Oemtilde`) | Select the monitor under the cursor and accept. |
| C, M, P | Turn the crosshair, magnifier or position text on or off. |
| Arrow keys | Move the cursor 1 px (Shift: 10 px). With a selection and no drag, they move the selection instead, and Ctrl + arrow keys change its size. In the app flow there is no selection at rest, so the arrow keys always move the cursor. |

**Accept (`Accept`, line 633)**
- The app clips the selection to the virtual screen and cuts each size to an even number by removing 1 px on the right or the bottom.
- If less than 2×2 px stays, the app does not accept, and the selector stays open.

**Size label**
- Text: `"{W} x {H}"`, with W and H already even. When position is on, add `"   at {X}, {Y}"` (three spaces, virtual-screen coordinates).
- Font: Segoe UI, 12 px × DPI scale.
- Background ARGB(220,20,20,20). Text is white.
- Box size: text width + 10, text height + 4. Text sits at +5, +2.
- Placement: `target.Y - h - 8`. If that is above the screen, place it at `target.Y + 8`. Then clamp it to the screen.

**Magnifier**
- Source: 10×10 px centered on the cursor (cursor − 5). Zoom: 8 times, nearest neighbor, so 80×80 px.
- Black background. A 1 px accent-color border around the box.
- The center pixel has a black outer square and a white inner square.
- Caption below the zoom area: `"{screenX}, {screenY}"`.
- Box width: `max(80, width of "-00000, -00000" + 8)`. Box height: `80 + font.Height + 4`.
- Offset: +24, +24 from the cursor. If the box leaves the monitor, the app flips it to the other side. Then it clamps the box to the monitor.

**Other drawing**
- Accent color: (64,158,255).
- The selection frame is 1 px. The hover frame is 2 px. Both are drawn just OUTSIDE the rectangle.
- Crosshair: white at alpha 170, 1 px, across the whole virtual screen.

**Saved values (`DesktopRecorder.cs:602-647`)**
- After an accept, `region = last_region = picked`. The app saves the file before the recording starts.
- `last_region` is saved but never used. "Record last region" is removed.
- The C, M and P options are saved if they changed. The save happens even when the user cancels.

**Errors**
- If the selector throws, the balloon text is `"The region selector failed: " + message`.

## 5. Recording frame (`RecordingFrame.cs`)

**Border**
- Color: RGB(255,64,64), opaque.
- Thickness: `max(2, round(2 × scale))`, where scale is the scale of the monitor at the region center. 2 px at 100%; at 125%, round(2.5) gives 2 (half to even).
- There is no gap: the border touches the region on the outside.
- Four separate windows: top, bottom, left, right. Each is layered, click-through (`WS_EX_TRANSPARENT` and `HTTRANSPARENT`), a tool window, no-activate and topmost. Title: `"Recording frame"`.

**Screen edge**
- When the outside strip of a side is not fully on the monitors, that side moves INSIDE the region, at the screen edge (`ComputeBorderRects`, lines 121-150).

**Stop button size**
- `round(84 × scale)` × `round(28 × scale)`. Gap: `round(4 × scale)`.

**Stop button position (`ComputeStopRect`, lines 161-194), in this order**
1. Below the outer edge of the border + gap, centered on the region, clamped to the monitor work area.
2. Above the border.
3. Top center of another monitor that does not touch the region, at y + gap.
4. Inside the region at the top center, + gap. When the taskbar is at the top, use the bottom center. This position sets `inside = true`.

**Stop button look**
- Background (32,32,32). On hover: (64,64,64).
- 1 px red edge (255,64,64).
- Red square icon: size `max(6, h/3)`, at x = h/3, centered vertically.
- `"Stop"` in Segoe UI Bold, 13 px × scale, white, centered in the space to the right of the icon.
- Hand cursor. Only a left click acts.
- `MA_NOACTIVATE`: the button takes the click but not the focus.

**Capture exclusion**
- The app calls `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE = 0x11)` on all frame windows.
- If any side or the Stop button is inside the region and the exclusion failed, the balloon warning is: `"The region touches the screen edge, so part of the red frame or the Stop button is inside it. Windows cannot keep them out of the video."`

**Other rules**
- The app shows no frame when it records the whole desktop.
- The frame shows only after `session.Start` succeeds.
- If the frame throws, the recording continues without the frame.

## 6. Tray, hotkey, sounds, clipboard, split, autostart, Settings

**Single instance**
- Mutex `DesktopRecorder_SingleInstance`.
- Message: `"Desktop Recorder is already running. Look for its icon in the tray."`

**Tray menu, in order**
1. Status, disabled:
   - When stopped: `Not recording`.
   - When recording: `Recording at {fps} fps, {W}x{H} region`, or `Recording at {fps} fps, whole desktop`. The fps value is the fps of the current recording.
2. Stats, disabled, hidden until the first stop.
3. Separator.
4. Toggle: `Select region and record` or `Stop recording`, plus `"\t" + hotkey text` if the hotkey is registered.
5. `Open recordings folder`. The app creates the folder, then runs explorer.
6. `Settings...`
7. Separator.
8. `Exit`

**Other tray behavior**
- A double-click opens Settings.
- Tooltip: `Desktop Recorder: recording` or `Desktop Recorder: stopped`.
- While FFmpeg finishes the file, the tray shows the stopped state.
- The app draws two icons in code (`TrayIcons.Draw`, `DesktopRecorder.cs:937-976`):
  - Idle: light blue (175,220,235) corner brackets, ring and small dot.
  - Recording: brackets from (225,120,255) to (80,195,255), ring (205,175,255), red dot (255,40,90).

**Hotkey flow**
- One id. Registered with `MOD_NOREPEAT` (0x4000).
- On a press:
  - While recording: stop.
  - Else: open the selector. This does nothing while the selector is open, while the app stops, or while it records.
- Warning balloon at start, 6000 ms: `"{hotkey} is used by another program, so that hotkey is off."`
- After Save in Settings, the same text plus `" Pick a different hotkey in Settings."` shows in a message box.
- The hotkey also works while Settings is open.

**Start**
- At launch with `record_on_launch = 1`, the app records the saved `region`, clipped and made even. There is no selector. A sound plays.
- If the saved region is not on the screen, it records the whole desktop with this note: `"The saved region is not on the screen now. Recording the whole desktop."`
- A start from the selector always shows a balloon, 3000 ms: `"Recording started ({backend}, {encoder})."`, then the note, the plan note and the frame warning, each on a new line.
- Start errors:
  - `ffmpeg was not found.`
  - `The recordings folder is empty.`
  - `Cannot create the folder {f}: {msg}`
  - `Desktop Recorder is already recording.`
  - `Cannot start ffmpeg: {msg}`

**Stop**
- The stop sound plays and the frame closes at once.
- A background thread writes `q` to FFmpeg's stdin. It waits `min(15000, 4000 + 2000/max(0.2, fps))` ms, then kills FFmpeg if it is still running.
- Then `FinishStop` runs on the UI thread.
- Exit stops synchronously and plays no sound.
- A Windows session end also stops the recording.

**Clipboard**
- The app puts all session files on the clipboard as a file-drop list.
- Balloon texts, 4000 ms:
  - One file: `"Video copied. Press Ctrl+V to paste it.\n" + stats`
  - More files: `"{n} video files copied. Press Ctrl+V to paste them.\n" + stats`
  - Copy off, or no files: `"Recording stopped.\n" + stats`
  - Copy error: `stats + "\nCould not copy the video to the clipboard: " + msg`

**FFmpeg ends by itself**
- If no fallback applies, the frame closes, the stop sound plays, and a balloon titled `"Desktop Recorder stopped"` shows `stats + "\n" + ffmpeg error`.
- If FFmpeg prints no error text, the message is `"ffmpeg stopped."`.
- Balloon texts are cut to 250 characters.

**Sounds (`BuildChimeWav`)**
- WAV, 22050 Hz, mono, 16-bit.
- Two tones of 90 ms each, 8 ms fade, amplitude 0.25.
- Start: 660 Hz then 880 Hz. Stop: 880 Hz then 660 Hz.

**Split**
- See section 2. The segment muxer uses forced keyframes at each cut, plus `-forced-idr 1` with NVENC.

**Settings dialog**
- Title: `"Desktop Recorder settings"`. Size 470×569 at 96 DPI. Fixed dialog. Appears in the taskbar.
- Fields in order:
  1. `Save recordings to:` text box and `Browse...` button.
  2. `Frames per second (0.2 to 60). Lower = smaller files:` number box, 1 decimal, step 1, range 0.2..60.
  3. `Quality:` list: `Smallest files (text still readable)`, `Balanced (recommended)`, `Sharpest text (bigger files)`.
  4. `Start a new file every (minutes, 0 = never):` number box, range 0..1440.
  5. `Hotkey:` check boxes `Win`, `Ctrl`, `Alt`, `Shift`, and a key list (A–Z, 0–9, F1–F12, plus the current key if it is not in the list).
  6. `Capture:` list: `ddagrab: GPU capture (recommended)`, `gdigrab: CPU capture (fallback)`.
  7. `Encoder:` list: `Auto: NVENC, else x264 (recommended)`, `NVIDIA NVENC (h264_nvenc)`, `x264 on the CPU (libx264)`.
  8. `Color detail (chroma):` list: `4:2:0 (plays everywhere)`, `4:4:4 (sharper colored text)`.
  9. `Frame-rate mode:` list: `Fixed frame rate`, `Changes only (drops still frames)`.
  10. Check box `Start Desktop Recorder when Windows starts`.
  11. Check box `Start recording (saved region) when Desktop Recorder starts`.
  12. Check box `Copy the video to the clipboard when recording stops`.
  13. Check box `Play a sound when recording starts and stops`.
  14. Check box `Hide the mouse pointer in the video`. This is the inverse of `show_pointer`.
  15. `Region selector:` check boxes `Crosshair`, `Magnifier`, `Position`.
  16. Buttons `Save` (accept button) and `Cancel`.
- Validation messages:
  - Hotkey: `"For the hotkey, tick at least one of Win, Ctrl, Alt and pick a key. Shift alone works only with F1 to F12."`
  - Folder: `"Give a full folder path, such as D:\Recordings."` (the path must be rooted). If the folder cannot be made: `"Cannot create that folder: "` + message.
- The folder is trimmed, outer quotes are removed, and a trailing `\` or `/` is removed (except for a 2-character path).
- Save starts from a copy of the current settings, so `nvenc_cq` and the extra lines stay. The app keeps the live `region` and `last_region`, in case the selector saved one while the dialog was open.
- Save registers the hotkey again. It does NOT restart a running recording. The new capture settings apply to the next recording.

## 7. Points a Linux port can easily miss

- **Default fps conflict.** Linux `DEFAULT_FPS = 2.0` (`linux/desktop_recorder/settings.py:10`). Windows uses 10, and NaN in the file also becomes 10.
- **Bad values of known keys are destroyed.** A known key with a bad value is not kept as an extra. If Linux writes `capture_backend=x11grab` or `encoder=h264_vaapi`, Windows resets them to `ddagrab` / `auto`, and the Linux value is lost. Use Linux-only key names for Linux-only values.
- **Linux-only keys.** Windows keeps `record_audio`, `start_on_login` and `wayland_restore_token` as extra lines. The new Linux code must parse all the Windows keys above, including `show_pointer`, the `selector_*` keys, `region`, `last_region` and `nvenc_cq`. It must also drop `last_region_hotkey` and `stop_hotkey`.
- **Record on launch.** With the default `record_on_launch = 1`, the app starts to record the saved region (or the whole desktop) at login, without the selector.
- **One hotkey.** The same hotkey starts and stops. It does nothing while the selector is open.
- **The first move does not apply Ctrl.** The move that starts the drag ignores Ctrl.
- **Inclusive pixels and even sizes.** The `+1` inclusive rule, then the shrink to even sizes. Never grow, never scale.
- **No selector cancel by hotkey.** A press of the hotkey while the selector is open does not cancel the selector.
- **Physical pixels everywhere.** On GNOME Wayland with fractional scaling, logical px and physical px are different.
- **Pointer setting.** It must reach the capture source. On Linux today, the portal `cursor_mode` is fixed at 2 (embedded pointer) (`linux/desktop_recorder/portal.py:60`).
- **mpdecimate needs a format filter.** `format=PIX` must come before `mpdecimate`. `max=K` keeps the file length correct: without it, a still screen gave a 0.1 s file (bug 2, HANDOFF 6.7). Use `-fps_mode vfr` in changes mode.
- **Stats need `-stats`.** Use `-stats` together with `-loglevel error`. Split stderr on a lone `\r`. A missing `dup=` or `drop=` means 0.
- **Stop with `q`.** Write `q` to stdin and use the wait formula. Only after that, kill FFmpeg.
- **FFmpeg must end with the app.** On Windows a job object does this (bug 5). Linux needs the same, for example `PR_SET_PDEATHSIG` or a process group.
- **Session files.** Find them by a snapshot of `desktop_*.mp4` before the start. Count only new files with a size above 0.
- **File name.** The stamp has milliseconds. `%` is doubled only in the split pattern.
- **Fragmented MP4.** The flags differ for one file (`-movflags …`) and for split (`-segment_format_options …`).
- **NVENC probe.** Two steps (listing, then a test encode), cached for each ffmpeg path. Do the warm-up only when `record_on_launch` is off. NVENC size limits: 146×50 to 4096×4096.
- **Fallback window.** The automatic fallback works only within 10 s of the start. The forced flags add up across retries.
- **Border outside the region.** No gap. A side moves inside the region only at the screen edge.
- **Stop button.** It must not take the focus. Its position order includes the work area (no taskbar), and it never goes to the bottom center of a full monitor.
- **Save order.** The app saves the region and the selector options before the recording starts, and the selector options also on cancel.
- **Running recording.** Save in Settings keeps the running recording. The status menu shows the fps of the current recording.
- **Start balloon.** It names the backend and the encoder, and it gives any fallback note.

Checked: every value, string, formula and argv above, read from the source files at the line numbers given. Not checked: no build, test or run; whether the README matches the runtime behavior where I did not compare it to the code; GUI behavior on Linux.