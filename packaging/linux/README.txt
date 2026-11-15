Desktop Recorder for Ubuntu 24.04 (portable)

Unpack this archive anywhere and run:

    ./desktop-recorder

No root is necessary. Settings go to ~/.config/DesktopRecorder/settings.txt.
The program is the Python files in this folder. It does not install itself.
To add it to the app menu of your user, run:

    ./desktop-recorder --install-menu

Install these Ubuntu 24.04 packages one time. They are not in this archive:

    sudo apt update
    sudo apt install ffmpeg python3 python3-gi python3-gi-cairo python3-xlib \
      gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7 \
      gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-pipewire \
      pipewire pipewire-pulse wireplumber pulseaudio-utils \
      xdg-desktop-portal xdg-desktop-portal-gnome xclip wl-clipboard

How to record:

1. Press Super+Shift+D. The region selector opens. The screen goes darker.
2. Drag a box, then release the mouse. The recording starts at once.
   On X11 you can also click a window to record it.
3. Press Super+Shift+D again to stop. You can also use the tray menu.
   On X11 a small Stop button shows below the region.

Selector keys: Esc cancels. Enter accepts. Space records the whole screen.
~ records the monitor under the cursor. Right-click also cancels.

Wayland: The first recording shows the GNOME screen-share dialog. Pick the
screen and allow 'Remember'. On Wayland there is no window detection and no
Stop button. A region stays on one monitor.

    ./desktop-recorder --help
    ./desktop-recorder --check
    ./desktop-recorder --smoke 2

--check shows the capture backend and the encoder. --smoke 2 records two
seconds of a 320x240 area with X11, then exits.
