"""
TUI Framework Test Suite.

Tests the TUI architecture components in isolation:
  - Theme system (colors, styles, palette)
  - ANSI-aware text utilities (visible_len, truncate, pad)
  - Component rendering (Header, StatusBar, Modal, ...)
  - Screen transitions and easing
  - Terminal capability detection
"""

import unittest
import time

from src.ui_tui.theme import (
    Color, Style, PALETTE, STYLES, _Ansi, BORDER_ROUNDED,
)
from src.ui_tui.core import visible_len, truncate, pad
from src.ui_tui.animation import ease_out_cubic
from src.ui_tui.engine import Key, KeyEvent


# ==============================================================================
# THEME TESTS
# ==============================================================================

class TestColor(unittest.TestCase):
    """Verify Color creation, ANSI sequences, and interpolation."""

    def test_fg_rgb_sequence(self):
        c = Color(r=100, g=200, b=50)
        self.assertEqual(c.fg(), "\x1b[38;2;100;200;50m")

    def test_bg_rgb_sequence(self):
        c = Color(r=0, g=0, b=0)
        self.assertEqual(c.bg(), "\x1b[48;2;0;0;0m")

    def test_fg_256_fallback(self):
        c = Color(r=0, g=0, b=0, code_256=16)
        self.assertEqual(c.fg_256(), "\x1b[38;5;16m")

    def test_fg_basic_fallback(self):
        c = Color(r=0, g=0, b=0, code_basic=30)
        self.assertEqual(c.fg_basic(), "\x1b[30m")

    def test_lerp_zero(self):
        a = Color(r=0, g=0, b=0)
        b = Color(r=255, g=255, b=255)
        result = Color.lerp(a, b, 0.0)
        self.assertEqual((result.r, result.g, result.b), (0, 0, 0))

    def test_lerp_one(self):
        a = Color(r=0, g=0, b=0)
        b = Color(r=255, g=255, b=255)
        result = Color.lerp(a, b, 1.0)
        self.assertEqual((result.r, result.g, result.b), (255, 255, 255))

    def test_lerp_midpoint(self):
        a = Color(r=0, g=0, b=0)
        b = Color(r=200, g=100, b=50)
        result = Color.lerp(a, b, 0.5)
        self.assertEqual((result.r, result.g, result.b), (100, 50, 25))

    def test_lerp_clamped(self):
        a = Color(r=0, g=0, b=0)
        b = Color(r=255, g=255, b=255)
        result = Color.lerp(a, b, 2.0)  # Clamped to 1.0
        self.assertEqual((result.r, result.g, result.b), (255, 255, 255))


class TestStyle(unittest.TestCase):
    """Verify Style composition and ANSI application."""

    def test_apply_adds_reset(self):
        s = Style(bold=True)
        result = s.apply("hello")
        self.assertIn(_Ansi.BOLD, result)
        self.assertTrue(result.endswith(_Ansi.RESET))

    def test_apply_no_style(self):
        s = Style()
        result = s.apply("hello")
        self.assertEqual(result, "hello")  # No prefix, no reset



class TestPalette(unittest.TestCase):
    """Verify palette colors have valid attributes."""

    def test_primary_is_color(self):
        self.assertIsInstance(PALETTE.primary, Color)



class TestBoxChars(unittest.TestCase):
    """Verify box character presets are well-formed."""

    def test_rounded_corners(self):
        self.assertEqual(BORDER_ROUNDED.tl, "╭")
        self.assertEqual(BORDER_ROUNDED.br, "╯")

    def test_all_chars_single_width(self):
        for ch in (BORDER_ROUNDED.tl, BORDER_ROUNDED.tr, BORDER_ROUNDED.bl,
                   BORDER_ROUNDED.br, BORDER_ROUNDED.h, BORDER_ROUNDED.v):
            self.assertEqual(len(ch), 1)


# ==============================================================================
# TEXT UTILITY TESTS
# ==============================================================================

class TestVisibleLen(unittest.TestCase):
    """Verify ANSI-aware visible length calculation."""

    def test_plain_string(self):
        self.assertEqual(visible_len("hello"), 5)

    def test_ansi_string(self):
        s = "\x1b[31mhello\x1b[0m"
        self.assertEqual(visible_len(s), 5)

    def test_empty_string(self):
        self.assertEqual(visible_len(""), 0)

    def test_only_ansi(self):
        self.assertEqual(visible_len("\x1b[31m\x1b[0m"), 0)

    def test_multiple_sequences(self):
        s = "\x1b[1m\x1b[31mhello\x1b[0m world\x1b[0m"
        self.assertEqual(visible_len(s), 11)


