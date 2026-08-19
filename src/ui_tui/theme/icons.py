"""
Icon and Symbol Sets.

Provides ``Icons`` (semantic UI symbols) and ``Glyphs`` (block-element
characters for data visualization).
"""

from __future__ import annotations


class Icons:
    """
    Curated Unicode symbols for semantic UI indicators.

    UX Best Practice: Consistent iconography provides instant visual meaning
    without requiring the user to read text labels.
    """
    # Navigation
    POINTER     = "▸"
    CHEVRON_R   = "›"

    # Status
    CHECK       = "✓"
    CROSS       = "✗"
    WARNING     = "⚠"
    INFO        = "ℹ"
    CIRCLE_FILL = "●"
    CIRCLE_OPEN = "○"
    DIAMOND     = "◆"

    # Progress

    # Data

    # Spinners (frame sequences)
    SPINNER_DOTS    = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")


class Glyphs:
    """
    Block-element characters for gauges, bar charts, and meters.

    UX Best Practice: Using block elements instead of plain text for
    data visualization provides instant visual meaning.
    """
    # Horizontal bar (8 levels)
    # Vertical bar (8 levels)
    # Gauge segments
    # Scrollbar
    # Separators
    THICK_H       = "━"
    # Toggle
