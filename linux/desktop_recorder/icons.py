"""Tray icons: a port of TrayIcons.Draw (Windows). GUI module: it needs pycairo.

cairo loads inside the functions, so a pure import path does not load it.
"""

from __future__ import annotations

import math
import os

IDLE_NAME = "desktop-recorder-idle"
RECORDING_NAME = "desktop-recorder-recording"
FILE_SIZE = 64

_IDLE = (175, 220, 235)
_TOP_REC = (225, 120, 255)
_BOTTOM_REC = (80, 195, 255)
_RING_REC = (205, 175, 255)
_DOT_REC = (255, 40, 90)


def _rgb(ctx, color: tuple[int, int, int]) -> None:
    ctx.set_source_rgb(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0)


def _polyline(ctx, points: list[tuple[float, float]]) -> None:
    ctx.move_to(*points[0])
    for point in points[1:]:
        ctx.line_to(*point)
    ctx.stroke()


def draw_tray_icon(size: int, recording: bool):
    """Return a cairo.ImageSurface (ARGB32) with the tray icon. Same formulas and colors as Windows."""
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    ctx.set_operator(cairo.OPERATOR_CLEAR)
    ctx.paint()
    ctx.set_operator(cairo.OPERATOR_OVER)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)

    k = size / 16.0
    stroke = max(1.25, 1.3 * k)
    inset = 0.5 * stroke + 0.3 * k
    length = 4.6 * k
    far = size - inset
    top = _TOP_REC if recording else _IDLE
    bottom = _BOTTOM_REC if recording else _IDLE

    # Corner brackets with round caps.
    ctx.set_line_width(stroke)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_MITER)
    _rgb(ctx, top)
    _polyline(ctx, [(inset, inset + length), (inset, inset), (inset + length, inset)])
    _polyline(ctx, [(far - length, inset), (far, inset), (far, inset + length)])
    _rgb(ctx, bottom)
    _polyline(ctx, [(inset, far - length), (inset, far), (inset + length, far)])
    _polyline(ctx, [(far - length, far), (far, far), (far, far - length)])

    # Ring.
    c = size / 2.0
    ring = 4.3 * k
    ctx.set_line_width(max(1.0, 1.1 * k))
    _rgb(ctx, _RING_REC if recording else _IDLE)
    ctx.new_path()
    ctx.arc(c, c, ring, 0, 2 * math.pi)
    ctx.stroke()

    # Dot.
    dot = 2.9 * k if recording else 1.5 * k
    _rgb(ctx, _DOT_REC if recording else _IDLE)
    ctx.new_path()
    ctx.arc(c, c, dot, 0, 2 * math.pi)
    ctx.fill()
    surface.flush()
    return surface


def icon_dir(config: str) -> str:
    return os.path.join(config, "icons")


def icon_path(config: str, recording: bool) -> str:
    return os.path.join(icon_dir(config), (RECORDING_NAME if recording else IDLE_NAME) + ".png")


def write_icons(config: str) -> tuple[str, str]:
    """Write the idle and the recording icon (64 px PNG). Return (idle path, recording path)."""
    folder = icon_dir(config)
    os.makedirs(folder, exist_ok=True)
    paths = []
    for recording in (False, True):
        path = icon_path(config, recording)
        temporary = path + ".tmp"
        draw_tray_icon(FILE_SIZE, recording).write_to_png(temporary)
        os.replace(temporary, path)
        paths.append(path)
    return paths[0], paths[1]