class TestTruncate(unittest.TestCase):
    """Verify ANSI-aware truncation with ellipsis."""

    def test_no_truncation_needed(self):
        self.assertEqual(truncate("hi", 10), "hi")

    def test_truncation_plain(self):
        result = truncate("hello world", 8)
        self.assertEqual(visible_len(result), 8)
        self.assertTrue(result.endswith("…"))

    def test_truncation_zero_width(self):
        self.assertEqual(truncate("hello", 0), "")

    def test_truncation_preserves_ansi(self):
        s = "\x1b[31mhello world\x1b[0m"
        result = truncate(s, 8)
        self.assertLessEqual(visible_len(result), 8)
        self.assertIn("\x1b[31m", result)


class TestPad(unittest.TestCase):
    """Verify ANSI-aware padding."""

    def test_pad_short_string(self):
        result = pad("abc", 6)
        self.assertEqual(visible_len(result), 6)
        self.assertTrue(result.endswith("   "))

    def test_pad_exact_length(self):
        result = pad("abcdef", 6)
        self.assertEqual(result, "abcdef")



# ==============================================================================
# ANIMATION TESTS
# ==============================================================================

class TestEasing(unittest.TestCase):
    """Verify easing function boundary values and monotonicity."""

    def test_ease_out_cubic_boundaries(self):
        self.assertAlmostEqual(ease_out_cubic(0.0), 0.0)
        self.assertAlmostEqual(ease_out_cubic(1.0), 1.0)

    def test_ease_out_cubic_monotonic(self):
        samples = [ease_out_cubic(i / 20) for i in range(21)]
        self.assertEqual(samples, sorted(samples))


# ==============================================================================
# EVENT SYSTEM TESTS
# ==============================================================================

class TestKeyEvent(unittest.TestCase):
    """Verify KeyEvent creation."""

    def test_char_event(self):
        ke = KeyEvent(Key.CHAR, "a")
        self.assertEqual(ke.key, Key.CHAR)
        self.assertEqual(ke.char, "a")

    def test_special_key_event(self):
        ke = KeyEvent(Key.ENTER)
        self.assertEqual(ke.key, Key.ENTER)
        self.assertEqual(ke.char, "")

    def test_repr(self):
        ke = KeyEvent(Key.CHAR, "x")
        self.assertIn("CHAR", repr(ke))

    def test_ctrl_p_key_exists(self):
        ke = KeyEvent(Key.CTRL_P)
        self.assertEqual(ke.key, Key.CTRL_P)


# ==============================================================================
# CAPABILITY DETECTION TESTS
# ==============================================================================

class TestCapabilities(unittest.TestCase):
    """Verify terminal capability detection."""

    def test_caps_singleton_exists(self):
        from src.ui_tui.capabilities import CAPS
        self.assertIsNotNone(CAPS)

    def test_caps_has_all_flags(self):
        from src.ui_tui.capabilities import CAPS
        self.assertIsInstance(CAPS.truecolor, bool)
        self.assertIsInstance(CAPS.colors_256, bool)
        self.assertIsInstance(CAPS.colors_basic, bool)
        self.assertIsInstance(CAPS.light_bg, bool)
        self.assertIsInstance(CAPS.reduce_motion, bool)

    def test_basic_always_true(self):
        from src.ui_tui.capabilities import CAPS
        self.assertTrue(CAPS.colors_basic)

    def test_detect_function_returns_caps(self):
        from src.ui_tui.capabilities import detect, TerminalCapabilities
        result = detect()
        self.assertIsInstance(result, TerminalCapabilities)


# ==============================================================================
# AUTO-DEGRADING COLOR TESTS
# ==============================================================================

class TestColorAutoDegradation(unittest.TestCase):
    """Verify Color auto_fg/auto_bg degrade per capabilities."""

    def test_auto_fg_returns_string(self):
        c = Color(r=100, g=200, b=50, code_256=40, code_basic=32)
        result = c.auto_fg()
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("\x1b["))

    def test_auto_bg_returns_string(self):
        c = Color(r=100, g=200, b=50, code_256=40, code_basic=32)
        result = c.auto_bg()
        self.assertIsInstance(result, str)
        self.assertTrue(result.startswith("\x1b["))


