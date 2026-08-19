"""
Color Palettes and Semantic Style Presets.

Provides the curated dark, high-contrast, and light palettes plus the
``Styles`` class that maps semantic names to ``Style`` instances.
"""

from __future__ import annotations

import os

from .color import Color
from .style import Style


# ==============================================================================
# COLOR PALETTE — Premium Dark Theme
# ==============================================================================

class Palette:
    """
    Curated color palette designed for terminal UIs.

    UX Best Practices enforced:
      - High contrast text on dark backgrounds for readability (WCAG-inspired)
      - Semantic naming (colors represent intent, not appearance)
      - Accent colors limited to draw attention to interactive elements
      - Muted tones for non-essential info to reduce cognitive load
      - Consistent status colors (green=success, amber=warning, red=error)
    """

    # --- Brand / Accent ---
    primary     = Color(r=0,   g=210, b=210, code_256=44,  code_basic=36)
    accent      = Color(r=100, g=180, b=255, code_256=111, code_basic=96)

    # --- Semantic Status ---
    success     = Color(r=80,  g=220, b=100, code_256=77,  code_basic=32)
    warning     = Color(r=240, g=180, b=40,  code_256=214, code_basic=33)
    error       = Color(r=240, g=70,  b=70,  code_256=196, code_basic=31)
    info        = Color(r=100, g=160, b=255, code_256=69,  code_basic=34)

    # --- Surfaces ---
    surface     = Color(r=30,  g=32,  b=40,  code_256=235, code_basic=40)
    surface_alt = Color(r=40,  g=44,  b=55,  code_256=237, code_basic=100)
    surface_hl  = Color(r=0,   g=80,  b=90,  code_256=23,  code_basic=46)

    # --- Text ---
    text        = Color(r=230, g=232, b=240, code_256=255, code_basic=97)
    text_muted  = Color(r=128, g=132, b=148, code_256=245, code_basic=37)
    text_dim    = Color(r=80,  g=84,  b=100, code_256=240, code_basic=90)
    text_bright = Color(r=255, g=255, b=255, code_256=231, code_basic=97)

    # --- Borders ---
    border      = Color(r=60,  g=64,  b=80,  code_256=238, code_basic=90)

    # --- Special ---
    gradient_start = Color(r=0,  g=140, b=170, code_256=30, code_basic=36)
    gradient_end   = Color(r=0,  g=90,  b=130, code_256=24, code_basic=34)


class PaletteHighContrast:
    """
    High-contrast palette for accessibility.

    UX Best Practice: WCAG AAA requires 7:1 contrast ratio. This palette
    uses maximally contrasting colors for users with low vision.
    """
    primary     = Color(r=0,   g=255, b=255, code_256=51,  code_basic=36)
    accent      = Color(r=120, g=200, b=255, code_256=117, code_basic=96)
    success     = Color(r=0,   g=255, b=0,   code_256=46,  code_basic=32)
    warning     = Color(r=255, g=255, b=0,   code_256=226, code_basic=33)
    error       = Color(r=255, g=0,   b=0,   code_256=196, code_basic=31)
    info        = Color(r=100, g=180, b=255, code_256=75,  code_basic=34)
    surface     = Color(r=0,   g=0,   b=0,   code_256=16,  code_basic=40)
    surface_alt = Color(r=20,  g=20,  b=20,  code_256=234, code_basic=100)
    surface_hl  = Color(r=0,   g=60,  b=80,  code_256=23,  code_basic=46)
    text        = Color(r=255, g=255, b=255, code_256=231, code_basic=97)
    text_muted  = Color(r=200, g=200, b=200, code_256=252, code_basic=37)
    text_dim    = Color(r=150, g=150, b=150, code_256=248, code_basic=90)
    text_bright = Color(r=255, g=255, b=255, code_256=231, code_basic=97)
    border      = Color(r=100, g=100, b=100, code_256=242, code_basic=90)
    gradient_start = Color(r=0, g=200, b=220, code_256=44, code_basic=36)
    gradient_end   = Color(r=0, g=100, b=160, code_256=25, code_basic=34)


