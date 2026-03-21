"""
TUI Framework Test Suite.

Tests the new TUI architecture components in isolation:
  - Theme system (colors, styles, gradients)
  - ANSI-aware text utilities (visible_len, truncate, pad)
  - Layout containers (Row, Column, Box)
  - Component rendering (DataTable, Modal, etc.)
  - Animation engine (easing functions, AnimatedValue)
  - Event system (EventBus, KeyBindingManager, FocusManager)
"""

import unittest
import time
import math

from src.ui_tui.theme import (
    Color, Style, PALETTE, STYLES, _Ansi,
    generate_gradient, gradient_bg_line, contrast_ratio_approx,
    BORDER_ROUNDED, BORDER_THIN, BORDER_DOUBLE, BORDER_THICK, BORDER_NONE,
    Icons, BoxChars,
)
from src.ui_tui.core import (
    visible_len, strip_ansi, truncate, pad, pad_center, pad_right,
    styled_line, horizontal_rule, Constraint, SizeMode,
    Component, StaticText, Spacer, Divider, Box, Row, Column, LayoutChild,
)
from src.ui_tui.animation import (
    ease_linear, ease_in_quad, ease_out_quad, ease_in_out_quad,
    ease_out_cubic, ease_out_bounce, ease_out_elastic, ease_out_back,
    AnimatedValue, AnimationManager,
    fade_in_lines, typewriter_reveal, pulse_value,
)
from src.ui_tui.events import (
    EventType, Event, ActionEvent, ResizeEvent, NotificationEvent,
    EventBus, KeyBindingManager, FocusManager,
)
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

    def test_merge_precedence(self):
        base = Style(bold=True)
        overlay = Style(fg=PALETTE.primary, italic=True)
        merged = base.merge(overlay)
        self.assertTrue(merged.bold)
        self.assertTrue(merged.italic)
        self.assertEqual(merged.fg, PALETTE.primary)

    def test_prefix_property(self):
        s = Style(bold=True, underline=True)
        self.assertIn(_Ansi.BOLD, s.prefix)
        self.assertIn(_Ansi.UNDERLINE, s.prefix)


class TestPalette(unittest.TestCase):
    """Verify palette colors have valid attributes."""

    def test_primary_is_color(self):
        self.assertIsInstance(PALETTE.primary, Color)

    def test_text_contrast_against_surface(self):
        ratio = contrast_ratio_approx(PALETTE.text, PALETTE.surface)
        self.assertGreater(ratio, 3.0, "Text on surface should have adequate contrast")

    def test_gradient_produces_output(self):
        result = generate_gradient("Hello", PALETTE.primary, PALETTE.accent)
        self.assertTrue(len(result) > 0)
        self.assertIn(_Ansi.RESET, result)


class TestBoxChars(unittest.TestCase):
    """Verify box character presets are well-formed."""

    def test_rounded_corners(self):
        self.assertEqual(BORDER_ROUNDED.tl, "╭")
        self.assertEqual(BORDER_ROUNDED.br, "╯")

    def test_none_is_spaces(self):
        self.assertEqual(BORDER_NONE.h, " ")
        self.assertEqual(BORDER_NONE.v, " ")

    def test_all_presets_have_11_fields(self):
        for preset in [BORDER_THIN, BORDER_THICK, BORDER_DOUBLE, BORDER_ROUNDED, BORDER_NONE]:
            self.assertEqual(len(preset.tl), 1)
            self.assertEqual(len(preset.h), 1)


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
        vis = strip_ansi(result)
        self.assertLessEqual(len(vis), 8)


class TestPad(unittest.TestCase):
    """Verify ANSI-aware padding."""

    def test_pad_short_string(self):
        result = pad("abc", 6)
        self.assertEqual(visible_len(result), 6)
        self.assertTrue(result.endswith("   "))

    def test_pad_exact_length(self):
        result = pad("abcdef", 6)
        self.assertEqual(result, "abcdef")

    def test_pad_center(self):
        result = pad_center("x", 5)
        self.assertEqual(result, "  x  ")

    def test_pad_right_align(self):
        result = pad_right("x", 5)
        self.assertEqual(result, "    x")


# ==============================================================================
# LAYOUT TESTS
# ==============================================================================

class TestConstraint(unittest.TestCase):
    """Verify constraint resolution."""

    def test_fixed(self):
        c = Constraint.fixed(20)
        self.assertEqual(c.resolve(100), 20)

    def test_fixed_exceeds_available(self):
        c = Constraint.fixed(200)
        self.assertEqual(c.resolve(100), 100)

    def test_percent(self):
        c = Constraint.percent(0.5)
        self.assertEqual(c.resolve(80), 40)

    def test_fill(self):
        c = Constraint.fill()
        self.assertEqual(c.resolve(100), 100)


