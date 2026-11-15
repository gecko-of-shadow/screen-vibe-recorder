**Review of the Linux port design spec: correctness and parity**

Most of the spec matches the Windows app. I found 26 problems. Five can break the app or give a wrong result (1 to 5). Seven change how the app acts compared with Windows (6 to 12). Six are gaps in the interfaces between files (13 to 18). Eight are problems in the tests and CI (19 to 26). Each problem gives what is wrong, why, and the fix.

### A. Problems that break the app or give a wrong result

**1. `plan_x11(region=settings.region or None)` (12.1) never gives None.**
- Why: `Rect` is a dataclass with no `__bool__`, so `Rect()` is always true. With no saved region, `plan_x11` intersects an empty rect. It records the whole screen, but it also adds the note "The saved region is not on the screen now...". Windows shows no note when no region is saved (`DesktopRecorder.cs:592-597`: the note is set only inside `if (!settings.Region.IsEmpty)`).
- Fix: write `region=None if settings.region.is_empty else settings.region`. In `plan_x11`, add the note only when a non-empty region clips to empty.

**2. The spec does not say which thread calls the Controller.**
- Why: the socket thread (`single_instance.py:_serve`) and the X11 hotkey thread (`hotkey_x11.py:136-141`, "x11-hotkey") call into the app. `popen_with_pdeathsig` raises off the main thread (6.1), and GTK must run on the main thread. Today `ui.py:104-126` sends each command to the main thread with `GLib.idle_add` and waits 5 s for the reply. `ui.py` is a full rewrite, and the spec does not keep this rule.
- Fix: add this to 8.4/12.1. Every `toggle`/`STATUS` from the socket goes to the main thread with `GLib.idle_add`. The socket thread waits on an Event (5 s), then replies with the state after the action. Every hotkey callback goes through `GLib.idle_add(controller.toggle)`. `on_error` from GStreamer and `on_exit` from FFmpeg also go through `GLib.idle_add` (already said for those two).

**3. `window_rect` (9.4) uses either the frame extents or the GTK extents, never both.**
- Why: Mutter sets `_NET_FRAME_EXTENTS = 0,0,0,0` on client-side-decorated GTK windows, and it sets `_GTK_FRAME_EXTENTS` on the same window. With the "else" rule, the shadow is never subtracted. The hover rect then includes the invisible shadow, which is the same bug that Windows fixed with `DWMWA_EXTENDED_FRAME_BOUNDS`. The platform report says to add one and subtract the other.
- Fix: start with `Rect(x, y, w, h)`. If `frame_extents` is set, grow by (l, r, t, b). Then, if `gtk_extents` is set, shrink by (l, r, t, b). Change `test_frame_extents_added` and `test_gtk_extents_subtracted`, and add a test with both set.

**4. 12.1 says "set `GDK_BACKEND=wayland` before you import Gtk. This does not change." This is false about the current code.**
- Why: `ui.py:9-12` imports `Gtk` at module level, and PyGObject runs `Gtk.init` at import. `ui.py:33-36` sets the variable later, inside `run()`, so it has no effect.
- Fix: set `GDK_BACKEND` in `__main__.py` before any `from .ui import ...`, or import `Gtk` lazily inside `ui.run`. Change "This does not change" to "This moves to `__main__.py`".

**5. `FfmpegProcess.write` uses `stdin=PIPE, bufsize=0` (6.2).**
- Why: with `bufsize=0`, `proc.stdin` is an unbuffered `FileIO`. `FileIO.write` can return a short count, and the spec ignores it. Bytes are then lost from a raw BGRx frame, and every frame after it shifts. This damages the Wayland video without an error.
- Fix: loop until all bytes are written (`mv = memoryview(data); while mv: n = stdin.write(mv); mv = mv[n:]`), or use `bufsize=-1` and call `flush()` after each frame. Use the same rule for `b"q"`.

### B. Parity gaps in behavior