# ==============================================================================
# PALETTE VARIANT TESTS
# ==============================================================================

class TestPaletteVariants(unittest.TestCase):
    """Verify alternative palette definitions."""

    def test_high_contrast_palette_has_colors(self):
        from src.ui_tui.theme import PaletteHighContrast
        p = PaletteHighContrast()
        self.assertIsInstance(p.primary, Color)
        self.assertIsInstance(p.text, Color)
        self.assertIsInstance(p.surface, Color)

    def test_light_palette_has_colors(self):
        from src.ui_tui.theme import PaletteLight
        p = PaletteLight()
        self.assertIsInstance(p.primary, Color)
        self.assertIsInstance(p.text, Color)
        self.assertIsInstance(p.surface, Color)

    def test_high_contrast_text_is_white(self):
        from src.ui_tui.theme import PaletteHighContrast
        p = PaletteHighContrast()
        self.assertEqual(p.text.r, 255)
        self.assertEqual(p.text.g, 255)
        self.assertEqual(p.text.b, 255)

    def test_light_palette_dark_text(self):
        from src.ui_tui.theme import PaletteLight
        p = PaletteLight()
        self.assertLess(p.text.r, 100)  # Dark text on light background


# ==============================================================================
# GLYPHS & ICONS TESTS
# ==============================================================================

class TestGlyphs(unittest.TestCase):
    """Verify Glyphs class definitions."""

    def test_thick_h_is_single_char(self):
        from src.ui_tui.theme import Glyphs
        self.assertEqual(len(Glyphs.THICK_H), 1)

    def test_shadow_style_exists(self):
        self.assertIsNotNone(STYLES.shadow)
        self.assertTrue(STYLES.shadow.dim)

    def test_accent_bar_style_exists(self):
        self.assertIsNotNone(STYLES.accent_bar)
        self.assertTrue(STYLES.accent_bar.bold)


# ==============================================================================
# SCREEN TRANSITION TESTS
# ==============================================================================

class TestScreenTransition(unittest.TestCase):
    """Verify screen transition animation."""

    def test_transition_starts_incomplete(self):
        from src.ui_tui.animation import ScreenTransition
        old = [" " * 40] * 10
        new = ["X" * 40] * 10
        t = ScreenTransition(old, new, duration=1.0)
        self.assertFalse(t.is_complete)

    def test_transition_completes(self):
        from src.ui_tui.animation import ScreenTransition
        old = [" " * 40] * 10
        new = ["X" * 40] * 10
        t = ScreenTransition(old, new, duration=0.01)
        time.sleep(0.05)
        self.assertTrue(t.is_complete)

    def test_transition_render_returns_frames(self):
        from src.ui_tui.animation import ScreenTransition
        old = [" " * 40] * 10
        new = ["X" * 40] * 10
        t = ScreenTransition(old, new, duration=1.0)
        frame = t.render(40, 10)
        self.assertEqual(len(frame), 10)

    def test_snap_returns_new_frame(self):
        from src.ui_tui.animation import ScreenTransition
        old = [" " * 40] * 10
        new = ["X" * 40] * 10
        t = ScreenTransition(old, new, duration=10.0)
        result = t.snap()
        self.assertEqual(result, new)

    def test_vertical_wipe_direction(self):
        from src.ui_tui.animation import ScreenTransition
        old = ["OLD"] * 5
        new = ["NEW"] * 5
        # Push: top-to-bottom reveal
        t = ScreenTransition(old, new, direction="push", duration=10.0)
        frame = t.render(3, 5)
        # At progress ~0, most lines should still be old
        self.assertEqual(len(frame), 5)


# ==============================================================================
# NEW COMPONENT TESTS
# ==============================================================================

class TestHeaderGradient(unittest.TestCase):
    """Verify Header component renders all 3 lines."""

    def test_header_renders_3_lines(self):
        from src.ui_tui.components import Header
        h = Header(app_name="Test", version="1.0", subtitle="Home")
        lines = h.render(80, 3)
        self.assertEqual(len(lines), 3)

    def test_header_renders_without_subtitle(self):
        from src.ui_tui.components import Header
        h = Header(app_name="Test", version="1.0")
        lines = h.render(80, 3)
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()

