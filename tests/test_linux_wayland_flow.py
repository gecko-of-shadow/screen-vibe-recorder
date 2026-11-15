"""Pure tests for the Wayland flow fixes: the portal transport, GstStream EOS and the controller.

The code under test needs gi on Linux. These tests use fakes in its place, so they
run on any OS. They check the logic only, not GNOME, the portal or GStreamer.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
import types
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder import messages  # noqa: E402
from desktop_recorder.geometry import Rect  # noqa: E402
from desktop_recorder.portal import TEXT_CANCELLED, GioTransport, PortalError  # noqa: E402
from desktop_recorder.selector_model import SelectorOptions  # noqa: E402
from desktop_recorder.settings import Settings  # noqa: E402
from desktop_recorder.wayland import TEXT_CAST_ENDED, GstStream  # noqa: E402

SESSION = "/org/freedesktop/portal/desktop/session/1_42/dr0123"


# ---------------------------------------------------------------- fake GLib and Gio


class FakeLoop:
    on_run: Any = None   # set by a test: called inside run()

    def __init__(self) -> None:
        self.quit_count = 0

    def run(self) -> None:
        if FakeLoop.on_run is not None:
            FakeLoop.on_run(self)

    def quit(self) -> None:
        self.quit_count += 1


class FakeGLib:
    MainLoop = FakeLoop
    VariantType = SimpleNamespace(new=lambda text: text)
    idle_calls: list = []
    removed: list = []

    @staticmethod
    def Variant(sig: str, value: Any) -> tuple:  # noqa: N802 - GLib name
        return (sig, value)

    @classmethod
    def timeout_add(cls, _ms: int, _fn: Any, *_args: Any) -> int:
        return 77

    @classmethod
    def source_remove(cls, source_id: int) -> bool:
        cls.removed.append(source_id)
        return True

    @classmethod
    def idle_add(cls, fn: Any, *args: Any) -> int:
        cls.idle_calls.append((fn, args))
        return 1


FakeGio = SimpleNamespace(
    DBusSignalFlags=SimpleNamespace(NONE=0),
    DBusCallFlags=SimpleNamespace(NONE=0),
)


class FakeBus:
    def __init__(self) -> None:
        self.log: list[tuple] = []
        self.subscriptions: dict[int, tuple] = {}
        self._next = 10

    def get_unique_name(self) -> str:
        return ":1.42"

    def signal_subscribe(self, sender, interface, member, path, arg0, flags, callback) -> int:
        self._next += 1
        self.subscriptions[self._next] = (interface, member, path, callback)
        self.log.append(("subscribe", member, self._next))
        return self._next

    def signal_unsubscribe(self, subscription: int) -> None:
        self.subscriptions.pop(subscription, None)
        self.log.append(("unsubscribe", subscription))

    def call_sync(self, _name, path, interface, method, *_rest) -> Any:
        self.log.append(("call", interface, method, path))
        return None


def make_transport() -> tuple[GioTransport, FakeBus]:
    transport = GioTransport.__new__(GioTransport)
    bus = FakeBus()
    transport._Gio = FakeGio
    transport._GLib = FakeGLib
    transport._bus = bus
    transport._loop = None
    transport._box = None
    transport._cancelled = False
    transport._closed_watches = {}
    return transport, bus


class TransportTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeGLib.removed = []
        FakeLoop.on_run = None
        self.addCleanup(setattr, FakeLoop, "on_run", None)

    def test_cancel_ends_the_dialog_wait(self) -> None:
        # Exit comes while the portal dialog is open: the nested loop must end at once.
        transport, bus = make_transport()
        seen: dict[str, Any] = {}

        def exit_during_dialog(loop: FakeLoop) -> None:
            seen["loop_is_kept"] = transport._loop is loop
            transport.cancel()
            seen["quit"] = loop.quit_count

        FakeLoop.on_run = exit_during_dialog
        with self.assertRaises(PortalError) as ctx:
            transport.request("CreateSession", {"session_handle_token": "x"})
        self.assertEqual(str(ctx.exception), TEXT_CANCELLED)
        self.assertTrue(seen["loop_is_kept"])
        self.assertEqual(seen["quit"], 1)
        self.assertEqual(FakeGLib.removed, [77], "the dialog timeout source must be removed")
        self.assertIsNone(transport._loop)
        self.assertEqual(bus.subscriptions, {}, "the Response watch must be removed")

        # Later requests fail at once, with no D-Bus call.
        calls_before = len([e for e in bus.log if e[0] == "call"])
        with self.assertRaises(PortalError):
            transport.request("SelectSources", {"session": SESSION, "types": 1})
        self.assertEqual(len([e for e in bus.log if e[0] == "call"]), calls_before)

    def test_cancel_with_no_dialog_is_safe(self) -> None:
        transport, _bus = make_transport()
        transport.cancel()
        self.assertTrue(transport._cancelled)

    def test_closed_watch(self) -> None:
        transport, bus = make_transport()
        hits: list[int] = []
        sid = transport.watch_closed(SESSION, lambda: hits.append(1))
        interface, member, path, callback = bus.subscriptions[sid]
        self.assertEqual((interface, member, path), ("org.freedesktop.portal.Session", "Closed", SESSION))
        callback(None, ":1.5", SESSION, interface, member, None)
        self.assertEqual(hits, [1])

        # close_session removes the watch before it sends Close, so our own Close
        # does not report "the screen cast ended".
        transport.close_session(SESSION)
        events = [e for e in bus.log if e[0] in ("unsubscribe", "call")]
        self.assertEqual(events[0], ("unsubscribe", sid))
        self.assertEqual(events[1][:3], ("call", "org.freedesktop.portal.Session", "Close"))
        self.assertNotIn(sid, bus.subscriptions)


# ---------------------------------------------------------------- GstStream EOS


class StreamEosTests(unittest.TestCase):
    def test_eos_reports_once(self) -> None:
        errors: list[str] = []
        stream = GstStream("pipewiresrc fd=3 path=1", pump=None, on_error=errors.append)
        stream._on_bus_eos(None, None)
        self.assertEqual(errors, [TEXT_CAST_ENDED])
        stream._send_error("later error")
        self.assertEqual(errors, [TEXT_CAST_ENDED], "a stream reports one error only")


# ---------------------------------------------------------------- Controller with a fake gi


def import_capture() -> types.ModuleType:
    """Import capture.py with a fake gi. sys.modules is restored afterwards."""
    gi = types.ModuleType("gi")
    gi.require_version = lambda *_a: None
    repo = types.ModuleType("gi.repository")
    repo.GLib = FakeGLib
    gi.repository = repo
    package = importlib.import_module("desktop_recorder")
    missing = object()
    old_attr = getattr(package, "capture", missing)
    try:
        with mock.patch.dict(sys.modules, {"gi": gi, "gi.repository": repo}):
            sys.modules.pop("desktop_recorder.capture", None)
            return importlib.import_module("desktop_recorder.capture")
    finally:
        # Keep "from desktop_recorder import capture" in other tests on the real module.
        if old_attr is missing:
            if hasattr(package, "capture"):
                delattr(package, "capture")
        else:
            package.capture = old_attr


class FakeUi:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def notify(self, _title: str, body: str, _timeout_ms: int) -> None:
        self.notes.append(body)

    def refresh(self) -> None:
        pass

    def play(self, _up: bool) -> None:
        pass

    def present_token(self) -> str:
        return ""


class FakePump:
    def __init__(self, seq: int | None) -> None:
        self.seq = seq
        self.stopped = False

    def latest(self) -> Any:
        if self.seq is None:
            return None
        return SimpleNamespace(seq=self.seq, width=1280, height=720)

    def stop(self) -> None:
        self.stopped = True


class FakeCastTransport:
    def __init__(self) -> None:
        self.closed: list[str] = []
        self.cancelled = False

    def close_session(self, session: str) -> None:
        self.closed.append(session)

    def cancel(self) -> None:
        self.cancelled = True


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.capture = import_capture()

    def setUp(self) -> None:
        FakeGLib.idle_calls = []
        self.ui = FakeUi()
        self.settings = Settings()
        self.saved: list[Settings] = []
        self.ctl = self.capture.Controller(self.ui, lambda: self.settings, self.saved.append, None, "ffmpeg")

    def make_cast(self, seqs: list[int | None]):
        cap = self.capture
        transport = FakeCastTransport()
        portal = SimpleNamespace(session=SESSION, fd=-1, restore_token="", streams=[])
        streams = []
        for i, seq in enumerate(seqs):
            info = SimpleNamespace(node_id=40 + i, position=(1280 * i, 0), size=None, source_type=1)
            streams.append(cap._Stream(info, FakePump(seq), SimpleNamespace(stop=lambda: None), -1))
        cast = cap._Cast(transport, portal, "select", "", streams=list(streams),
                         infos=[s.info for s in streams])
        self.ctl.cast = cast
        return cast, streams

    # Finding: a stream error before RECORDING must not leave a frozen stream in use.

    def test_error_before_recording_marks_stream(self) -> None:
        cast, (s0, s1) = self.make_cast([1, 1])
        self.ctl.state = self.capture.SELECTING
        self.ctl._stream_error(cast, s1, "bus error")
        self.assertEqual(s1.failed, "bus error")
        self.assertIsNone(s0.failed)
        self.assertEqual(len(cast.streams), 2, "indexes of the open selector must stay valid")

    def test_poll_drops_failed_streams(self) -> None:
        cast, (s0, s1) = self.make_cast([3, None])
        s1.failed = "size changed"
        self.ctl.state = self.capture.PORTAL
        cast.deadline = time.monotonic() + 30   # the poll must not wait for a failed stream
        opened: list = []
        self.ctl._wayland_open_selector = opened.append
        self.assertFalse(self.ctl._wayland_poll(cast))
        self.assertEqual(opened, [cast])
        self.assertEqual(cast.streams, [s0])
        self.assertTrue(s1.stopped)

    def test_poll_all_failed_shows_the_error(self) -> None:
        cast, (s0,) = self.make_cast([2])
        s0.failed = "pipewire error"
        self.ctl.state = self.capture.PORTAL
        cast.deadline = time.monotonic() + 30
        self.ctl._wayland_poll(cast)
        self.assertEqual(self.ctl.state, self.capture.IDLE)
        self.assertTrue(cast.closed)
        self.assertIsNone(self.ctl.cast)
        self.assertTrue(any("pipewire error" in note for note in self.ui.notes))

    def test_accept_on_failed_stream_fails(self) -> None:
        cast, (_s0, s1) = self.make_cast([1, 1])
        self.ctl.state = self.capture.SELECTING
        self.ctl._stream_error(cast, s1, "size changed")
        started: list = []
        self.ctl._wayland_start = lambda *a, **k: started.append((a, k))
        self.ctl._wayland_selected(cast, 1, Rect(0, 0, 100, 100), SelectorOptions(False, True, True))
        self.assertEqual(started, [])
        self.assertEqual(self.ctl.state, self.capture.IDLE)
        self.assertTrue(cast.closed)
        self.assertTrue(any("size changed" in note for note in self.ui.notes))

    # Findings: accept_seq is read before the selector windows go; the window size is kept.

    def test_before_close_sets_accept_seq_and_window_size(self) -> None:
        cast, (s0, s1) = self.make_cast([4, 7])
        self.ctl.state = self.capture.SELECTING
        self.capture.Controller._wayland_before_close(cast, 1, (1536, 864))
        s1.pump.seq = 9   # a frame that comes while the windows close
        started: list = []
        self.ctl._wayland_start = lambda *a, **k: started.append((a, k))
        self.ctl._wayland_selected(cast, 1, Rect(10, 20, 100, 50), SelectorOptions(False, True, True))
        self.assertEqual(len(started), 1)
        args, kwargs = started[0]
        self.assertIs(args[1], s1)
        self.assertEqual(kwargs["after_seq"], 7)
        self.assertEqual(s1.window_size, (1536, 864))
        self.assertTrue(s0.stopped)
        self.assertEqual(self.settings.wayland_region, (1280, 0, 10, 20, 100, 50))

    def test_before_close_bad_index_is_ignored(self) -> None:
        cast, (s0,) = self.make_cast([4])
        self.capture.Controller._wayland_before_close(cast, 3, (10, 10))
        self.assertIsNone(s0.accept_seq)

    # Finding: the portal session can close without a GStreamer error.

    def test_session_closed_while_portal(self) -> None:
        cast, _streams = self.make_cast([None])
        self.ctl.state = self.capture.PORTAL
        self.ctl._portal_closed_soon(cast)
        fn, args = FakeGLib.idle_calls[-1]
        fn(*args)
        self.assertEqual(self.ctl.state, self.capture.IDLE)
        self.assertTrue(cast.closed)
        self.assertIn(messages.CAST_CLOSED, self.ui.notes)

    def test_session_closed_while_selecting(self) -> None:
        cast, streams = self.make_cast([1, 1])
        self.ctl.state = self.capture.SELECTING
        self.ctl._portal_closed(cast)
        self.assertEqual([s.failed for s in streams], [messages.CAST_CLOSED] * 2)
        self.assertEqual(self.ctl.state, self.capture.SELECTING)

    def test_session_closed_after_our_close_is_ignored(self) -> None:
        cast, _streams = self.make_cast([1])
        self.ctl.state = self.capture.PORTAL
        cast.close()
        self.ctl._portal_closed(cast)
        self.assertEqual(self.ctl.state, self.capture.PORTAL)
        self.assertEqual(self.ui.notes, [])

    def test_session_closed_while_recording_stops(self) -> None:
        cast, (s0,) = self.make_cast([1])
        self.ctl.state = self.capture.RECORDING
        self.ctl.session = SimpleNamespace(cast=cast, stream=s0, error_text=None)
        stops: list = []
        self.ctl.stop = lambda *a, **k: stops.append(1)
        self.ctl._portal_closed(cast)
        self.assertEqual(stops, [1])
        self.assertEqual(self.ctl.session.error_text, messages.CAST_ENDED)

    # Finding: Exit during the portal dialog must end the nested loop.

    def test_stop_sync_cancels_the_portal_dialog(self) -> None:
        transport = FakeCastTransport()
        self.ctl._portal_transport = transport
        self.ctl.state = self.capture.PORTAL
        self.ctl.stop_sync()
        self.assertTrue(transport.cancelled)
        self.assertEqual(self.ctl.state, self.capture.IDLE)


if __name__ == "__main__":
    unittest.main()
