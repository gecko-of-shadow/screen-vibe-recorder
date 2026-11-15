"""All user texts of the tray, the controller, the Settings dialog and the CLI.

Pure module: no gi, Xlib or cairo. FFmpeg plan notes and fallback reasons stay in
ffmpeg_cmd.py. Portal errors stay in portal.py (DESIGN.md section 13).
"""

from __future__ import annotations

# ---------------------------------------------------------------- titles

APP_TITLE = "Desktop Recorder"
STOPPED_TITLE = "Desktop Recorder stopped"

# ---------------------------------------------------------------- stderr lines (tests read them)

READY_LINE = "Desktop Recorder: ready"


def plan_line(backend: str, encoder: str) -> str:
    return f"Desktop Recorder: plan {backend} {encoder}"


def notify_line(title: str, body: str) -> str:
    return title + ": " + body.replace("\n", " | ")


# ---------------------------------------------------------------- start (8.2)

FFMPEG_MISSING = "ffmpeg was not found. Install it with: sudo apt install ffmpeg"
FOLDER_EMPTY = "The recordings folder is empty."


def folder_error(folder: str, exc: object) -> str:
    return f"Cannot create the folder {folder}: {exc}"


def recording_started(backend: str, encoder: str) -> str:
    return f"Recording started ({backend}, {encoder})."


AUDIO_NOT_FOUND = "System audio was not found, so this recording is silent."
AUDIO_NO_RESPONSE = "System audio did not respond, so this recording is silent."
SAVED_REGION_OFF_SCREEN = "The saved region is not on the screen now. Recording the whole desktop."
FFMPEG_LINE_PREFIX = "\nFFmpeg: "

# ---------------------------------------------------------------- stop (8.3)

VIDEO_COPIED_ONE = "Video copied. Press Ctrl+V to paste it.\n"


def videos_copied(count: int) -> str:
    return f"{count} video files copied. Press Ctrl+V to paste them.\n"


RECORDING_STOPPED = "Recording stopped.\n"
COPY_FAILED = "\nCould not copy the video to the clipboard: "
FFMPEG_STOPPED = "ffmpeg stopped."
NO_STATS = "No stats."
LAST_RECORDING_PREFIX = "Last recording: "

# ---------------------------------------------------------------- status (8.1)

NOT_RECORDING = "Not recording"


def recording_region(fps_text: str, width: int, height: int) -> str:
    return f"Recording at {fps_text} fps, {width}x{height} region"


def recording_whole(fps_text: str) -> str:
    return f"Recording at {fps_text} fps, whole desktop"


# ---------------------------------------------------------------- selector and frame (9.3, 10)

SELECTOR_FAILED = "The region selector failed: "
SELECTOR_HINT = "Esc or right-click: cancel"
FRAME_EDGE_NOTE = "The region touches the screen edge, so the red frame is not drawn on that side."


def frame_no_stop_note(hotkey_text: str) -> str:
    return f"There is no room for the Stop button. Press {hotkey_text} or use the tray menu to stop."


def wayland_no_stop_note(hotkey_text: str) -> str:
    return (f"GNOME on Wayland does not let apps put a Stop button on the screen. "
            f"Press {hotkey_text} or use the tray menu to stop.")


# ---------------------------------------------------------------- Wayland (11.3)

NO_PICTURE = "The screen cast sent no picture in 3 seconds. Try again."

# ---------------------------------------------------------------- hotkey (8.5)


def hotkey_in_use(hotkey_text: str) -> str:
    return f"{hotkey_text} is used by another program, so that hotkey is off."


HOTKEY_PICK_OTHER = " Pick a different hotkey in Settings."
WAYLAND_HOTKEY_NEEDS_INSTALL = "Install the program to enable the Wayland hotkey."
WAYLAND_NO_SHORTCUT = "This Wayland session has no GNOME shortcut setting, so the hotkey is off. Use the tray menu."

# ---------------------------------------------------------------- tray (12.1)

