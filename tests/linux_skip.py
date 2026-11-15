"""One skip rule for all Linux tests. DESKTOP_RECORDER_REQUIRE_GUI=1 turns a skip into a failure."""

from __future__ import annotations

import importlib
import os
import shutil
import socket
import subprocess
import sys
import unittest
from typing import Any

REQUIRE = os.environ.get("DESKTOP_RECORDER_REQUIRE_GUI") == "1"
IS_LINUX = sys.platform.startswith("linux")


def need(ok: bool, reason: str) -> None:
    if ok:
        return
    if REQUIRE:
        raise AssertionError("Required for this test: " + reason)
    raise unittest.SkipTest(reason)


def need_linux() -> None:
    need(IS_LINUX, "Linux")


def need_af_unix() -> None:
    need(hasattr(socket, "AF_UNIX"), "AF_UNIX sockets")


def need_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except Exception as exc:  # ImportError, or a broken binding
        need(False, f"{name} ({exc})")


def need_gi(namespace: str, version: str) -> Any:
    try:
        import gi

        gi.require_version(namespace, version)
        return importlib.import_module("gi.repository." + namespace)
    except Exception as exc:
        need(False, f"gi {namespace} {version} ({exc})")


def need_program(name: str) -> str:
    path = shutil.which(name)
    need(path is not None, name)
    return path or ""


def need_display() -> str:
    display = os.environ.get("DISPLAY", "")
    ok = False
    if display and shutil.which("xdpyinfo"):
        ok = subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    need(ok, "an X display (DISPLAY and xdpyinfo)")
    return display
