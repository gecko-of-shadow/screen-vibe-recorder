# Desktop Recorder

A small Windows tray program that records a part of your screen to MP4.

It makes recordings that an AI model can read. You select the area with the text. The program records that area at full resolution, so each character stays sharp. A still screen costs almost no space, so the files stay small.

## Get it

Download a portable archive from the [Releases page](../../releases/latest). Unzip or untar it and run it. Nothing is copied into Program Files, and the Linux archive does not need root.

- Windows: `desktop-recorder-<version>-windows-x64.zip`. Start `DesktopRecorder.exe`.
- Ubuntu 24.04: `desktop-recorder-<version>-linux-x86_64.tar.gz`. Run `./desktop-recorder`. The README in the archive lists the apt packages it still needs (GTK, GStreamer, ffmpeg, and the Python GI bindings).

Version 2.0.0 and later have the region selector on Windows. Version 2.1.0 adds it to the Ubuntu program. Version 1.0.0 records the full desktop.

Install ffmpeg, if you do not have it. It is not inside the archive. The GPU capture (`ddagrab`) needs a recent ffmpeg build. The test used the gyan.dev full build of 2026-04-30. In PowerShell:

```
winget install -e --id Gyan.FFmpeg
```

On Ubuntu: `sudo apt install ffmpeg`.

The Windows program uses an NVIDIA GPU to encode, when the PC has one. Without an NVIDIA GPU, it encodes on the CPU.

Windows SmartScreen can show a warning, because the program is not signed. Click **More info**, then **Run anyway**.

## Use it (Windows)

1. Press **Win+Shift+D**. The region selector opens over all monitors. The screen stops and goes darker.
2. Select the area to record:
   - Drag a rectangle, then release the mouse button. The recording starts at once.
   - Or move the cursor over a window. A border shows around the window. Click to record that window area.
   - Or press **Space** to record all monitors.
3. A thin red frame shows around the recorded area. A small **Stop** button shows below it. Both are outside the area, and Windows keeps them out of the video.
4. To stop, press **Win+Shift+D** again, or click **Stop**.

When the recording stops:

- The video file goes on the clipboard. Press Ctrl+V to paste it into a chat or a folder.
- The tray menu shows a status line, for example: "Last recording: Real frames: 83 of 83. Duplicates: 0. Dropped: 0. File size: 0.05 MB."

The recording area is a fixed rectangle. If a window moves during the recording, the area does not move with it.

Other controls:

- A short sound plays when the recording starts and when it stops.
- Right-click the tray icon for: Select region and record (or Stop recording), Open recordings folder, Settings, Exit.
- Double-click the tray icon to open Settings.

### Region selector keys

| Key | Result |
|---|---|
| Drag, then release | Records the rectangle. |
| Click | Records the window under the cursor (its visible frame, without the shadow). |
| Shift while you drag | Keeps the selection square. |
| Ctrl while you drag | Moves the rectangle that you draw. |
| Arrow keys | Move the cursor 1 px. Shift + arrow keys move it 10 px. |
| Enter | Records the current selection. |
| Space | Records all monitors. |
| `~` | Records the monitor under the cursor. |
| C | Shows or hides a crosshair across the screen. |
| M | Shows or hides the magnifier near the cursor. |
| P | Shows or hides the position and size of the selection. |
| Esc | Closes the selector. Nothing is recorded. |

The size label shows the size in physical pixels. The program makes the width and the height even numbers, because H.264 needs even sizes. It removes at most 1 px. It never scales the picture.

## Settings (Windows)

