"""PDEATHSIG test (DESIGN.md 6.1 and 14.1): the child ends when its parent is killed. Linux only."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import unittest

try:
    import linux_skip
except ImportError:  # tests/linux_skip.py (owner C8) is not there yet: same rule, local copy.
    import types

    linux_skip = types.ModuleType("linux_skip")
    linux_skip.REQUIRE = os.environ.get("DESKTOP_RECORDER_REQUIRE_GUI") == "1"
    linux_skip.IS_LINUX = sys.platform.startswith("linux")

    def _need(ok: bool, reason: str) -> None:
        if ok:
            return
        if linux_skip.REQUIRE:
            raise AssertionError("Required for this test: " + reason)
        raise unittest.SkipTest(reason)

    def _need_linux() -> None:
        _need(linux_skip.IS_LINUX, "Linux")

    def _need_program(name: str) -> str:
        path = shutil.which(name)
        _need(path is not None, name)
        return path or ""

    linux_skip.need = _need
    linux_skip.need_linux = _need_linux
    linux_skip.need_program = _need_program

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINUX_DIR = os.path.join(REPO, "linux")

# The helper parent: start "sleep 60" with PDEATHSIG, print the child pid, then wait.
HELPER = (
    "import sys, time\n"
    "from desktop_recorder.recording import popen_with_pdeathsig\n"
    "child = popen_with_pdeathsig(['sleep', '60'])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(60)\n"
)


def _is_gone(pid: int) -> bool:
    """True when the process does not exist or is a zombie (no reaper in some containers)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            stat = handle.read()
    except OSError:
        return True
    # Format: pid (comm) state ... ; comm can hold spaces, so split after the last ")".
    rest = stat[stat.rfind(")") + 1 :].split()
    return bool(rest) and rest[0] == "Z"


class PdeathsigTests(unittest.TestCase):
    def setUp(self) -> None:
        linux_skip.need_linux()
        linux_skip.need_program("sleep")

    def test_child_dies_with_parent(self) -> None:
        env = dict(os.environ)
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = LINUX_DIR + (os.pathsep + old if old else "")
        parent = subprocess.Popen(
            [sys.executable, "-c", HELPER],
            stdout=subprocess.PIPE,
            env=env,
            text=True,
        )
        child_pid = 0
        try:
            line = parent.stdout.readline() if parent.stdout is not None else ""
            self.assertTrue(line.strip().isdigit(), f"helper output: {line!r}")
            child_pid = int(line.strip())
            self.assertFalse(_is_gone(child_pid), "the child must run before the parent is killed")
            os.kill(parent.pid, signal.SIGKILL)
            parent.wait(5)
            deadline = time.monotonic() + 2.0
            gone = _is_gone(child_pid)
            while not gone and time.monotonic() < deadline:
                time.sleep(0.05)
                gone = _is_gone(child_pid)
            self.assertTrue(gone, f"child {child_pid} still runs 2 s after its parent was killed")
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(5)
            if parent.stdout is not None:
                parent.stdout.close()
            if child_pid and not _is_gone(child_pid):
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