**6. "Recording started" notification (8.2 step 5).**
- Why: Windows shows it only when `balloon` is true or the plan has a note (`DesktopRecorder.cs:680-688`). The start at app launch calls `StartSavedRegion(true, false)` (`:531`), so a normal auto-start shows no notification. The spec always shows it, and the test `test_auto_encoder_falls_back_to_x264` depends on that.
- Fix: choose one of two options.
  - Parity: notify at launch only when there are notes. Then change that test to read a separate stderr debug line, for example `Desktop Recorder: plan x11grab libx264`.
  - Deviation: name it as a decision D15.

**7. Text of the fallback retry notification (5.4).**
- Why: Windows passes `reason + "\nFFmpeg: " + firstLine` as a note into the normal start notification. The result is `"Recording started (gdigrab, libx264).\n<reason>\nFFmpeg: <line>"`, 3000 ms, no sound (`DesktopRecorder.cs:549-551`, `:681-686`). The spec's sentence "The notification text is reason + ..." reads as a separate notification.
- Fix: say that the reason line goes into the 8.2 start notification as the first note, before the plan notes and the frame notes.

**8. Notification when FFmpeg stops by itself (8.3.4) has no timeout and no tray update.**
- Why: Windows uses 8000 ms. It also calls `UpdateStats()`, so the tray stats row becomes visible, and `Refresh()` (`DesktopRecorder.cs:499-514`). A start error from `FfmpegProcess.start` is also 8000 ms with `Shorten` (`:672-675`). The spec gives no value for either.
- Fix: add "8000 ms" to both. Add "update and show tray row 2 and refresh the tray" to 8.3.4.

**9. Session files after a fallback retry (11.3.7).**
- Why: Windows takes a new `before` snapshot at each `Start` (`RecordingSession.cs:60`). It also resets the progress (the `generation` counter). Thus the failed first file is not copied to the clipboard and is not counted in the file size. The spec keeps the first snapshot, so "all files count". The X11 retry path does not say either way.
- Fix: take a new snapshot and reset the stats at each retry, on both paths. Or name this as a deviation.

**10. Wayland start with the saved region (11.3.8) when no region is saved.**
- Why: if `wayland_region` is all zeros, the spec still adds the note "The saved region is not on the screen now...". Windows adds the note only when a saved region exists and is off screen.
- Fix: all zeros means record the whole stream 0, `accept_rect(Rect(0,0,iw,ih), Rect(0,0,iw,ih))`, with no note.

**11. Right-click in `pending` mode (9.1).**
- Why: Windows reverts the drag for any `mode != None`, and `Pending` is one of those modes (`RegionSelector.cs:386-394`). The selector stays open. The spec reverts only in `creating`, so a right-click while the left button is down in `pending` cancels the selector.
- Fix: "press 3 in `pending` or `creating`: `selection = prev`, mode `hover`". Add this case to `test_right_click_rules`.

**12. Corner rule in `border_layout` (9.2).**
- Why: on Windows, top and bottom always go from `outer.Left` to `outer.Right`. Each end grows only when that side (left or right) is drawn (`RecordingFrame.cs` `ComputeBorderRects`). The spec grows the corners only "when the left and right sides are present". If one of them is omitted, the spec leaves a corner gap that Windows does not have. Windows tests whether each side is on the monitors with the strip before the corner extension.
- Fix: top = `Rect(outer.x, y-g-t, outer.w, t)` and the same for bottom, with `outer` computed first from the four tests on the un-extended strips. Left and right = `(x-g-t, y, t, h)` and `(right+g, y, t, h)`.

### C. Interface gaps

**13. Wayland fallback (11.3.7) says "a new pump ticker on the same `GstStream`".**
- Why: `GstStream.__init__` takes one `FramePump` and offers frames only to it (11.2). `FramePump` has no restart or reset (7.1). Its counters would also carry over into the retry.
- Fix: choose one.
  - Add `GstStream.set_pump(pump: FramePump) -> None`, safe across threads, and make a new `FramePump` with its crop for the retry.
  - Or add `FramePump.restart(write) -> None` that zeroes the counters and keeps the latest frame.

