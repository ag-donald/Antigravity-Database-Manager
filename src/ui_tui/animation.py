"""
Animated screen transitions for the TUI.

UX Best Practices enforced:
  - Animations have purpose (feedback, orientation) — not decoration
  - Short durations for UI transitions to feel responsive
  - Animations can be skipped/cancelled to never block the user
"""

from __future__ import annotations

import time
from typing import Optional, Callable


# ==============================================================================
# EASING FUNCTIONS
# ==============================================================================

def ease_out_cubic(t: float) -> float:
    """Cubic ease-out — natural deceleration (UX recommended default)."""
    return 1 - (1 - t) ** 3


# Type alias for easing functions
EasingFn = Callable[[float], float]


# ==============================================================================
# SCREEN TRANSITIONS — Animated Push/Pop
# ==============================================================================

class ScreenTransition:
    """
    Interpolates between two screen frames for animated transitions.

    Uses a vertical wipe (line-by-line reveal) which is fully ANSI-safe
    since it always uses complete lines — never slicing within a line.

    UX Best Practice: Screen transitions provide spatial continuity,
    helping users understand navigation direction (push = forward,
    pop = backward). The wipe is fast (100ms) to feel responsive.
    """

    def __init__(self, old_frame: list[str], new_frame: list[str],
                 direction: str = "push", duration: float = 0.10,
                 easing: Optional[EasingFn] = None) -> None:
        self.old_frame = list(old_frame)
        self.new_frame = list(new_frame)
        self.direction = direction  # "push" or "pop"
        self.duration = max(0.01, duration)
        self.easing = easing or ease_out_cubic
        self.start_time = time.monotonic()

    @property
    def is_complete(self) -> bool:
        return (time.monotonic() - self.start_time) >= self.duration

    @property
    def progress(self) -> float:
        elapsed = time.monotonic() - self.start_time
        t = min(1.0, elapsed / self.duration)
        return self.easing(t)

    def render(self, width: int, height: int) -> list[str]:
        """Render the interpolated transition frame using vertical wipe."""
        p = self.progress

        if p >= 1.0:
            return self.new_frame[:height]

        # Vertical wipe: reveal new-frame lines top-to-bottom (push)
        # or bottom-to-top (pop). Each line is a complete ANSI string,
        # so no escape-code slicing occurs.
        reveal_count = int(height * p)

        result: list[str] = []
        for i in range(height):
            old_line = self.old_frame[i] if i < len(self.old_frame) else " " * width
            new_line = self.new_frame[i] if i < len(self.new_frame) else " " * width

            if self.direction == "push":
                # Top-to-bottom reveal: lines 0..reveal_count show new
                result.append(new_line if i < reveal_count else old_line)
            else:
                # Bottom-to-top reveal: lines (height-reveal_count)..height show new
                threshold = height - reveal_count
                result.append(new_line if i >= threshold else old_line)

        return result

    def snap(self) -> list[str]:
        """Immediately finish the transition and return the final frame."""
        return list(self.new_frame)


