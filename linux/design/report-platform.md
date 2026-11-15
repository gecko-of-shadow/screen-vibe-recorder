# Ubuntu 24.04 (noble) platform facts for the Linux region recorder

Tags: **C** = CONFIRMED, from a page that I fetched in this session (URL given). **U** = UNSURE. A U fact comes from recall or from an inference, and a test method follows it.

## 1. FFmpeg on noble

- **C:** The `ffmpeg` package version is `7:6.1.1-3ubuntu5`, in universe. Source: https://packages.ubuntu.com/noble/ffmpeg
- **C (build dependency only):** Debian 6.1.1-3 `debian/control` lists `libffmpeg-nvenc-dev [amd64 arm64 i386]`. `debian/rules` has no explicit `--enable-nvenc`. FFmpeg configure finds ffnvcodec automatically when the headers are present. Thus `h264_nvenc` is very probably in the amd64 build. Sources: https://salsa.debian.org/multimedia-team/ffmpeg/-/raw/debian/7%256.1.1-3/debian/control and https://salsa.debian.org/multimedia-team/ffmpeg/-/raw/debian/7%256.1.1-3/debian/rules
- **U:** I read the Debian files, not the Ubuntu `3ubuntu5` files. Test it with `ffmpeg -hide_banner -encoders | grep nvenc`.
- **U:** NVENC loads `libnvidia-encode.so.1` and `libcuda.so.1` at run time. On Ubuntu they come from the NVIDIA driver packages, for example `libnvidia-encode-<ver>`. I did not check the package names.
- **C:** nv-codec-headers 12.1 needs NVIDIA driver 530.41.03 or later on Linux. Source: https://raw.githubusercontent.com/FFmpeg/nv-codec-headers/n12.1.14.0/README
- **C:** h264_nvenc in 6.1.1 has these options. Source: https://raw.githubusercontent.com/FFmpeg/FFmpeg/n6.1.1/libavcodec/nvenc_h264.c
  - `-preset p1` to `p7`.
  - `-tune hq`, `ll`, `ull`, `lossless`.
  - `-rc vbr`.
  - `-cq` (0 to 51).
  - `-profile high444p`.
  - `-rgb_mode yuv420|yuv444|disabled`. It has an effect only on RGB input. x11grab gives `bgr0`, so the Windows argv `-rgb_mode yuv444` carries over.
- **C:** The rules file has `--enable-libx264` and `--enable-libpulse`. They are off only in the stage1 bootstrap profile. Source: the debian/rules URL above.
- **C:** The rules file has no xcb flag. The control file has `libxcb-shape0-dev`, `libxcb-shm0-dev` and `libxcb-xfixes0-dev`. x11grab is detected automatically. Source: the debian/control URL above.
- **C:** `-fps_mode` is in the 6.1.1 docs. Values: `passthrough`, `cfr`, `vfr`, `drop`, `auto`. `-vsync` is deprecated. Source: https://raw.githubusercontent.com/FFmpeg/FFmpeg/n6.1.1/doc/ffmpeg.texi
- **U:** `mpdecimate` is in the noble build. It is an old built-in filter. Test it with `ffmpeg -filters | grep mpdecimate`.
- **C:** x11grab in 6.1.1 (`libavdevice/xcbgrab.c`) has these options. Source: https://raw.githubusercontent.com/FFmpeg/FFmpeg/n6.1.1/libavdevice/xcbgrab.c

  | Option | Type | Default | Range or note |
  |---|---|---|---|
  | `window_id` | int | 0 (root) | |
  | `x`, `y` | int | 0 | |
  | `grab_x`, `grab_y` | int | 0 | Same fields as `x`, `y`. |
  | `video_size` | image size | full screen or window | |
  | `framerate` | string | `ntsc` | |
  | `draw_mouse` | int | 1 | 0 to 1 |
  | `follow_mouse` | int | 0 | `centered` = -1, or a pixel count |
  | `show_region` | int | 0 | 0 to 1 |
  | `region_border` | int | 3 | 1 to 128 |
  | `select_region` | bool | 0 | 0 to 1 |