**14. Audio warnings are lost.**
- Why: `capture.py:36-41` has `"System audio was not found, so this recording is silent."` and `"System audio did not respond, so this recording is silent."`. `capture.py` is rewritten, and 8.2 step 6 does not list these texts.
- Fix: put both in `messages.py`. Add them as notes to the start notification.

**15. `probe_pulse` signature (12.3).**
- Why: the current signature is `probe_pulse(device: str, timeout: float = 2.0)` (`audio.py:31`). The spec gives `probe_pulse(device, ffmpeg: str = "ffmpeg")`. This removes `timeout`, or it breaks positional calls.
- Fix: `probe_pulse(device: str, timeout: float = 2.0, ffmpeg: str = "ffmpeg")`. Always pass `ffmpeg=` as a keyword.

**16. `load_settings` (4.1).**
- Why: the spec says "the existing behavior stays" and also "if the read or the parse raises, returns `Settings()`". The current code (`settings.py:200-205`) catches nothing.
- Fix: call the catch a change. Catch `OSError`, `UnicodeDecodeError` and `ValueError`.

**17. `parse_progress` checks "all digits" (6.3).**
- Why: Python `str.isdigit()` returns true for `"²"`, and then `int()` raises. C# `NumberStyles.None` accepts ASCII digits only. Python `int()` in the settings parser also accepts `_` and non-ASCII digits, and C# does not.
- Fix: use `val.isascii() and val.isdigit()` in `parse_progress`. For the settings ints, use `re.fullmatch(r"\s*[+-]?[0-9]+\s*", val)` before `int()`.

**18. Font scale for the X11 frame (10).**
- Why: `RecordingFrame.show(scale=...)` gets no source on X11. Windows uses the DPI scale of the monitor at the region center.
- Fix: on X11 set `scale = float(S)` and `gdk_scale = S`.

### D. Tests and CI

**19. Expected replies in `test_hotkey_toggle_socket`.**
- Why: by 8.4, the second `TOGGLE` stops the recording. The reply is `STOPPING` or `STOPPED`, never `RECORDING`.
- Fix: expect `SELECTING`, then `STOPPING|STOPPED`.

**20. CI unit-test step (14.4 step 1) gives two different commands.**
- Why: it gives `-m unittest tests.test_pdeathsig tests.test_gst_pipeline` and then says to use `discover`.
- Fix: give one exact form, for example two runs of `PYTHONPATH=linux python3 -m unittest discover -s tests -p 'test_pdeathsig.py' -v`, the second with `-p 'test_gst_pipeline.py'`. Copy the same lines into `run-tests.sh`.

**21. Notifications on CI.**
- Why: the apt line (14.4) has no `gir1.2-notify-0.7`. `xvfb-run` has no notification server and maybe no session bus, so `Notify.Notification.show()` raises `GLib.Error`. Every GUI test waits for stderr lines.
- Fix: write the stderr line first, always. Load `Notify` lazily and catch `ImportError`, `ValueError` and `GLib.Error`. Add `gir1.2-notify-0.7` to the CI apt line, or say that the app runs without it.

**22. Golden string for Wayland (5.2) says "starts with ` -f rawvideo`".**
- Why: the argv starts with the head (`ffmpeg -hide_banner ...`).
- Fix: say "contains".

**23. `fake_ffmpeg.py --stats` (13) duplicates an existing file.**
- Why: `tests/fake_ffmpeg_stats.py` already writes stats lines, and `CoreTests.cs:814` uses it.
- Fix: reuse that file in `test_ffmpeg_process_stats_via_fake`, or give the reason for the duplicate.

**24. Exact pixel checks in `test_selector_dim_and_magnifier`.**
- Why: the test checks for "Accent (64,158,255) exact" on a 1 px line. Cairo antialiases a 1 px line at integer coordinates across two pixels. Windows draws the magnifier caption at `box.x + 4` and `zoom.bottom + 2`, and the zoom area is centered horizontally (`RegionSelector.cs:879`, `:908`). The spec does not give these offsets.
- Fix: draw 1 px lines at `+0.5`, or set `ANTIALIAS_NONE` for frames. Add the caption and zoom offsets to 9.3.

