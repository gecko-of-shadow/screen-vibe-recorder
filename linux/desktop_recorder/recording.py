"""One FFmpeg process: start with PDEATHSIG, write raw frames, read stats, stop.

Pure module (DESIGN.md 6.1 and 6.2). It imports on Windows too: the Linux-only
parts (libc prctl) load only on Linux, and the spawn raises on other systems.
"""

from __future__ import annotations

import codecs
import ctypes
import functools
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from .ffstats import FfmpegProgress, LineSplitter, parse_progress

# Resolved at import, before any fork. CDLL(None) raises on Windows, so guard it.
_libc = ctypes.CDLL(None, use_errno=True) if sys.platform.startswith("linux") else None
_PR_SET_PDEATHSIG = 1

ERROR_TEXT_LIMIT = 2000


def _child_setup(parent_pid: int) -> None:
    # Runs in the child after fork, before exec. Call only prctl and getppid here.
    _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    if os.getppid() != parent_pid:
        os._exit(1)


def popen_with_pdeathsig(argv: list[str], **kwargs: Any) -> subprocess.Popen:
    """Starts a process that gets SIGTERM when the thread that started it ends.

    Linux sends the signal when the forking thread ends, so only the main thread may call this.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("FFmpeg must start on the main thread.")
    if _libc is None:
        raise RuntimeError("FFmpeg start with PDEATHSIG needs Linux.")
    return subprocess.Popen(argv, preexec_fn=functools.partial(_child_setup, os.getpid()), **kwargs)


def write_all(stream: Any, data: bytes) -> None:
    """Writes all bytes. An unbuffered FileIO can write fewer bytes than asked in one call."""
    mv = memoryview(data)
    while mv:
        n = stream.write(mv)
        if n is None:
            n = 0
        mv = mv[n:]


class FfmpegProcess:
    def __init__(self, argv: list[str], on_exit: Callable[[int, str], None] | None = None) -> None:
        self.argv = list(argv)
        self.on_exit = on_exit
        self.pid: int | None = None
        self.started_at: float = 0.0
        self.stopping: bool = False
        self._proc: subprocess.Popen | None = None
        self._stdin: Any = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._progress: FfmpegProgress | None = None
        self._errors: list[str] = []
        self._error_chars = 0

    # Start (main thread only)

    def start(self) -> str | None:
        """Starts FFmpeg. Returns an error text, or None when FFmpeg runs."""
        try:
            proc = popen_with_pdeathsig(
                self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            return f"Cannot start ffmpeg: {exc}"
        self._proc = proc
        self._stdin = proc.stdin
        self.pid = proc.pid
        self.started_at = time.monotonic()
        self._reader = threading.Thread(target=self._read_stderr, args=(proc,), name="ffmpeg-stderr", daemon=True)
        self._reader.start()
        return None

    # Input

    def write(self, data: bytes) -> None:
        """Writes all bytes to FFmpeg stdin. Raises BrokenPipeError or OSError."""
        with self._write_lock:
            stdin = self._stdin
            if stdin is None:
                raise BrokenPipeError("FFmpeg is not running.")
            try:
                write_all(stdin, data)
            except ValueError as exc:  # write on a closed file
                raise BrokenPipeError(str(exc)) from exc

    def _close_stdin(self) -> None:
        # Do not take the write lock: a writer can be blocked in write() when FFmpeg stalls.
        stdin = self._stdin
        self._stdin = None
        if stdin is None:
            return
        try:
            stdin.close()
        except Exception:
            pass

    # Stop (blocking; call it off the main thread)

    def request_stop(self, fps: float, use_q: bool = True) -> None:
        self.stopping = True
        proc = self._proc
        if proc is None:
            return
        if use_q:
            try:
                self.write(b"q")
            except (OSError, ValueError):
                pass
        else:
            self._close_stdin()
        wait_s = min(15.0, 4.0 + 2.0 / max(0.2, fps))
        try:
            proc.wait(timeout=wait_s)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(10)
        self._close_pipes(proc)

    def _close_pipes(self, proc: subprocess.Popen) -> None:
        self._close_stdin()
        for stream in (proc.stderr, proc.stdout):
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                pass

    # Output

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        splitter = LineSplitter()
        stream = proc.stderr
        try:
            if stream is not None:
                fd = stream.fileno()
                while True:
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    for line in splitter.feed(decoder.decode(chunk)):
                        self._take_line(line)
                for line in splitter.feed(decoder.decode(b"", final=True)):
                    self._take_line(line)
        except (OSError, ValueError):
            pass
        for line in splitter.flush():
            self._take_line(line)
        try:
            code = proc.wait()
        except Exception:
            code = proc.returncode if proc.returncode is not None else -1
        callback = self.on_exit
        if callback is not None:
            try:
                callback(code, self.error_text())
            except Exception as exc:
                sys.stderr.write(f"Desktop Recorder: on_exit failed: {exc}\n")

    def _take_line(self, line: str) -> None:
        value = parse_progress(line)
        with self._lock:
            if value is not None:
                self._progress = value
            elif self._error_chars < ERROR_TEXT_LIMIT:
                self._errors.append(line)
                self._error_chars += len(line) + 1

    def progress(self) -> FfmpegProgress | None:
        with self._lock:
            value = self._progress
        if value is None:
            return None
        return FfmpegProgress(value.frames, value.dup, value.drop)

    def error_text(self) -> str:
        with self._lock:
            text = "\n".join(self._errors)
        return text[:ERROR_TEXT_LIMIT].strip()

    def first_error_line(self) -> str:
        for line in self.error_text().split("\n"):
            if line.strip():
                return line.strip()
        return ""

    def is_running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None