class PaletteLight:
    """
    Light-background palette for terminals with light themes.

    UX Best Practice: Auto-detecting terminal background and switching
    to a matching palette ensures readability in all environments.
    """
    primary     = Color(r=0,   g=130, b=140, code_256=30,  code_basic=36)
    accent      = Color(r=40,  g=100, b=200, code_256=62,  code_basic=34)
    success     = Color(r=30,  g=140, b=50,  code_256=34,  code_basic=32)
    warning     = Color(r=180, g=120, b=0,   code_256=172, code_basic=33)
    error       = Color(r=200, g=30,  b=30,  code_256=160, code_basic=31)
    info        = Color(r=30,  g=100, b=180, code_256=25,  code_basic=34)
    surface     = Color(r=250, g=250, b=252, code_256=231, code_basic=47)
    surface_alt = Color(r=235, g=238, b=245, code_256=255, code_basic=47)
    surface_hl  = Color(r=200, g=235, b=240, code_256=152, code_basic=46)
    text        = Color(r=30,  g=32,  b=40,  code_256=235, code_basic=30)
    text_muted  = Color(r=100, g=104, b=120, code_256=243, code_basic=90)
    text_dim    = Color(r=160, g=164, b=180, code_256=248, code_basic=37)
    text_bright = Color(r=0,   g=0,   b=0,   code_256=16,  code_basic=30)
    border      = Color(r=180, g=184, b=200, code_256=249, code_basic=37)
    gradient_start = Color(r=0, g=130, b=140, code_256=30,  code_basic=36)
    gradient_end   = Color(r=0, g=80,  b=120, code_256=24,  code_basic=34)


# ==============================================================================
# PALETTE SELECTION
# ==============================================================================

def _select_palette() -> Palette:
    """Choose the best palette for the current terminal."""
    from ..capabilities import CAPS
    if os.environ.get("AGMERCIUM_HIGH_CONTRAST", "").lower() in ("1", "true"):
        return PaletteHighContrast()  # type: ignore[return-value]
    if CAPS.light_bg:
        return PaletteLight()  # type: ignore[return-value]
    return Palette()


PALETTE = _select_palette()


# ==============================================================================
# SEMANTIC STYLE PRESETS
# ==============================================================================

class Styles:
    """
    Predefined, named styles for consistent visual language.

    UX Best Practices enforced:
      - Consistent visual hierarchy (header > subheader > body > muted)
      - Interactive elements are always distinguishable from static content
      - Selected/focused state is immediately obvious
      - Status indicators use universally understood color semantics
    """

    # --- Typography Hierarchy ---
    header       = Style(fg=PALETTE.text_bright, bg=PALETTE.primary, bold=True)
    subheader    = Style(fg=PALETTE.text, bg=PALETTE.surface_alt, bold=False)
    title        = Style(fg=PALETTE.primary, bold=True)
    body         = Style(fg=PALETTE.text)
    muted        = Style(fg=PALETTE.text_muted)
    dim          = Style(fg=PALETTE.text_dim)
    emphasis     = Style(fg=PALETTE.text_bright, bold=True)

    # --- Interactive Elements ---
    selected     = Style(fg=PALETTE.text_bright, bg=PALETTE.surface_hl, bold=True)
    cursor       = Style(fg=PALETTE.primary, bold=True)

    # --- Status ---
    success      = Style(fg=PALETTE.success, bold=True)
    warning      = Style(fg=PALETTE.warning, bold=True)
    error        = Style(fg=PALETTE.error, bold=True)
    info         = Style(fg=PALETTE.info)

    # --- Borders ---

    # --- Footer / StatusBar ---
    footer       = Style(fg=PALETTE.text, bg=PALETTE.surface_alt)
    footer_key   = Style(fg=PALETTE.primary, bg=PALETTE.surface_alt, bold=True)

    # --- Overlay / Modal ---
    modal_border = Style(fg=PALETTE.primary, bold=True)
    modal_title  = Style(fg=PALETTE.text_bright, bold=True)

    # --- Data Table / Tree ---
    table_header = Style(fg=PALETTE.primary, bold=True)
    tree_leaf    = Style(fg=PALETTE.text)

    # --- Badge / Tag ---
    badge_new    = Style(fg=PALETTE.surface, bg=PALETTE.success, bold=True)
    badge_shared = Style(fg=PALETTE.text_muted, dim=True)

    # --- Progress / Activity ---
    spinner        = Style(fg=PALETTE.primary, bold=True)

    # --- Shadow ---
    shadow       = Style(fg=PALETTE.text_dim, dim=True)

    # --- Accent Bar ---
    accent_bar   = Style(fg=PALETTE.primary, bold=True)


STYLES = Styles()
