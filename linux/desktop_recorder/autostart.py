"""XDG autostart entry. Disabling hides it instead of removing the file."""

from __future__ import annotations

import os


# Characters that the Desktop Entry spec reserves in an Exec argument.
_EXEC_RESERVED = frozenset(" \t\n\"'\\><~|&;$*?#()`")
# Characters to escape with a backslash inside a double-quoted Exec argument.
_EXEC_ESCAPE = frozenset("\"`$\\")


def desktop_exec_argument(text: str) -> str:
    """One Exec argument, quoted as the Desktop Entry spec says.

    A path with a space stays one argument. The spec applies the string escape
    (backslash) after the quote rule, so each backslash is doubled again. A
    percent sign is a field code, so it becomes %%.
    """
    if text and not any(char in _EXEC_RESERVED for char in text):
        return text.replace("%", "%%")
    quoted = "".join("\\" + char if char in _EXEC_ESCAPE else char for char in text)
    return ('"' + quoted + '"').replace("\\", "\\\\").replace("%", "%%")


def command_path() -> str:
    """The absolute path of the launcher, or "". The path can contain spaces.

    The launcher sets DESKTOP_RECORDER_COMMAND to its own path. Do not split it.
    """
    command = os.environ.get("DESKTOP_RECORDER_COMMAND", "").strip()
    if command and os.path.exists(command):
        return command
    local = os.path.expanduser("~/.local/bin/desktop-recorder")
    if os.path.exists(local):
        return local
    return ""


def autostart_command() -> str:
    """The Exec value for the autostart file."""
    path = command_path()
    return desktop_exec_argument(path) if path else "desktop-recorder"


def autostart_path() -> str:
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(config, "autostart", "desktop-recorder.desktop")


def write_autostart(command: str, enabled: bool, path: str | None = None) -> None:
    target = path or autostart_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    hidden = "false" if enabled else "true"
    text = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Desktop Recorder\n"
        "Comment=Record the desktop to MP4\n"
        f"Exec={command}\n"
        f"Hidden={hidden}\n"
        "X-GNOME-Autostart-enabled=" + ("true" if enabled else "false") + "\n"
        "Terminal=false\n"
    )
    temporary = target + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, target)


def autostart_enabled(path: str | None = None) -> bool:
    target = path or autostart_path()
    if not os.path.exists(target):
        return False
    with open(target, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip() == "Hidden=true":
                return False
            if line.strip() == "X-GNOME-Autostart-enabled=false":
                return False
    return True
