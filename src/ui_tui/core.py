"""
Core TUI Framework — ANSI-aware text utilities and the Component base.

UX Best Practices enforced:
  - All text operations are ANSI-aware (escape codes never corrupt layout math)
  - Padding and alignment enforce whitespace best practices
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


# ==============================================================================
# ANSI-AWARE TEXT UTILITIES
# ==============================================================================

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def visible_len(s: str) -> int:
    """
    Returns the number of visible characters in a string, excluding ANSI
    escape sequences.

    UX Best Practice: All layout math must use visible length to prevent
    misaligned columns and truncated text.
    """
    return len(_ANSI_RE.sub("", s))


def truncate(s: str, max_width: int, ellipsis: str = "…") -> str:
    """
    Truncate a string to ``max_width`` visible characters, preserving ANSI
    sequences encountered before the cut point.

    UX Best Practice: Always show truncation via ellipsis so the user knows
    content was clipped. Never silently drop content.
    """
    if max_width <= 0:
        return ""
    if visible_len(s) <= max_width:
        return s

    target = max_width - len(ellipsis)
    if target <= 0:
        return ellipsis[:max_width]

    visible_count = 0
    i = 0
    while i < len(s):
        m = _ANSI_RE.match(s, i)
        if m:
            i = m.end()
            continue
        if visible_count >= target:
            break
        visible_count += 1
        i += 1
    return s[:i] + ellipsis


def pad(s: str, width: int, fill: str = " ") -> str:
    """
    Right-pad a string to exactly ``width`` visible characters.

    UX Best Practice: Consistent column widths prevent ragged alignment
    that reduces scannability.
    """
    vis = visible_len(s)
    if vis >= width:
        return s
    return s + fill * (width - vis)


# ==============================================================================
# ABSTRACT COMPONENT BASE
# ==============================================================================

class Component(ABC):
    """
    Abstract base class for all TUI components: a render contract that
    produces one string per line, each at most ``width`` visible characters.
    """

    @abstractmethod
    def render(self, width: int, height: int) -> list[str]:
        """
        Produce the visual output for this component.

        Args:
            width: Available horizontal characters.
            height: Available vertical lines.

        Returns:
            A list of strings, one per line. Each line must be at most
            ``width`` visible characters (ANSI sequences excluded from count).
        """
        ...
