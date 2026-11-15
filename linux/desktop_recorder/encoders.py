"""NVENC probe (spec 5.5). Port of RecorderCore.HasNvencEncoder and TestNvencEncode.

This module is pure: it does not import gi, Xlib or cairo.
The probe does not use PDEATHSIG. The timeout ends it.
"""

from __future__ import annotations

import subprocess
import threading
from typing import Callable

LIST_ARGS = ["-hide_banner", "-encoders"]
PROBE_ARGS = ["-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=10",
              "-frames:v", "5", "-c:v", "h264_nvenc", "-f", "null", "-"]

NVENC = "h264_nvenc"
LIST_TIMEOUT = 5
PROBE_TIMEOUT = 15


def encoder_listed(listing: str, name: str) -> bool:
    """True when a line has a 1st token that starts with "V" and a 2nd token equal to name.

    A line looks like: " V....D h264_nvenc   NVIDIA NVENC H.264 encoder (codec h264)".
    This proves only that the FFmpeg build has the encoder, not that a GPU can run it.
    """
    if not listing:
        return False
    for line in listing.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V") and parts[1] == name:
            return True
    return False


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class NvencProbe:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self._runner = runner
        self._lock = threading.Lock()      # guards the cache
        self._probe_lock = threading.Lock()  # one probe at a time
        self._cache: dict[str, bool] = {}

    def _probe(self, ffmpeg: str) -> bool:
        try:
            listed = self._runner([ffmpeg] + LIST_ARGS, capture_output=True, text=True, timeout=LIST_TIMEOUT)
            if not encoder_listed(_text(listed.stdout) + "\n" + _text(listed.stderr), NVENC):
                return False
            result = self._runner([ffmpeg] + PROBE_ARGS, capture_output=True, timeout=PROBE_TIMEOUT)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def usable(self, ffmpeg: str) -> bool:
        """Cached for each ffmpeg path. Thread-safe. A second caller waits for the first probe."""
        with self._probe_lock:
            with self._lock:
                if ffmpeg in self._cache:
                    return self._cache[ffmpeg]
            ok = self._probe(ffmpeg)
            with self._lock:
                # mark_unusable can run while the probe runs. Its False wins.
                return self._cache.setdefault(ffmpeg, ok)

    def mark_unusable(self, ffmpeg: str) -> None:
        """Cache False until the app restarts."""
        with self._lock:
            self._cache[ffmpeg] = False

    def warm_up(self, ffmpeg: str) -> None:
        """Run usable() on a daemon thread, so the first start does not wait for the probe."""
        thread = threading.Thread(target=self.usable, args=(ffmpeg,), name="nvenc-probe", daemon=True)
        thread.start()