- **C:** The input syntax is `[hostname]:display_number.screen_number[+x_offset,y_offset]`. The offset is from the top-left of the X screen. `select_region` overrides `video_size`, `grab_x` and `grab_y`. `window_id` disables `follow_mouse` and `select_region`. Source: https://ffmpeg.org/ffmpeg-devices.html
- **Region argv example:** `-f x11grab -framerate 10 -draw_mouse 0 -video_size 1120x892 -grab_x 8 -grab_y 120 -i :0.0`. The form `-i :0.0+8,120` is the same.
- **C:** The current docs list no PipeWire input device. Noble FFmpeg cannot read PipeWire. Source: https://ffmpeg.org/ffmpeg-devices.html
- **C:** The `pulse` input has the options `server`, `name`, `stream_name`, `sample_rate`, `channels` and `wallclock`. Source: https://ffmpeg.org/ffmpeg-devices.html

## 2. ScreenCast portal on noble (GNOME 46)

- **C:** Package versions:
  - `xdg-desktop-portal` is `1.18.4-1ubuntu2.24.04.3` on amd64. Source: https://packages.ubuntu.com/noble/xdg-desktop-portal
  - `xdg-desktop-portal-gnome` is `46.0-1build1`, in main. Source: https://packages.ubuntu.com/noble/xdg-desktop-portal-gnome
  - `gnome-shell` is `46.0-0ubuntu6~24.04.17`. Source: https://packages.ubuntu.com/noble/gnome-shell
- **C:** The ScreenCast XML at tag 1.18.4 documents **version 5** of the interface. Source: https://raw.githubusercontent.com/flatpak/xdg-desktop-portal/1.18.4/data/org.freedesktop.portal.ScreenCast.xml
  - The stream properties are `id`, `position (ii)`, `size (ii)`, `source_type` and `mapping_id`.
  - **`pipewire-serial` is not in 1.18.4.** It is a version 6 key. Use the node id from `streams[i][0]` and the fd from `OpenPipeWireRemote`. Read the `version` property and do not assume a version.
- **C:** SelectSources options and Start results. Source: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html

  | Key | Values |
  |---|---|
  | `types` (bitmask) | MONITOR = 1, WINDOW = 2, VIRTUAL = 4. Default: MONITOR. |
  | `multiple` | Default: false. |
  | `cursor_mode` | Hidden = 1 (default), Embedded = 2, Metadata = 4. A mode that `AvailableCursorModes` does not advertise closes the session. Interface version 2 or later. |
  | `persist_mode` | 0 = no (default), 1 = while the app runs, 2 = until revoked. Interface version 4 or later. |
  | `restore_token` | One use only. Start returns a new token. Interface version 4 or later. |

- **Hide the pointer:** use `cursor_mode=1`. Show the pointer: use `cursor_mode=2`.
- **C:** `position` is present only for monitor streams, "in the compositor coordinate space". The docs say that `size` can differ from the stream pixel size. Source: same docs page as above.
- **C (Mutter 46 code):** `position` and `size` are the logical monitor layout, with no scale. The stream pixel size is `roundf(logical.width * scale)`, but only when `meta_backend_is_stage_views_scaled()` is true. Otherwise the scale is 1.0. Sources: https://gitlab.gnome.org/GNOME/mutter/-/raw/46.0/src/backends/meta-screen-cast-monitor-stream.c and https://gitlab.gnome.org/GNOME/mutter/-/raw/46.0/src/backends/meta-screen-cast-monitor-stream-src.c
- **U:** The pixel units on a default noble Wayland session are not established. If stage views are scaled, the stream is in physical pixels and `size` is logical. With fractional scaling, the stream is approximately physical, rounded. Measure the scale for each monitor as the negotiated stream width ÷ `size.width`.
- **C (Mutter 46 code):** Mutter makes frames from stage paints. A still screen gives no frames, so the stream has a variable rate. Source: meta-screen-cast-monitor-stream-src.c, URL above.
- **C:** In embedded mode, Mutter paints the pointer into the frame. Source: same file.
- **U:** On the X11 session, Mutter ScreenCast is probably not available. Use x11grab there.
- **U:** `persist_mode=2` and `restore_token` work for a host app (not Flatpak) on xdg-desktop-portal-gnome 46. Test it: the second start must show no dialog.

## 3. Region selector on GNOME Wayland

