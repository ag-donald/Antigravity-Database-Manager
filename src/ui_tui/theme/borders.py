"""
Box-Drawing Character Sets.

Provides the ``BoxChars`` dataclass and the border preset used
throughout the TUI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoxChars:
    """
    A set of box-drawing characters for borders and frames.

    UX Best Practice: Consistent border style across all UI elements creates
    visual cohesion and reduces cognitive overhead.
    """
    tl: str   # top-left corner
    tr: str   # top-right corner
    bl: str   # bottom-left corner
    br: str   # bottom-right corner
    h: str    # horizontal line
    v: str    # vertical line


BORDER_ROUNDED = BoxChars(tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│")

