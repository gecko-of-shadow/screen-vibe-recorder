"""One tray process per user. A second start sends a command over a socket (DESIGN.md 8.4).

Pure module: it imports on Windows too. AF_UNIX is used inside functions only.
"""

from __future__ import annotations

import os
import socket
import threading
from collections.abc import Callable

from .settings import config_dir, runtime_dir

READ_LIMIT = 512
CLIENT_TIMEOUT = 6.0
SERVER_WAIT = 5.0
BUSY = "BUSY"
SOCKET_NAME = "control.sock"


def socket_path() -> str:
    """$XDG_RUNTIME_DIR/desktop-recorder/control.sock, else config_dir()/control.sock."""
    return os.path.join(runtime_dir(), SOCKET_NAME)


def parse_command(text: str) -> tuple[str, str]:
    """Return (verb, token). Strip the text, then split it on the first space."""
    stripped = (text or "").strip()
    verb, _sep, rest = stripped.partition(" ")
    return verb, rest.strip()


def _unix_socket() -> socket.socket:
    family = getattr(socket, "AF_UNIX", None)
    if family is None:
        raise OSError("AF_UNIX sockets are not available on this system.")
    return socket.socket(family, socket.SOCK_STREAM)


def is_reachable(path: str) -> bool:
    """True when a live server accepts a connection on this path."""
    if not os.path.exists(path):
        return False
    try:
        sock = _unix_socket()
    except OSError:
        return False
    sock.settimeout(0.2)
    try:
        sock.connect(path)
        return True
    except OSError:
        return False
    finally:
        sock.close()


# The old private name. Keep it for old callers.
_reachable = is_reachable


def send_command(path: str, command: str, timeout: float = CLIENT_TIMEOUT) -> str | None:
    """Send one command. Return the reply, or None when no server answers in time."""
    if not is_reachable(path):
        return None
    try:
        sock = _unix_socket()
    except OSError:
        return None
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall((command.strip() + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        total = 0
        while total < READ_LIMIT:
            data = sock.recv(READ_LIMIT - total)
            if not data:
                break
            chunks.append(data)
            total += len(data)
            if b"\n" in data:
                break
        reply = b"".join(chunks).decode("utf-8", errors="replace").strip()
        return reply or None
    except OSError:
        return None
    finally:
        sock.close()


def _make_private_folder(directory: str) -> None:
    """Make the socket folder. Set mode 0700, but never on config_dir()."""
    if not directory:
        return
    if os.path.normpath(directory) == os.path.normpath(config_dir()):
        os.makedirs(directory, exist_ok=True)
        return
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


class InstanceServer:
    """Socket server. on_command(text) gives the reply.

    With schedule set, the server thread gives a job to schedule() (the tray uses
    GLib.idle_add, so on_command runs on the main thread). It waits `wait` s for the
    job. If the job does not finish in time, the reply is BUSY.
    With schedule None, the server thread runs the job itself.
    """

    def __init__(
        self,
        path: str,
        on_command: Callable[[str], str],
        schedule: Callable[[Callable[[], None]], None] | None = None,
        wait: float = SERVER_WAIT,
    ) -> None:
        self.path = path
        self._on_command = on_command
        self._schedule = schedule
        self._wait = wait
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    def start(self) -> bool:
        """Return False when another live instance already owns the socket."""
        self._stop.clear()
        _make_private_folder(os.path.dirname(self.path))
        if is_reachable(self.path):
            return False
        if os.path.exists(self.path):
            os.unlink(self.path)
        sock = _unix_socket()
        sock.bind(self.path)
        os.chmod(self.path, 0o600)
        sock.listen(4)
        sock.settimeout(0.3)
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, name="desktop-recorder-socket", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(2)
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def handle(self, text: str) -> str:
        """Run one command with the schedule and wait rules. Return the reply."""
        done = threading.Event()
        box: dict[str, str] = {}

        def job() -> None:
            try:
                box["reply"] = str(self._on_command(text))
            except Exception as exc:  # noqa: BLE001 - a bad command must not kill the server
                box["reply"] = "ERROR " + str(exc)
            finally:
                done.set()

        if self._schedule is None:
            job()
        else:
            try:
                self._schedule(job)
            except Exception:  # noqa: BLE001
                return BUSY
        if not done.wait(self._wait):
            return BUSY
        return box.get("reply", BUSY)

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()  # type: ignore[union-attr]
            except (socket.timeout, OSError):
                continue
            try:
                conn.settimeout(2.0)
                data = conn.recv(READ_LIMIT).decode("utf-8", errors="replace").strip()
                # A liveness probe connects and closes without a command.
                if not data:
                    continue
                reply = self.handle(data)
                conn.sendall((reply + "\n").encode("utf-8"))
            except Exception:  # noqa: BLE001
                pass
            finally:
                conn.close()