- **U:** A GTK3 window can call `gtk_window_fullscreen_on_monitor(screen, n)` on Wayland. Make one selector window for each `Gdk.Monitor`. The window origin is then the monitor origin, `Gdk.Monitor.get_geometry()`.
- **U:** A Wayland client cannot read or set the global position of its own toplevel. `Gtk.Window.move` and keep-above have no effect.
- **U:** GTK3 `get_scale_factor()` is an integer. At 125%, GTK reports 2, and the compositor scales the window down.
- **Mapping (a formula, not tested):**
  - `stream_x = (sel_x_logical - mon.x) * stream_w / mon.width`
  - `stream_y = (sel_y_logical - mon.y) * stream_h / mon.height`
  - Then round to even values.
  - Match each monitor to its stream by `position == (mon.x, mon.y)`. The match by position is UNSURE.
  - Do not use `get_scale_factor()` alone.
- **C:** Since xdg-desktop-portal 1.15, a Screenshot backend of version 2 asks for the `screenshot` permission. xdg-desktop-portal-gnome skips the dialog only when the permission is already granted and the request is not interactive. GNOME Shell blocks the dialog when the app does not have focus. Then the app gets no image. Sources:
  - https://lists.gnome.org/archives/commits-list/2022-August/msg04856.html
  - https://discourse.nixos.org/t/looking-for-a-gnome-compatible-screenshot-annotation-tool/75964/5
  - https://github.com/flameshot-org/flameshot/issues/4463
- **U:** Whether a host app, with an empty app id, gets the first-time dialog on 46.
- **Recommendation:** for the frozen background, take one frame from the ScreenCast stream itself. This avoids a second permission. It also gives the image in the same pixels as the recording.
- **C:** `org.gnome.Shell.Introspect.GetWindows` (and the related Shell D-Bus APIs) check the caller against an allowlist of portal backends, or need unsafe mode. A normal app gets AccessDenied. Source: https://discourse.gnome.org/t/unable-to-call-the-remote-getwindows-gnome-method-via-dbus/21201
- **Window detection on Wayland is not possible.** Offer the drag and Space (full monitor) only.

## 4. Click-through border and exclusion from capture

- **C:** `gdk_window_input_shape_combine_region` makes the input shape apply only to events. Pointer events over areas outside the shape go to the window below. On X11 it needs Shape 1.1. The docs do not mention Wayland. Source: https://docs.gtk.org/gdk3/method.Window.input_shape_combine_region.html
- **X11 (U):** make 4 thin windows, or one window with an XShape output shape. Set `override_redirect` (a Gtk POPUP window) or the type hint `DOCK` or `NOTIFICATION`, plus keep-above, skip-taskbar and skip-pager. Set an empty input shape.
  - Use a shaped opaque window, not an RGBA window. RGBA needs a compositor, and Xvfb has none.
- **Wayland (U):** GTK3 sets the input region with `wl_surface.set_input_region`, so click-through works. But a normal toplevel cannot be put at a position. Mutter has no wlr-layer-shell. A fullscreen transparent overlay with an empty input region can draw the border, but Mutter can push it behind other windows when it loses focus. Treat the border on Wayland as best effort, or leave it out.
- **U:** I found no equivalent of `WDA_EXCLUDEFROMCAPTURE` on X11 or on GNOME Wayland. x11grab and the ScreenCast stream capture all pixels. Thus keep the border and the Stop button outside the region.
  - If the region is the full monitor, the border is in the video. Do not draw it then, or draw it only in the selector.

## 5. Window list on X11 for hover detection

- **C:** `gir1.2-wnck-3.0` `43.0-3build4` is in main. Source: https://packages.ubuntu.com/noble/gir1.2-wnck-3.0
- **C:** `python3-xlib` `0.33-2` is in universe. Source: https://packages.ubuntu.com/noble/python3-xlib
- **U:** Wnck needs an X11 screen. `Wnck.Screen.get_default()` gives nothing useful on Wayland.
- **U:** Wnck gives `get_geometry()` (with the frame) and `get_client_window_geometry()`.
- **U:** With python3-xlib, read these root and window properties:
  - `_NET_CLIENT_LIST_STACKING` gives the windows from bottom to top.
  - `_NET_WM_STATE` and `_NET_WM_WINDOW_TYPE` let you skip hidden windows and dock/tool windows.
  - `_NET_FRAME_EXTENTS` (left, right, top, bottom) is for decorations from the window manager. Add it.
  - `_GTK_FRAME_EXTENTS` is for the invisible shadow of a GTK CSD window. Subtract it.
  - `TranslateCoordinates` to the root window gives the global position.
