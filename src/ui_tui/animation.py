"""
Animation Engine for the TUI.

Provides a frame-based animation system for smooth, lively interfaces:
  - 20+ easing functions for natural motion
  - AnimatedValue for interpolated numeric properties
  - Transition controller for property animations
  - AnimationManager for coordinating multiple animations
  - Built-in effects (fade, slide, pulse, typewriter)

UX Best Practices enforced:
  - Animations have purpose (feedback, orientation, delight) — not decoration
  - Ease-in-out for natural-feeling motion (matches physical world expectations)
  - Short durations (150-300ms) for UI transitions to feel responsive
  - Animations can be skipped/cancelled to never block the user
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Callable


# ==============================================================================
# EASING FUNCTIONS
# ==============================================================================

def ease_linear(t: float) -> float:
    """Linear interpolation — constant speed."""
    return t


def ease_in_quad(t: float) -> float:
    """Quadratic ease-in — starts slow, accelerates."""
    return t * t


def ease_out_quad(t: float) -> float:
    """Quadratic ease-out — starts fast, decelerates."""
    return 1 - (1 - t) * (1 - t)


def ease_in_out_quad(t: float) -> float:
    """Quadratic ease-in-out — smooth acceleration and deceleration."""
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2


def ease_in_cubic(t: float) -> float:
    """Cubic ease-in."""
    return t * t * t


def ease_out_cubic(t: float) -> float:
    """Cubic ease-out — natural deceleration (UX recommended default)."""
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    """Cubic ease-in-out — smooth natural motion."""
    if t < 0.5:
        return 4 * t * t * t
    return 1 - (-2 * t + 2) ** 3 / 2


def ease_in_quart(t: float) -> float:
    """Quartic ease-in."""
    return t * t * t * t


def ease_out_quart(t: float) -> float:
    """Quartic ease-out — sharp deceleration."""
    return 1 - (1 - t) ** 4


def ease_in_out_quart(t: float) -> float:
    """Quartic ease-in-out."""
    if t < 0.5:
        return 8 * t * t * t * t
    return 1 - (-2 * t + 2) ** 4 / 2


def ease_in_quint(t: float) -> float:
    """Quintic ease-in."""
    return t ** 5


def ease_out_quint(t: float) -> float:
    """Quintic ease-out."""
    return 1 - (1 - t) ** 5


def ease_in_out_quint(t: float) -> float:
    """Quintic ease-in-out."""
    if t < 0.5:
        return 16 * t ** 5
    return 1 - (-2 * t + 2) ** 5 / 2


def ease_out_bounce(t: float) -> float:
    """Bounce ease-out — playful bouncing effect at the end."""
    n1 = 7.5625
    d1 = 2.75
    if t < 1 / d1:
        return n1 * t * t
    elif t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    elif t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625 / d1
        return n1 * t * t + 0.984375


def ease_in_bounce(t: float) -> float:
    """Bounce ease-in."""
    return 1 - ease_out_bounce(1 - t)


def ease_in_out_bounce(t: float) -> float:
    """Bounce ease-in-out."""
    if t < 0.5:
        return (1 - ease_out_bounce(1 - 2 * t)) / 2
    return (1 + ease_out_bounce(2 * t - 1)) / 2


def ease_out_elastic(t: float) -> float:
    """Elastic ease-out — spring-like overshoot."""
    if t == 0 or t == 1:
        return t
    c4 = (2 * math.pi) / 3
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * c4) + 1


def ease_in_elastic(t: float) -> float:
    """Elastic ease-in."""
    if t == 0 or t == 1:
        return t
    c4 = (2 * math.pi) / 3
    return -(2 ** (10 * t - 10)) * math.sin((t * 10 - 10.75) * c4)


def ease_out_back(t: float) -> float:
    """Back ease-out — slight overshoot past target then return."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_in_back(t: float) -> float:
    """Back ease-in — pulls back before moving forward."""
    c1 = 1.70158
    c3 = c1 + 1
    return c3 * t * t * t - c1 * t * t


def ease_in_out_back(t: float) -> float:
    """Back ease-in-out."""
    c1 = 1.70158
    c2 = c1 * 1.525
    if t < 0.5:
        return ((2 * t) ** 2 * ((c2 + 1) * 2 * t - c2)) / 2
    return ((2 * t - 2) ** 2 * ((c2 + 1) * (t * 2 - 2) + c2) + 2) / 2


def ease_in_expo(t: float) -> float:
    """Exponential ease-in."""
    return 0 if t == 0 else 2 ** (10 * t - 10)


def ease_out_expo(t: float) -> float:
    """Exponential ease-out."""
    return 1 if t == 1 else 1 - 2 ** (-10 * t)


