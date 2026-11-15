"""Unit tests for the launcher path in the autostart file and the GNOME shortcut.

A tarball can be unpacked into a folder with a space. The path must stay one
argument. Pure: they run on Windows too.
"""

from __future__ import annotations

import os
import shlex
import shutil
import tempfile
import unittest
from unittest import mock

from desktop_recorder.autostart import (
    autostart_command,
    command_path,
    desktop_exec_argument,
    write_autostart,
)
from desktop_recorder.gnome_hotkey import gvariant_string, update_gnome_shortcut


class _Result:
    def __init__(self, stdout: str = "") -> None:
        self.returncode = 0
        self.stdout = stdout


def _parse_gvariant_string(text: str) -> str:
    """Read back one GVariant string literal in single quotes."""
    if len(text) < 2 or text[0] != "'" or text[-1] != "'":
        raise ValueError(text)
    out = []
    index = 1
    while index < len(text) - 1:
        char = text[index]
        if char == "\\":
            index += 1
            char = text[index]
        elif char == "'":
            raise ValueError("bare quote in " + text)
        out.append(char)
        index += 1
    return "".join(out)


def _parse_exec(value: str) -> list[str]:
    """Undo the key-file string escape, then split as the Desktop Entry spec says.

    Inside double quotes, a backslash escapes only " ` $ and the backslash (POSIX).
    shlex does not escape $ and ` in double quotes, so this test has its own parser.
    """
    text = value.replace("\\\\", "\\")
    words: list[str] = []
    word: list[str] | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            word = word if word is not None else []
            index += 1
            while text[index] != '"':
                if text[index] == "\\" and text[index + 1] in '"`$\\':
                    index += 1
                elif text[index] == "%":
                    index += 1  # "%%" is one percent sign.
                word.append(text[index])
                index += 1
        elif char == " ":
            if word is not None:
                words.append("".join(word))
            word = None
        elif char == "%":
            word = word if word is not None else []
            word.append("%")
            index += 1  # "%%" is one percent sign.
        else:
            word = word if word is not None else []
            word.append(char)
        index += 1
    if word is not None:
        words.append("".join(word))
    return words


class CommandPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp(prefix="Desktop Recorder ")
        self.launcher = os.path.join(self.folder, "desktop-recorder")
        with open(self.launcher, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
        self.home = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _env(self, command: str) -> mock._patch:
        return mock.patch.dict(os.environ, {"DESKTOP_RECORDER_COMMAND": command, "HOME": self.home,
                                            "USERPROFILE": self.home})

    def test_path_with_space_is_kept(self) -> None:
        self.assertIn(" ", self.launcher)
        with self._env(self.launcher):
            self.assertEqual(command_path(), self.launcher)

    def test_missing_path_gives_empty(self) -> None:
        with self._env(os.path.join(self.folder, "missing")):
            self.assertEqual(command_path(), "")
            self.assertEqual(autostart_command(), "desktop-recorder")

    def test_autostart_exec_keeps_one_argument(self) -> None:
        with self._env(self.launcher):
            value = autostart_command()
        self.assertEqual(_parse_exec(value), [self.launcher])
        target = os.path.join(self.home, "autostart", "desktop-recorder.desktop")
        write_autostart(value, True, target)
        with open(target, encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle]
        exec_line = next(line for line in lines if line.startswith("Exec="))
        self.assertEqual(_parse_exec(exec_line[len("Exec="):]), [self.launcher])


class DesktopExecArgumentTest(unittest.TestCase):
    def test_plain_path_is_not_quoted(self) -> None:
        self.assertEqual(desktop_exec_argument("/usr/bin/desktop-recorder"), "/usr/bin/desktop-recorder")

    def test_reserved_characters(self) -> None:
        for path in ("/home/u/Desktop Recorder/desktop-recorder", '/a/b"c$d', "/a/it's/x",
                     "/a/50%/x y", "/a/back\\slash x", "/a/`tick`"):
            value = desktop_exec_argument(path)
            self.assertEqual(_parse_exec(value), [path], value)

    def test_percent_is_doubled(self) -> None:
        self.assertEqual(desktop_exec_argument("/a/50%/x"), "/a/50%%/x")


class GnomeShortcutQuoteTest(unittest.TestCase):
    def test_gvariant_string_round_trip(self) -> None:
        for text in ("Desktop Recorder", "<Super><Shift>d", "'/a b/desktop-recorder' --toggle",
                     "/a/it's\\x --toggle"):
            self.assertEqual(_parse_gvariant_string(gvariant_string(text)), text)

    def test_quoted_command_reaches_gsettings_as_one_string(self) -> None:
        launcher = "/home/u/Desktop Recorder/desktop-recorder"
        command = shlex.quote(launcher) + " --toggle"
        calls: list[list[str]] = []

        def runner(args):
            calls.append(args)
            return _Result("@as []" if args[1] == "get" else "")

        self.assertTrue(update_gnome_shortcut(12, "D", command, runner))
        values = {call[-2]: call[-1] for call in calls if len(call) == 5}
        self.assertEqual(_parse_gvariant_string(values["command"]), command)
        self.assertEqual(shlex.split(_parse_gvariant_string(values["command"])), [launcher, "--toggle"])
        self.assertEqual(_parse_gvariant_string(values["name"]), "Desktop Recorder")


if __name__ == "__main__":
    unittest.main()
