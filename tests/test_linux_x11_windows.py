"""Tests for the pure core of linux/desktop_recorder/x11_windows.py (runs on any OS)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.geometry import Rect  # noqa: E402
from desktop_recorder.x11_windows import XWin, visible_rects, window_rect  # noqa: E402

SCREEN = Rect(0, 0, 1280, 800)


def xwin(x: int = 100, y: int = 100, w: int = 400, h: int = 300, *, xid: int = 1,
         frame=None, gtk=None, types=None, states=None, viewable: bool = True,
         override_redirect: bool = False, pid: int | None = None) -> XWin:
    return XWin(xid=xid, x=x, y=y, w=w, h=h, frame_extents=frame, gtk_extents=gtk,
                types=list(types or []), states=list(states or []), viewable=viewable,
                override_redirect=override_redirect, pid=pid)


class WindowRectTests(unittest.TestCase):
    def test_frame_extents_added(self) -> None:
        r = window_rect(xwin(frame=(2, 3, 30, 4)))
        self.assertEqual(r, Rect(98, 70, 405, 334))

    def test_gtk_extents_subtracted(self) -> None:
        r = window_rect(xwin(gtk=(10, 10, 8, 12)))
        self.assertEqual(r, Rect(110, 108, 380, 280))

    def test_both_extents(self) -> None:
        # Mutter: _NET_FRAME_EXTENTS 0,0,0,0 together with _GTK_FRAME_EXTENTS on a CSD window.
        r = window_rect(xwin(frame=(0, 0, 0, 0), gtk=(10, 10, 8, 12)))
        self.assertEqual(r, Rect(110, 108, 380, 280))
        # Both non-zero: grow first, then shrink.
        r = window_rect(xwin(frame=(1, 1, 20, 1), gtk=(10, 10, 8, 12)))
        self.assertEqual(r, Rect(99 + 10, 80 + 8, 402 - 20, 321 - 20))

    def test_no_extents(self) -> None:
        self.assertEqual(window_rect(xwin()), Rect(100, 100, 400, 300))


class VisibleRectsTests(unittest.TestCase):
    def test_skip_rules(self) -> None:
        wins = [
            xwin(xid=1, states=["_NET_WM_STATE_HIDDEN"]),
            xwin(xid=2, types=["_NET_WM_WINDOW_TYPE_DOCK"]),
            xwin(xid=3, override_redirect=True),
            xwin(xid=4, viewable=False),
            xwin(xid=5, x=10, y=10, w=1, h=1),
            xwin(xid=6, x=1279, y=10, w=50, h=50),          # 1 px wide after the clip
            xwin(xid=7, types=["_NET_WM_WINDOW_TYPE_TOOLTIP"]),
            xwin(xid=8, x=20, y=30, w=40, h=50, types=["_NET_WM_WINDOW_TYPE_NORMAL"],
                 states=["_NET_WM_STATE_MAXIMIZED_VERT"]),
        ]
        self.assertEqual(visible_rects(wins, SCREEN), [Rect(20, 30, 40, 50)])

    def test_clip_to_screen(self) -> None:
        wins = [xwin(x=-50, y=700, w=200, h=300)]
        self.assertEqual(visible_rects(wins, SCREEN), [Rect(0, 700, 150, 100)])

    def test_own_pid_not_skipped(self) -> None:
        wins = [xwin(pid=os.getpid())]
        self.assertEqual(visible_rects(wins, SCREEN), [Rect(100, 100, 400, 300)])

    def test_order_top_first(self) -> None:
        bottom = xwin(xid=1, x=0, y=0, w=100, h=100)
        middle = xwin(xid=2, x=10, y=10, w=100, h=100)
        top = xwin(xid=3, x=20, y=20, w=100, h=100)
        self.assertEqual(visible_rects([bottom, middle, top], SCREEN),
                         [Rect(20, 20, 100, 100), Rect(10, 10, 100, 100), Rect(0, 0, 100, 100)])


if __name__ == "__main__":
    unittest.main()