- **U:** Both methods need a window manager that implements EWMH. Xvfb alone has none.

## 6. Global hotkey

- **C:** The GlobalShortcuts portal came with GNOME 48: "With GNOME 48, it is now possible for apps to register system-wide global shortcuts." Source: https://release.gnome.org/48/developers/
- **It is not on noble (GNOME 46).**
- **Wayland (U):** use a GNOME custom keybinding.
  - Relocatable schema: `org.gnome.settings-daemon.plugins.media-keys.custom-keybinding`, with the keys `name`, `command` and `binding` (for example `'<Super><Shift>d'`).
  - Add the path to `org.gnome.settings-daemon.plugins.media-keys custom-keybindings`.
  - The command sends `--toggle` to the running instance, for example through GApplication D-Bus.
  - The current port does this already: `linux/desktop_recorder/gnome_hotkey.py:15-16` and `:22`, `:32`.
- **X11 (U):** use `XGrabKey` on the root window with Mod4 + Shift. Grab it also with the Lock and NumLock variants.
  - The current port does this with ctypes: `linux/desktop_recorder/hotkey_x11.py:86-126`.
  - GTK3 GdkX11 has no key-grab API.
  - On Wayland, `XGrabKey` through Xwayland does not work globally.
  - It is not known whether GNOME or Mutter already uses Super+Shift+D.

## 7. Tray

- **C:** `gir1.2-ayatanaappindicator3-0.1` `0.5.93-1build3` is in main. Use `gi.require_version("AyatanaAppIndicator3", "0.1")`. Source: https://packages.ubuntu.com/noble/gir1.2-ayatanaappindicator3-0.1
- **C:** `gnome-shell-extension-appindicator` `57-2` is in main. Its description is "AppIndicator, KStatusNotifierItem and tray support for GNOME Shell." Source: https://packages.ubuntu.com/noble/gnome-shell-extension-appindicator
- **U:** Ubuntu enables this extension by default.
- **U:** `Gtk.StatusIcon` is deprecated, and GNOME Shell has no tray of its own. It shows only through the extension's legacy tray support.
- **Use AppIndicator first and `StatusIcon` as the fallback.** The current port does this: `ui.py:97`, `ui.py:296-305`.
- **U:** An AppIndicator has no left-click event. Put the status line in the menu, as on Windows.

## 8. GStreamer `pipewiresrc` (PipeWire 1.0.5 on noble)

- **C:** `gstreamer1.0-pipewire` `1.0.5-1ubuntu3.3` (amd64) is in main. Source: https://packages.ubuntu.com/noble/gstreamer1.0-pipewire
- **C:** Element properties. Source: https://raw.githubusercontent.com/PipeWire/pipewire/1.0.5/src/gst/gstpipewiresrc.c

  | Property | Default | Note |
  |---|---|---|
  | `path` | | Deprecated. |
  | `target-object` | | |
  | `client-name` | | |
  | `always-copy` | false | |
  | `min-buffers` | 8 | |
  | `max-buffers` | INT32_MAX | |
  | `fd` | -1 | |
  | `resend-last` | false | Resend the last buffer on EOS. |
  | `keepalive-time` | 0 ms | 0 = off. |
  | `autoconnect` | true | |

- **C:** The PTS comes from the PipeWire `spa_meta_header` pts, or else from the buffer time. A keepalive or EOS resend of the last buffer gets the time of the pipeline clock. Source: same file.
- **U:** `do-timestamp` is a GstBaseSrc property. It replaces the PTS with the clock time at arrival.
- **To avoid drops:**
  - Do not use `appsink drop=true`.
  - Do not use a bounded queue that drops.
  - Count the frames in each step.
- **The current port has these drop risks:**
  - `linux/desktop_recorder/ffmpeg_cmd.py:180` has `appsink ... sync=false max-buffers=2 drop=true`. It drops frames silently.
  - `linux/desktop_recorder/wayland.py:22` has `queue.Queue(maxsize=2)`, and `wayland.py:130` uses `put(..., timeout=0.05)`. A frame is lost when the encoder is slow.
