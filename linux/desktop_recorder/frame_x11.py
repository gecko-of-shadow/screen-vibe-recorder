"""Recording frame on X11 (GUI module).

A red border around the recorded region, made of python-xlib override-redirect windows
that do not take mouse input, and a small GTK Stop button below the region.
Linux has no exclude-from-capture API. So the border is always outside the region, and a
side or the Stop button that has no place outside the region is not drawn.

The same border is used on Wayland through XWayland, best effort (no Stop button there).
"""

from __future__ import annotations

import math
import sys
from typing import Callable

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from .geometry import Rect, border_layout, border_thickness, monitor_at, stop_rect  # noqa: E402

__all__ = ["RecordingFrame", "FRAME_NAME", "STOP_TITLE"]

FRAME_NAME = "Recording frame"
STOP_TITLE = "Stop recording"
BORDER_RGB = (255, 64, 64)

# Texts of section 10. messages.py (owner C7) holds them. These are the same texts, used
# when messages.py does not have the names below.
_EDGE_NOTE = "The region touches the screen edge, so the red frame is not drawn on that side."
_NO_STOP_NOTE = "There is no room for the Stop button. Press {0} or use the tray menu to stop."
_WAYLAND_NOTE = ("GNOME on Wayland does not let apps put a Stop button on the screen. "
                 "Press {0} or use the tray menu to stop.")


def _log(line: str) -> None:
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _messages():
    try:
        from . import messages  # type: ignore[attr-defined]

        return messages
    except Exception:
        return None


def _edge_note() -> str:
    value = getattr(_messages(), "FRAME_EDGE_NOTE", None)
    return value if isinstance(value, str) and value else _EDGE_NOTE


def _hotkey_note(name: str, fallback: str, hotkey_text: str) -> str:
    func = getattr(_messages(), name, None)
    if callable(func):
        try:
            text = func(hotkey_text)
            if isinstance(text, str) and text:
                return text
        except Exception:
            pass
    return fallback.format(hotkey_text)


