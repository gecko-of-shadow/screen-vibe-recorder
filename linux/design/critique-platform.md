**Review: platform risk and testability of the Linux port spec**

I found 7 problems that will block or break things, 9 smaller problems, and 9 risks to verify. P1 to P5 break CI on Xvfb. P6 and P7 put wrong pictures into Wayland videos.

## Problems that block or break things

**P1. Spec 14.2 `STATS_RE` never matches.**
- What is wrong: `STATS_RE` starts with `Last recording: `. That text is only in tray row 2 (12.1). The stop notification (8.3) is `"Recording stopped.\n" + stats`. Stderr (8.6) gets `Desktop Recorder: Recording stopped. | Real frames: ...`.
- Effect: `test_drag_records_region` waits 15 s for the stats line, then fails.
- Fix: remove the `Last recording: ` prefix from `STATS_RE`. Or also write tray row 2 to stderr.

**P2. Spec 9.1 table: a drag with one motion event is not accepted.**
- What is wrong: the rule "motion in `pending`" only sets mode `creating`. It does not set `selection`. Xdotool `mousemove 150 150 mousedown 1 mousemove 349 299 mouseup 1` sends one motion. So `release` sees `selection=None`, and `accept_rect(None)` gives None.
- Effect: `test_drag_records_region` and `test_edge_region_omits_border` fail.
- Fix: the motion that changes the mode to `creating` must also apply the `creating` rule in the same call. Add a unit test: press, one motion of more than 3 px, release gives accept.

**P3. Spec 9.1: hover is set only on motion.**
- What is wrong: `test_click_window_selects_it` does `mousemove 300 250 click 1`. Two cases give no motion event:
  - The selector is not mapped yet when xdotool moves the pointer.
  - The pointer is already at 300,250, so xdotool sends no motion.

  In both cases `hover` stays None, and "release 1 in `pending`" does nothing.
- Fix, in two parts:
  - Model: `press` sets the cursor and recomputes `hover` at the press point. The shell sets the first hover from `seat.get_pointer().get_position()` when it opens.
  - Tests: after "Open the selector", wait until `xwininfo -name "Select region"` succeeds.

**P4. Two "changes" mode tests fail because of how `mpdecimate` works.**
- What is wrong: `mpdecimate=max=K` keeps 1 frame in K+1 (for 10 fps: t=0, 1, 2, ... s). The file length is the last kept frame + 0.1 s.
- Test `test_space_whole_screen_changes_mode` (14.2) asks for "Duration ≥ 3.5 s":
  - The test waits 4 s after Space.
  - The capture starts later: 60 ms selector delay, the spawn, and the x11grab start.
  - Thus the last kept frame is probably at 3.0 s, and the length is 3.1 s. The test fails.
- Test `test_still_source_keeps_length` (14.3) asks for "duration ≥ 2.5 s" from about 30 ticks: the length is 2.1 s or 3.1 s. The result changes from run to run.
- Fix: assert duration ≥ (wall time − 1 s − 1/fps), or check the frame count only. The README must also say that "changes" mode can cut up to 1 s at the end.

**P5. `--toggle` can start a second tray, which shows a modal dialog.**
- Code: `send_command` (`single_instance.py:77-89`) returns None on a recv timeout of 2 s. The server side `_command` (`ui.py:105-127`) waits up to 5 s.
- Spec 8.6: "If no tray answers, run `ui.run(select=True)`". So a tray that is busy for more than 2 s causes a second process. That process shows the GTK dialog "Desktop Recorder is already running...".
  - Examples of a busy tray: the FFmpeg snapshot fallback, the `stop_sync` wait, the synchronous NVENC probe in `start_saved_region` (up to 20 s).
- On Wayland the GNOME keybinding runs `--toggle`, so a hotkey press can show this dialog.
- Fix:
  - Start a tray only when `_reachable(path)` is False.
  - On a timeout from a reachable socket, exit 0 with no UI.
  - Make the client timeout longer than the server timeout (for example 6 s).

**P6. Wayland: frame 0 of the video can show the dimmed selector.**
- What is wrong: in 11.3 step 5, `pump_i.start(proc.write)` runs immediately on accept. The pump slot holds the last frame that Mutter sent. While the selector is open, that frame contains the fullscreen selector. X11 has a 60 ms delay (9.3 step 7). Wayland has none.
- Fix:
  - Store `accept_seq = pump.latest().seq` and destroy the selector windows.
  - Start the ticker only when a frame with `seq > accept_seq` comes in, or after 500 ms.
  - Add the same check to the pump unit tests.

**P7. Wayland: `stride = width * 4` is not safe (spec 11.2 `GstFrame`).**
- What is wrong: `videoconvert ! video/x-raw,format=BGRx` is passthrough when Mutter already sends BGRx. The buffer can then have a padded stride, which a GstVideoMeta gives. The size check `get_size() >= width*4*height` passes. `crop_rows` then reads sheared rows with no error.
- Fix (one of these):
  - (a) Read the stride from GstVideo `VideoMeta`. This needs `gir1.2-gst-plugins-base-1.0`, which is missing from the CI apt line (14.4) and the user apt line (15.1).
  - (b) Use `stride = buffer.get_size() // height` when it divides exactly, else call `on_error`.
  - (c) Crop in GStreamer with `videocrop`.