- **Fixed mode (U):** `pipewiresrc keepalive-time=<1000/fps> ! videoconvert ! videocrop left= right= top= bottom= ! videorate ! video/x-raw,format=BGRx,framerate=N/D`. Then send the frames to FFmpeg (`-f rawvideo -pix_fmt bgr0 -video_size WxH -framerate fps -i pipe:0`), which reuses the Windows encoder argv.
  - Crop in GStreamer, before the copy to Python, so that less data moves.
- **Changes mode (U):** run the same constant-rate pipe, then `mpdecimate` and `-fps_mode vfr` in FFmpeg, as on Windows.
- **Status line:** compute "real frames" and "duplicates" from the `videorate` `in`/`out`/`dup`/`drop` properties. Mutter gives no frames on a still screen, so `videorate` duplicates are normal there. They are not lost captures.
- **Other current-port facts:**
  - `portal.py:71` uses only `streams[0]`.
  - `portal.py:58-60` uses `types=1`, `multiple=True` and a fixed `cursor_mode=2`. Make it 1 or 2 from `show_pointer`, after a check of `AvailableCursorModes`.
  - `portal.py:73` reads `pipewire-serial`. That key does not exist on 1.18.4, so the code falls back to `path=node_id` (`ffmpeg_cmd.py:173`). `path` is deprecated but still works on 1.0.5.

## 9. Xvfb in GitHub Actions `ubuntu-24.04`

- **C:** `xdotool` `1:3.20160805.1-5build1` is in universe. Source: https://packages.ubuntu.com/noble/xdotool
- **U:** x11grab records an Xvfb display. Xvfb has the MIT-SHM, XFIXES, SHAPE and XTEST extensions. Run it with `xvfb-run -a -s "-screen 0 1280x800x24"`.
- **U:** xdotool drives GTK apps on Xvfb through XTEST: `mousemove`, `mousedown 1`, `mouseup 1`, `key super+shift+d`.
- **U:** Xvfb has no window manager and no compositor. Without a window manager:
  - `_NET_CLIENT_LIST_STACKING` and `_NET_FRAME_EXTENTS` are absent.
  - Fullscreen and keep-above hints are ignored. Set the size and position of POPUP windows directly.
  - RGBA transparency does not composite.
  - For window-detection tests, add a light window manager from apt (for example `openbox` or `xfwm4`). Its package name and section are not checked.
- **Pixel test (U):**
  1. Draw known colored blocks at known coordinates, with a GTK window or `xsetroot`.
  2. Record a region with the app's own argv and `libx264`.
  3. Decode one frame with `ffmpeg -i out.mp4 -frames:v 1 -f rawvideo -pix_fmt rgb24 -`.
  4. Check the size and the block colors with a tolerance in plain Python.
  5. Also check that no border-colored pixels are in the frame.
  6. Count the frames with `ffprobe -count_frames`.
- **Limits:**
  - CI has no NVIDIA GPU, so only the `libx264` fallback runs there.
  - CI has no GNOME Wayland session, portal or PipeWire session. Only unit tests with a fake transport cover the Wayland path.

## Design constraints for the Linux port

1. Use two capture paths, chosen by `XDG_SESSION_TYPE` / `WAYLAND_DISPLAY`:
   - X11: FFmpeg `x11grab` with `-video_size WxH -grab_x X -grab_y Y` (or `:0.0+X,Y`).
   - Wayland: the ScreenCast portal, then GStreamer `pipewiresrc`, then raw frames on FFmpeg stdin.
   - Noble FFmpeg 6.1.1 has no PipeWire input.
2. Use only apt packages:
   - `ffmpeg` (universe)
   - `python3-gi`, `gir1.2-gtk-3.0`
   - `gir1.2-gstreamer-1.0`, `gstreamer1.0-plugins-base`, `gstreamer1.0-pipewire` (main)
   - `gir1.2-ayatanaappindicator3-0.1` (main)
   - `gir1.2-wnck-3.0` (main) or `python3-xlib` (universe)
   - CI only: `xvfb`, `xdotool` (universe)
3. Find the encoders at run time with `ffmpeg -encoders`. Then do a short NVENC test encode at app start, in the background, as on Windows. Fall back to `libx264 -preset veryfast`.
   - NVENC needs the NVIDIA driver 530.41.03 or later, and its `libnvidia-encode`.
   - Keep the Windows NVENC argv: `-preset p4 -rc vbr -cq 28/23/17`. 4:4:4 is `-rgb_mode yuv444` (x11grab gives bgr0) or `-pix_fmt yuv444p` with `-profile high444p`.