MENU_SELECT = "Select region and record"
MENU_STOP = "Stop recording"
MENU_HOTKEY_GAP = "    "
MENU_OPEN_FOLDER = "Open recordings folder"
MENU_SETTINGS = "Settings..."
MENU_EXIT = "Exit"
TOOLTIP_RECORDING = "Desktop Recorder: recording"
TOOLTIP_STOPPED = "Desktop Recorder: stopped"
ALREADY_RUNNING = "Desktop Recorder is already running. Look for its icon in the tray."
CANNOT_SAVE_SETTINGS = "Cannot save the settings: "
CANNOT_OPEN_FOLDER = "Cannot open the folder: "

# ---------------------------------------------------------------- CLI (8.6)

DID_NOT_ANSWER = "Desktop Recorder did not answer."

HELP = """\
Desktop Recorder records a region of the desktop to MP4.

  desktop-recorder              start the tray
  desktop-recorder --select     start the tray and open the region selector
  desktop-recorder --toggle     open the selector, or stop the recording (starts the tray if needed)
  desktop-recorder --check      print ffmpeg, capture backend, display, audio and NVENC state
  desktop-recorder --smoke SEC  record 320x240 with X11 for SEC seconds and check the file
  desktop-recorder --help       print this text
"""

# ---------------------------------------------------------------- Settings dialog (12.2)

SETTINGS_TITLE = "Desktop Recorder settings"
BUTTON_CANCEL = "Cancel"
BUTTON_SAVE = "Save"
BUTTON_BROWSE = "Browse..."
BUTTON_SELECT = "Select"
FOLDER_CHOOSER_TITLE = "Recordings folder"

LABEL_FOLDER = "Save recordings to:"
LABEL_FPS = "Frames per second (0.2 to 60). Lower = smaller files:"
LABEL_QUALITY = "Quality:"
LABEL_SPLIT = "Start a new file every (minutes, 0 = never):"
LABEL_HOTKEY = "Hotkey:"
LABEL_CAPTURE = "Capture:"
LABEL_ENCODER = "Encoder:"
LABEL_CHROMA = "Color detail (chroma):"
LABEL_MODE = "Frame-rate mode:"
LABEL_SELECTOR = "Region selector:"

CAPTURE_X11 = "x11grab (X11 session)"
CAPTURE_WAYLAND = "PipeWire screen cast (Wayland session)"

QUALITY_NAMES = (
    "Smallest files (text still readable)",
    "Balanced (recommended)",
    "Sharpest text (bigger files)",
)
ENCODER_NAMES = (
    "Auto: NVENC, else x264 (recommended)",
    "NVIDIA NVENC (h264_nvenc)",
    "x264 on the CPU (libx264)",
)
CHROMA_NAMES = ("4:2:0 (plays everywhere)", "4:4:4 (sharper colored text)")
MODE_NAMES = ("Fixed frame rate", "Changes only (drops still frames)")

CHECK_WIN = "Win"
CHECK_CTRL = "Ctrl"
CHECK_ALT = "Alt"
CHECK_SHIFT = "Shift"
CHECK_LOGIN = "Start Desktop Recorder when I log in"
CHECK_RECORD_ON_LAUNCH = "Start recording (saved region) when Desktop Recorder starts"
CHECK_COPY = "Copy the video to the clipboard when recording stops"
CHECK_SOUNDS = "Play a sound when recording starts and stops"
CHECK_HIDE_POINTER = "Hide the mouse pointer in the video"
CHECK_AUDIO = "Record system audio (what you hear)"
CHECK_WAYLAND_FRAME = "Show a red frame around the region (Wayland, experimental)"
CHECK_CROSSHAIR = "Crosshair"
CHECK_MAGNIFIER = "Magnifier"
CHECK_POSITION = "Position"

HOTKEY_INVALID = ("For the hotkey, tick at least one of Win, Ctrl, Alt and pick a key. "
                  "Shift alone works only with F1 to F12.")
FOLDER_NOT_ABSOLUTE = "Give a full folder path, such as /home/you/Recordings."
FOLDER_CANNOT_CREATE = "Cannot create that folder: "