- Add a unit test that uses a padded stride.

## Smaller problems

**P8. Spec 9.4 `translate_coords` direction.**
- In python-xlib, `w.translate_coords(src, x, y)` converts from `src` to `w`. If a coder reads "translate_coords(root, 0, 0)" as `win.translate_coords(root, 0, 0)`, the result is (−100, −100).
- Effect: `test_click_window_selects_it` fails.
- Fix: write the exact call `root.translate_coords(win, 0, 0)` → `(x, y)`.

**P9. CI can pass while it proves nothing.**
- What is wrong: 14.2 skips the GUI tests when `xdotool`, `xwininfo`, `Xlib` or `Gtk` is missing. 14.3 skips when `Gst` is missing. An apt change then makes CI green with the tests skipped.
- Fix: the CI env sets `DESKTOP_RECORDER_REQUIRE_GUI=1`. With it, each skip condition fails the test.

**P10. Merge order breaks CI between merges (spec 13).**
- What is wrong: `tests/test_linux.py:19-31` imports `Recording`, `PortalError`/`ScreenCast` and the old `ffmpeg_cmd` names at module level. C3 rewrites `ffmpeg_cmd.py` and C4 removes `Recording`. Only C8, which merges last, removes the old classes.
- Effect: from C3 to C8, `discover -p 'test_linux*.py'` gets an ImportError for the whole file. Every merge until C8 then fails the CI.
- Fix: each of C1, C3, C4 and C5 removes its own class from `test_linux.py` in its own commit. Give them that file in the section 13 table.

**P11. The notification path in CI has no session D-Bus.**
- What is wrong: `xvfb-run` starts no session bus. GLib can then try X11 autolaunch (`dbus-launch`), or fail or hang in `Notify.Notification.show()` on the GTK main thread. Today, `ui.py` writes to stderr only in the `except` path.
- Fix:
  - Write the stderr line before the libnotify call, always.
  - Run the GUI step as `dbus-run-session -- xvfb-run -a -s "-screen 0 1280x800x24" ...`.
  - Add env `DESKTOP_RECORDER_NOTIFY=stderr` to skip libnotify in tests.

**P12. `release.yml` has no apt step.**
- What is wrong: the `linux` job (`release.yml:67-80`) installs nothing. Spec 14.4 says `--check` "exit 0 needs `ffmpeg`, which the job installs". Nothing installs it.
- Today `__main__.py:12` imports `.capture`, which loads the whole capture stack (also on `--check`). The new `capture.py` (C7) is GUI and will import `gi` at the top. Then `--check` and `--toggle` load GTK.
- Fix:
  - Add an explicit `apt-get install ffmpeg python3-gi python3-xlib` step.
  - In `__main__.py`, import the GUI modules lazily, inside the branches that need them.

**P13. `run-tests.sh` runs the GUI tests on the real desktop.**
- What is wrong: spec 14.4 says "The Xvfb group runs only when `DISPLAY` works". On Bran's Ubuntu desktop that is the live session. The tests then move the real pointer and grab Ctrl+Shift+F12 and Win+Shift+D. They also assert 1280×800 and window positions that are exact only with no window manager.
- Fix:
  - `run-tests.sh` always runs the GUI group under its own `xvfb-run -a -s "-screen 0 1280x800x24"`.
  - Tests read the screen size from `xdpyinfo`.

**P14. The pattern window depends on Expose timing.**
- What is wrong: `x11_pattern.py` redraws on Expose. When the override-redirect selector is destroyed, Xvfb (no backing store, no compositor) shows the background until the Python client redraws. Frame 0 can catch it, and then "green block ... not dimmed" fails.
- Fix: set the block pattern as the window `background_pixmap`. The X server then repaints the blocks with no client round trip.

**P15. `test_selector_dim_and_magnifier` asks for an "exact" accent color.**
- What is wrong: Cairo strokes a 1 px line at integer coordinates over two pixels at half alpha. The test then fails.
- Fix: say "draw 1 px lines with `rectangle` + `fill`, or stroke at +0.5". Or use `near(..., tol=24)`.

**P16. `test_hotkey_no_repeat` can pass without testing anything.**
- What is wrong: it is not known that Xvfb auto-repeats keys that XTEST holds down. If it does not, the test passes with no repeat.
- Fix:
  - Put the press and release filter in a pure function and unit-test it with the sequence press, press, press, release.
  - In the X test, run `xset r on` first.

## Risks to verify on a real Ubuntu 24.04 machine

**R1. All GUI tests open the selector with the hotkey.**
- Spec 16 says: "If it fails, the GUI tests use `--toggle`". But only `test_hotkey_toggle_socket` does. If `super+shift+d` does not reach Mod4 on Xvfb, about 9 tests fail together.
- Fix: open the selector with `python3 -m desktop_recorder --toggle` in all tests. Keep one test for the hotkey.