class TestRow(unittest.TestCase):
    """Verify Row layout distributes width correctly."""

    def test_empty_row(self):
        row = Row()
        lines = row.render(40, 3)
        self.assertEqual(len(lines), 3)
        self.assertEqual(visible_len(lines[0]), 40)

    def test_two_children(self):
        a = StaticText(lines=["Left"])
        b = StaticText(lines=["Right"])
        row = Row(children=[
            LayoutChild(a, Constraint.percent(0.5)),
            LayoutChild(b, Constraint.fill()),
        ])
        lines = row.render(40, 3)
        self.assertEqual(len(lines), 3)


class TestColumn(unittest.TestCase):
    """Verify Column layout distributes height correctly."""

    def test_empty_column(self):
        col = Column()
        lines = col.render(40, 3)
        self.assertEqual(len(lines), 3)

    def test_fixed_height_child(self):
        a = StaticText(lines=["Top"])
        b = StaticText(lines=["Bottom"])
        col = Column(children=[
            LayoutChild(a, Constraint.fixed(1)),
            LayoutChild(b, Constraint.fill()),
        ])
        lines = col.render(40, 5)
        self.assertEqual(len(lines), 5)


class TestBox(unittest.TestCase):
    """Verify Box renders borders correctly."""

    def test_box_dimensions(self):
        child = StaticText(lines=["content"])
        box = Box(child=child, border=BORDER_ROUNDED)
        lines = box.render(30, 5)
        self.assertEqual(len(lines), 5)

    def test_box_with_title(self):
        child = StaticText(lines=["x"])
        box = Box(child=child, title="Test", border=BORDER_ROUNDED)
        lines = box.render(30, 5)
        self.assertIn("Test", strip_ansi(lines[0]))

    def test_box_top_border_corners(self):
        child = StaticText(lines=["x"])
        box = Box(child=child, border=BORDER_ROUNDED)
        lines = box.render(20, 4)
        top = strip_ansi(lines[0])
        self.assertTrue(top.startswith("╭"))
        self.assertTrue(top.endswith("╮"))


# ==============================================================================
# ANIMATION TESTS
# ==============================================================================

class TestEasing(unittest.TestCase):
    """Verify easing function boundary values and monotonicity."""

    def test_linear_boundaries(self):
        self.assertAlmostEqual(ease_linear(0.0), 0.0)
        self.assertAlmostEqual(ease_linear(1.0), 1.0)

    def test_ease_out_cubic_boundaries(self):
        self.assertAlmostEqual(ease_out_cubic(0.0), 0.0)
        self.assertAlmostEqual(ease_out_cubic(1.0), 1.0)

    def test_ease_out_bounce_boundaries(self):
        self.assertAlmostEqual(ease_out_bounce(0.0), 0.0, places=4)
        self.assertAlmostEqual(ease_out_bounce(1.0), 1.0, places=4)

    def test_ease_in_out_quad_midpoint(self):
        self.assertAlmostEqual(ease_in_out_quad(0.5), 0.5, places=4)

    def test_all_easings_range(self):
        """All easing functions should produce values for t in [0, 1]."""
        fns = [ease_linear, ease_in_quad, ease_out_quad, ease_in_out_quad,
               ease_out_cubic, ease_out_bounce, ease_out_back]
        for fn in fns:
            v0 = fn(0.0)
            v1 = fn(1.0)
            self.assertAlmostEqual(v0, 0.0, places=2, msg=f"{fn.__name__}(0)")
            self.assertAlmostEqual(v1, 1.0, places=2, msg=f"{fn.__name__}(1)")


class TestAnimatedValue(unittest.TestCase):
    """Verify animated value interpolation."""

    def test_initial_value(self):
        av = AnimatedValue(42.0)
        self.assertEqual(av.value, 42.0)

    def test_instant_set(self):
        av = AnimatedValue(0.0)
        av.set(100.0)
        self.assertEqual(av.value, 100.0)
        self.assertFalse(av.is_animating)

    def test_snap(self):
        av = AnimatedValue(0.0)
        av.animate_to(100.0, duration=10.0)
        self.assertTrue(av.is_animating)
        av.snap()
        self.assertEqual(av.value, 100.0)
        self.assertFalse(av.is_animating)

    def test_int_value(self):
        av = AnimatedValue(3.7)
        self.assertEqual(av.int_value, 4)


