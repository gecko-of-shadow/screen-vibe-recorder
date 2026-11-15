"""Test pattern window for the Xvfb GUI tests (DESIGN.md 14.2).

A normal top-level window "dr-pattern" at (100,100), 400x300. Background (40,40,40),
with four 100x100 blocks (root px): green at (120,120), blue at (280,120),
yellow at (120,260), white at (280,260). The pattern is a background pixmap, so the
X server repaints it with no client round trip. The window is not override-redirect,
so the selector window list keeps it.

Usage: python3 tests/x11_pattern.py [DISPLAY]. Prints "pattern ready <xid>" after map.
Runs until it gets SIGTERM.
"""

from __future__ import annotations

import signal
import sys

from Xlib import X, display as xdisplay

POS = (100, 100)
SIZE = (400, 300)
BACKGROUND = (40, 40, 40)
BLOCKS = [
    ((0, 200, 0), (120, 120)),
    ((0, 0, 200), (280, 120)),
    ((255, 255, 0), (120, 260)),
    ((255, 255, 255), (280, 260)),
]
BLOCK = 100


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else None
    dpy = xdisplay.Display(name)
    screen = dpy.screen()
    root = screen.root
    colormap = screen.default_colormap

    def color(rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        return colormap.alloc_color(r * 257, g * 257, b * 257).pixel

    width, height = SIZE
    pixmap = root.create_pixmap(width, height, screen.root_depth)
    gc = pixmap.create_gc(foreground=color(BACKGROUND))
    pixmap.fill_rectangle(gc, 0, 0, width, height)
    for rgb, (bx, by) in BLOCKS:
        gc.change(foreground=color(rgb))
        pixmap.fill_rectangle(gc, bx - POS[0], by - POS[1], BLOCK, BLOCK)

    win = root.create_window(
        POS[0], POS[1], width, height, 0, screen.root_depth,
        X.InputOutput, X.CopyFromParent,
        background_pixmap=pixmap,
        override_redirect=False,
        event_mask=X.StructureNotifyMask,
    )
    win.set_wm_name("dr-pattern")
    win.set_wm_class("dr-pattern", "DrPattern")
    win.map()
    dpy.sync()
    # Wait for MapNotify, so the window is on the screen before the test goes on.
    while True:
        event = dpy.next_event()
        if event.type == X.MapNotify:
            break
    win.clear_area(0, 0, 0, 0)
    dpy.sync()
    print(f"pattern ready {win.id}", flush=True)

    signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
    while True:
        dpy.next_event()


if __name__ == "__main__":
    raise SystemExit(main())
