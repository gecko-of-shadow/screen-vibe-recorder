"""Pure state machine of the region selector (port of the Windows RegionSelector input rules).

All coordinates are image px. The GTK view (selector_gtk.py) sends mouse and key events
to this model and acts on the Outcome. This module imports no GUI library.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Rect, accept_rect, inclusive_rect, monitor_at, square_point

__all__ = ["SelectorOptions", "Outcome", "SelectorModel", "DRAG_THRESHOLD"]

# A move of more than this many px after a press starts a drag (Windows DragThreshold).
DRAG_THRESHOLD = 3


@dataclass
class SelectorOptions:
    crosshair: bool
    magnifier: bool
    position: bool


@dataclass
class Outcome:
    kind: str                 # "none" | "redraw" | "accept" | "cancel" | "warp"
    rect: Rect | None = None  # for "accept": clipped and even
    # For "warp": the applied (clamped) move. The model cursor is already at the target.
    # The shell warps the pointer to model.cursor. It must not add dx, dy again.
    dx: int = 0
    dy: int = 0


_NONE = "none"
_REDRAW = "redraw"


class SelectorModel:
    def __init__(self, bounds: Rect, monitors: list[Rect], windows: list[Rect],
                 options: SelectorOptions) -> None:
        self.bounds = bounds
        self.monitors = list(monitors)
        self.windows = list(windows)  # top-to-bottom order; empty on Wayland
        # C, M, P change this object in place (the caller's object, not a copy).
        # The shell saves it on close. Wayland windows can share one object.
        self.options = options
        self.cursor: tuple[int, int] = (bounds.x, bounds.y)
        self.selection: Rect | None = None
        self.hover: Rect | None = None
        self.mode: str = "hover"  # "hover" | "pending" | "creating"
        self._anchor: tuple[int, int] = self.cursor
        self._prev: Rect | None = None
        self._last: tuple[int, int] = self.cursor

    # ------------------------------------------------------------ helpers

    def _window_at(self, x: int, y: int) -> Rect | None:
        for w in self.windows:
            if w.contains(x, y):
                return w
        return None

    def _update_hover(self) -> None:
        self.hover = self._window_at(*self.cursor)

    def _update_creating(self, shift: bool, ctrl: bool) -> None:
        ax, ay = self._anchor
        cx, cy = self.cursor
        if ctrl:
            lx, ly = self._last
            ax, ay = ax + cx - lx, ay + cy - ly
            self._anchor = (ax, ay)
        ex, ey = square_point(ax, ay, cx, cy) if shift else (cx, cy)
        r = inclusive_rect(ax, ay, ex, ey).intersect(self.bounds)
        self.selection = None if r.is_empty else r

    def _accept(self, r: Rect | None) -> Outcome:
        a = accept_rect(r, self.bounds)
        if a is None:
            return Outcome(_NONE)
        return Outcome("accept", rect=a)

    # ------------------------------------------------------------ mouse

    def press(self, x: int, y: int, button: int) -> Outcome:
        if button == 3:
            self.cursor = (x, y)
            self._last = (x, y)
            if self.mode in ("pending", "creating"):
                # Cancel the drag. Go back to the selection from before the press. Stay open.
                self.selection = self._prev
                self.mode = "hover"
            elif self.selection is not None:
                self.selection = None
            else:
                return Outcome("cancel")
            self._update_hover()
            return Outcome(_REDRAW)

        if button != 1:
            return Outcome(_NONE)

        self.cursor = (x, y)
        self._last = (x, y)
        self._update_hover()
        self.mode = "pending"
        self._anchor = (x, y)
        self._prev = self.selection
        return Outcome(_REDRAW)

    def motion(self, x: int, y: int, shift: bool, ctrl: bool) -> Outcome:
        self.cursor = (x, y)
        if self.mode == "pending":
            ax, ay = self._anchor
            if abs(x - ax) > DRAG_THRESHOLD or abs(y - ay) > DRAG_THRESHOLD:
                self.mode = "creating"
                self.hover = None
                self._update_creating(shift, False)  # Ctrl is ignored on this move
        elif self.mode == "creating":
            self._update_creating(shift, ctrl)
        else:
            self._update_hover()
        self._last = (x, y)
        return Outcome(_REDRAW)

    def release(self, x: int, y: int, button: int) -> Outcome:
        if button != 1:
            return Outcome(_NONE)
        self.cursor = (x, y)
        self._last = (x, y)

        if self.mode == "creating":
            r = accept_rect(self.selection, self.bounds)
            if r is not None:
                self.mode = "hover"
                return Outcome("accept", rect=r)
            # Too small: no selection. The selector stays open.
            self.selection = None
            self.mode = "hover"
            self._update_hover()
            return Outcome(_REDRAW)

        if self.mode == "pending":
            self.mode = "hover"
            if self.hover is not None:
                r = accept_rect(self.hover, self.bounds)
                if r is not None:
                    return Outcome("accept", rect=r)
            self._update_hover()
            return Outcome(_NONE)

        return Outcome(_NONE)

    # ------------------------------------------------------------ keyboard

    def key(self, name: str, shift: bool, ctrl: bool) -> Outcome:
        """Apply one key (GDK key name).

        Arrow keys: the model moves its cursor to the clamped target, applies the motion
        rules there, and returns "warp" with the applied delta. The shell then warps the
        pointer to model.cursor (X11) or only redraws (Wayland). A later motion event at
        model.cursor changes nothing.
        """
        if name == "Escape":
            return Outcome("cancel")

        if name in ("Return", "KP_Enter"):
            # Windows Accept(): a selection wins over hover, also when it is too small.
            if self.selection is not None:
                return self._accept(self.selection)
            if self.hover is not None:
                return self._accept(self.hover)
            return Outcome(_NONE)

        if name == "space":
            return self._accept(self.bounds)

        if name in ("grave", "asciitilde"):
            m = monitor_at(self.cursor[0], self.cursor[1], self.monitors)
            return self._accept(m if m is not None else self.bounds)

        lower = name.lower() if len(name) == 1 else ""
        if lower == "c":
            self.options.crosshair = not self.options.crosshair
            return Outcome(_REDRAW)
        if lower == "m":
            self.options.magnifier = not self.options.magnifier
            return Outcome(_REDRAW)
        if lower == "p":
            self.options.position = not self.options.position
            return Outcome(_REDRAW)

        if name in ("Left", "Right", "Up", "Down"):
            step = 10 if shift else 1
            dx = -step if name == "Left" else step if name == "Right" else 0
            dy = -step if name == "Up" else step if name == "Down" else 0
            if self.bounds.is_empty:
                return Outcome(_NONE)
            cx, cy = self.cursor
            nx = max(self.bounds.x, min(cx + dx, self.bounds.right - 1))
            ny = max(self.bounds.y, min(cy + dy, self.bounds.bottom - 1))
            # Apply the move like a mouse move (Windows MoveCursorBy calls HandleMouseMove).
            self.motion(nx, ny, shift, ctrl)
            return Outcome("warp", dx=nx - cx, dy=ny - cy)

        return Outcome(_NONE)
