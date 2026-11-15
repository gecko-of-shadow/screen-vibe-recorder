"""Tests for portal.ScreenCast with a fake transport (DESIGN.md 11.1 and 14.1). Pure: any OS."""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.portal import (  # noqa: E402
    PortalError,
    PortalSession,
    PortalStreamInfo,
    ScreenCast,
)

SESSION = "/org/freedesktop/portal/desktop/session/1_42/dr0123"


class FakeTransport:
    def __init__(self, version: Any = 5, modes: Any = 3, streams: list | None = None,
                 token_out: str | None = "new-token", start_error: Exception | None = None) -> None:
        self.version = version
        self.modes = modes
        self.streams = [(57, {"position": (0, 0), "size": (1536, 864), "source_type": 1})] if streams is None else streams
        self.token_out = token_out
        self.start_error = start_error
        self.calls: list[tuple[str, Any]] = []
        self.closed: list[str] = []

    def request(self, method: str, options: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, dict(options)))
        if method == "CreateSession":
            return {"session_handle": SESSION}
        if method == "SelectSources":
            return {}
        if method == "Start":
            if self.start_error is not None:
                raise self.start_error
            result: dict[str, Any] = {"streams": self.streams}
            if self.token_out is not None:
                result["restore_token"] = self.token_out
            return result
        raise AssertionError("unknown method " + method)

    def open_pipewire(self, session: str) -> int:
        self.calls.append(("OpenPipeWireRemote", session))
        return 99

    def close_session(self, session: str) -> None:
        self.calls.append(("Close", session))
        self.closed.append(session)

    def get_property(self, name: str) -> Any:
        self.calls.append(("Get", name))
        if name == "version":
            return self.version
        if name == "AvailableCursorModes":
            return self.modes
        return None

    def method_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def select_options(self) -> dict[str, Any]:
        for name, options in self.calls:
            if name == "SelectSources":
                return options
        raise AssertionError("SelectSources was not called")


class PortalTests(unittest.TestCase):
    def test_call_order(self) -> None:
        transport = FakeTransport()
        result = ScreenCast(transport).open()
        self.assertEqual(
            transport.method_names(),
            ["CreateSession", "Get", "Get", "SelectSources", "Start", "OpenPipeWireRemote"],
        )
        create = transport.calls[0][1]
        self.assertRegex(create["session_handle_token"], r"^dr[0-9a-f]{16}$")
        self.assertEqual([arg for name, arg in transport.calls if name == "Get"], ["version", "AvailableCursorModes"])
        select = transport.select_options()
        self.assertEqual(select["session"], SESSION)
        self.assertEqual(select["types"], 1)
        self.assertIs(select["multiple"], True)
        start = transport.calls[4][1]
        self.assertEqual(start, {"session": SESSION, "parent": ""})
        self.assertEqual(transport.calls[5], ("OpenPipeWireRemote", SESSION))
        self.assertIsInstance(result, PortalSession)
        self.assertEqual(result.session, SESSION)
        self.assertEqual(result.fd, 99)
        self.assertEqual(transport.closed, [])

    def test_cursor_mode_shown_hidden_and_fallback(self) -> None:
        cases = [
            # (available modes, show_pointer, expected cursor_mode or None)
            (1, True, None),   # only hidden: shown is not there, and 2 is not there
            (1, False, 1),
            (2, True, 2),
            (2, False, 2),     # hidden is not there: fall back to embedded
            (3, True, 2),
            (3, False, 1),
            (0, True, None),
            (0, False, None),
            (None, True, None),  # property read failed
        ]
        for modes, shown, expected in cases:
            with self.subTest(modes=modes, shown=shown):
                transport = FakeTransport(modes=modes)
                ScreenCast(transport).open(show_pointer=shown)
                select = transport.select_options()
                if expected is None:
                    self.assertNotIn("cursor_mode", select)
                else:
                    self.assertEqual(select["cursor_mode"], expected)

    def test_version_3_omits_persist(self) -> None:
        transport = FakeTransport(version=3)
        result = ScreenCast(transport).open(restore_token="old-token")
        select = transport.select_options()
        self.assertNotIn("persist_mode", select)
        self.assertNotIn("restore_token", select)
        self.assertEqual(result.restore_token, "new-token")

        transport = FakeTransport(version=None)  # property read failed: version 0
        ScreenCast(transport).open(restore_token="old-token")
        self.assertNotIn("persist_mode", transport.select_options())

        transport = FakeTransport(version=4)
        ScreenCast(transport).open()
        select = transport.select_options()
        self.assertEqual(select["persist_mode"], 2)
        self.assertNotIn("restore_token", select)  # empty token is not sent

    def test_all_streams_read(self) -> None:
        streams = [
            (57, {"position": (0, 0), "size": (1536, 864), "source_type": 1}),
            (61, {"position": [1536, 0], "size": [1920, 1080], "source_type": 1}),
            (70, {}),
        ]
        transport = FakeTransport(streams=streams)
        result = ScreenCast(transport).open()
        self.assertEqual(
            result.streams,
            [
                PortalStreamInfo(node_id=57, position=(0, 0), size=(1536, 864), source_type=1),
                PortalStreamInfo(node_id=61, position=(1536, 0), size=(1920, 1080), source_type=1),
                PortalStreamInfo(node_id=70, position=None, size=None, source_type=0),
            ],
        )

    def test_zero_streams_closes(self) -> None:
        transport = FakeTransport(streams=[])
        with self.assertRaises(PortalError) as caught:
            ScreenCast(transport).open()
        self.assertEqual(str(caught.exception), "No screen was shared.")
        self.assertEqual(transport.closed, [SESSION])
        self.assertNotIn("OpenPipeWireRemote", transport.method_names())

    def test_cancel_closes(self) -> None:
        transport = FakeTransport(start_error=PortalError("Screen sharing was cancelled."))
        with self.assertRaises(PortalError) as caught:
            ScreenCast(transport).open()
        self.assertEqual(str(caught.exception), "Screen sharing was cancelled.")
        self.assertEqual(transport.closed, [SESSION])

    def test_token_in_out(self) -> None:
        transport = FakeTransport(version=5, token_out="new-token")
        result = ScreenCast(transport).open(restore_token="old-token")
        select = transport.select_options()
        self.assertEqual(select["restore_token"], "old-token")
        self.assertEqual(select["persist_mode"], 2)
        self.assertEqual(result.restore_token, "new-token")

        transport = FakeTransport(version=5, token_out=None)  # no new token: keep the old one
        result = ScreenCast(transport).open(restore_token="old-token")
        self.assertEqual(result.restore_token, "old-token")

        transport = FakeTransport(version=5, token_out=None)
        result = ScreenCast(transport).open()
        self.assertEqual(result.restore_token, "")

    def test_no_session_handle(self) -> None:
        class NoHandle(FakeTransport):
            def request(self, method: str, options: dict[str, Any]) -> dict[str, Any]:
                if method == "CreateSession":
                    self.calls.append((method, options))
                    return {}
                return super().request(method, options)

        transport = NoHandle()
        with self.assertRaises(PortalError):
            ScreenCast(transport).open()
        self.assertEqual(transport.method_names(), ["CreateSession"])


if __name__ == "__main__":
    unittest.main()
