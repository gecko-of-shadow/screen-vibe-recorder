"""FFmpeg stats lines, the status text and the files of one recording.

Pure module: no gi, no Xlib, no cairo. Port of RecorderCore.TryParseProgress and
RecorderCore.FormatStats (DESIGN.md 3.2 and 6.3).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MAX_LINE = 8192


@dataclass
class FfmpegProgress:
    frames: int = 0
    dup: int = 0
    drop: int = 0


@dataclass
class RecordingStats:
    has_progress: bool
    frames: int
    dup: int
    drop: int
    file_bytes: int


@dataclass
class PumpCounters:
    received: int = 0     # buffers from the source
    superseded: int = 0   # buffers replaced before a tick used them (normal: the screen changes faster than fps)
    ticks: int = 0        # frames written to FFmpeg
    fresh: int = 0        # ticks that wrote a buffer for the first time
    repeats: int = 0      # ticks that wrote the same buffer again (still screen)
    late: int = 0         # ticks written 1 interval or more after their due time
    skipped: int = 0      # ticks not written because the writer was more than 2 s behind


class LineSplitter:
    """Splits text on CR or LF. FFmpeg ends its stats lines with a lone CR."""

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> list[str]:
        text = self._pending + chunk
        parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        # The last part has no line end yet. Keep it, but never more than MAX_LINE chars.
        self._pending = parts.pop()[:MAX_LINE]
        return [part[:MAX_LINE] for part in parts if part]

    def flush(self) -> list[str]:
        rest = self._pending
        self._pending = ""
        return [rest[:MAX_LINE]] if rest else []


def _is_ascii_number(val: str) -> bool:
    return bool(val) and val.isascii() and val.isdigit()


def parse_progress(line: str) -> FfmpegProgress | None:
    """Reads frame=, dup= and drop= from one FFmpeg stats line. Returns None for other lines."""
    if line is None:
        return None
    t = line.strip()
    if not t.startswith("frame="):
        return None
    progress = FfmpegProgress()
    saw_frame = False
    i = 0
    n = len(t)
    while i < n:
        eq = t.find("=", i)
        if eq < 0:
            break
        key_start = eq
        while key_start > i and t[key_start - 1] != " ":
            key_start -= 1
        key = t[key_start:eq]
        v = eq + 1
        while v < n and t[v] == " ":
            v += 1
        end = v
        while end < n and t[end] != " ":
            end += 1
        val = t[v:end]
        is_number = _is_ascii_number(val)
        if key == "frame":
            if not is_number:
                return None
            progress.frames = int(val)
            saw_frame = True
        elif key == "dup" and is_number:
            progress.dup = int(val)
        elif key == "drop" and is_number:
            progress.drop = int(val)
        i = end
    return progress if saw_frame else None


def mb_text(file_bytes: int) -> str:
    return f"{file_bytes / 1048576:.2f}"


def format_stats(stats: RecordingStats) -> str:
    mb = mb_text(stats.file_bytes)
    if not stats.has_progress:
        return f"Frames: unknown. File size: {mb} MB."
    real = max(0, stats.frames - stats.dup)
    return (
        f"Real frames: {real} of {stats.frames}. Duplicates: {stats.dup}. "
        f"Dropped: {stats.drop}. File size: {mb} MB."
    )


def _is_recording_name(name: str) -> bool:
    return name.startswith("desktop_") and name.endswith(".mp4")


def snapshot(folder: str) -> set[str]:
    """Paths of the desktop_*.mp4 files that are in the folder now."""
    found: set[str] = set()
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    for name in names:
        if _is_recording_name(name):
            found.add(os.path.join(folder, name))
    return found


def session_files(folder: str, before: set[str]) -> list[str]:
    """New desktop_*.mp4 files with a size above 0, sorted by path.lower()."""
    if not folder:
        return []
    skip = {os.path.normcase(path) for path in before}
    found: list[str] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    for name in names:
        if not _is_recording_name(name):
            continue
        path = os.path.join(folder, name)
        if os.path.normcase(path) in skip:
            continue
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                found.append(path)
        except OSError:
            continue
    found.sort(key=lambda path: path.lower())
    return found


def total_bytes(paths: list[str]) -> int:
    total = 0
    for path in paths:
        try:
            total += os.path.getsize(path)
        except OSError:
            continue
    return total


def x11_stats(progress: FfmpegProgress | None, file_bytes: int) -> RecordingStats:
    if progress is None:
        return RecordingStats(has_progress=False, frames=0, dup=0, drop=0, file_bytes=file_bytes)
    return RecordingStats(
        has_progress=True,
        frames=progress.frames,
        dup=progress.dup,
        drop=progress.drop,
        file_bytes=file_bytes,
    )


def wayland_stats(progress: FfmpegProgress | None, pump: PumpCounters, file_bytes: int) -> RecordingStats:
    frames = progress.frames if progress is not None else pump.ticks
    dup = (progress.dup if progress is not None else 0) + pump.late
    drop = (progress.drop if progress is not None else 0) + pump.skipped
    return RecordingStats(
        has_progress=progress is not None,
        frames=frames,
        dup=dup,
        drop=drop,
        file_bytes=file_bytes,
    )
