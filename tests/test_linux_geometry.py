"""Tests for linux/desktop_recorder/geometry.py (pure, runs on any OS)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.geometry import (  # noqa: E402
    EMPTY,
    DrawMap,
    Rect,
    accept_rect,
    border_layout,
    border_thickness,
    fit_image,
    image_to_widget,
    inclusive_rect,
    is_on_monitors,
    label_rect,
    magnifier_rect,
    make_even,
    monitor_at,
    square_point,
    stop_rect,
    stream_to_layout,
    widget_to_image,
)

SCREEN = Rect(0, 0, 1920, 1080)


class RectTests(unittest.TestCase):
    def test_rect_basics(self) -> None:
        r = Rect(10, 20, 30, 40)
        self.assertEqual((r.right, r.bottom), (40, 60))
        self.assertTrue(r.contains(10, 20))
        self.assertFalse(r.contains(40, 20))
        self.assertTrue(Rect().is_empty)
        self.assertEqual(EMPTY, Rect())
        self.assertEqual(r.intersect(Rect(30, 50, 100, 100)), Rect(30, 50, 10, 10))
        self.assertEqual(r.intersect(Rect(40, 20, 5, 5)), Rect())
        self.assertFalse(r.intersects(Rect(40, 20, 5, 5)))


class GeometryTests(unittest.TestCase):
    def test_inclusive_drag(self) -> None:
        self.assertEqual(inclusive_rect(440, 172, 1421, 601), Rect(440, 172, 982, 430))
        self.assertEqual(inclusive_rect(1421, 601, 440, 172), Rect(440, 172, 982, 430))
        self.assertEqual(inclusive_rect(5, 5, 5, 5), Rect(5, 5, 1, 1))

    def test_make_even_shrinks(self) -> None:
        self.assertEqual(make_even(Rect(3, 4, 301, 201)), Rect(3, 4, 300, 200))
        self.assertEqual(make_even(Rect(0, 0, 1, 5)), EMPTY)
        self.assertEqual(make_even(Rect(0, 0, 0, 0)), EMPTY)
        self.assertEqual(make_even(Rect(0, 0, 2, 2)), Rect(0, 0, 2, 2))

    def test_accept_rect(self) -> None:
        self.assertIsNone(accept_rect(None, SCREEN))
        self.assertEqual(accept_rect(Rect(1900, 1000, 101, 101), SCREEN), Rect(1900, 1000, 20, 80))
        self.assertIsNone(accept_rect(Rect(5000, 5000, 10, 10), SCREEN))

    def test_square_point(self) -> None:
        self.assertEqual(square_point(100, 100, 150, 120), (150, 150))
        self.assertEqual(square_point(100, 100, 80, 160), (40, 160))
        self.assertEqual(square_point(100, 100, 70, 90), (70, 70))
        # A zero delta takes the + sign.
        self.assertEqual(square_point(100, 100, 100, 130), (130, 130))
        self.assertEqual(square_point(100, 100, 100, 100), (100, 100))

    def test_monitor_at_and_on_monitors(self) -> None:
        mons = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1280, 1024)]
        self.assertEqual(monitor_at(2000, 10, mons), mons[1])
        self.assertIsNone(monitor_at(2000, 1050, mons))
        self.assertTrue(is_on_monitors(Rect(1900, 0, 40, 10), mons))
        self.assertFalse(is_on_monitors(Rect(1900, 1020, 40, 10), mons))
        self.assertFalse(is_on_monitors(Rect(0, 0, 0, 10), mons))

    def test_border_thickness(self) -> None:
        self.assertEqual(border_thickness(1.0), 2)
        self.assertEqual(border_thickness(0.5), 2)
        self.assertEqual(border_thickness(2.0), 4)
        self.assertEqual(border_thickness(1.75), 4)

    def test_border_outside(self) -> None:
        lay = border_layout(Rect(100, 100, 200, 100), 2, [SCREEN])
        top, bottom, left, right = lay.sides
        self.assertEqual(top, Rect(98, 98, 204, 2))
        self.assertEqual(bottom, Rect(98, 200, 204, 2))
        self.assertEqual(left, Rect(98, 100, 2, 100))
        self.assertEqual(right, Rect(300, 100, 2, 100))
        self.assertEqual(lay.outer, Rect(98, 98, 204, 104))
        self.assertEqual(lay.omitted, [])

    def test_border_edge_omits_side(self) -> None:
        lay = border_layout(Rect(0, 0, 200, 100), 2, [Rect(0, 0, 1280, 800)])
        top, bottom, left, right = lay.sides
        self.assertIsNone(top)
        self.assertIsNone(left)
        self.assertEqual(lay.omitted, ["top", "left"])
        self.assertEqual(lay.outer, Rect(0, 0, 202, 102))
        self.assertEqual(bottom, Rect(0, 100, 202, 2))
        self.assertEqual(right, Rect(200, 0, 2, 100))

    def test_border_gap(self) -> None:
        lay = border_layout(Rect(100, 100, 200, 100), 2, [SCREEN], gap=1)
        top, bottom, left, right = lay.sides
        self.assertEqual(top, Rect(97, 97, 206, 2))
        self.assertEqual(left, Rect(97, 99, 2, 102))
        self.assertEqual(bottom, Rect(97, 201, 206, 2))
        self.assertEqual(right, Rect(301, 99, 2, 102))
        self.assertEqual(lay.outer, Rect(97, 97, 206, 106))

    def test_border_one_side_corner(self) -> None:
        # Region at the right screen edge: the right side is omitted.
        lay = border_layout(Rect(1720, 100, 200, 100), 2, [SCREEN])
        top, bottom, left, right = lay.sides
        self.assertIsNone(right)
        self.assertEqual(lay.omitted, ["right"])
        self.assertEqual(lay.outer, Rect(1718, 98, 202, 104))
        # Top spans from outer.x to the region right edge (Windows corner rule).
        self.assertEqual(top, Rect(1718, 98, 202, 2))
        self.assertEqual(top.right, 1920)
        self.assertEqual(bottom, Rect(1718, 200, 202, 2))
        self.assertEqual(left, Rect(1718, 100, 2, 100))

    def test_border_full_screen_has_no_side(self) -> None:
        lay = border_layout(SCREEN, 2, [SCREEN])
        self.assertEqual(lay.sides, [None, None, None, None])
        self.assertEqual(lay.outer, SCREEN)

    def test_stop_below_above_other_none(self) -> None:
        work = Rect(0, 0, 1920, 1040)
        # 1. Below the outer edge, centered.
        region = Rect(100, 100, 200, 100)
        outer = border_layout(region, 2, [SCREEN]).outer
        self.assertEqual(stop_rect(region, outer, SCREEN, work, [SCREEN], 1.0), Rect(158, 206, 84, 28))
        # 2. Above, when below does not fit in the work area.
        region = Rect(100, 900, 200, 130)
        outer = border_layout(region, 2, [SCREEN]).outer
        self.assertEqual(stop_rect(region, outer, SCREEN, work, [SCREEN], 1.0), Rect(158, 866, 84, 28))
        # 3. Another monitor that does not touch the region.
        second = Rect(1920, 0, 1280, 1024)
        region = SCREEN
        outer = border_layout(region, 2, [SCREEN, second]).outer
        self.assertEqual(stop_rect(region, outer, SCREEN, work, [SCREEN, second], 1.0),
                         Rect(1920 + (1280 - 84) // 2, 4, 84, 28))
        # 4. Full-monitor region on one monitor: no place.
        outer = border_layout(SCREEN, 2, [SCREEN]).outer
        self.assertIsNone(stop_rect(SCREEN, outer, SCREEN, work, [SCREEN], 1.0))

    def test_stop_scale_and_clamp(self) -> None:
        region = Rect(0, 100, 50, 50)
        outer = border_layout(region, 3, [SCREEN]).outer
        r = stop_rect(region, outer, SCREEN, EMPTY, [SCREEN], 1.5)
        assert r is not None
        self.assertEqual((r.x, r.w, r.h), (0, 126, 42))
        self.assertEqual(r.y, outer.bottom + 6)

    def test_label_flip(self) -> None:
        target = Rect(100, 5, 300, 200)
        self.assertEqual(label_rect(target, 80, 20, SCREEN), Rect(100, 13, 80, 20))
        target = Rect(100, 300, 300, 200)
        self.assertEqual(label_rect(target, 80, 20, SCREEN), Rect(100, 272, 80, 20))
        # Clamped to the right edge.
        self.assertEqual(label_rect(Rect(1900, 300, 20, 20), 80, 20, SCREEN).x, 1840)

    def test_magnifier_flip(self) -> None:
        self.assertEqual(magnifier_rect(100, 100, 120, 100, SCREEN), Rect(124, 124, 120, 100))
        # Near the bottom-right corner: flip on both axes.
        self.assertEqual(magnifier_rect(1900, 1060, 120, 100, SCREEN), Rect(1756, 936, 120, 100))
        # Flip on x only.
        self.assertEqual(magnifier_rect(1850, 100, 120, 100, SCREEN), Rect(1706, 124, 120, 100))
        # Flip goes off the monitor: clamp.
        self.assertEqual(magnifier_rect(10, 1060, 120, 2000, SCREEN).y, 0)

    def test_fit_and_map(self) -> None:
        m = fit_image(1536, 864, 1920, 1080)
        self.assertEqual(m, DrawMap(0, 0, 1536, 864, 1920, 1080))
        self.assertEqual(widget_to_image(767.5, 0, m), (959, 0))
        self.assertEqual(widget_to_image(-5, 9999, m), (0, 1079))
        self.assertEqual(image_to_widget(960, 540, m), (768.0, 432.0))
        # Letterbox: 1920x1080 image in a 1600x1200 widget.
        lb = fit_image(1600, 1200, 1920, 1080)
        self.assertAlmostEqual(lb.ox, 0.0)
        self.assertAlmostEqual(lb.dw, 1600.0)
        self.assertAlmostEqual(lb.dh, 900.0)
        self.assertAlmostEqual(lb.oy, 150.0)
        self.assertEqual(widget_to_image(0, 150, lb), (0, 0))
        self.assertEqual(widget_to_image(1599.9, 1049.9, lb), (1919, 1079))
        self.assertEqual(widget_to_image(800, 10, lb), (960, 0))
        x, y = image_to_widget(960, 540, lb)
        self.assertAlmostEqual(x, 800.0)
        self.assertAlmostEqual(y, 600.0)
        # Within 1%: no letterbox.
        self.assertEqual(fit_image(1920, 1085, 1920, 1080).oy, 0)

    def test_stream_to_layout(self) -> None:
        r = Rect(100, 200, 500, 250)
        x, y, w, h = stream_to_layout(r, (1536, 0), (1536, 864), (1920, 1080))
        self.assertAlmostEqual(x, 1536 + 80.0)
        self.assertAlmostEqual(y, 160.0)
        self.assertAlmostEqual(w, 400.0)
        self.assertAlmostEqual(h, 200.0)


if __name__ == "__main__":
    unittest.main()
