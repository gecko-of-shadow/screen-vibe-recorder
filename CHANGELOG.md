# Changelog

All notable changes to this repository are in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This file was made from the commit history.

## Relation to Desktop Recorder

This repository was made on 2026-11-15 from [gecko-of-shadow/desktop-recorder](https://github.com/gecko-of-shadow/desktop-recorder). It is not a GitHub fork. The `main` branch here is Desktop Recorder commit `cb07dff` (2026-11-15), which is the Desktop Recorder 2.0.0 program plus the two commits below. All history before that commit is the Desktop Recorder history. See the [Desktop Recorder changelog](https://github.com/gecko-of-shadow/desktop-recorder/blob/main/CHANGELOG.md) and [releases](https://github.com/gecko-of-shadow/desktop-recorder/releases) for versions 1.0.0 to 2.0.2.

This repository has no releases and no tags.

## [Unreleased]

### On `main` (since Desktop Recorder 2.0.0)

#### Fixed

- `packaging/make-windows-zip.sh` gives the paths to Python as arguments. A Windows path such as `D:\a\_temp` inside the Python source became an escape sequence, so the zip step of the release workflow failed. (`febdccc`)

#### Changed

- `HANDOFF.md` section 7.2 records how Desktop Recorder 2.0.0 was published, with a corrected path. (`febdccc`, `cb07dff`)
- README: names this repository, explains the relation to Desktop Recorder, and says where to download. No program change.

### On branch `linux-port` (not merged into `main`)

The Ubuntu 24.04 port of the Desktop Recorder 2.0 features. It is tested on GitHub Actions in this repository (HANDOFF decision 13).

#### Added

- Ubuntu region selector with window detection, magnifier, dimming and keys. On Wayland, the selector shows a frame of the portal stream. (`f869f0c`)
- Click-through border outside the region and a Stop button (X11). (`f869f0c`)
- NVENC with an x264 fallback, 4:2:0 or 4:4:4, and the "Changes only" mode. (`f869f0c`)
- A setting to hide the mouse pointer, and a status line with real, duplicate and dropped frames and file size. (`f869f0c`)
- One hotkey that opens the selector and stops a recording. (`f869f0c`)
- FFmpeg ends when the app ends (`PR_SET_PDEATHSIG`). (`f869f0c`)
- Unit tests, Xvfb GUI tests, GStreamer pipeline tests and a CI job that tests the real archive on `ubuntu-24.04`. (`f869f0c`, `0f4a490`)
- The Desktop Recorder 2.0.1 changes, merged from `test-kit`. (`e548c64`)

#### Fixed

- A recording shorter than about 2 s had no frames. FFmpeg no longer probes the `x11grab` and rawvideo input. (`6a6d07b`)
- A held hotkey fired again. The X11 hotkey filter now looks only at the hotkey key. (`6a6d07b`, `774d1ba`)
- Wayland: the recording stops when the screen cast ends (pipeline EOS or portal session closed). (`0f4a490`)
- Wayland: a stream error before the recording starts now fails that stream. (`0f4a490`)
- Exit during the portal dialog ends at once. (`0f4a490`)
- No busy loop below 0.5 fps. A gsettings list that does not parse no longer deletes the other GNOME shortcuts. Settings commits typed fps and split values before Save. The launcher also checks cairo. (`0f4a490`)

#### Notes

- The Linux version number 2.1.0 in `__init__.py` on this branch is a default from the design, not a decision (HANDOFF decision 13).
- Not tested: a real GNOME desktop, Wayland with a real portal, NVENC on Linux, the real tray, audio, HiDPI and multi-monitor (HANDOFF section 6.11).
