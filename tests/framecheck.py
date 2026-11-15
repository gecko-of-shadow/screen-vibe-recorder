"""Helpers for the Xvfb GUI tests: read frames and the screen as RGB, and probe MP4 files.

This module only runs programs (ffmpeg, ffprobe). It imports no gi and no Xlib.
"""

from __future__ import annotations

import subprocess

STATS_RE = r"Real frames: (\d+) of (\d+)\. Duplicates: (\d+)\. Dropped: (\d+)\. File size: [0-9.]+ MB\."
PLAN_RE = r"Desktop Recorder: plan (\S+) (\S+)"


def _read_ppm(data: bytes) -> tuple[int, int, bytes]:
    """Parse one binary PPM (P6, maxval 255). Return width, height and the RGB bytes."""
    fields: list[bytes] = []
    pos = 0
    while len(fields) < 4:
        # Skip white space and comments.
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            while pos < len(data) and data[pos:pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        if start == pos:
            raise ValueError("The PPM header is not complete.")
        fields.append(data[start:pos])
    if fields[0] != b"P6" or fields[3] != b"255":
        raise ValueError("The picture is not a P6 PPM with maxval 255.")
    width, height = int(fields[1]), int(fields[2])
    pos += 1  # one white space character after maxval
    pixels = data[pos:pos + width * height * 3]
    if len(pixels) != width * height * 3:
        raise ValueError("The PPM data is too short.")
    return width, height, pixels


def _run_ppm(argv: list[str]) -> tuple[int, int, bytes]:
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if done.returncode != 0 or not done.stdout:
        raise RuntimeError("ffmpeg failed: " + done.stderr.decode("utf-8", "replace").strip())
    return _read_ppm(done.stdout)


def frame_rgb(path: str, index: int) -> tuple[int, int, bytes]:
    """Decode frame number `index` (0 = first) of a video as RGB."""
    return _run_ppm([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
        "-vf", f"select=eq(n\\,{index})", "-fps_mode", "passthrough", "-frames:v", "1",
        "-f", "image2pipe", "-c:v", "ppm", "-pix_fmt", "rgb24", "-",
    ])


def screen_rgb(display: str) -> tuple[int, int, bytes]:
    """Grab one frame of the whole X screen with x11grab, as RGB."""
    target = display if "." in display.rsplit(":", 1)[-1] else display + ".0"
    return _run_ppm([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
        "-i", target, "-frames:v", "1", "-f", "image2pipe", "-c:v", "ppm", "-pix_fmt", "rgb24", "-",
    ])


def pixel(w: int, data: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * w + x) * 3
    return data[i], data[i + 1], data[i + 2]


def near(a: tuple[int, int, int], b: tuple[int, int, int], tol: int = 24) -> bool:
    return all(abs(int(p) - int(q)) <= tol for p, q in zip(a, b))


def count_near(w: int, h: int, data: bytes, color: tuple[int, int, int], tol: int = 24) -> int:
    """Count the pixels of a picture that are near `color`."""
    total = 0
    for i in range(0, w * h * 3, 3):
        if near((data[i], data[i + 1], data[i + 2]), color, tol):
            total += 1
    return total


def _probe(path: str, extra: list[str]) -> str:
    done = subprocess.run(
        ["ffprobe", "-v", "error"] + extra + ["-of", "default=nw=1:nk=1", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError("ffprobe failed: " + done.stderr.strip())
    return done.stdout.strip()


def count_frames(path: str) -> int:
    out = _probe(path, ["-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames"])
    return int(out.splitlines()[0])


def probe_size(path: str) -> tuple[int, int]:
    out = _probe(path, ["-select_streams", "v:0", "-show_entries", "stream=width,height"])
    lines = out.splitlines()
    return int(lines[0]), int(lines[1])


def probe_duration(path: str) -> float:
    out = _probe(path, ["-show_entries", "format=duration"])
    return float(out.splitlines()[0])