class RecordingFrame:
    def __init__(self, display_name: str | None) -> None:
        self.display_name = display_name
        self._disp = None          # python-xlib connection, opened in show (D27)
        self._windows: list = []   # python-xlib border windows
        self._stop_win: Gtk.Window | None = None
        self._timer: int | None = None
        self._shown = False
        self._stopping = False

    # ------------------------------------------------------------ public

    def show(self, region: Rect, monitors: list[Rect], work_areas: list[Rect], scale: float,
             gdk_scale: int, hotkey_text: str, on_stop: Callable[[], None] | None,
             gap: int = 0) -> list[str]:
        """Show the border (and the Stop button when on_stop is set). Return notes for the start notification."""
        self.close()
        notes: list[str] = []
        try:
            layout = border_layout(region, border_thickness(scale), monitors, gap)
            self._show_border([s for s in layout.sides if s is not None and not s.is_empty])
            if layout.omitted:
                notes.append(_edge_note())

            if on_stop is not None:
                rect = self._stop_place(region, layout.outer, monitors, work_areas, scale)
                if rect is None:
                    notes.append(_hotkey_note("frame_no_stop_note", _NO_STOP_NOTE, hotkey_text))
                else:
                    self._show_stop(rect, region, scale, max(1, int(gdk_scale)), on_stop)
            else:
                notes.append(_hotkey_note("wayland_no_stop_note", _WAYLAND_NOTE, hotkey_text))

            self._shown = True
            self._timer = GLib.timeout_add(1000, self._restack)
        except Exception:
            self.close()
            raise
        return notes

    def close(self) -> None:
        """Remove the border and the Stop button. Safe to call more than once."""
        self._shown = False
        if self._timer is not None:
            try:
                GLib.source_remove(self._timer)
            except Exception:
                pass
            self._timer = None
        if self._stop_win is not None:
            try:
                self._stop_win.destroy()
            except Exception:
                pass
            self._stop_win = None
        disp = self._disp
        windows = self._windows
        self._windows = []
        self._disp = None
        if disp is not None:
            for win in windows:
                try:
                    win.destroy()
                except Exception:
                    pass
            try:
                disp.flush()
            except Exception:
                pass
            try:
                disp.close()
            except Exception:
                pass

    # ------------------------------------------------------------ border

    def _show_border(self, sides: list[Rect]) -> None:
        if not sides:
            return
        from Xlib import X, display as xdisplay

        disp = xdisplay.Display(self.display_name) if self.display_name else xdisplay.Display()
        self._disp = disp
        screen = disp.screen()
        root = screen.root
        r, g, b = BORDER_RGB
        pixel = screen.default_colormap.alloc_color(r * 257, g * 257, b * 257).pixel
        for side in sides:
            win = root.create_window(
                side.x, side.y, side.w, side.h, 0, screen.root_depth,
                X.InputOutput, X.CopyFromParent,
                background_pixel=pixel,
                override_redirect=True,
            )
            self._windows.append(win)
            win.set_wm_name(FRAME_NAME)
            self._empty_input_shape(disp, win)
            win.map()
        disp.flush()

    @staticmethod
    def _empty_input_shape(disp, win) -> None:
        """Let mouse input go through the window. A failure only logs."""
        from Xlib import X

        try:
            if not disp.has_extension("SHAPE"):
                _log("Desktop Recorder: the X server has no SHAPE extension. The frame takes mouse input.")
                return
            from Xlib.ext import shape

            so_set = getattr(getattr(shape, "SO", None), "Set", 0)
            sk_input = getattr(getattr(shape, "SK", None), "Input", 2)
            win.shape_rectangles(so_set, sk_input, X.Unsorted, 0, 0, [])
        except Exception as exc:
            _log(f"Desktop Recorder: cannot make the frame click-through: {exc}")

    def _restack(self) -> bool:
        if not self._shown:
            self._timer = None
            return False
        try:
            if self._disp is not None and self._windows:
                from Xlib import X

                for win in self._windows:
                    win.configure(stack_mode=X.Above)
                self._disp.flush()
            if self._stop_win is not None:
                gdkwin = self._stop_win.get_window()
                if gdkwin is not None:
                    gdkwin.raise_()
        except Exception as exc:
            _log(f"Desktop Recorder: cannot keep the frame on top: {exc}")
        return True

    # ------------------------------------------------------------ Stop button

    @staticmethod
    def _stop_place(region: Rect, outer: Rect, monitors: list[Rect], work_areas: list[Rect],
                    scale: float) -> Rect | None:
        if not monitors:
            return None
        cx = region.x + region.w // 2
        cy = region.y + region.h // 2
        monitor = monitor_at(cx, cy, monitors)
        if monitor is None:
            monitor = next((m for m in monitors if m.intersects(region)), monitors[0])
        index = monitors.index(monitor)
        work = work_areas[index] if index < len(work_areas) else monitor
        return stop_rect(region, outer, monitor, work, monitors, scale)

    def _show_stop(self, rect: Rect, region: Rect, scale: float, gdk_scale: int,
                   on_stop: Callable[[], None]) -> None:
        g = gdk_scale
        x = rect.x // g
        y = math.ceil(rect.y / g) if rect.y >= region.bottom else rect.y // g
        w = max(1, math.ceil(rect.w / g))
        h = max(1, math.ceil(rect.h / g))

        win = Gtk.Window(type=Gtk.WindowType.POPUP)
        win.set_title(STOP_TITLE)
        win.move(x, y)
        win.set_default_size(w, h)
        win.resize(w, h)

        area = Gtk.DrawingArea()
        area.set_size_request(w, h)
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        state = {"hot": False}

        def on_draw(widget: Gtk.Widget, cr: cairo.Context) -> bool:
            alloc = widget.get_allocation()
            # Draw in physical px, as on Windows.
            cr.scale(1.0 / g, 1.0 / g)
            pw = alloc.width * g
            ph = alloc.height * g
            cr.set_antialias(cairo.ANTIALIAS_NONE)
            shade = 64 / 255.0 if state["hot"] else 32 / 255.0
            cr.set_source_rgb(shade, shade, shade)
            cr.rectangle(0, 0, pw, ph)
            cr.fill()

            red = (BORDER_RGB[0] / 255.0, BORDER_RGB[1] / 255.0, BORDER_RGB[2] / 255.0)
            cr.set_source_rgb(*red)
            for rx, ry, rw, rh in ((0, 0, pw, 1), (0, ph - 1, pw, 1), (0, 1, 1, ph - 2), (pw - 1, 1, 1, ph - 2)):
                if rw > 0 and rh > 0:
                    cr.rectangle(rx, ry, rw, rh)
            cr.fill()

            icon = max(6, ph // 3)
            icon_x = ph // 3
            icon_y = (ph - icon) // 2
            cr.rectangle(icon_x, icon_y, icon, icon)
            cr.fill()

            cr.set_antialias(cairo.ANTIALIAS_DEFAULT)
            layout = PangoCairo.create_layout(cr)
            desc = Pango.FontDescription.from_string("Sans Bold")
            desc.set_absolute_size(13.0 * scale * Pango.SCALE)
            layout.set_font_description(desc)
            layout.set_text("Stop", -1)
            tw, th = layout.get_pixel_size()
            left = icon_x + icon
            tx = left + (pw - left - tw) / 2.0
            ty = (ph - th) / 2.0
            cr.set_source_rgb(1.0, 1.0, 1.0)
            cr.move_to(tx, ty)
            PangoCairo.show_layout(cr, layout)
            return True

        def on_cross(widget: Gtk.Widget, event: Gdk.EventCrossing) -> bool:
            state["hot"] = event.type == Gdk.EventType.ENTER_NOTIFY
            widget.queue_draw()
            return False

        def on_press(_widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
            if event.button != 1 or event.type != Gdk.EventType.BUTTON_PRESS or self._stopping:
                return True
            self._stopping = True

            def call() -> bool:
                self._stopping = False
                on_stop()
                return False

            # Run the stop after this handler. The stop closes this window.
            GLib.idle_add(call)
            return True

        area.connect("draw", on_draw)
        area.connect("enter-notify-event", on_cross)
        area.connect("leave-notify-event", on_cross)
        area.connect("button-press-event", on_press)
        win.add(area)
        self._stop_win = win
        win.show_all()

        try:
            display = win.get_display()
            cursor = Gdk.Cursor.new_from_name(display, "pointer")
            gdkwin = area.get_window()
            if cursor is not None and gdkwin is not None:
                gdkwin.set_cursor(cursor)
        except Exception:
            pass