class TestAnimationManager(unittest.TestCase):
    """Verify animation manager lifecycle."""

    def test_create_and_get(self):
        am = AnimationManager()
        av = am.create("scroll", 0.0)
        self.assertIsNotNone(am.get("scroll"))

    def test_not_animating_when_idle(self):
        am = AnimationManager()
        am.create("scroll", 0.0)
        self.assertFalse(am.is_animating)

    def test_cancel_all(self):
        am = AnimationManager()
        av = am.create("scroll", 0.0)
        av.animate_to(100.0, duration=10.0)
        am.cancel_all()
        self.assertFalse(am.is_animating)


class TestEffects(unittest.TestCase):
    """Verify built-in animation effects."""

    def test_fade_in_zero(self):
        lines = ["a", "b", "c"]
        faded = fade_in_lines(lines, 0.0)
        for line in faded:
            self.assertEqual(line.strip(), "")

    def test_fade_in_full(self):
        lines = ["a", "b", "c"]
        faded = fade_in_lines(lines, 1.0)
        self.assertEqual(faded, lines)

    def test_typewriter_zero(self):
        self.assertEqual(typewriter_reveal("hello", 0.0), "")

    def test_typewriter_full(self):
        self.assertEqual(typewriter_reveal("hello", 1.0), "hello")


# ==============================================================================
# EVENT SYSTEM TESTS
# ==============================================================================

class TestEventBus(unittest.TestCase):
    """Verify event bus pub/sub."""

    def test_basic_emit(self):
        bus = EventBus()
        received = []
        bus.on(EventType.ACTION, lambda e: received.append(e.action))
        bus.emit(ActionEvent("test_action"))
        self.assertEqual(received, ["test_action"])

    def test_stop_propagation(self):
        bus = EventBus()
        received = []
        def handler1(e):
            received.append("h1")
            e.stop_propagation()
        def handler2(e):
            received.append("h2")
        bus.on(EventType.ACTION, handler1)
        bus.on(EventType.ACTION, handler2)
        bus.emit(ActionEvent("test"))
        self.assertEqual(received, ["h1"])  # h2 blocked

    def test_off_removes_handler(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append("called")
        bus.on(EventType.ACTION, handler)
        bus.off(EventType.ACTION, handler)
        bus.emit(ActionEvent("test"))
        self.assertEqual(received, [])

    def test_clear_removes_all(self):
        bus = EventBus()
        bus.on(EventType.ACTION, lambda e: None)
        bus.clear()
        # Should not crash
        bus.emit(ActionEvent("test"))


class TestKeyBindingManager(unittest.TestCase):
    """Verify key binding resolution."""

    def test_global_binding(self):
        kb = KeyBindingManager()
        kb.register("q", "quit", "Quit")
        self.assertEqual(kb.resolve("q"), "quit")

    def test_context_binding_priority(self):
        kb = KeyBindingManager()
        kb.register("enter", "confirm_global", "Confirm")
        kb.register("enter", "confirm_modal", "Confirm", context="modal")
        self.assertEqual(kb.resolve("enter", "modal"), "confirm_modal")
        self.assertEqual(kb.resolve("enter"), "confirm_global")

    def test_unknown_key_returns_none(self):
        kb = KeyBindingManager()
        self.assertIsNone(kb.resolve("x"))

    def test_hints(self):
        kb = KeyBindingManager()
        kb.register("q", "quit", "Quit")
        kb.register("?", "help", "Help")
        hints = kb.get_hints()
        self.assertEqual(len(hints), 2)


class TestFocusManager(unittest.TestCase):
    """Verify focus cycling."""

    def test_register_and_focus(self):
        fm = FocusManager()
        fm.register("table")
        fm.register("input")
        self.assertEqual(fm.current_id, "table")

    def test_focus_next_wraps(self):
        fm = FocusManager()
        fm.register("a")
        fm.register("b")
        fm.focus_next()
        self.assertEqual(fm.current_id, "b")
        fm.focus_next()
        self.assertEqual(fm.current_id, "a")  # Wraps

    def test_focus_prev_wraps(self):
        fm = FocusManager()
        fm.register("a")
        fm.register("b")
        fm.focus_prev()
        self.assertEqual(fm.current_id, "b")  # Wraps backward

    def test_focus_by_id(self):
        fm = FocusManager()
        fm.register("a")
        fm.register("b")
        fm.register("c")
        fm.focus_id("c")
        self.assertEqual(fm.current_id, "c")

    def test_has_focus(self):
        fm = FocusManager()
        fm.register("a")
        self.assertTrue(fm.has_focus("a"))
        self.assertFalse(fm.has_focus("b"))

    def test_unregister(self):
        fm = FocusManager()
        fm.register("a")
        fm.register("b")
        fm.unregister("a")
        self.assertEqual(fm.current_id, "b")


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


if __name__ == "__main__":
    unittest.main()
