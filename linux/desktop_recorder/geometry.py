"""Pure rectangle math for the selector, the recording frame and the Wayland mapping.

All values are integer pixels unless a function says something different.
This module imports no GUI library, so it runs on Windows Python too.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "Rect",
    "EMPTY",
    "inclusive_rect",
    "square_point",
    "make_even",
    "accept_rect",
    "monitor_at",
    "is_on_monitors",
    "border_thickness",
    "BorderLayout",
    "border_layout",
    "stop_rect",
    "label_rect",
    "magnifier_rect",
    "DrawMap",
    "fit_image",
    "widget_to_image",
    "image_to_widget",
    "stream_to_layout",
]


@dataclass(frozen=True)
class Rect:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    @property
    def right(self) -> int:
        return self.x + self.w  # exclusive

    @property
    def bottom(self) -> int:
        return self.y + self.h  # exclusive

    @property
    def is_empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def intersect(self, other: "Rect") -> "Rect":
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        x1, y1 = min(self.right, other.right), min(self.bottom, other.bottom)
        if x1 <= x0 or y1 <= y0:
            return Rect()
        return Rect(x0, y0, x1 - x0, y1 - y0)

    def intersects(self, other: "Rect") -> bool:
        return not self.intersect(other).is_empty


EMPTY = Rect()


def _ltrb(left: int, top: int, right: int, bottom: int) -> Rect:
    return Rect(left, top, right - left, bottom - top)


def _clamp(value: int, low: int, high: int) -> int:
    # Same order as C# Math.Max(low, Math.Min(value, high)): low wins when high < low.
    return max(low, min(value, high))


# ---------------------------------------------------------------- selector


def inclusive_rect(ax: int, ay: int, bx: int, by: int) -> Rect:
    """The rectangle that holds both points, with both points inside."""
    return Rect(min(ax, bx), min(ay, by), abs(bx - ax) + 1, abs(by - ay) + 1)


def square_point(ax: int, ay: int, bx: int, by: int) -> tuple[int, int]:
    """The end point of a square drag from (ax, ay) toward (bx, by)."""
    dx = bx - ax
    dy = by - ay
    side = max(abs(dx), abs(dy))
    return (ax + (-side if dx < 0 else side), ay + (-side if dy < 0 else side))


def make_even(r: Rect) -> Rect:
    """Shrink the width and the height to even values (never grow). EMPTY if too small."""
    if r.is_empty:
        return EMPTY
    w = r.w & ~1
    h = r.h & ~1
    if w < 2 or h < 2:
        return EMPTY
    return Rect(r.x, r.y, w, h)


def accept_rect(r: Rect | None, bounds: Rect) -> Rect | None:
    """Clip to the bounds and make even. None when nothing is left."""
    if r is None:
        return None
    even = make_even(r.intersect(bounds))
    if even.is_empty:
        return None
    return even


def monitor_at(px: int, py: int, monitors: list[Rect]) -> Rect | None:
    for m in monitors:
        if m.contains(px, py):
            return m
    return None


def is_on_monitors(r: Rect, monitors: list[Rect]) -> bool:
    """True when the monitors cover the full rectangle. Monitors do not overlap."""
    area = r.w * r.h
    if r.is_empty or area <= 0:
        return False
    covered = 0
    for m in monitors:
        part = r.intersect(m)
        covered += part.w * part.h
    return covered >= area


# ---------------------------------------------------------------- recording frame


def border_thickness(scale: float) -> int:
    return max(2, int(round(2 * scale)))


@dataclass
class BorderLayout:
    sides: list[Rect | None]  # top, bottom, left, right; None = not drawn
    outer: Rect
    omitted: list[str] = field(default_factory=list)  # names from "top", "bottom", "left", "right"


def border_layout(region: Rect, t: int, monitors: list[Rect], gap: int = 0) -> BorderLayout:
    """Port of ComputeBorderRects, with a gap. Linux never draws inside the region."""
    g = gap
    x, y, w, h = region.x, region.y, region.w, region.h
    right, bottom = region.right, region.bottom

    # 1. Test each side with its strip, before any corner extension.
    top_on = is_on_monitors(Rect(x, y - g - t, w, t), monitors)
    bottom_on = is_on_monitors(Rect(x, bottom + g, w, t), monitors)
    left_on = is_on_monitors(Rect(x - g - t, y, t, h), monitors)
    right_on = is_on_monitors(Rect(right + g, y, t, h), monitors)

    # 2. Outer edge: grow only on the present sides.
    outer = _ltrb(
        x - (g + t if left_on else 0),
        y - (g + t if top_on else 0),
        right + (g + t if right_on else 0),
        bottom + (g + t if bottom_on else 0),
    )

    # 3. Sides. Top and bottom span the outer edge from left to right.
    y0 = y - g if top_on else y
    y1 = bottom + g if bottom_on else bottom
    candidates = [
        ("top", top_on, Rect(outer.x, y - g - t, outer.w, t)),
        ("bottom", bottom_on, Rect(outer.x, bottom + g, outer.w, t)),
        ("left", left_on, Rect(x - g - t, y0, t, y1 - y0)),
        ("right", right_on, Rect(right + g, y0, t, y1 - y0)),
    ]
    sides: list[Rect | None] = []
    omitted: list[str] = []
    for name, present, rect in candidates:
        if present:
            sides.append(rect)
        else:
            sides.append(None)
            omitted.append(name)
    return BorderLayout(sides=sides, outer=outer, omitted=omitted)


def stop_rect(region: Rect, outer: Rect, monitor: Rect, work_area: Rect,
              monitors: list[Rect], scale: float) -> Rect | None:
    """Port of ComputeStopRect steps 1 to 3. None when the button has no place outside the region."""
    w = int(round(84 * scale))
    h = int(round(28 * scale))
    gap = int(round(4 * scale))
    if work_area.is_empty:
        work_area = monitor

    # C# integer division truncates toward zero. int() does the same.
    x = region.x + int((region.w - w) / 2)
    x = _clamp(x, work_area.x, work_area.right - w)

    # Step 1: below the outer edge.
    below = outer.bottom + gap
    if below + h <= work_area.bottom and below >= work_area.y:
        return Rect(x, below, w, h)

    # Step 2: above the outer edge.
    above = outer.y - gap - h
    if above >= work_area.y and above + h <= work_area.bottom:
        return Rect(x, above, w, h)

    # Step 3: top center of another monitor that does not touch the region.
    for m in monitors:
        if m.intersects(region) or m.w < w or m.h < h + gap:
            continue
        return Rect(m.x + (m.w - w) // 2, m.y + gap, w, h)

    return None


# ---------------------------------------------------------------- selector layout


def label_rect(target: Rect, box_w: int, box_h: int, bounds: Rect) -> Rect:
    """Size label above the target, else just inside its top edge. Clamped to the bounds."""
    x = target.x
    y = target.y - box_h - 8
    if y < bounds.y:
        y = target.y + 8
    x = _clamp(x, bounds.x, bounds.right - box_w)
    y = _clamp(y, bounds.y, bounds.bottom - box_h)
    return Rect(x, y, box_w, box_h)


def magnifier_rect(cx: int, cy: int, box_w: int, box_h: int, monitor: Rect) -> Rect:
    """Magnifier box down-right of the cursor. Flip on an axis where it leaves the monitor."""
    x = cx + 24
    y = cy + 24
    if x + box_w > monitor.right:
        x = cx - 24 - box_w
    if y + box_h > monitor.bottom:
        y = cy - 24 - box_h
    x = _clamp(x, monitor.x, monitor.right - box_w)
    y = _clamp(y, monitor.y, monitor.bottom - box_h)
    return Rect(x, y, box_w, box_h)


# ---------------------------------------------------------------- widget and image mapping


@dataclass(frozen=True)
class DrawMap:
    ox: float
    oy: float
    dw: float
    dh: float
    iw: int
    ih: int


def fit_image(widget_w: float, widget_h: float, iw: int, ih: int) -> DrawMap:
    """Where an iw x ih image goes in the widget. Same aspect (1%): fill. Else letterbox, centered."""
    if widget_w <= 0 or widget_h <= 0 or iw <= 0 or ih <= 0:
        return DrawMap(0.0, 0.0, float(max(widget_w, 0)), float(max(widget_h, 0)), iw, ih)
    image_aspect = iw / ih
    if abs(widget_w / widget_h - image_aspect) <= 0.01 * image_aspect:
        return DrawMap(0.0, 0.0, float(widget_w), float(widget_h), iw, ih)
    s = min(widget_w / iw, widget_h / ih)
    dw = iw * s
    dh = ih * s
    return DrawMap((widget_w - dw) / 2.0, (widget_h - dh) / 2.0, dw, dh, iw, ih)


def _to_image_axis(p: float, o: float, d: float, size: int) -> int:
    if size <= 0:
        return 0
    if d <= 0:
        return 0
    v = math.floor((p - o) * size / d)
    return max(0, min(int(v), size - 1))


def widget_to_image(px: float, py: float, m: DrawMap) -> tuple[int, int]:
    return (_to_image_axis(px, m.ox, m.dw, m.iw), _to_image_axis(py, m.oy, m.dh, m.ih))


def image_to_widget(ix: float, iy: float, m: DrawMap) -> tuple[float, float]:
    sx = m.dw / m.iw if m.iw > 0 else 0.0
    sy = m.dh / m.ih if m.ih > 0 else 0.0
    return (m.ox + ix * sx, m.oy + iy * sy)


def stream_to_layout(r: Rect, position: tuple[int, int], logical: tuple[int, int],
                     stream: tuple[int, int]) -> tuple[float, float, float, float]:
    """A crop in stream px to (x, y, w, h) in logical layout px."""
    sx = stream[0] / logical[0]
    sy = stream[1] / logical[1]
    return (position[0] + r.x / sx, position[1] + r.y / sy, r.w / sx, r.h / sy)