def ease_in_out_expo(t: float) -> float:
    """Exponential ease-in-out."""
    if t == 0:
        return 0
    if t == 1:
        return 1
    if t < 0.5:
        return 2 ** (20 * t - 10) / 2
    return (2 - 2 ** (-20 * t + 10)) / 2


def ease_in_circ(t: float) -> float:
    """Circular ease-in."""
    return 1 - math.sqrt(1 - t * t)


def ease_out_circ(t: float) -> float:
    """Circular ease-out."""
    return math.sqrt(1 - (t - 1) ** 2)


def ease_in_out_circ(t: float) -> float:
    """Circular ease-in-out."""
    if t < 0.5:
        return (1 - math.sqrt(1 - (2 * t) ** 2)) / 2
    return (math.sqrt(1 - (-2 * t + 2) ** 2) + 1) / 2


def ease_in_sine(t: float) -> float:
    """Sinusoidal ease-in."""
    return 1 - math.cos((t * math.pi) / 2)


def ease_out_sine(t: float) -> float:
    """Sinusoidal ease-out."""
    return math.sin((t * math.pi) / 2)


def ease_in_out_sine(t: float) -> float:
    """Sinusoidal ease-in-out — gentle, natural motion."""
    return -(math.cos(math.pi * t) - 1) / 2


# Type alias for easing functions
EasingFn = Callable[[float], float]

# Named presets — UX-recommended defaults
EASING_PRESETS: dict[str, EasingFn] = {
    "linear":         ease_linear,
    "ease_in":        ease_in_cubic,
    "ease_out":       ease_out_cubic,
    "ease_in_out":    ease_in_out_cubic,
    "bounce":         ease_out_bounce,
    "elastic":        ease_out_elastic,
    "back":           ease_out_back,
    "snap":           ease_out_quart,
    "gentle":         ease_in_out_sine,
}


# ==============================================================================
# ANIMATED VALUE — Interpolated Numeric Property
# ==============================================================================

class AnimatedValue:
    """
    A numeric value that smoothly transitions between states.

    UX Best Practice: Smooth value transitions prevent jarring visual jumps.
    Use for scroll positions, progress bars, opacity, and sizes.

    Usage::

        scroll = AnimatedValue(0)
        scroll.animate_to(100, duration=0.3, easing=ease_out_cubic)
        # In render loop:
        current = scroll.value  # Returns interpolated value
    """

    def __init__(self, initial: float = 0.0) -> None:
        self._current = initial
        self._start = initial
        self._target = initial
        self._start_time = 0.0
        self._duration = 0.0
        self._easing: EasingFn = ease_out_cubic
        self._animating = False

    @property
    def value(self) -> float:
        """Current interpolated value."""
        if not self._animating:
            return self._current
        self._update()
        return self._current

    @property
    def int_value(self) -> int:
        """Current value rounded to integer."""
        return int(round(self.value))

    @property
    def is_animating(self) -> bool:
        """Whether an animation is currently active."""
        if self._animating:
            self._update()
        return self._animating

    def set(self, value: float) -> None:
        """Instantly set the value (no animation)."""
        self._current = value
        self._target = value
        self._animating = False

    def animate_to(self, target: float, duration: float = 0.25,
                   easing: Optional[EasingFn] = None) -> None:
        """
        Begin animating toward the target value.

        Args:
            target: Destination value.
            duration: Animation duration in seconds.
            easing: Easing function (defaults to ease_out_cubic).
        """
        if abs(self._current - target) < 0.001:
            self._current = target
            self._animating = False
            return

        self._start = self._current
        self._target = target
        self._start_time = time.monotonic()
        self._duration = max(0.01, duration)
        self._easing = easing or ease_out_cubic
        self._animating = True

    def _update(self) -> None:
        """Advance the animation based on elapsed time."""
        if not self._animating:
            return

        elapsed = time.monotonic() - self._start_time
        if elapsed >= self._duration:
            self._current = self._target
            self._animating = False
            return

        t = elapsed / self._duration
        eased_t = self._easing(t)
        self._current = self._start + (self._target - self._start) * eased_t

    def snap(self) -> None:
        """Immediately finish any active animation."""
        self._current = self._target
        self._animating = False


# ==============================================================================
# TRANSITION — Named Property Animation
# ==============================================================================

@dataclass
class Transition:
    """
    A named animation transition for tracking purposes.

    UX Best Practice: Named transitions make it easy to cancel or replace
    specific animations without affecting others.
    """
    name: str
    animated_value: AnimatedValue
    on_complete: Optional[Callable[[], None]] = None

    @property
    def is_complete(self) -> bool:
        return not self.animated_value.is_animating


# ==============================================================================
# ANIMATION MANAGER — Coordinates All Active Animations
# ==============================================================================