**R2. Wayland primary monitor (9.3 step 3).**
- GTK3 on Wayland does not support a primary monitor. `get_primary_monitor()` can return None (not checked).
- Fix: fall back to `display.get_monitor(0)`.

**R3. Wayland focus and cancel.**
- Not checked: that GNOME's custom-keybinding launch sets `XDG_ACTIVATION_TOKEN` or `DESKTOP_STARTUP_ID`. If neither is set, the token is "". Then focus depends only on how Mutter handles a new window.
- Fix:
  - State that right-click cancels (press 3, 9.1) when Esc does not work.
  - Draw a one-line hint on the selector: "Esc or right-click: cancel".

**R4. Wayland border (D10).**
- Not checked: GNOME 46 can start Xwayland on demand. If it does, the first python-xlib `Display()` call can block the main thread for about 1 s.
- Fix: open the border connection in the background while the portal runs, or accept the delay and document it.
- No problem: X11 coordinates on GNOME 46 Xwayland are logical layout px, so `stream_to_layout` is the correct space.

**R5. `-thread_queue_size 1024` on x11grab (5.2).**
- If the encoder stalls, the queue can hold 1024 raw frames, which is very much memory for a large region. Example: 1024 × 1920×1080×4 bytes is about 8 GB.
- The old code has the same value (`ffmpeg_cmd.py:121-122`).
- Fix: use 64 to 128 for x11grab.

**R6. The clipboard on GNOME Wayland is not checked.**
- `clipboard.py:19-20` uses `wl-copy -t text/uri-list`. GNOME 46 does not support wlr-data-control, so wl-copy needs focus. Also, Nautilus and browsers may accept only `x-special/gnome-copied-files` for a file paste.
- Spec 12.3 says "no change", and spec 16 does not list it.
- Fix: add it to the 16 table. Consider also offering `x-special/gnome-copied-files`.

**R7. `preexec_fn` while other threads run (6.1).**
- Python documents `preexec_fn` as not safe when the process has threads. The app has the hotkey, socket and probe threads. The risk is low with only a `prctl` call, but it is not zero.
- Fix: keep the code, and name the risk in the spec. No better stdlib option exists for PDEATHSIG.

**R8. CI command text in 14.4 step 1 contradicts itself.**
- It gives `-m unittest tests.test_pdeathsig ...`, then says to use `discover -p`. A coder can pick the wrong one.
- Fix: write one exact command for each file: `discover -s tests -p 'test_pdeathsig.py' -v`.

**R9. "Whole screen" is not defined for X11 Space.**
- 10 says "no frame for an X11 whole-screen recording", but Space returns a Rect. The test expects no "Recording frame" window. Today that is true only by accident: `border_layout` drops all 4 sides.
- Fix: define whole screen as `region == screen`.

## Parts with no problem

- x11grab argv, offsets, `-draw_mouse` and `bgr0` into NVENC / `-rgb_mode yuv444`. They match the platform report.
- `-stats` with `-loglevel error`: FFmpeg 6.1 still writes the stats line to stderr.
- A raw `pipe:0` input turns off FFmpeg's stdin keys, so `use_q=False` on Wayland is correct.
- Portal: version 5 handling, cursor_mode fallback, no `pipewire-serial`, `os.dup` for each pipewiresrc, all streams read.
- Border math in the test: (148,200) and (350,200) for t=2.
- Golden argv 1 values: T=10, G=300, L=20. The CQ formula gives 28/23/17 and 51.
- The PDEATHSIG design: main thread only, `getppid` race check, and zombie handling in `test_pdeathsig`.
- X11 seat grab against the passive hotkey grab. The 1000 ms grab retry also covers the case where the hotkey key is still down.
- `.gitattributes`: the index already holds LF for all 26 Linux files (`git ls-files --eol`), so CI checkouts are correct.
- The `build.yml` trigger change, and the CI apt names: `python3-xlib`, `x11-utils`, `gir1.2-gstreamer-1.0`, `gstreamer1.0-plugins-base`.

Checked: the lines above in `ffmpeg_cmd.py`, `portal.py`, `wayland.py`, `hotkey_x11.py`, `hotkey.py`, `gnome_hotkey.py`, `single_instance.py`, `__main__.py`, `ui.py`, `capture.py`, `settings.py`, `audio.py`, `clipboard.py`, `recording.py`, `build.yml`, `release.yml`, `run-tests.sh`, `tests/test_x11_session.py`, `tests/fake_ffmpeg*.py`, `tests/test_linux.py` imports and the launcher, all in `G:/CLAUDE CODE/svr-linux-port`.

Not checked (from my own knowledge, with no run):
- The `mpdecimate` keep pattern.
- The python-xlib `translate_coords` direction.
- Xvfb auto-repeat for XTEST keys.
- GTK3 primary monitor on Wayland.
- Xwayland start on demand.
- The GNOME activation token for custom keybindings.
- Nautilus paste targets.