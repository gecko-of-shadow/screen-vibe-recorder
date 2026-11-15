"""Tests for linux/desktop_recorder/selector_model.py (pure, runs on any OS)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.geometry import Rect  # noqa: E402
from desktop_recorder.selector_model import Outcome, SelectorModel, SelectorOptions  # noqa: E402

BOUNDS = Rect(0, 0, 1920, 1080)
WINDOW_TOP = Rect(100, 100, 400, 300)
WINDOW_BACK = Rect(50, 50, 1000, 800)


def make(windows: list[Rect] | None = None, monitors: list[Rect] | None = None) -> SelectorModel:
    return SelectorModel(BOUNDS, monitors if monitors is not None else [BOUNDS],
                         windows if windows is not None else [WINDOW_TOP, WINDOW_BACK],
                         SelectorOptions(crosshair=False, magnifier=True, position=False))


def drag(m: SelectorModel, x0: int, y0: int, x1: int, y1: int) -> Outcome:
    m.press(x0, y0, 1)
    m.motion((x0 + x1) // 2, (y0 + y1) // 2, False, False)
    m.motion(x1, y1, False, False)
    return m.release(x1, y1, 1)


class SelectorModelTests(unittest.TestCase):
    def test_drag_accepts_on_release(self) -> None:
        m = make()
        out = drag(m, 440, 172, 1421, 601)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, Rect(440, 172, 982, 430))

    def test_one_motion_drag_accepts(self) -> None:
        m = make()
        m.press(150, 150, 1)
        m.motion(349, 299, False, False)
        self.assertEqual(m.mode, "creating")
        self.assertEqual(m.selection, Rect(150, 150, 200, 150))
        out = m.release(349, 299, 1)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, Rect(150, 150, 200, 150))

    def test_small_move_is_click(self) -> None:
        m = make()
        m.press(200, 200, 1)
        m.motion(203, 197, False, False)
        self.assertEqual(m.mode, "pending")
        out = m.release(203, 197, 1)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, WINDOW_TOP)

    def test_click_selects_hover_window(self) -> None:
        m = make()
        m.motion(700, 600, False, False)
        self.assertEqual(m.hover, WINDOW_BACK)
        m.motion(200, 200, False, False)
        self.assertEqual(m.hover, WINDOW_TOP)
        m.press(200, 200, 1)
        out = m.release(200, 200, 1)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, WINDOW_TOP)

    def test_click_window_is_made_even_and_clipped(self) -> None:
        m = make(windows=[Rect(-10, 1000, 301, 201)])
        m.press(5, 1010, 1)
        out = m.release(5, 1010, 1)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, Rect(0, 1000, 290, 80))

    def test_press_sets_hover_without_motion(self) -> None:
        m = make()
        self.assertIsNone(m.hover)
        m.press(700, 600, 1)
        self.assertEqual(m.hover, WINDOW_BACK)
        out = m.release(700, 600, 1)
        self.assertEqual(out.kind, "accept")
        self.assertEqual(out.rect, WINDOW_BACK)

    def test_click_without_window_does_nothing(self) -> None:
        m = make()
        m.press(1500, 1000, 1)
        out = m.release(1500, 1000, 1)
        self.assertEqual(out.kind, "none")
        self.assertEqual(m.mode, "hover")
        self.assertIsNone(m.selection)

    def test_shift_square(self) -> None:
        m = make()
        m.press(100, 100, 1)
        m.motion(300, 160, True, False)
        self.assertEqual(m.selection, Rect(100, 100, 201, 201))
        m.motion(20, 160, True, False)
        self.assertEqual(m.selection, Rect(20, 100, 81, 81))
        out = m.release(20, 160, 1)
        self.assertEqual(out.rect, Rect(20, 100, 80, 80))

    def test_ctrl_moves_anchor_not_on_first_move(self) -> None:
        m = make()
        m.press(100, 100, 1)
        # First move with Ctrl: Ctrl is ignored, the anchor stays.
        m.motion(200, 200, False, True)
        self.assertEqual(m.selection, Rect(100, 100, 101, 101))
        # Later move with Ctrl: the anchor follows the mouse delta.
        m.motion(250, 230, False, True)
        self.assertEqual(m.selection, Rect(150, 130, 101, 101))
        # Without Ctrl: the anchor stays at the moved place.
        m.motion(350, 330, False, False)
        self.assertEqual(m.selection, Rect(150, 130, 201, 201))

    def test_right_click_rules(self) -> None:
        # In creating: back to prev, stays open.
        m = make()
        drag_out = m.press(10, 10, 1)
        self.assertEqual(drag_out.kind, "redraw")
        m.motion(600, 500, False, False)
        self.assertEqual(m.mode, "creating")
        out = m.press(600, 500, 3)
        self.assertEqual(out.kind, "redraw")
        self.assertEqual(m.mode, "hover")
        self.assertIsNone(m.selection)

        # With a selection from before the press: in pending, back to that selection.
        m = make()
        m.press(10, 10, 1)
        m.motion(600, 500, False, False)
        m.press(600, 500, 3)
        self.assertIsNone(m.selection)  # prev of that drag was None
        m.selection = Rect(10, 10, 100, 100)
        m.press(1500, 1000, 1)
        self.assertEqual(m.mode, "pending")
        out = m.press(1500, 1000, 3)
        self.assertEqual(out.kind, "redraw")
        self.assertEqual(m.mode, "hover")
        self.assertEqual(m.selection, Rect(10, 10, 100, 100))

        # With a selection in hover mode: the selection is cleared.
        out = m.press(1500, 1000, 3)
        self.assertEqual(out.kind, "redraw")
        self.assertIsNone(m.selection)

        # Else: cancel.
        out = m.press(1500, 1000, 3)
        self.assertEqual(out.kind, "cancel")

    def test_escape_enter_space_tilde(self) -> None:
        mons = [Rect(0, 0, 1920, 1080), Rect(1920, 0, 1281, 1024)]
        bounds_model = SelectorModel(Rect(0, 0, 3201, 1080), mons, [WINDOW_TOP], SelectorOptions(False, False, False))
        self.assertEqual(bounds_model.key("Escape", False, False).kind, "cancel")

        out = bounds_model.key("space", False, False)
        self.assertEqual((out.kind, out.rect), ("accept", Rect(0, 0, 3200, 1080)))

        bounds_model.motion(2000, 500, False, False)
        out = bounds_model.key("grave", False, False)
        self.assertEqual((out.kind, out.rect), ("accept", Rect(1920, 0, 1280, 1024)))
        out = bounds_model.key("asciitilde", True, False)
        self.assertEqual(out.rect, Rect(1920, 0, 1280, 1024))

        # Cursor not on a monitor: the bounds.
        bounds_model.motion(2000, 1050, False, False)
        out = bounds_model.key("grave", False, False)
        self.assertEqual(out.rect, Rect(0, 0, 3200, 1080))

        # Enter with nothing: none. With hover: hover. With a selection: the selection.
        self.assertEqual(bounds_model.key("Return", False, False).kind, "none")
        bounds_model.motion(150, 150, False, False)
        out = bounds_model.key("KP_Enter", False, False)
        self.assertEqual((out.kind, out.rect), ("accept", WINDOW_TOP))
        bounds_model.selection = Rect(7, 9, 41, 33)
        out = bounds_model.key("Return", False, False)
        self.assertEqual((out.kind, out.rect), ("accept", Rect(7, 9, 40, 32)))

    def test_arrows_warp_1_and_10(self) -> None:
        m = make()
        m.motion(500, 500, False, False)
        out = m.key("Right", False, False)
        self.assertEqual((out.kind, out.dx, out.dy), ("warp", 1, 0))
        self.assertEqual(m.cursor, (501, 500))
        # The shell's motion at model.cursor after the warp changes nothing.
        before = (m.cursor, m.hover, m.selection, m.mode)
        m.motion(*m.cursor, False, False)
        self.assertEqual((m.cursor, m.hover, m.selection, m.mode), before)
        out = m.key("Down", True, False)
        self.assertEqual((out.kind, out.dx, out.dy), ("warp", 0, 10))
        self.assertEqual(m.cursor, (501, 510))
        out = m.key("Left", True, False)
        self.assertEqual(m.cursor, (491, 510))
        out = m.key("Up", False, False)
        self.assertEqual(m.cursor, (491, 509))
        # The cursor stays inside the bounds.
        m.motion(1915, 2, False, False)
        out = m.key("Right", True, False)
        self.assertEqual((out.dx, m.cursor), (4, (1919, 2)))
        out = m.key("Up", True, False)
        self.assertEqual((out.dy, m.cursor), (-2, (1919, 0)))
        # A warp also updates hover, like a mouse move.
        m.motion(98, 150, False, False)
        self.assertEqual(m.hover, WINDOW_BACK)
        m.key("Right", True, False)
        self.assertEqual(m.hover, WINDOW_TOP)

    def test_cmp_toggle_options(self) -> None:
        opts = SelectorOptions(crosshair=False, magnifier=True, position=False)
        m = SelectorModel(BOUNDS, [BOUNDS], [], opts)
        self.assertEqual(m.key("c", False, False).kind, "redraw")
        self.assertEqual(m.key("M", True, False).kind, "redraw")
        self.assertEqual(m.key("p", False, False).kind, "redraw")
        self.assertEqual(m.options, SelectorOptions(crosshair=True, magnifier=False, position=True))
        m.key("C", True, False)
        self.assertFalse(m.options.crosshair)
        # The model changes the caller's object, so the shell can save it.
        self.assertIs(m.options, opts)
        self.assertEqual(opts, SelectorOptions(crosshair=False, magnifier=False, position=True))
        self.assertEqual(m.key("x", False, False).kind, "none")

    def test_accept_is_even_and_clipped(self) -> None:
        m = make()
        m.press(1800, 1000, 1)
        m.motion(2500, 1500, False, False)
        self.assertEqual(m.selection, Rect(1800, 1000, 120, 80))
        out = m.release(2500, 1500, 1)
        self.assertEqual(out.rect, Rect(1800, 1000, 120, 80))
        m = make()
        out = drag(m, 10, 10, 110, 60)  # 101 x 51
        self.assertEqual(out.rect, Rect(10, 10, 100, 50))
        self.assertEqual(out.rect.w % 2, 0)

    def test_tiny_drag_not_accepted(self) -> None:
        # A drag that leaves only 1 px inside the bounds is not accepted. The selector stays open.
        m = make(windows=[])
        m.press(1919, 500, 1)
        m.motion(2100, 500, False, False)
        self.assertEqual(m.mode, "creating")
        self.assertEqual(m.selection, Rect(1919, 500, 1, 1))
        out = m.release(2100, 500, 1)
        self.assertNotEqual(out.kind, "accept")
        self.assertNotEqual(out.kind, "cancel")
        self.assertEqual(m.mode, "hover")
        self.assertIsNone(m.selection)

    def test_other_buttons_do_nothing(self) -> None:
        m = make()
        self.assertEqual(m.press(10, 10, 2).kind, "none")
        self.assertEqual(m.release(10, 10, 3).kind, "none")
        self.assertEqual(m.mode, "hover")


if __name__ == "__main__":
    unittest.main()