class AnimationManager:
    """
    Central coordinator for all active animations.

    The main event loop should call ``tick()`` each frame to advance
    animations, and check ``is_animating`` to determine render timing.

    UX Best Practice: When animations are active, render at higher FPS
    for smoothness. When idle, reduce FPS to save CPU (adaptive frame rate).

    Usage::

        am = AnimationManager()
        scroll_anim = am.create("scroll", initial=0)
        scroll_anim.animate_to(100, duration=0.3)

        # In event loop:
        am.tick()
        if am.is_animating:
            render_at_60fps()
        else:
            render_on_input()
    """

    def __init__(self) -> None:
        self._transitions: dict[str, Transition] = {}
        self._on_frame_callbacks: list[Callable[[], None]] = []

    def create(self, name: str, initial: float = 0.0) -> AnimatedValue:
        """
        Create a tracked animated value.

        If a transition with this name already exists, its value is returned
        (allowing continuity of in-progress animations).
        """
        if name in self._transitions:
            return self._transitions[name].animated_value

        av = AnimatedValue(initial)
        self._transitions[name] = Transition(name=name, animated_value=av)
        return av

    def get(self, name: str) -> Optional[AnimatedValue]:
        """Retrieve a tracked animated value by name."""
        t = self._transitions.get(name)
        return t.animated_value if t else None

    def remove(self, name: str) -> None:
        """Remove a tracked animation."""
        self._transitions.pop(name, None)

    def tick(self) -> None:
        """
        Advance all active animations by one frame.

        Fires completion callbacks for finished transitions and removes them.
        Also calls all registered per-frame callbacks (for spinners, etc.).
        """
        completed: list[str] = []

        for name, transition in self._transitions.items():
            if transition.is_complete:
                completed.append(name)
                if transition.on_complete:
                    try:
                        transition.on_complete()
                    except Exception:
                        pass

        for name in completed:
            self._transitions.pop(name, None)

        for callback in self._on_frame_callbacks:
            try:
                callback()
            except Exception:
                pass

    def on_frame(self, callback: Callable[[], None]) -> None:
        """Register a callback to run every frame (for spinners, etc.)."""
        self._on_frame_callbacks.append(callback)

    def remove_frame_callback(self, callback: Callable[[], None]) -> None:
        """Remove a per-frame callback."""
        try:
            self._on_frame_callbacks.remove(callback)
        except ValueError:
            pass

    @property
    def is_animating(self) -> bool:
        """Whether any animations are currently active."""
        return any(
            not t.is_complete for t in self._transitions.values()
        )

    def cancel_all(self) -> None:
        """Cancel all active animations (snap to targets)."""
        for transition in self._transitions.values():
            transition.animated_value.snap()
        self._transitions.clear()

    def cancel(self, name: str) -> None:
        """Cancel a specific animation (snap to target)."""
        t = self._transitions.get(name)
        if t:
            t.animated_value.snap()
            self._transitions.pop(name, None)


# ==============================================================================
# BUILT-IN ANIMATION EFFECTS
# ==============================================================================

def fade_in_lines(lines: list[str], progress: float,
                  total_lines: int = 0) -> list[str]:
    """
    Fade-in effect: progressively reveals lines from top to bottom.

    UX Best Practice: Staggered reveals draw attention to new content
    without overwhelming the user with a sudden wall of text.
    """
    n = total_lines or len(lines)
    visible_count = int(n * max(0.0, min(1.0, progress)))
    result: list[str] = []
    for i, line in enumerate(lines):
        if i < visible_count:
            result.append(line)
        else:
            result.append(" " * len(line) if line else "")
    return result


def slide_in_horizontal(lines: list[str], progress: float,
                        width: int, from_right: bool = False) -> list[str]:
    """
    Slide-in effect: content slides in from left or right edge.

    UX Best Practice: Slide transitions provide spatial continuity,
    helping the user understand navigation direction.
    """
    offset = int(width * (1.0 - max(0.0, min(1.0, progress))))
    if from_right:
        return [" " * offset + line for line in lines]
    else:
        return [" " * max(0, width - offset) + line for line in lines]


def typewriter_reveal(text: str, progress: float) -> str:
    """
    Typewriter effect: progressively reveals characters.

    UX Best Practice: Typewriter effects add personality to important
    messages and guide the user's reading pace.
    """
    visible = int(len(text) * max(0.0, min(1.0, progress)))
    return text[:visible]


def pulse_value(base: float, amplitude: float, speed: float = 2.0) -> float:
    """
    Generate a pulsing value using sine wave.

    Useful for making elements glow or breathe.

    UX Best Practice: Subtle pulsing draws attention to important elements
    without being as aggressive as blinking.
    """
    t = time.monotonic()
    return base + amplitude * math.sin(t * speed * math.pi)
