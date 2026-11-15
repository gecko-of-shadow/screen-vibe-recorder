"""KeyRepeatFilter in hotkey_x11.py (DESIGN.md 8.5, 14.1). Pure: runs on Windows too."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linux"))

from desktop_recorder.hotkey_x11 import KeyPress, KeyRelease, KeyRepeatFilter, keysym_for, x_modifiers  # noqa: E402


class KeyRepeatFilterTests(unittest.TestCase):
    def test_repeat_filter(self) -> None:
        f = KeyRepeatFilter()
        self.assertTrue(f.event(2))
        self.assertFalse(f.event(2))
        self.assertFalse(f.event(2))
        self.assertFalse(f.event(3))
        self.assertTrue(f.event(2))

    def test_repeat_pairs_without_detectable_repeat(self) -> None:
        # No detectable auto-repeat: press, then release + press pairs with one time stamp.
        f = KeyRepeatFilter()
        self.assertTrue(f.event(2, 1000))
        self.assertFalse(f.event(3, 1500))
        self.assertFalse(f.event(2, 1500))
        self.assertFalse(f.event(3, 1540))
        self.assertFalse(f.event(2, 1541))
        self.assertFalse(f.event(3, 1700))
        # A real new press after the real release fires again.
        self.assertTrue(f.event(2, 2500))

    def test_release_without_press(self) -> None:
        f = KeyRepeatFilter()
        self.assertFalse(f.event(KeyRelease))
        self.assertTrue(f.event(KeyPress))
        self.assertFalse(f.event(KeyPress))

    def test_other_event_kinds_do_nothing(self) -> None:
        f = KeyRepeatFilter()
        self.assertFalse(f.event(4))
        self.assertTrue(f.event(KeyPress))

    def test_modifier_and_keysym_map(self) -> None:
        # Win+Shift = 12 gives Mod4Mask | ShiftMask.
        self.assertEqual(x_modifiers(12), 64 | 1)
        self.assertEqual(keysym_for("D"), ord("D"))
        self.assertEqual(keysym_for("F1"), 0xFFBE)
        self.assertEqual(keysym_for("F12"), 0xFFC9)
        self.assertEqual(keysym_for("?"), 0)


if __name__ == "__main__":
    unittest.main()
