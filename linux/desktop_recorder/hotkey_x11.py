"""Global hotkey on X11.

NumLock and CapsLock are grabbed as well, or the shortcut dies when they are on.
Wayland compositors do not deliver these grabs; GNOME uses a custom shortcut instead.

This module imports on any OS. It loads libX11 inside functions only.
"""

from __future__ import annotations

import ctypes
import select
import threading
from collections.abc import Callable

ShiftMask = 1
LockMask = 2
ControlMask = 4
Mod1Mask = 8
Mod2Mask = 16
Mod4Mask = 64
GrabModeAsync = 1
KeyPress = 2
KeyRelease = 3


class KeyRepeatFilter:
    """Lets only the first press of a held key through (the X11 form of MOD_NOREPEAT).

    With detectable auto-repeat, a held key gives press, press, press ... release.
    Without it (for example on Xvfb), a held key gives press, then release + press
    pairs. The X server gives both events of a pair the same time stamp.
    """

    def __init__(self) -> None:
        self.down = False
        self._release_time: int | None = None

    def event(self, kind: int, time: int | None = None) -> bool:
        """kind 2 = press, 3 = release. time = X server time in ms, or None.

        True when the press must fire the hotkey.
        """
        if kind == KeyPress:
            if self.down:
                return False
            self.down = True
            last = self._release_time
            self._release_time = None
            if time is not None and last is not None and 0 <= time - last <= 1:
                return False  # auto-repeat pair: release and press at the same time
            return True
        if kind == KeyRelease:
            self.down = False
            self._release_time = time
        return False


class _XEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("pad", ctypes.c_byte * 188)]


class _XKeyEvent(ctypes.Structure):
    # The start of XKeyEvent (Xlib.h), up to the time field.
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("root", ctypes.c_ulong),
        ("subwindow", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("x_root", ctypes.c_int),
        ("y_root", ctypes.c_int),
        ("state", ctypes.c_uint),
        ("keycode", ctypes.c_uint),
    ]


def _key_event(event: _XEvent) -> _XKeyEvent:
    return ctypes.cast(ctypes.byref(event), ctypes.POINTER(_XKeyEvent)).contents


def x_modifiers(modifiers: int) -> int:
    value = 0
    if modifiers & 1:
        value |= Mod1Mask
    if modifiers & 2:
        value |= ControlMask
    if modifiers & 4:
        value |= ShiftMask
    if modifiers & 8:
        value |= Mod4Mask
    return value


def keysym_for(key: str) -> int:
    if len(key) == 1 and "A" <= key <= "Z":
        return ord(key)
    if len(key) == 1 and key.isdigit():
        return ord(key)
    if key.startswith("F") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0xFFBE + number - 1
    return 0


_HANDLER_TYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _load_xlib():
    lib = ctypes.CDLL("libX11.so.6")
    lib.XInitThreads()
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XKeysymToKeycode.restype = ctypes.c_uint
    lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XGrabKey.restype = ctypes.c_int
    lib.XGrabKey.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    lib.XUngrabKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong]
    lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XConnectionNumber.restype = ctypes.c_int
    lib.XConnectionNumber.argtypes = [ctypes.c_void_p]
    lib.XPending.restype = ctypes.c_int
    lib.XPending.argtypes = [ctypes.c_void_p]
    lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    # The handler is a function pointer. Use c_void_p, so a NULL old handler round-trips.
    lib.XSetErrorHandler.restype = ctypes.c_void_p
    lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    lib.XkbSetDetectableAutoRepeat.restype = ctypes.c_int
    lib.XkbSetDetectableAutoRepeat.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    return lib


class X11Hotkey:
    def __init__(self, display_name: str | None, modifiers: int, key: str, callback: Callable[[], None]) -> None:
        self._display_name = display_name
        self._modifiers = modifiers
        self._key = key
        self._callback = callback
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._grab_failed = False
        self._filter = KeyRepeatFilter()
        self.registered = False

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._run, name="x11-hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.registered

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _grab(self, lib, display, keycode: int, base: int, root: int, extras: tuple[int, ...]) -> bool:
        """Grab the key. The X error handler is set only for the grab and the XSync."""

        def on_error(_display, _event):
            self._grab_failed = True
            return 0

        handler = _HANDLER_TYPE(on_error)
        self._grab_failed = False
        old = lib.XSetErrorHandler(ctypes.cast(handler, ctypes.c_void_p))
        try:
            for extra in extras:
                lib.XGrabKey(display, keycode, base | extra, root, 0, GrabModeAsync, GrabModeAsync)
            lib.XSync(display, 0)
        finally:
            lib.XSetErrorHandler(old)
        # Keep the handler object alive until the old handler is back.
        del handler
        return not self._grab_failed

    def _run(self) -> None:
        try:
            lib = _load_xlib()
        except (OSError, AttributeError):
            self._ready.set()
            return
        name = None if not self._display_name else self._display_name.encode()
        display = lib.XOpenDisplay(name)
        if not display:
            self._ready.set()
            return
        try:
            root = lib.XDefaultRootWindow(display)
            keycode = lib.XKeysymToKeycode(display, keysym_for(self._key))
            if keycode == 0:
                return
            supported = ctypes.c_int(0)
            lib.XkbSetDetectableAutoRepeat(display, 1, ctypes.byref(supported))
            base = x_modifiers(self._modifiers)
            extras = (0, LockMask, Mod2Mask, LockMask | Mod2Mask)
            if not self._grab(lib, display, keycode, base, root, extras):
                for extra in extras:
                    lib.XUngrabKey(display, keycode, base | extra, root)
                lib.XSync(display, 0)
                return
            self.registered = True
            self._ready.set()
            fd = lib.XConnectionNumber(display)
            event = _XEvent()
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.2)
                if not ready:
                    continue
                while lib.XPending(display):
                    lib.XNextEvent(display, ctypes.byref(event))
                    if event.type not in (KeyPress, KeyRelease):
                        continue
                    key = _key_event(event)
                    # While the grab is active, X11 also sends the other keys (for example
                    # the release of Ctrl). Only the hotkey key may change the filter.
                    if key.keycode != keycode:
                        continue
                    if self._filter.event(event.type, int(key.time)):
                        try:
                            self._callback()
                        except Exception:  # noqa: BLE001
                            pass
            for extra in extras:
                lib.XUngrabKey(display, keycode, base | extra, root)
            lib.XSync(display, 0)
        finally:
            self._ready.set()
            lib.XCloseDisplay(display)
