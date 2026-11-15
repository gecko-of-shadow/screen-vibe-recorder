"""GTK view and shells of the region selector (GUI module).

SelectorView draws the frozen picture and sends mouse and key events to the pure
SelectorModel (selector_model.py). Two shells use the same view:

- X11: one override-redirect POPUP window over the root window, with a seat grab.
- Wayland: one fullscreen window for each shared monitor, with a frozen stream frame.

All drawing is in image px. Image px are X screen px on X11 and stream px on Wayland.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Callable

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import x11_windows  # noqa: E402
from .ffmpeg_cmd import x11_target  # noqa: E402
from .geometry import (  # noqa: E402
    DrawMap,
    Rect,
    fit_image,
    label_rect,
    magnifier_rect,
    monitor_at,
    widget_to_image,
)
from .selector_model import Outcome, SelectorModel, SelectorOptions  # noqa: E402

if TYPE_CHECKING:
    from .portal import PortalStreamInfo
    from .settings import Settings
    from .wayland_pump import Frame

__all__ = ["SelectorView", "open_x11_selector", "open_wayland_selector", "bgrx_to_rgb"]

ACCENT = (64 / 255.0, 158 / 255.0, 1.0)
DIM_ALPHA = 120 / 255.0
CROSSHAIR_ALPHA = 170 / 255.0
LABEL_BG = (20 / 255.0, 20 / 255.0, 20 / 255.0, 220 / 255.0)
MAG_SOURCE = 10
MAG_ZOOM = 8
MAG_SIZE = MAG_SOURCE * MAG_ZOOM  # 80
OPEN_LINE = "Desktop Recorder: selector open"
GRAB_ERROR = "cannot grab the keyboard and mouse."
_HINT_FALLBACK = "Esc or right-click: cancel"

_EVENT_MASK = (Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
               | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK
               | Gdk.EventMask.KEY_RELEASE_MASK)

# Keep the open selectors alive until they close.
_active: set[object] = set()


def _log(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _hint_text() -> str:
    """The Wayland hint. messages.py (owner C7) holds it. The spec names no constant."""
    try:
        from . import messages  # type: ignore[attr-defined]
    except Exception:
        return _HINT_FALLBACK
    for name in ("SELECTOR_HINT", "WAYLAND_SELECTOR_HINT", "SELECTOR_CANCEL_HINT", "WAYLAND_HINT"):
        value = getattr(messages, name, None)
        if isinstance(value, str) and value:
            return value
    return _HINT_FALLBACK


def bgrx_to_rgb(data: bytes | bytearray | memoryview, width: int, height: int) -> bytes:
    """Packed BGRx rows (width*4 per row) to packed RGB rows (width*3 per row)."""
    src = bytes(data)
    n = width * height
    if len(src) < n * 4:
        raise ValueError("The frame is smaller than its size.")
    src = src[: n * 4]
    rgb = bytearray(n * 3)
    rgb[0::3] = src[2::4]
    rgb[1::3] = src[1::4]
    rgb[2::3] = src[0::4]
    return bytes(rgb)


def _pixbuf_from_rgb(data: bytes, width: int, height: int) -> GdkPixbuf.Pixbuf:
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data), GdkPixbuf.Colorspace.RGB,
                                           False, 8, width, height, width * 3)


def _fill(cr: cairo.Context, x: float, y: float, w: float, h: float) -> None:
    if w > 0 and h > 0:
        cr.rectangle(x, y, w, h)
        cr.fill()


def _ring(cr: cairo.Context, x: int, y: int, w: int, h: int, t: int = 1) -> None:
    """A frame of thickness t on the inner edge of the box (x, y, w, h), as filled rectangles."""
    if w <= 0 or h <= 0:
        return
    _fill(cr, x, y, w, t)
    _fill(cr, x, y + h - t, w, t)
    _fill(cr, x, y + t, t, h - 2 * t)
    _fill(cr, x + w - t, y + t, t, h - 2 * t)


def _outside_frame(cr: cairo.Context, r: Rect, t: int) -> None:
    """A frame of thickness t just outside the rect."""
    _ring(cr, r.x - t, r.y - t, r.w + 2 * t, r.h + 2 * t, t)


# ---------------------------------------------------------------- view


class SelectorView(Gtk.DrawingArea):
    """Draws the selector. The shell connects the window events to the handle_* methods.

    With a seat grab (X11), GTK sends the events to the toplevel window, not to this child.
    So the shell connects them on the window. The view fills the window at 0,0, so the
    event coordinates are the same.
    """

    def __init__(self, image: GdkPixbuf.Pixbuf, model: SelectorModel, monitor_rects: list[Rect],
                 coord_origin: tuple[int, int], on_outcome: Callable[[Outcome], None],
                 hint: str | None = None) -> None:
        super().__init__()
        self.image = image
        self.model = model
        self.monitor_rects = list(monitor_rects)
        self.coord_origin = coord_origin
        self.on_outcome = on_outcome
        self.hint = hint
        self.iw = int(image.get_width())
        self.ih = int(image.get_height())
        self.bounds = Rect(0, 0, self.iw, self.ih)
        # Fixed widget-to-image map (X11). None: compute it from the allocation (Wayland).
        self.fixed_map: DrawMap | None = None
        self._surface = Gdk.cairo_surface_create_from_pixbuf(image, 1, None)
        self.set_can_focus(True)
        self.add_events(_EVENT_MASK)
        self.connect("draw", self._on_draw)

    # ------------------------------------------------------------ mapping

    def draw_map(self) -> DrawMap:
        if self.fixed_map is not None:
            return self.fixed_map
        alloc = self.get_allocation()
        return fit_image(float(alloc.width), float(alloc.height), self.iw, self.ih)

    def to_image(self, x: float, y: float) -> tuple[int, int]:
        return widget_to_image(x, y, self.draw_map())

    def _scale(self) -> float:
        m = self.draw_map()
        if m.dw <= 0 or self.iw <= 0:
            return 1.0
        return max(self.iw / m.dw, 0.1)

    # ------------------------------------------------------------ input

    def _dispatch(self, outcome: Outcome) -> None:
        if outcome.kind in ("redraw", "warp"):
            self.queue_draw()
        if outcome.kind in ("accept", "cancel", "warp"):
            self.on_outcome(outcome)

    def pointer_at(self, x: float, y: float) -> None:
        """Send one motion at a widget position (the pointer position when the selector opens)."""
        ix, iy = self.to_image(x, y)
        self.model.motion(ix, iy, False, False)
        self.queue_draw()

    def handle_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return True  # double and triple clicks: the model gets the single presses only
        x, y = self.to_image(event.x, event.y)
        self._dispatch(self.model.press(x, y, int(event.button)))
        return True

    def handle_release(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        x, y = self.to_image(event.x, event.y)
        self._dispatch(self.model.release(x, y, int(event.button)))
        return True

    def handle_motion(self, _widget: Gtk.Widget, event: Gdk.EventMotion) -> bool:
        x, y = self.to_image(event.x, event.y)
        state = event.state
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        self._dispatch(self.model.motion(x, y, shift, ctrl))
        return True

    def handle_key(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        name = Gdk.keyval_name(event.keyval) or ""
        state = event.state
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        self._dispatch(self.model.key(name, shift, ctrl))
        return True

    # ------------------------------------------------------------ drawing

    def _paint_image(self, cr: cairo.Context) -> None:
        cr.set_source_surface(self._surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.rectangle(0, 0, self.iw, self.ih)
        cr.fill()

    def _layout(self, cr: cairo.Context, text: str) -> Pango.Layout:
        layout = PangoCairo.create_layout(cr)
        desc = Pango.FontDescription.from_string("Sans")
        desc.set_absolute_size(12.0 * self._scale() * Pango.SCALE)
        layout.set_font_description(desc)
        layout.set_text(text, -1)
        return layout

    def _show_text(self, cr: cairo.Context, layout: Pango.Layout, x: float, y: float) -> None:
        cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)
        cr.set_antialias(cairo.ANTIALIAS_NONE)

    def _on_draw(self, _widget: Gtk.Widget, cr: cairo.Context) -> bool:
        m = self.draw_map()
        cr.set_source_rgb(0.0, 0.0, 0.0)
        cr.paint()
        if self.iw <= 0 or self.ih <= 0 or m.dw <= 0 or m.dh <= 0:
            return True

        cr.save()
        cr.translate(m.ox, m.oy)
        cr.scale(m.dw / self.iw, m.dh / self.ih)
        cr.rectangle(0, 0, self.iw, self.ih)
        cr.clip()

        # Background: the picture, dimmed.
        self._paint_image(cr)
        cr.set_source_rgba(0.0, 0.0, 0.0, DIM_ALPHA)
        cr.rectangle(0, 0, self.iw, self.ih)
        cr.fill()

        model = self.model
        bright = model.selection if model.selection is not None else model.hover
        if bright is not None and not bright.is_empty:
            cr.save()
            cr.rectangle(bright.x, bright.y, bright.w, bright.h)
            cr.clip()
            self._paint_image(cr)
            cr.restore()

        cr.set_antialias(cairo.ANTIALIAS_NONE)
        cr.set_source_rgb(*ACCENT)
        if model.hover is not None:
            _outside_frame(cr, model.hover, 2)
        if model.selection is not None:
            _outside_frame(cr, model.selection, 1)

        cx, cy = model.cursor
        options = model.options
        if options.crosshair:
            cr.set_source_rgba(1.0, 1.0, 1.0, CROSSHAIR_ALPHA)
            _fill(cr, 0, cy, self.iw, 1)
            _fill(cr, cx, 0, 1, self.ih)

        self._draw_label(cr, bright)
        if options.magnifier:
            self._draw_magnifier(cr, cx, cy)
        if self.hint:
            self._draw_hint(cr)

        cr.restore()
        return True

    def _draw_label(self, cr: cairo.Context, target: Rect | None) -> None:
        if target is None or target.is_empty:
            return
        ox, oy = self.coord_origin
        text = f"{target.w & ~1} x {target.h & ~1}"
        if self.model.options.position:
            text += f"   at {target.x + ox}, {target.y + oy}"
        layout = self._layout(cr, text)
        tw, th = layout.get_pixel_size()
        box = label_rect(target, tw + 10, th + 4, self.bounds)
        cr.set_source_rgba(*LABEL_BG)
        _fill(cr, box.x, box.y, box.w, box.h)
        self._show_text(cr, layout, box.x + 5, box.y + 2)

    def _draw_hint(self, cr: cairo.Context) -> None:
        layout = self._layout(cr, self.hint or "")
        tw, th = layout.get_pixel_size()
        bw, bh = tw + 10, th + 4
        x = max(0, (self.iw - bw) // 2)
        y = min(8, max(0, self.ih - bh))
        cr.set_source_rgba(*LABEL_BG)
        _fill(cr, x, y, bw, bh)
        self._show_text(cr, layout, x + 5, y + 2)

    def _draw_magnifier(self, cr: cairo.Context, cx: int, cy: int) -> None:
        monitor = monitor_at(cx, cy, self.monitor_rects)
        monitor = monitor.intersect(self.bounds) if monitor is not None else self.bounds
        if monitor.is_empty:
            monitor = self.bounds

        sample = self._layout(cr, "-00000, -00000")
        sw, sh = sample.get_pixel_size()
        box_w = max(MAG_SIZE, sw + 8)
        box_h = MAG_SIZE + sh + 4
        box = magnifier_rect(cx, cy, box_w, box_h, monitor)

        cr.set_source_rgb(0.0, 0.0, 0.0)
        _fill(cr, box.x, box.y, box.w, box.h)

        zx = box.x + (box.w - MAG_SIZE) // 2
        zy = box.y
        half = MAG_SOURCE // 2
        source = Rect(cx - half, cy - half, MAG_SOURCE, MAG_SOURCE)
        visible = source.intersect(self.bounds)
        if not visible.is_empty:
            cr.save()
            cr.rectangle(zx + (visible.x - source.x) * MAG_ZOOM, zy + (visible.y - source.y) * MAG_ZOOM,
                         visible.w * MAG_ZOOM, visible.h * MAG_ZOOM)
            cr.clip()
            cr.translate(zx - source.x * MAG_ZOOM, zy - source.y * MAG_ZOOM)
            cr.scale(MAG_ZOOM, MAG_ZOOM)
            cr.set_source_surface(self._surface, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            cr.restore()

        # Mark the pixel under the cursor.
        ccx = zx + half * MAG_ZOOM
        ccy = zy + half * MAG_ZOOM
        cr.set_source_rgb(0.0, 0.0, 0.0)
        _ring(cr, ccx - 1, ccy - 1, MAG_ZOOM + 2, MAG_ZOOM + 2)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        _ring(cr, ccx, ccy, MAG_ZOOM, MAG_ZOOM)

        ox, oy = self.coord_origin
        caption = self._layout(cr, f"{cx + ox}, {cy + oy}")
        self._show_text(cr, caption, box.x + 4, zy + MAG_SIZE + 2)

        cr.set_source_rgb(*ACCENT)
        _ring(cr, box.x, box.y, box.w, box.h)


def _connect_input(win: Gtk.Window, view: SelectorView) -> None:
    win.add_events(_EVENT_MASK)
    win.connect("button-press-event", view.handle_press)
    win.connect("button-release-event", view.handle_release)
    win.connect("motion-notify-event", view.handle_motion)
    win.connect("key-press-event", view.handle_key)


def _crosshair_cursor(display: Gdk.Display) -> Gdk.Cursor | None:
    try:
        return Gdk.Cursor.new_from_name(display, "crosshair")
    except Exception:
        return None


def _options_of(settings: "Settings") -> SelectorOptions:
    return SelectorOptions(crosshair=bool(settings.selector_crosshair),
                           magnifier=bool(settings.selector_magnifier),
                           position=bool(settings.selector_position))


# ---------------------------------------------------------------- X11 shell


def _ffmpeg_path() -> str | None:
    env = os.environ.get("DESKTOP_RECORDER_FFMPEG", "").strip()
    if env:
        return env
    return shutil.which("ffmpeg")


class _X11Selector:
    def __init__(self, settings: "Settings", display_name: str | None,
                 on_done: Callable[[Rect | None, SelectorOptions], None]) -> None:
        self.settings = settings
        self.display_name = display_name
        self.on_done = on_done
        self.options = _options_of(settings)
        self.display: Gdk.Display | None = None
        self.seat: Gdk.Seat | None = None
        self.window: Gtk.Window | None = None
        self.view: SelectorView | None = None
        self.model: SelectorModel | None = None
        self._xdisplay = None
        self._done = False

    # ------------------------------------------------------------ snapshot

    def _ffmpeg_snapshot(self, pw: int, ph: int) -> GdkPixbuf.Pixbuf | None:
        ffmpeg = _ffmpeg_path()
        if not ffmpeg:
            return None
        target = x11_target(self.display_name or os.environ.get("DISPLAY"))
        argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0",
                "-i", target, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            _log(f"Desktop Recorder: selector snapshot with ffmpeg failed: {exc}")
            return None
        size = pw * ph * 3
        if done.returncode != 0 or len(done.stdout) < size:
            return None
        return _pixbuf_from_rgb(done.stdout[:size], pw, ph)

    def _snapshot(self, root: Gdk.Window, lw: int, lh: int, pw: int, ph: int) -> GdkPixbuf.Pixbuf:
        pix = None
        try:
            pix = Gdk.pixbuf_get_from_window(root, 0, 0, lw, lh)
        except Exception:
            pix = None
        if pix is not None and pix.get_width() == pw and pix.get_height() == ph:
            return pix
        pix = self._ffmpeg_snapshot(pw, ph)
        if pix is not None:
            return pix
        black = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, pw, ph)
        black.fill(0x000000FF)
        return black

    # ------------------------------------------------------------ open

    def open(self) -> str | None:
        display = Gdk.Display.get_default()
        if display is None:
            return "no display."
        self.display = display
        first = display.get_monitor(0)
        s = max(1, int(first.get_scale_factor())) if first is not None else 1

        root = Gdk.get_default_root_window()
        lw, lh = int(root.get_width()), int(root.get_height())
        pw, ph = lw * s, lh * s
        bounds = Rect(0, 0, pw, ph)
        image = self._snapshot(root, lw, lh, pw, ph)

        try:
            windows = x11_windows.list_windows(self.display_name)
        except Exception as exc:
            _log(f"Desktop Recorder: cannot read the window list: {exc}")
            windows = []

        monitors: list[Rect] = []
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            if mon is None:
                continue
            g = mon.get_geometry()
            monitors.append(Rect(g.x * s, g.y * s, g.width * s, g.height * s))
        if not monitors:
            monitors = [bounds]

        self.model = SelectorModel(bounds, monitors, windows, self.options)
        view = SelectorView(image, self.model, monitors, (0, 0), self._on_outcome)
        view.fixed_map = DrawMap(0.0, 0.0, float(lw), float(lh), pw, ph)
        self.view = view

        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_title("Select region")
        win.move(0, 0)
        win.set_default_size(lw, lh)
        win.resize(lw, lh)
        _connect_input(win, view)
        win.add(view)
        self.window = win
        try:
            return self._grab_and_show(display, win, view, lw, lh)
        except Exception as exc:
            self._done = True
            try:
                if self.seat is not None:
                    self.seat.ungrab()
            except Exception:
                pass
            win.destroy()
            self.window = None
            display.flush()
            return str(exc) or exc.__class__.__name__

    def _grab_and_show(self, display: Gdk.Display, win: Gtk.Window, view: SelectorView,
                       lw: int, lh: int) -> str | None:
        win.show_all()

        gdkwin = win.get_window()
        cursor = _crosshair_cursor(display)
        if gdkwin is not None and cursor is not None:
            gdkwin.set_cursor(cursor)

        # Grab the keyboard and the mouse. Retry for 1 s: a hotkey that is still down holds a grab.
        seat = display.get_default_seat()
        self.seat = seat
        deadline = time.monotonic() + 1.0
        while True:
            status = Gdk.GrabStatus.FAILED
            if gdkwin is not None:
                status = seat.grab(gdkwin, Gdk.SeatCapabilities.ALL, False, cursor, None, None, None)
            if status == Gdk.GrabStatus.SUCCESS:
                break
            if time.monotonic() >= deadline:
                self._done = True
                win.destroy()
                self.window = None
                display.flush()
                return GRAB_ERROR
            time.sleep(0.05)

        # First hover without a motion event.
        try:
            _screen, px, py = seat.get_pointer().get_position()
            ix, iy = widget_to_image(float(px), float(py), view.fixed_map)
            self.model.motion(ix, iy, False, False)
        except Exception as exc:
            _log(f"Desktop Recorder: cannot read the pointer position: {exc}")
        view.queue_draw()

        _active.add(self)
        _log(OPEN_LINE)
        return None

    # ------------------------------------------------------------ events

    def _warp(self) -> None:
        if self.model is None:
            return
        x, y = self.model.cursor
        try:
            if self._xdisplay is None:
                from Xlib import display as xdisplay

                self._xdisplay = (xdisplay.Display(self.display_name) if self.display_name
                                  else xdisplay.Display())
            self._xdisplay.screen().root.warp_pointer(int(x), int(y))
            self._xdisplay.sync()
        except Exception as exc:
            _log(f"Desktop Recorder: cannot move the pointer: {exc}")

    def _on_outcome(self, outcome: Outcome) -> None:
        if self._done:
            return
        if outcome.kind == "warp":
            self._warp()
        elif outcome.kind == "accept":
            self._finish(outcome.rect)
        elif outcome.kind == "cancel":
            self._finish(None)

    def _finish(self, rect: Rect | None) -> None:
        if self._done:
            return
        self._done = True
        try:
            if self.seat is not None:
                self.seat.ungrab()
        except Exception:
            pass
        if self.window is not None:
            self.window.destroy()
            self.window = None
        if self.display is not None:
            self.display.flush()
            self.display.sync()
        if self._xdisplay is not None:
            try:
                self._xdisplay.close()
            except Exception:
                pass
            self._xdisplay = None
        options = self.options

        def deliver() -> bool:
            _active.discard(self)
            self.on_done(rect, options)
            return False

        # Give the compositor time to remove the selector before the first capture.
        GLib.timeout_add(60, deliver)


def open_x11_selector(settings: "Settings", display_name: str | None,
                      on_done: Callable[[Rect | None, SelectorOptions], None]) -> str | None:
    """Open the X11 selector. Return an error text, or None. on_done gets (rect or None, options)."""
    return _X11Selector(settings, display_name, on_done).open()


# ---------------------------------------------------------------- Wayland shell


class _WaylandSelector:
    def __init__(self, frames: list[tuple["PortalStreamInfo", "Frame"]], settings: "Settings",
                 token: str, on_done: Callable[[int | None, Rect | None, SelectorOptions], None]) -> None:
        self.frames = frames
        self.token = token
        self.on_done = on_done
        # One options object for all windows. C, M, P change it.
        self.options = _options_of(settings)
        self.windows: list[Gtk.Window] = []
        self._done = False

    @staticmethod
    def _match(frames: list, display: Gdk.Display) -> list[tuple[int, int]]:
        """(stream index, monitor index) pairs."""
        n = display.get_n_monitors()
        geoms = []
        for mi in range(n):
            mon = display.get_monitor(mi)
            geoms.append(mon.get_geometry() if mon is not None else None)
        pairs: list[tuple[int, int]] = []
        used: set[int] = set()
        for si, (info, _frame) in enumerate(frames):
            pos = getattr(info, "position", None)
            if pos is None:
                continue
            for mi, g in enumerate(geoms):
                if g is None or mi in used:
                    continue
                if (int(g.x), int(g.y)) == (int(pos[0]), int(pos[1])):
                    pairs.append((si, mi))
                    used.add(mi)
                    break
        if pairs:
            return pairs
        if len(frames) == 1 and n == 1:
            return [(0, 0)]
        index = 0
        primary = display.get_primary_monitor()  # GTK3 on Wayland can give None
        if primary is not None:
            for mi in range(n):
                if display.get_monitor(mi) == primary:
                    index = mi
                    break
        return [(0, index)]

    def open(self) -> str | None:
        if not self.frames:
            return "no screen picture."
        display = Gdk.Display.get_default()
        if display is None:
            return "no display."
        if display.get_n_monitors() < 1:
            return "no monitor was found."
        try:
            return self._open_windows(display)
        except Exception as exc:
            self._done = True
            self._destroy_all()
            display.flush()
            return str(exc) or exc.__class__.__name__

    def _open_windows(self, display: Gdk.Display) -> str | None:
        screen = Gdk.Screen.get_default()
        hint = _hint_text()
        cursor = _crosshair_cursor(display)

        for si, mi in self._match(self.frames, display):
            frame = self.frames[si][1]
            iw, ih = int(frame.width), int(frame.height)
            data = frame.crop(Rect(0, 0, iw, ih))
            image = _pixbuf_from_rgb(bgrx_to_rgb(data, iw, ih), iw, ih)
            bounds = Rect(0, 0, iw, ih)
            model = SelectorModel(bounds, [bounds], [], self.options)
            view = SelectorView(image, model, [bounds], (0, 0),
                                lambda outcome, index=si: self._on_outcome(index, outcome), hint=hint)

            win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            win.set_decorated(False)
            win.set_title("Select region")
            _connect_input(win, view)
            win.connect("delete-event", self._on_delete)
            win.connect("map-event", self._on_map, view, cursor)
            win.add(view)
            win.fullscreen_on_monitor(screen, mi)
            if self.token:
                win.set_startup_id(self.token)
            self.windows.append(win)
            win.show_all()
            win.present()

        _active.add(self)
        _log(OPEN_LINE)
        return None

    def _on_map(self, win: Gtk.Window, _event: Gdk.Event, view: SelectorView,
                cursor: Gdk.Cursor | None) -> bool:
        gdkwin = win.get_window()
        if gdkwin is not None and cursor is not None:
            gdkwin.set_cursor(cursor)

        def first_motion() -> bool:
            if self._done or gdkwin is None:
                return False
            try:
                pointer = win.get_display().get_default_seat().get_pointer()
                _child, x, y, _mask = gdkwin.get_device_position(pointer)
                alloc = view.get_allocation()
                if 0 <= x < alloc.width and 0 <= y < alloc.height:
                    view.pointer_at(float(x), float(y))
            except Exception:
                pass
            return False

        GLib.idle_add(first_motion)
        return False

    def _on_delete(self, _win: Gtk.Window, _event: Gdk.Event) -> bool:
        self._finish(None, None)
        return True

    def _on_outcome(self, index: int, outcome: Outcome) -> None:
        if self._done:
            return
        if outcome.kind == "accept":
            self._finish(index, outcome.rect)
        elif outcome.kind == "cancel":
            self._finish(None, None)
        # "warp": Wayland apps cannot move the pointer. The view already redraws.

    def _destroy_all(self) -> None:
        for win in self.windows:
            try:
                win.destroy()
            except Exception:
                pass
        self.windows = []

    def _finish(self, index: int | None, rect: Rect | None) -> None:
        if self._done:
            return
        self._done = True
        _active.discard(self)
        # Send the destroy requests first (11.3 step 5). The controller then reads the
        # accept frame, and the pump waits for a frame after it.
        self._destroy_all()
        try:
            display = Gdk.Display.get_default()
            if display is not None:
                display.flush()
        except Exception:
            pass
        if index is not None:
            self.on_done(index, rect, self.options)
        else:
            self.on_done(None, None, self.options)


def open_wayland_selector(frames: list[tuple["PortalStreamInfo", "Frame"]], settings: "Settings",
                          token: str,
                          on_done: Callable[[int | None, Rect | None, SelectorOptions], None]) -> str | None:
    """Open one selector window for each matched stream. Return an error text, or None.

    on_done gets (index into frames, crop in stream px, options), or (None, None, options) on cancel.
    """
    return _WaylandSelector(frames, settings, token, on_done).open()
