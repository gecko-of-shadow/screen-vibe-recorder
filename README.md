<p align="center">
  <img src="packaging/icon/app-icon-source.jpg" alt="Screen Vibe Recorder icon" width="420">
</p>

<h1 align="center">Screen Vibe Recorder</h1>

<p align="center">
  <b>Record the part of the screen that has the text. Give the video to an AI. The AI reads every character.</b>
</p>

<p align="center">
  <a href="https://github.com/gecko-of-shadow/screen-vibe-recorder/releases/latest"><b>Download the latest release</b></a>
  &nbsp;·&nbsp;
  <a href="#quick-start-windows">Quick start</a>
  &nbsp;·&nbsp;
  <a href="CHANGELOG.md">Patch notes</a>
  &nbsp;·&nbsp;
  <a href="#troubleshooting">Help</a>
</p>

---

## At a glance

| | |
|---|---|
| **What it does** | Records a region of the screen to an MP4 that an AI can read frame by frame. |
| **Why** | Sharp text at full resolution, no lost frames, and small files. A still screen costs almost nothing. |
| **Systems** | Windows 10 and 11 (full program). Ubuntu 24.04 (earlier full-screen recorder). |
| **Needs** | FFmpeg 6.0 or later. An NVIDIA GPU is used when the PC has one. |
| **Hotkey** | **Win+Shift+D** opens the region selector. The same keys stop the recording. |
| **Output** | Fragmented MP4. It goes on the clipboard when the recording stops. |
| **Program name** | Desktop Recorder (`DesktopRecorder.exe`). See [Relation to Desktop Recorder](#relation-to-desktop-recorder). |

## Contents

| Start here | Use it | Learn more |
|---|---|---|
| [Quick start (Windows)](#quick-start-windows) | [Use it (Windows)](#use-it-windows) | [Capture and encoding](#capture-and-encoding-windows) |
| [Download and install](#download-and-install) | [Region selector keys](#region-selector-keys) | [Choose a frame rate](#choose-a-frame-rate) |
| [Update an existing copy](#update-an-existing-copy-windows) | [Settings](#settings-windows) | [Test results](#test-results) |
| [Features](#features) | [Use it (Ubuntu 24.04)](#use-it-ubuntu-2404) | [Build from source](#build-from-source) |
| | [Troubleshooting](#troubleshooting) | [More documents](#more-documents) |

## Quick start (Windows)

1. Install FFmpeg. In PowerShell: `winget install -e --id Gyan.FFmpeg`
2. Download `screen-vibe-recorder-<version>-windows-x64.zip` from the [latest release](https://github.com/gecko-of-shadow/screen-vibe-recorder/releases/latest). Unzip it anywhere.
3. Start `DesktopRecorder.exe`. An icon shows in the tray.
4. Press **Win+Shift+D**, drag a box around the text, and release the mouse button. The recording starts.
5. Press **Win+Shift+D** again to stop. Press **Ctrl+V** to paste the video into a chat or a folder.

## Features

Windows:

- **Region selector.** Win+Shift+D opens the selector over all monitors. Drag a rectangle, click a window, or press Space for all monitors. The recording starts when you release the mouse button.
- **One hotkey** starts and stops the recording. The hotkey is a setting.
- **Recording frame.** A red frame and a Stop button show around the recorded area. Windows keeps them out of the video.
- **GPU capture and encode.** `ddagrab` capture and `h264_nvenc` encode by default. The program uses `gdigrab` and `libx264` when the GPU path is not available.
- **"Changes only" mode** (default). Frames that do not change are dropped. A still screen keeps one frame each 60 s. A one-character change is kept.
- **Status line** after each recording: real frames, duplicates, dropped frames, file size.
- The finished video goes on the **clipboard**. Press Ctrl+V to paste it into a chat or a folder.
- **Per-monitor DPI aware.** All positions and sizes are physical pixels.
- FFmpeg stops when the program stops, also after a crash.
- Start and stop sounds, an option to hide the mouse pointer, start with Windows, split long recordings into parts.

Ubuntu 24.04:

- Full-screen recording. X11 uses FFmpeg `x11grab`. Wayland uses xdg-desktop-portal and PipeWire.
- System audio (what you hear), through the PulseAudio API that PipeWire provides.
- Tray icon, Super+Shift+D shortcut, and the same settings file format as Windows.

## Download and install

Download from the [Releases page](https://github.com/gecko-of-shadow/screen-vibe-recorder/releases). Each release has these files:

| File | For | Start |
|---|---|---|
| `screen-vibe-recorder-<version>-windows-x64.zip` | Windows 10 and 11 (x64), new install | `DesktopRecorder.exe` |
| `DesktopRecorder.exe` | Windows, update of a copy that you have | `DesktopRecorder.exe` |
| `screen-vibe-recorder-<version>-linux-x86_64.tar.gz` | Ubuntu 24.04 (x86_64) | `./desktop-recorder` |
| `SHA256SUMS.txt` | Check the downloads | |

Nothing is copied into Program Files, and the Linux archive does not need root.

FFmpeg is not inside the archives. An FFmpeg build that records H.264 links libx264 and is GPL, so you install it yourself.

**Windows.** .NET Framework 4 is part of Windows 10 and 11. Install FFmpeg in PowerShell:

```
winget install -e --id Gyan.FFmpeg
```

Or put `ffmpeg.exe` next to `DesktopRecorder.exe`. The GPU capture (`ddagrab`) needs FFmpeg 6.0 or later. The tests used the gyan.dev full build of 2026-04-30.

The program uses an NVIDIA GPU to encode when the PC has one. Without an NVIDIA GPU, it encodes on the CPU.

Windows SmartScreen can show a warning, because the program is not signed. Click **More info**, then **Run anyway**.

**Ubuntu 24.04.** The `README.txt` in the archive lists the apt packages that the program needs (the same list as in [Build from source](#ubuntu-2404)).

### Update an existing copy (Windows)

1. Exit Desktop Recorder (right-click the tray icon, then Exit).
2. Download `DesktopRecorder.exe` from the [latest release](https://github.com/gecko-of-shadow/screen-vibe-recorder/releases/latest).
3. Put it in place of your old `DesktopRecorder.exe`.
4. Start it. Your settings stay in `%APPDATA%\DesktopRecorder\settings.txt`.

## Use it (Windows)

1. Press **Win+Shift+D**. The region selector opens over all monitors. The screen stops and goes darker.
2. Select the area to record:
   - Drag a rectangle, then release the mouse button. The recording starts at once.
   - Or move the cursor over a window. A border shows around the window. Click to record that window area.
   - Or press **Space** to record all monitors.
3. A thin red frame shows around the recorded area. A small **Stop** button shows below it. Both are outside the area, and Windows keeps them out of the video.
4. To stop, press **Win+Shift+D** again, or click **Stop**.

When the recording stops:

- The video file goes on the clipboard (you can turn this off in Settings).
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

### Settings (Windows)

| Setting | Default | Notes |
|---|---|---|
| Save recordings to | `C:\Users\<you>\Recordings` | The program makes the folder. |
| Frames per second | 10 | 0.2 to 60. See [Choose a frame rate](#choose-a-frame-rate). |
| Quality | Balanced | Smallest files, Balanced, or Sharpest text. See [Capture and encoding](#capture-and-encoding-windows). |
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
| Hide the mouse pointer in the video | Off | On removes the pointer from the video. See [Good to know](#good-to-know). |
| Region selector: Crosshair, Magnifier, Position | Off, On, On | The keys C, M and P in the selector change them too. |

Settings are stored in `%APPDATA%\DesktopRecorder\settings.txt`.

When you click Save during a recording, the recording continues. New capture settings apply to the next recording. A new hotkey applies at once.

## Use it (Ubuntu 24.04)

Start `desktop-recorder`. A monitor icon shows in the tray. On GNOME it uses an app indicator. On an X11 session such as Xfce it uses the classic tray.

- **Super+Shift+D** is the shortcut (the same keys as Win+Shift+D on Windows). On X11 the program grabs the keys. On GNOME Wayland it adds a custom shortcut named Desktop Recorder. Other Wayland desktops use the tray menu.
- On X11 the whole X display is recorded. On Wayland, Ubuntu asks which screen to share, and the recorder keeps the first screen that you select. The first Wayland recording opens the system screen-share dialog. Later recordings use that permission again.
- System audio is the monitor of the default output. It is recorded unless you turn it off in Settings. If that device is missing or does not answer within 2 seconds, the recording continues with video only and the tray says so.
- Settings are stored in `~/.config/DesktopRecorder/settings.txt`. "Start when I log in" writes `~/.config/autostart/desktop-recorder.desktop`.
- `desktop-recorder --help` shows the options. `desktop-recorder --check` prints the capture backend. `desktop-recorder --smoke 2` records two seconds with X11 and exits.

## Capture and encoding (Windows)

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

A lower number gives a sharper picture and a larger file. The AI read test read each NVENC level one time. The differences between the levels were not larger than the differences between two reads of the same frames. Sharpest text gave files about 1.5 times larger than Balanced.

**Chroma.** 4:2:0 plays in all players and browsers. 4:4:4 keeps full color detail, for colored text. In the read test, 4:4:4 gave no read gain, and the files were about 20% larger. Some browsers and players cannot play 4:4:4. FFmpeg can read it.

**Frame-rate mode.**

- Changes only (default): FFmpeg captures at the frame rate that you set and drops frames that do not change (`mpdecimate`, variable frame rate). The goal is an AI copy of the screen with the fewest frames. A frame is kept when any 8x8 pixel block changes by more than 64 (`hi=64:lo=64:frac=0`), so a one-character change is kept. The FFmpeg default thresholds dropped such a change. On a still screen, the file keeps one frame each 60 s only. Thus the length of the file is correct to 60 s: a still part at the end of a recording can be missing from the file length, but not from the content. A video player shows the last frame until the next frame comes, so the video looks normal. A tool that reads the video at a fixed rate makes copies of the frames again.
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

## Good to know

- On Windows, no audio is recorded. On Ubuntu, system audio is recorded unless you turn it off in Settings.
- The MP4 stays playable if the PC loses power during a recording. You lose about the last 5 seconds at the default settings, and more at a very low frame rate.
- If the program stops without a normal stop (for example, a crash), FFmpeg stops with it. A file shorter than 2 seconds can then be unreadable.
- Hide the mouse pointer when the screen is mostly still and you move the mouse. In "Changes only" mode, each pointer move otherwise adds a frame. Hover effects in other programs (button colors, tooltips) still add frames.

## Troubleshooting

**Part of the red frame shows in the video.**
This occurs only when the area touches the screen edge and Windows cannot exclude the frame. The program shows a warning. Windows 10 version 2004 or later is necessary to keep the frame out of the video.

**The recording uses x264, not NVENC.**
The tray balloon at the start of the recording gives the reason. Windows does not show the balloon when notifications are off. Update the NVIDIA driver, or select a larger area.

**"Protected folder access blocked" from Windows Security.**
Controlled folder access protects Videos, Documents, Pictures, Desktop and Music. The default folder, `C:\Users\<you>\Recordings`, is outside those. If you selected a protected folder, open Settings from the tray icon and select a different folder. Or allow both `DesktopRecorder.exe` and `ffmpeg.exe` in Windows Security.

**"ffmpeg.exe was not found."**
Run the winget command in [Download and install](#download-and-install), or put `ffmpeg.exe` next to `DesktopRecorder.exe`.

**The hotkey does nothing.**
Another program already uses that hotkey. The recorder shows a warning when that occurs. Select a different hotkey in Settings, or use the tray menu.

**Ubuntu: `~/.local/bin/desktop-recorder` is not found.**
Log out and back in, or run `export PATH="$HOME/.local/bin:$PATH"`.

## Build from source

### Windows

You need nothing extra. The C# compiler ships with Windows (.NET Framework 4, `csc.exe`).

Exit the running recorder first. If you do not, the build cannot replace the `.exe`.

Double-click `build.cmd`. It builds `DesktopRecorder.exe` in the repository folder, and installs FFmpeg with winget if FFmpeg is missing. Or run this in PowerShell in the folder:

```
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize+ /out:DesktopRecorder.exe /r:System.Windows.Forms.dll /r:System.Drawing.dll /win32manifest:DesktopRecorder.manifest /win32icon:app.ico RecorderCore.cs RecordingSession.cs NativeMethods.cs RegionSelector.cs RecordingFrame.cs DesktopRecorder.cs
```

The app manifest (`DesktopRecorder.manifest`) makes the program per-monitor DPI aware and holds the version number.

To run the unit tests on Windows, build them:

```
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:exe /out:"$env:TEMP\CoreTests.exe" tests\CoreTests.cs RecorderCore.cs RecordingSession.cs
```

Then run them. The tests write `ok` when all checks pass:

```
& "$env:TEMP\CoreTests.exe"
```

### Ubuntu 24.04

Install the packages, then build and install the program for your user:

```
sudo apt update
sudo apt install ffmpeg python3 python3-gi python3-gi-cairo \
  gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 \
  gstreamer1.0-plugins-base gstreamer1.0-pipewire \
  pipewire pipewire-pulse wireplumber pulseaudio-utils \
  xdg-desktop-portal xdg-desktop-portal-gnome xdg-desktop-portal-gtk \
  xclip wl-clipboard
./build-linux.sh --install
export PATH="$HOME/.local/bin:$PATH"
desktop-recorder
```

`./build-linux.sh` alone only byte-compiles `linux/desktop_recorder`. With `--install` it copies the program to `~/.local/share/desktop-recorder`, writes the launcher `~/.local/bin/desktop-recorder` and the menu entry `~/.local/share/applications/desktop-recorder.desktop`. Set `PREFIX` to install somewhere else.

To run the tests on Ubuntu 24.04 (Mono runs the Windows rules; Python runs the Linux rules):

```
sudo apt install mono-devel libmono-system-windows-forms4.0-cil libmono-system-drawing4.0-cil x11-utils xdotool
./run-tests.sh
```

### Release archives

The Release workflow (`.github/workflows/release.yml`) starts on a `v*` tag, or by hand with a version. It builds the Windows zip (`packaging/make-windows-zip.sh`), the Ubuntu archive (`packaging/make-linux-tarball.sh`) and `DesktopRecorder.exe`, writes `SHA256SUMS.txt`, and makes the GitHub release. The release notes come from `packaging/release-notes/v<version>.md`.

## Test results

Version 2.0.0 was tested on one PC: one 1920x1080 monitor at 125% scale, RTX 4060, FFmpeg 2026-04-30. `HANDOFF.md` sections 6.5 to 6.9 have the full tables. Summary:

- **Frame rate.** All capture and encoder settings kept every frame at 10 fps. `ddagrab` with NVENC also kept every frame at 30 fps. No frame was lost during a fast scroll.
- **Read test.** A Claude Sonnet reader read the frames of a 300-line test page. Every run below the frame-rate limit caught 300 of 300 lines. Errors were mostly in emoji lines, and they occurred on lossless frames too.
- **File size.** A 10 s recording of a still area in "Changes only" mode gave 11 frames and 12 KB. That build kept one frame each second. The current build keeps one frame each 60 s (not tested on Windows yet).
- **Pointer.** In "Changes only" mode, a moving mouse pointer on a still screen made the file 18 times larger. With the pointer hidden, the program dropped those frames.

Not tested: PCs with two or more monitors (also `gdigrab` with an area across two monitors), monitors with different scales, the `libx264` fallback in the program, PCs without an NVIDIA GPU, and AI tools other than Claude. In the selector, these keys are not tested: `~`, Shift and Ctrl while you drag, C, M and P.

The test kit is in `test/`: a source text, an auto-scroll page, a frame-counter page, and scripts that count frames and score an AI copy.

## More documents

- [Releases](https://github.com/gecko-of-shadow/screen-vibe-recorder/releases): downloads and patch notes.
- [CHANGELOG.md](CHANGELOG.md): changes in this repository, and how it relates to Desktop Recorder.
- [HANDOFF.md](HANDOFF.md): requirements, decisions, test plans and full test results (from Desktop Recorder).
- The full version history of the program is in the [Desktop Recorder releases](https://github.com/gecko-of-shadow/desktop-recorder/releases).

## Relation to Desktop Recorder

- This repository was made on 2026-11-15. It is not a GitHub fork. Its `main` branch is the same commit as Desktop Recorder commit `cb07dff` ("Correct a path in HANDOFF.md section 7.2"). That is the Desktop Recorder 2.0.0 code plus a fix of the Windows zip script. Screen Vibe Recorder 2.1.0 is the first release of this repository (see [CHANGELOG.md](CHANGELOG.md)).
- The `linux-port` branch adds the Ubuntu 24.04 port of the 2.0 features: region selector, recording frame and Stop button (X11), NVENC with x264 fallback, "Changes only" mode, hide the pointer, status line, one hotkey to start and stop. It also has the Desktop Recorder 2.0.1 changes. CI on GitHub Actions (`ubuntu-24.04`, X11 on Xvfb) passes. A real GNOME desktop, Wayland and NVENC on Linux are not tested. The branch is not merged and not released. Its `HANDOFF.md` sections 5 (decision 13) and 6.11 give the details.
- Desktop Recorder continued after `cb07dff` with versions 2.0.1 and 2.0.2 (see its releases). Those changes are not on `main` here.