4. Do not use `pipewire-serial` or other version 6 portal keys. Noble has ScreenCast version 5. Use the node id and the `OpenPipeWireRemote` fd.
5. Set `cursor_mode` from `show_pointer`: 2 = shown, 1 = hidden. Check `AvailableCursorModes` first. The portal default is Hidden. On X11, set `-draw_mouse 1|0`.
6. Use `persist_mode=2` and save the new `restore_token` after each Start. The first recording on Wayland always shows the GNOME share dialog. Make the user choose all monitors (`multiple=true`).
7. Wayland selector:
   - Make one fullscreen GTK window on each `Gdk.Monitor`.
   - For the frozen background, use one frame from the ScreenCast stream, not the Screenshot portal.
   - Map logical selection coordinates to stream pixels with stream_w ÷ `size.w`, measured. Do not use `get_scale_factor()`.
   - Round to even sizes.
   - A region must stay on one monitor (one stream).
   - No window detection on Wayland.
8. X11 selector:
   - Use one POPUP (override-redirect) window that covers the root window. Read physical pixels from `Gdk.get_default_root_window()`.
   - Get windows from `_NET_CLIENT_LIST_STACKING`. Add `_NET_FRAME_EXTENTS` and subtract `_GTK_FRAME_EXTENTS`.
   - Skip hidden windows, minimized windows and dock/tool windows.
9. Border and Stop button:
   - X11: shaped, opaque, override-redirect windows with an empty input shape, outside the region.
   - Wayland: positioning is not possible, so the border is best effort or absent. Put Stop in the tray menu and on the hotkey.
   - No exclude-from-capture API exists on either path. Never draw inside the region. Hide the border for a full-monitor region.
10. Hotkey:
    - X11: `XGrabKey` Mod4+Shift+D.
    - Wayland (GNOME 46): a gsettings custom keybinding that runs `desktop-recorder --toggle`. Send the toggle to the running instance through D-Bus (GApplication).
    - No GlobalShortcuts portal before GNOME 48.
11. Frame-rate modes on Wayland:
    - Mutter sends frames only when the screen changes.
    - Use `keepalive-time` and `videorate` to a constant rate. Then use FFmpeg `mpdecimate=max=ceil(fps)-1` with `-fps_mode vfr` for "changes", or a constant rate for "fixed".
    - Remove `appsink drop=true` (`ffmpeg_cmd.py:180`) and the drop on the bounded queue (`wayland.py:22`, `:130`). Count every frame in each step.
12. Status line:
    - X11: read FFmpeg `-progress` / stats `frame=`, `dup=`, `drop=`.
    - Wayland: also read the `videorate` `in`, `out`, `dup` and `drop` counters, and the count of frames written to the pipe.
13. Keep fragmented MP4 (`+frag_keyframe+empty_moov`, `-frag_duration 2000000`). Make FFmpeg end when the app dies: set `prctl(PR_SET_PDEATHSIG)` through `preexec_fn`, or use a process group. This is the Linux equivalent of the Windows job object (U).
14. Tray: use AyatanaAppIndicator3 first and `Gtk.StatusIcon` as the fallback. Put the status line in the menu.
15. CI (Xvfb, no GPU, no Wayland):
    - Test the x11grab argv and a region recording with a pixel check, using libx264.
    - Test the selector with xdotool.
    - Test the portal and the GStreamer path only with fakes.
    - Add a light window manager for window-detection tests.
    - Do not use RGBA transparency in features that the tests check.

Checked in this session: the package versions and sections above, the FFmpeg 6.1.1 x11grab, nvenc and `-fps_mode` sources, the Debian build dependencies, the portal 1.18.4 XML and the current portal docs, the Mutter 46 screen-cast code, the pipewiresrc 1.0.5 code, the GNOME 48 release note, and the lines in the current port.

Not checked: that the Ubuntu `3ubuntu5` build has h264_nvenc, the NVIDIA runtime package names, the scaled-stage-views default and fractional scaling on noble, the first Screenshot dialog for host apps, the Wayland overlay and border behavior, x11grab and xdotool on Xvfb, and which apt window manager to use. All U items above need a run on a real Ubuntu 24.04 machine or in CI.