"""single_instance.py (DESIGN.md 8.4, 14.1).

The pure tests run on any OS. The socket tests need AF_UNIX.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

try:
    import linux_skip  # noqa: E402
except ImportError:  # tests/linux_skip.py (owner C8) is not there yet: same rule, local copy.
    import types

    linux_skip = types.ModuleType("linux_skip")
    linux_skip.REQUIRE = os.environ.get("DESKTOP_RECORDER_REQUIRE_GUI") == "1"

    def _need(ok: bool, reason: str) -> None:
        if ok:
            return
        if linux_skip.REQUIRE:
            raise AssertionError("Required for this test: " + reason)
        raise unittest.SkipTest(reason)

    def _need_af_unix() -> None:
        _need(hasattr(socket, "AF_UNIX"), "AF_UNIX sockets")

    linux_skip.need = _need
    linux_skip.need_af_unix = _need_af_unix

from desktop_recorder import single_instance  # noqa: E402
from desktop_recorder.single_instance import (  # noqa: E402
    BUSY,
    InstanceServer,
    is_reachable,
    parse_command,
    send_command,
    socket_path,
)


class PureTests(unittest.TestCase):
    def test_runtime_dir_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = os.path.join(tmp, "run")
            os.makedirs(run)
            cfg = os.path.join(tmp, "cfg")
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": run, "XDG_CONFIG_HOME": cfg}):
                self.assertEqual(socket_path(), os.path.join(run, "desktop-recorder", "control.sock"))
            # A runtime dir that is not a folder is not used.
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": os.path.join(tmp, "missing"),
                                              "XDG_CONFIG_HOME": cfg}):
                self.assertEqual(socket_path(), os.path.join(cfg, "DesktopRecorder", "control.sock"))
            env = dict(os.environ)
            env.pop("XDG_RUNTIME_DIR", None)
            env["XDG_CONFIG_HOME"] = cfg
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(socket_path(), os.path.join(cfg, "DesktopRecorder", "control.sock"))

    def test_parse_command(self) -> None:
        self.assertEqual(parse_command("TOGGLE"), ("TOGGLE", ""))
        self.assertEqual(parse_command("TOGGLE abc"), ("TOGGLE", "abc"))
        self.assertEqual(parse_command(" STATUS\n"), ("STATUS", ""))
        self.assertEqual(parse_command(""), ("", ""))

    def test_busy_rule_without_socket(self) -> None:
        # The wait and BUSY rule is in handle(); it needs no socket.
        server = InstanceServer("unused", lambda text: "SELECTING", schedule=lambda job: None, wait=0.2)
        start = time.monotonic()
        self.assertEqual(server.handle("TOGGLE"), BUSY)
        self.assertGreaterEqual(time.monotonic() - start, 0.15)

    def test_schedule_on_other_thread_without_socket(self) -> None:
        seen: list[str] = []

        def schedule(job) -> None:
            threading.Thread(target=job, daemon=True).start()

        def on_command(text: str) -> str:
            seen.append(threading.current_thread().name)
            return "STOPPED"

        server = InstanceServer("unused", on_command, schedule=schedule, wait=2.0)
        self.assertEqual(server.handle("STATUS"), "STOPPED")
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(seen[0], threading.current_thread().name)

    def test_unreachable_path_without_server(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "control.sock")
            self.assertFalse(is_reachable(path))
            self.assertIsNone(send_command(path, "STATUS"))


class SocketTests(unittest.TestCase):
    def setUp(self) -> None:
        linux_skip.need_af_unix()
        self._tmp = tempfile.TemporaryDirectory()
        # A short path: AF_UNIX paths are limited to about 108 bytes.
        self.path = os.path.join(self._tmp.name, "c.sock")
        self.servers: list[InstanceServer] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.stop()
        self._tmp.cleanup()

    def _serve(self, on_command, schedule=None, wait: float = 5.0) -> InstanceServer:
        server = InstanceServer(self.path, on_command, schedule=schedule, wait=wait)
        self.assertTrue(server.start())
        self.servers.append(server)
        return server

    def test_toggle_token_command(self) -> None:
        got: list[str] = []

        def on_command(text: str) -> str:
            got.append(text)
            verb, token = parse_command(text)
            return "SELECTING" if verb == "TOGGLE" else "?"

        self._serve(on_command)
        self.assertEqual(send_command(self.path, "TOGGLE tok-123"), "SELECTING")
        self.assertEqual(parse_command(got[-1]), ("TOGGLE", "tok-123"))

    def test_status_command(self) -> None:
        self._serve(lambda text: "STOPPED" if parse_command(text)[0] == "STATUS" else "?")
        self.assertEqual(send_command(self.path, "STATUS"), "STOPPED")

    def test_512_byte_limit(self) -> None:
        lengths: list[int] = []

        def on_command(text: str) -> str:
            lengths.append(len(text))
            return "STOPPED"

        self._serve(on_command)
        reply = send_command(self.path, "TOGGLE " + "x" * 2000)
        self.assertEqual(reply, "STOPPED")
        self.assertLessEqual(lengths[0], 512)

    def test_busy_reply_after_wait(self) -> None:
        self._serve(lambda text: "STOPPED", schedule=lambda job: None, wait=0.2)
        self.assertEqual(send_command(self.path, "STATUS"), BUSY)

    def test_schedule_runs_job(self) -> None:
        def schedule(job) -> None:
            threading.Thread(target=job, daemon=True).start()

        self._serve(lambda text: "RECORDING", schedule=schedule)
        self.assertEqual(send_command(self.path, "STATUS"), "RECORDING")

    def test_is_reachable_false_for_stale_file(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.path)
        sock.close()  # the file stays, no server listens
        self.assertTrue(os.path.exists(self.path))
        self.assertFalse(is_reachable(self.path))
        # A new server takes over the stale file.
        self._serve(lambda text: "STOPPED")
        self.assertTrue(is_reachable(self.path))

    def test_second_server_loses(self) -> None:
        self._serve(lambda text: "STOPPED")
        other = InstanceServer(self.path, lambda text: "X")
        self.assertFalse(other.start())

    def test_old_call_shape(self) -> None:
        server = single_instance.InstanceServer(self.path, lambda text: "OK " + text)
        self.assertTrue(server.start())
        self.servers.append(server)
        self.assertEqual(single_instance.send_command(self.path, "PING"), "OK PING")


if __name__ == "__main__":
    unittest.main()
