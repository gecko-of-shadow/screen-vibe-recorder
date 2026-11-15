"""xdg-desktop-portal ScreenCast (DESIGN.md 11.1).

Ubuntu's ffmpeg package has no PipeWire input, so the portal file descriptor
goes to GStreamer, and a Python pump sends the frames to ffmpeg.

ScreenCast is pure: a transport does the D-Bus calls. GioTransport is the real
transport. It imports gi only when it is made, so this module imports on Windows.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "PortalError",
    "PortalStreamInfo",
    "PortalSession",
    "PortalTransport",
    "ScreenCast",
    "GioTransport",
    "SOURCE_MONITOR",
    "CURSOR_HIDDEN",
    "CURSOR_EMBEDDED",
    "PERSIST_UNTIL_REVOKED",
]

SOURCE_MONITOR = 1          # SelectSources "types": monitors only
CURSOR_HIDDEN = 1           # "cursor_mode" values
CURSOR_EMBEDDED = 2
PERSIST_UNTIL_REVOKED = 2   # "persist_mode" value (portal version 4 and later)

TEXT_NOT_STARTED = "The screen cast session did not start."
TEXT_CANCELLED = "Screen sharing was cancelled."
TEXT_NO_SCREEN = "No screen was shared."
TEXT_TIMED_OUT = "The screen share dialog timed out."


class PortalError(RuntimeError):
    pass


@dataclass
class PortalStreamInfo:
    node_id: int
    position: tuple[int, int] | None   # logical compositor coordinates, or None
    size: tuple[int, int] | None       # logical size, or None
    source_type: int


@dataclass
class PortalSession:
    session: str
    fd: int                  # owned fd for the PipeWire remote
    restore_token: str
    streams: list[PortalStreamInfo] = field(default_factory=list)


class PortalTransport(Protocol):
    def request(self, method: str, options: dict[str, Any]) -> dict[str, Any]:
        """Run one portal method and return the Response results dictionary."""

    def open_pipewire(self, session: str) -> int:
        """Return an owned file descriptor for the PipeWire remote."""

    def close_session(self, session: str) -> None:
        """End the portal session."""

    def get_property(self, name: str) -> Any:
        """Read an org.freedesktop.portal.ScreenCast property. None on error."""


def _pair(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stream_info(item: Any) -> PortalStreamInfo:
    node_id, props = item[0], (item[1] if len(item) > 1 else None)
    props = props if isinstance(props, dict) else {}
    return PortalStreamInfo(
        node_id=int(node_id),
        position=_pair(props.get("position")),
        size=_pair(props.get("size")),
        source_type=_int_or(props.get("source_type"), 0),
    )


class ScreenCast:
    """Opens a screen cast session and reads all streams. The transport does the D-Bus calls."""

    def __init__(self, transport: PortalTransport) -> None:
        self.transport = transport

    def open(self, restore_token: str = "", show_pointer: bool = True) -> PortalSession:
        session_token = "dr" + uuid.uuid4().hex[:16]
        created = self.transport.request("CreateSession", {"session_handle_token": session_token})
        session = str(created.get("session_handle") or "")
        if not session:
            raise PortalError(TEXT_NOT_STARTED)
        try:
            return self._open_session(session, restore_token, show_pointer)
        except BaseException:
            self.transport.close_session(session)
            raise

    def _open_session(self, session: str, restore_token: str, show_pointer: bool) -> PortalSession:
        version = _int_or(self.transport.get_property("version") or 0, 0)
        modes = _int_or(self.transport.get_property("AvailableCursorModes") or 0, 0)

        select: dict[str, Any] = {
            "session": session,
            "types": SOURCE_MONITOR,
            "multiple": True,
        }
        wanted = CURSOR_EMBEDDED if show_pointer else CURSOR_HIDDEN
        if modes & wanted:
            select["cursor_mode"] = wanted
        elif modes & CURSOR_EMBEDDED:
            select["cursor_mode"] = CURSOR_EMBEDDED
        if version >= 4:
            select["persist_mode"] = PERSIST_UNTIL_REVOKED
            if restore_token:
                select["restore_token"] = restore_token
        self.transport.request("SelectSources", select)

        started = self.transport.request("Start", {"session": session, "parent": ""})
        raw_streams = started.get("streams") or []
        streams = [_stream_info(item) for item in raw_streams]
        if not streams:
            raise PortalError(TEXT_NO_SCREEN)

        fd = self.transport.open_pipewire(session)
        return PortalSession(
            session=session,
            fd=fd,
            restore_token=str(started.get("restore_token") or restore_token or ""),
            streams=streams,
        )


class GioTransport:
    """Real portal client. Needs a session bus and xdg-desktop-portal."""

    BUS_NAME = "org.freedesktop.portal.Desktop"
    OBJECT_PATH = "/org/freedesktop/portal/desktop"
    INTERFACE = "org.freedesktop.portal.ScreenCast"
    DIALOG_TIMEOUT_MS = 120000
    PROPERTY_TIMEOUT_MS = 5000

    def __init__(self) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib

        self._Gio = Gio
        self._GLib = GLib
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._loop: Any = None          # the nested loop of the running request, or None
        self._box: dict[str, Any] | None = None
        self._cancelled = False
        self._closed_watches: dict[str, int] = {}

    def cancel(self) -> None:
        """Main thread. End a running dialog wait at once. Later requests fail at once.

        Exit and session signals call this: Gtk.main_quit() does not end the nested loop.
        """
        self._cancelled = True
        if self._box is not None:
            self._box["cancelled"] = True
        loop = self._loop
        if loop is not None:
            loop.quit()

    def watch_closed(self, session: str, callback: Any) -> int:
        """Call callback() when the portal closes the session (for example the user
        clicks Stop in the GNOME screen sharing indicator). Return the subscription id."""
        def on_signal(*_args: Any) -> None:
            callback()

        subscription = self._bus.signal_subscribe(
            self.BUS_NAME,
            "org.freedesktop.portal.Session",
            "Closed",
            session,
            None,
            self._Gio.DBusSignalFlags.NONE,
            on_signal,
        )
        self._closed_watches[session] = subscription
        return subscription

    def request(self, method: str, options: dict[str, Any]) -> dict[str, Any]:
        token = "dr" + uuid.uuid4().hex[:16]
        path = _request_path(self._bus.get_unique_name(), token)
        payload = dict(options)
        payload["handle_token"] = token
        session = payload.pop("session", None)
        parent = payload.pop("parent", None)
        variant_options = {key: _variant(self._GLib, value) for key, value in payload.items()}
        if method == "CreateSession":
            parameters = self._GLib.Variant("(a{sv})", (variant_options,))
        elif method == "SelectSources":
            parameters = self._GLib.Variant("(oa{sv})", (session, variant_options))
        elif method == "Start":
            parameters = self._GLib.Variant("(osa{sv})", (session, parent or "", variant_options))
        else:
            raise PortalError("Unknown portal method " + method)
        return self._call(method, path, parameters)

    def _call(self, method: str, path: str, parameters: Any) -> dict[str, Any]:
        Gio = self._Gio
        GLib = self._GLib
        if self._cancelled:
            raise PortalError(TEXT_CANCELLED)
        box: dict[str, Any] = {}
        loop = GLib.MainLoop()

        def on_signal(_conn, _sender, object_path, _interface, signal, params):
            if signal != "Response" or object_path != path or params is None:
                return
            code, details = params.unpack()
            box["code"] = code
            box["details"] = details
            loop.quit()

        def on_timeout() -> bool:
            box["timed_out"] = True
            loop.quit()
            return False

        subscription = self._bus.signal_subscribe(
            self.BUS_NAME,
            "org.freedesktop.portal.Request",
            "Response",
            path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_signal,
        )
        try:
            self._bus.call_sync(
                self.BUS_NAME,
                self.OBJECT_PATH,
                self.INTERFACE,
                method,
                parameters,
                GLib.VariantType.new("(o)"),
                Gio.DBusCallFlags.NONE,
                self.DIALOG_TIMEOUT_MS,
                None,
            )
            if "code" not in box and not self._cancelled:
                timeout_id = GLib.timeout_add(self.DIALOG_TIMEOUT_MS, on_timeout)
                self._loop = loop
                self._box = box
                try:
                    loop.run()
                finally:
                    self._loop = None
                    self._box = None
                if not box.get("timed_out"):
                    GLib.source_remove(timeout_id)
        finally:
            self._bus.signal_unsubscribe(subscription)
        if self._cancelled and "code" not in box:
            raise PortalError(TEXT_CANCELLED)
        if "code" not in box:
            raise PortalError(TEXT_TIMED_OUT)
        if box["code"] != 0:
            raise PortalError(TEXT_CANCELLED)
        details = box["details"] or {}
        return dict(details)

    def get_property(self, name: str) -> Any:
        GLib = self._GLib
        try:
            result = self._bus.call_sync(
                self.BUS_NAME,
                self.OBJECT_PATH,
                "org.freedesktop.DBus.Properties",
                "Get",
                GLib.Variant("(ss)", (self.INTERFACE, name)),
                GLib.VariantType.new("(v)"),
                self._Gio.DBusCallFlags.NONE,
                self.PROPERTY_TIMEOUT_MS,
                None,
            )
            value = result.unpack()[0]
        except Exception:  # noqa: BLE001 - GLib.Error or a bad reply: the caller uses 0
            return None
        if hasattr(value, "unpack"):
            value = value.unpack()
        return value

    def open_pipewire(self, session: str) -> int:
        GLib = self._GLib
        parameters = GLib.Variant("(oa{sv})", (session, {}))
        result, fds = self._bus.call_with_unix_fd_list_sync(
            self.BUS_NAME,
            self.OBJECT_PATH,
            self.INTERFACE,
            "OpenPipeWireRemote",
            parameters,
            GLib.VariantType.new("(h)"),
            self._Gio.DBusCallFlags.NONE,
            30000,
            None,
            None,
        )
        index = result.unpack()[0]
        raw = fds.get(index)
        owned = os.dup(raw)
        os.close(raw)
        return owned

    def close_session(self, session: str) -> None:
        # Stop the Closed watch first, so our own Close does not call it.
        subscription = self._closed_watches.pop(session, None)
        if subscription is not None:
            try:
                self._bus.signal_unsubscribe(subscription)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._bus.call_sync(
                self.BUS_NAME,
                session,
                "org.freedesktop.portal.Session",
                "Close",
                None,
                None,
                self._Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
        except Exception:  # noqa: BLE001 - the session can be closed already
            return


def _request_path(unique_name: str, token: str) -> str:
    sender = unique_name[1:].replace(".", "_") if unique_name.startswith(":") else unique_name.replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def _variant(glib: Any, value: Any) -> Any:
    if isinstance(value, bool):
        return glib.Variant("b", value)
    if isinstance(value, int):
        return glib.Variant("u", value)
    if isinstance(value, str):
        return glib.Variant("s", value)
    raise PortalError("Cannot send portal option of type " + type(value).__name__)