| Setting | Default | Notes |
|---|---|---|
| Save recordings to | `C:\Users\<you>\Recordings` | The program makes the folder. |
| Frames per second | 10 | 0.2 to 60. See "Choose a frame rate". |
| Quality | Balanced | Smallest files, Balanced, or Sharpest text. See "Capture and encoding". |
| Start a new file every | 30 minutes | 0 means one file for each recording. |
| Hotkey | Win+Shift+D | Win, Ctrl, Alt and Shift, plus a letter, a digit or F1 to F12. Shift alone works only with F1 to F12. The same hotkey opens the selector and stops the recording. |
| Capture | ddagrab (GPU) | ddagrab or gdigrab. |
| Encoder | Auto | Auto (NVENC, else x264), NVENC only, or x264 only. |
| Color detail (chroma) | 4:2:0 | 4:2:0 or 4:4:4. |
| Frame-rate mode | Changes only | Fixed frame rate, or Changes only. |
| Start Desktop Recorder when Windows starts | Off | Adds one entry for your user account only. |
| Start recording (saved region) when Desktop Recorder starts | On | Records the last selected area, without the selector. With no saved area, or an area that is not on the screen now, it records the full desktop. |
| Copy the video to the clipboard when recording stops | On | |
| Play a sound when recording starts and stops | On | Two rising tones for start, two falling tones for stop. |
| Hide the mouse pointer in the video | Off | On removes the pointer from the video. See "Good to know". |
| Region selector: Crosshair, Magnifier, Position | Off, On, On | The keys C, M and P in the selector change them too. |

Settings are stored in `%APPDATA%\DesktopRecorder\settings.txt`.

When you click Save during a recording, the recording continues. New capture settings apply to the next recording.

## Capture and encoding (Windows)