**25. `x11_windows.visible_rects` skips `pid == own_pid`.**
- Why: this also hides the app's own Settings dialog from hover. Windows skips only the selector window (`WindowList.Get(skip, ...)`).
- Fix: skip only the selector window ID, or name this as a deviation. The selector is created after the list, so a pid skip is not needed.

**26. `wayland_stats` sets `has_progress = True` with no FFmpeg stats.**
- Why: Windows shows `"Frames: unknown. File size: ... MB."` when no stats line came.
- Fix: keep `has_progress = progress is not None`, or name this as a deviation in 7.3.

### No problem

- **Settings (4):** the key names, the write order (19 Windows keys, then 5 Linux keys, then extras), the defaults (fps 10, `changes`, quality 1, `show_pointer=1`, `auto`, `yuv420`, CQ 23, hotkey 12/`D`), the `eq < 1` rule, the exact enum matches, the bad value that keeps the old value, the dropped `last_region_hotkey`/`stop_hotkey`, and the region normalize. All match `RecorderCore.cs` lines 324-490.
- **Derived values (5.1):** F, G, L, T, K, CRF and CQ match `RecorderCore.cs:836-848` and `:184-188`. The claim that Python `round()` and C# `Math.Round` both round half to even is correct.
- **Argv (5.2):** the NVENC args, `high444p`, `-rgb_mode` only in fixed mode, no `-pix_fmt` for NVENC, the x264 args, `format=PIX,mpdecimate=max=K` and the split/output args match `RecorderCore.cs:899-1013`. Golden argv 1 is correct. The added `-fps_mode cfr` is a declared deviation (D5).
- **Plan, fallback and probe (5.3 to 5.5):** NVENC size limits 146/50/4096 and the note texts, the `choose_fallback` rules 1 and 3, the marker strings, the 10000 ms window, the probe args, the 5 s/15 s timeouts, the per-path cache and `warm_up` only for `auto` with `record_on_launch=0`. All match.
- **Stats and process (6.2, 6.3):** `parse_progress`, `format_stats`, the 8192-character line cap, the `\r` split, the stop wait `min(15, 4 + 2/max(0.2, fps))`, and `session_files` with size > 0, sorted case-insensitively. All match `RecordingSession.cs`.
- **Selector geometry (9.1, 9.2):** `inclusive_rect`, `square_point`, the drag threshold 3, Ctrl ignored on the first move, the release rules, the keys Enter/Space/`~`/C/M/P/arrows, the `label_rect` offset 8 and flip, the magnifier 10x10 at 8 times with offset 24 and flip, `stop_rect` 84/28/4 with steps 1 to 3, and `border_thickness`.
- **Tray texts:** the status/toggle/tooltip texts, the `"Last recording: "` prefix with `"No stats."`, the hotkey warning text, the Settings labels and validation texts, and the `TrayIcons` colors. All match.
- **Platform rules:** the PDEATHSIG main-thread rationale, and the portal `cursor_mode`/`persist_mode` version rules.

Checked: every Windows reference above, in `RecorderCore.cs`, `RecordingSession.cs`, `RegionSelector.cs`, `RecordingFrame.cs` and `DesktopRecorder.cs`. Also the current Linux files `settings.py`, `ffmpeg_cmd.py`, `ui.py`, `portal.py`, `capture.py`, `audio.py`, `hotkey.py`, `hotkey_x11.py`, `gnome_hotkey.py`, `single_instance.py`, `__main__.py`, `tests/fake_ffmpeg*.py`, `build.yml`, `run-tests.sh` and `.gitattributes`, all in `G:/CLAUDE CODE/svr-linux-port`. Not checked: whether Mutter sets `_NET_FRAME_EXTENTS` to zeros on CSD windows (problem 3), and whether `FileIO` really gives short writes on Ubuntu pipes (problem 5). Neither has run on a real Ubuntu machine. I ran no code and changed no files.