The program is a tray front end for [ffmpeg](https://ffmpeg.org).

**Capture.**

- `ddagrab` (default) uses the Desktop Duplication API on the GPU. It records one monitor.
- `gdigrab` uses GDI on the CPU. It can record an area that crosses two monitors.
- The program uses `gdigrab` without a question in these cases: the area crosses two monitors; no area and more than one monitor; or `ddagrab` fails at the start.

**Encoder.**

- Auto (default) uses `h264_nvenc` on an NVIDIA GPU. When NVENC is not available or fails at the start, it uses `libx264` with preset `veryfast`.
- NVENC cannot encode an area smaller than about 146x50 px (the limit changes with the GPU) or larger than 4096x4096 px. For these sizes, the program uses `libx264`.

**Quality.**

| Quality | NVENC (CQ) | x264 (CRF) |
|---|---|---|
| Smallest files | 28 | 32 |
| Balanced | 23 | 27 |
| Sharpest text | 17 | 21 |

A lower number gives a sharper picture and a larger file. The Phase B read test read each NVENC level one time. The differences between the levels were not larger than the differences between two reads of the same frames. Sharpest text gave files about 1.5 times larger than Balanced.

**Chroma.** 4:2:0 plays in all players and browsers. 4:4:4 keeps full color detail, for colored text. In the read test, 4:4:4 gave no read gain, and the files were about 20% larger. Some browsers and players cannot play 4:4:4. ffmpeg can read it.

**Frame-rate mode.**

- Changes only (default): ffmpeg captures at the frame rate that you set and drops frames that do not change (`mpdecimate`, variable frame rate). The file keeps at least one frame each second, so the length of the file stays correct. A still screen costs almost nothing.
- Fixed frame rate: every frame is kept.

**Output.** Fragmented MP4. A recording is one file named `desktop_yyyy-mm-dd_hh-mm-ss_mmm.mp4`. When a recording is split, the parts are `desktop_yyyy-mm-dd_hh-mm-ss_mmm_000.mp4` and so on.

## Choose a frame rate

When text scrolls, each frame must overlap the frame before it. If the scroll moves more than the area height between two frames, lines are lost.

Use this rule:

```
lowest safe fps = 1.5 x scroll speed (physical px/s) / (area height in px - 2 text lines)
```

- Physical px/s = page px/s x Windows display scale. At 125% scale, 1000 page px/s is 1250 physical px/s.
- 1.5 is a safety margin. The test found an error of about 6% in the rule.

Example: an area 892 px high, text lines 31 px high, a scroll of 1000 page px/s at 125% scale. The rule gives 1.5 x 1250 / 830 = 2.3 fps. A fast scroll of 3000 page px/s needs 6.8 fps.

In the test, 4, 6, 10 and 15 fps all caught 300 of 300 lines at 1000 page px/s. At 4 fps and 3000 page px/s (above the limit), the AI lost 45 of 300 lines.

With "Changes only", a higher frame rate costs space only while the screen changes. Thus 10 fps is a safe choice for most scrolls.

## Test results

The rebuild was tested on one PC: one 1920x1080 monitor at 125% scale, RTX 4060, ffmpeg 2026-04-30. `HANDOFF.md` sections 6.5 to 6.9 have the full tables. Summary:

- **Frame rate.** All capture and encoder settings kept every frame at 10 fps. `ddagrab` with NVENC also kept every frame at 30 fps. No frame was lost during a fast scroll.
- **Read test.** A Claude Sonnet reader read the frames of a 300-line test page. Every run below the frame-rate limit caught 300 of 300 lines. Errors were mostly in emoji lines, and they occurred on lossless frames too.
- **File size.** A 10 s recording of a still area in "Changes only" mode gave 11 frames and 12 KB.
- **Pointer.** In "Changes only" mode, a moving mouse pointer on a still screen made the file 18 times larger. With the pointer hidden, the program dropped those frames.

Not tested: PCs with two or more monitors (also `gdigrab` with an area across two monitors), monitors with different scales, the `libx264` fallback in the program, PCs without an NVIDIA GPU, and AI tools other than Claude. In the selector, these keys are not tested: `~`, Shift and Ctrl while you drag, C, M and P.

The test kit is in `test/`: a source text, an auto-scroll page, a frame-counter page, and scripts that count frames and score an AI copy.

## Good to know

- On Windows, no audio is recorded. On Ubuntu, system audio (what you hear) is recorded unless you turn it off in Settings.
- The MP4 stays playable if the PC loses power during a recording. You lose about the last 5 seconds at the default settings, and more at a very low frame rate.
- If the program stops without a normal stop (for example, a crash), ffmpeg stops with it. A file shorter than 2 seconds can then be unreadable.
- Hide the mouse pointer when the screen is mostly still and you move the mouse. In "Changes only" mode, each pointer move otherwise adds a frame. Hover effects in other programs (button colors, tooltips) still add frames.
- On Ubuntu, the region selector works on X11 and on Wayland. On Wayland, Ubuntu first asks which screen to share. The selector cannot detect windows on Wayland. See "Ubuntu Desktop 24.04".

## Problems

**Part of the red frame shows in the video.**
This occurs only when the area touches the screen edge and Windows cannot exclude the frame. The program shows a warning. Windows 10 version 2004 or later is necessary to keep the frame out of the video.

**The recording uses x264, not NVENC.**
The tray balloon at the start of the recording gives the reason. Windows does not show the balloon when notifications are off. Update the NVIDIA driver, or select a larger area.

**"Protected folder access blocked" from Windows Security.**
Controlled folder access protects Videos, Documents, Pictures, Desktop and Music. The default folder, `C:\Users\<you>\Recordings`, is outside those. If you selected a protected folder, open Settings from the tray icon and select a different folder. Or allow both `DesktopRecorder.exe` and `ffmpeg.exe` in Windows Security.

**"ffmpeg.exe was not found."**
Run the winget command above, or put `ffmpeg.exe` next to `DesktopRecorder.exe`.

**The hotkey does nothing.**
Another program already uses that hotkey. The recorder shows a warning when that occurs. Select a different hotkey in Settings, or use the tray menu.

## Build it yourself

You need nothing extra. The C# compiler ships with Windows.

Exit the running recorder first. If you do not, the build cannot replace the `.exe`.

Double-click `build.cmd`, or run this in PowerShell in the folder:

```
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize+ /out:DesktopRecorder.exe /r:System.Windows.Forms.dll /r:System.Drawing.dll /win32manifest:DesktopRecorder.manifest /win32icon:app.ico RecorderCore.cs RecordingSession.cs NativeMethods.cs RegionSelector.cs RecordingFrame.cs DesktopRecorder.cs
```

To run the unit tests on Windows, build them:

```
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /out:"$env:TEMP\CoreTests.exe" tests\CoreTests.cs RecorderCore.cs RecordingSession.cs
```

Then run them. The tests write `ok` when all checks pass:

```
& "$env:TEMP\CoreTests.exe"
```

The app manifest makes the program per-monitor DPI aware. All positions and sizes are physical pixels.

## Ubuntu Desktop 24.04

The Ubuntu program has the same start flow as the Windows program:

1. Press **Super+Shift+D**. The region selector opens. The screen stops and goes darker.
2. Drag a box and release the mouse. The recording starts at once. On X11 you can also click a window to record it.
3. Press **Super+Shift+D** again to stop. You can also use the tray menu. On X11 a small Stop button shows below the region.

When the recording stops, the program copies the video to the clipboard. The tray menu shows the frame count and the file size of the last recording.

### Selector keys (Ubuntu)

| Key | Result |
|---|---|
| Drag, then release | Records the rectangle. |
| Click | X11 only: records the window under the cursor. |
| Shift while you drag | Keeps the selection square. |
| Ctrl while you drag | Moves the rectangle that you draw. |
| Arrow keys | Move the cursor 1 px. Shift + arrow keys move it 10 px. On Wayland the arrow keys move the selector cursor only, not the real pointer. |
| Enter | Records the current selection, else the window under the cursor. |
| Space | Records the whole screen (X11) or the whole shared monitor (Wayland). |
| `~` | Records the monitor under the cursor. |
| C | Shows or hides a crosshair across the screen. |
| M | Shows or hides the magnifier near the cursor. |
| P | Shows or hides the position in the size label. |
| Esc | Closes the selector. Nothing is recorded. |
| Right-click | Cancels the drag. With no drag and no selection, it closes the selector. |

### X11 and Wayland

The session type selects the capture. Ubuntu 24.04 starts a Wayland session by default. You can select "Ubuntu on Xorg" on the login screen.

| Item | X11 session | Wayland session (default) |
|---|---|---|
| Capture | ffmpeg `x11grab` | GNOME screen-share portal, then PipeWire and GStreamer, then ffmpeg |
| Region | Any rectangle on the X screen | A rectangle on one shared monitor |
| Window detection | Yes | No. GNOME does not let apps read the window list. |
| Red frame | Yes, outside the region | Experimental (`wayland_frame`), drawn through XWayland |
| Stop button on the screen | Yes, below or above the region | No. Use the hotkey or the tray menu. |
| Hotkey | The program grabs it | A GNOME custom shortcut named Desktop Recorder runs `desktop-recorder --toggle` |

Limits:

- The first Wayland recording opens the GNOME screen-share dialog. Pick the screen and allow "Remember". Later recordings use that permission again.
- On Wayland, a region stays on one monitor. The program cannot detect windows, and it cannot show a Stop button.
- Linux cannot keep a window out of the video. When a side of the red frame cannot be outside the region (the region touches the screen edge), that side is not drawn. When the Stop button has no room outside the region, it is not shown.
- On Wayland, Esc can fail when GNOME does not give the keyboard to the selector. Right-click then cancels.
- In "Changes only" mode, late captures can make "Real frames" too low. On X11 in "Changes only" mode, a late capture is not counted.
- In "Changes only" mode, `mpdecimate` keeps at least one frame each second. On a still screen the file can end up to 1 s before the stop.
- CI tests the X11 path on Xvfb only. A real GNOME session (Wayland portal, tray, NVENC, HiDPI) is not tested yet.

### Settings (Ubuntu)

Open **Settings...** from the tray menu. The file is `~/.config/DesktopRecorder/settings.txt`. A Windows settings file reads correctly on Ubuntu.

| Key | Default | Meaning |
|---|---|---|
| `folder` | `~/Recordings` | Folder for the MP4 files |
| `fps` | `10` | Frames per second, 0.2 to 60 |
| `quality` | `1` | 0 = smallest files, 1 = balanced, 2 = sharpest text |
| `split_minutes` | `30` | Start a new file after this number of minutes. 0 = never. |
| `record_on_launch` | `1` | Record the saved region when the program starts |
| `copy_to_clipboard` | `1` | Copy the video when the recording stops |
| `play_sounds` | `1` | Play a sound at start and stop |
| `show_pointer` | `1` | Show the mouse pointer in the video |
| `hotkey` | `Win+Shift+D` | Win is the Super key |
| `capture_backend` | `ddagrab` | Windows only. Ubuntu keeps it and does not use it. |
| `encoder` | `auto` | `auto` (NVENC, else x264), `h264_nvenc` or `libx264` |
| `chroma` | `yuv420` | `yuv420` or `yuv444` |
| `frame_rate_mode` | `changes` | `changes` or `fixed` |
| `nvenc_cq` | `23` | NVENC quality at "balanced" |
| `selector_crosshair`, `selector_magnifier`, `selector_position` | `0`, `1`, `1` | Selector options (C, M, P) |
| `region`, `last_region` | empty | Last X11 region, in X screen px |
| `record_audio` | `1` | Ubuntu only. Record system audio (what you hear). |
| `start_on_login` | `0` | Ubuntu only. Writes `~/.config/autostart/desktop-recorder.desktop`. |
| `wayland_restore_token` | empty | Ubuntu only. The screen-share permission. |
| `wayland_region` | empty | Ubuntu only. Last Wayland region: monitor position, then x, y, width and height in stream px. |
| `wayland_frame` | `1` | Ubuntu only. Show the experimental red frame on Wayland. |

Save in Settings does not touch a running recording. The new values apply to the next recording.

### Install

Install the packages, then build and install the program for your user:

```
sudo apt update
sudo apt install ffmpeg python3 python3-gi python3-gi-cairo python3-xlib gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-pipewire pipewire pipewire-pulse wireplumber pulseaudio-utils xdg-desktop-portal xdg-desktop-portal-gnome xclip wl-clipboard
./build-linux.sh --install
export PATH="$HOME/.local/bin:$PATH"
desktop-recorder
```

Log out and back in if `~/.local/bin` is not on your PATH yet. On Ubuntu Desktop the tray icon uses the app indicator extension (`gnome-shell-extension-appindicator`, installed by default). On other desktops, install that extension, or use a desktop with a classic tray.

- System audio is the monitor of the default output. If that device is missing or does not answer, the recording continues with video only, and the start message says so.
- `desktop-recorder --check` shows ffmpeg, the capture backend, the audio device and NVENC. `desktop-recorder --smoke 2` records two seconds of a 320x240 area with X11 and exits.
- With the portable archive, `./desktop-recorder --install-menu` adds the program to your app menu.

### Frame rate (Ubuntu)

The rule in "Choose a frame rate" applies on Ubuntu too:

```
lowest safe fps = 1.5 x scroll speed (physical px/s) / (area height in px - 2 text lines)
```

On X11 the region is in X screen px. On Wayland it is in stream px. With GNOME scaling, stream px are physical px (not checked).

### Tests (Ubuntu)

```
sudo apt install mono-devel libmono-system-windows-forms4.0-cil libmono-system-drawing4.0-cil python3-xlib gir1.2-gstreamer-1.0 xvfb xdotool x11-utils x11-xserver-utils dbus
./run-tests.sh
```

`run-tests.sh` runs the unit tests, the Mono core tests, then the GUI tests. It always runs the GUI tests in their own Xvfb (1280x800), never on your live desktop, because the tests move the pointer and grab keys. A missing package skips a test there. In CI (`DESKTOP_RECORDER_REQUIRE_GUI=1`), a missing package fails the test.

The pure unit tests also run on Windows (Git Bash):

```
PYTHONPATH=linux python -m unittest discover -s tests -p 'test_linux*.py' -v
```
