"""
Semantic Theme & Style System for the TUI.

Provides a centralized, enterprise-grade color and typography system that
enforces UX/UI best practices:
  - WCAG-inspired contrast considerations for terminal displays
  - Semantic color tokens (intent-driven, not appearance-driven)
  - Composable Style objects for consistent visual language
  - Box-drawing character sets for clean borders
  - Gradient generation for premium header aesthetics
  - All output is pure ANSI VT100 — zero external dependencies
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ==============================================================================
# ANSI ESCAPE CODE PRIMITIVES
# ==============================================================================

class _Ansi:
    """Low-level ANSI VT100 sequence builders."""

    RESET = "\x1b[0m"

    # --- Attribute codes ---
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    ITALIC = "\x1b[3m"
    UNDERLINE = "\x1b[4m"
    BLINK = "\x1b[5m"
    REVERSE = "\x1b[7m"
    STRIKETHROUGH = "\x1b[9m"

    @staticmethod
    def fg_256(code: int) -> str:
        """Foreground color from the 256-color palette."""
        return f"\x1b[38;5;{code}m"

    @staticmethod
    def bg_256(code: int) -> str:
        """Background color from the 256-color palette."""
        return f"\x1b[48;5;{code}m"

    @staticmethod
    def fg_rgb(r: int, g: int, b: int) -> str:
        """24-bit truecolor foreground."""
        return f"\x1b[38;2;{r};{g};{b}m"

    @staticmethod
    def bg_rgb(r: int, g: int, b: int) -> str:
        """24-bit truecolor background."""
        return f"\x1b[48;2;{r};{g};{b}m"

    @staticmethod
    def fg_basic(code: int) -> str:
        """Basic 16-color foreground (30-37, 90-97)."""
        return f"\x1b[{code}m"

    @staticmethod
    def bg_basic(code: int) -> str:
        """Basic 16-color background (40-47, 100-107)."""
        return f"\x1b[{code}m"


# ==============================================================================
# COLOR REPRESENTATION
# ==============================================================================

@dataclass(frozen=True)
class Color:
    """
    A terminal color supporting multiple encoding levels.

    Usage::

        cyan = Color(r=0, g=200, b=200, code_256=44, code_basic=36)
        seq = cyan.fg()  # Returns best available ANSI escape
    """
    r: int = 255
    g: int = 255
    b: int = 255
    code_256: Optional[int] = None
    code_basic: Optional[int] = None

    def fg(self) -> str:
        """Foreground escape sequence (truecolor preferred)."""
        return _Ansi.fg_rgb(self.r, self.g, self.b)

    def bg(self) -> str:
        """Background escape sequence (truecolor preferred)."""
        return _Ansi.bg_rgb(self.r, self.g, self.b)

    def fg_256(self) -> str:
        """Foreground via 256-color palette (fallback)."""
        if self.code_256 is not None:
            return _Ansi.fg_256(self.code_256)
        return self.fg()

    def bg_256(self) -> str:
        """Background via 256-color palette (fallback)."""
        if self.code_256 is not None:
            return _Ansi.bg_256(self.code_256)
        return self.bg()

    def fg_basic(self) -> str:
        """Foreground via basic 16-color (most compatible fallback)."""
        if self.code_basic is not None:
            return _Ansi.fg_basic(self.code_basic)
        return self.fg_256()

    def bg_basic(self) -> str:
        """Background via basic 16-color (most compatible fallback)."""
        if self.code_basic is not None:
            return _Ansi.bg_basic(self.code_basic + 10)
        return self.bg_256()

    @staticmethod
    def lerp(a: "Color", b: "Color", t: float) -> "Color":
        """
        Linear interpolation between two colors.

        ``t=0.0`` → color ``a``, ``t=1.0`` → color ``b``.
        UX Best Practice: Smooth gradients prevent jarring visual transitions.
        """
        t = max(0.0, min(1.0, t))
        return Color(
            r=int(a.r + (b.r - a.r) * t),
            g=int(a.g + (b.g - a.g) * t),
            b=int(a.b + (b.b - a.b) * t),
        )


# ==============================================================================
# STYLE COMPOSITION
# ==============================================================================

@dataclass(frozen=True)
class Style:
    """
    A composable visual style combining foreground, background, and text
    attributes.

    UX Best Practice: Consistent styling through composition rather than
    ad-hoc ANSI concatenation prevents visual inconsistency.

    Usage::

        heading = Style(fg=PALETTE.primary, bold=True)
        rendered = heading.apply("Hello World")
    """
    fg: Optional[Color] = None
    bg: Optional[Color] = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    reverse: bool = False

    def apply(self, text: str) -> str:
        """Wrap text in this style's escape sequences with guaranteed reset."""
        prefix = self._build_prefix()
        if not prefix:
            return text
        return f"{prefix}{text}{_Ansi.RESET}"

    def _build_prefix(self) -> str:
        """Build the ANSI prefix for this style."""
        parts: list[str] = []
        if self.fg:
            parts.append(self.fg.fg())
        if self.bg:
            parts.append(self.bg.bg())
        if self.bold:
            parts.append(_Ansi.BOLD)
        if self.dim:
            parts.append(_Ansi.DIM)
        if self.italic:
            parts.append(_Ansi.ITALIC)
        if self.underline:
            parts.append(_Ansi.UNDERLINE)
        if self.strikethrough:
            parts.append(_Ansi.STRIKETHROUGH)
        if self.reverse:
            parts.append(_Ansi.REVERSE)
        return "".join(parts)

    def merge(self, other: "Style") -> "Style":
        """
        Merge another style on top of this one (other takes precedence).

        UX Best Practice: Cascading styles enable inheritance patterns
        similar to CSS, reducing visual inconsistency.
        """
        return Style(
            fg=other.fg if other.fg else self.fg,
            bg=other.bg if other.bg else self.bg,
            bold=other.bold or self.bold,
            dim=other.dim or self.dim,
            italic=other.italic or self.italic,
            underline=other.underline or self.underline,
            strikethrough=other.strikethrough or self.strikethrough,
            reverse=other.reverse or self.reverse,
        )

    @property
    def prefix(self) -> str:
        """Raw ANSI prefix (for manual use where apply() isn't suitable)."""
        return self._build_prefix()

    @property
    def reset(self) -> str:
        """ANSI reset sequence."""
        return _Ansi.RESET


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
    primary     = Color(r=0,   g=210, b=210, code_256=44,  code_basic=36)    # Teal/Cyan
    accent      = Color(r=100, g=180, b=255, code_256=111, code_basic=96)    # Soft blue
    highlight   = Color(r=0,   g=255, b=210, code_256=49,  code_basic=96)    # Mint

    # --- Semantic Status ---
    success     = Color(r=80,  g=220, b=100, code_256=77,  code_basic=32)    # Green
    warning     = Color(r=240, g=180, b=40,  code_256=214, code_basic=33)    # Amber
    error       = Color(r=240, g=70,  b=70,  code_256=196, code_basic=31)    # Red
    info        = Color(r=100, g=160, b=255, code_256=69,  code_basic=34)    # Blue

    # --- Surfaces ---
    surface     = Color(r=30,  g=32,  b=40,  code_256=235, code_basic=40)    # Deep charcoal BG
    surface_alt = Color(r=40,  g=44,  b=55,  code_256=237, code_basic=100)   # Slightly lighter
    surface_hl  = Color(r=0,   g=80,  b=90,  code_256=23,  code_basic=46)    # Selected row BG
    overlay     = Color(r=20,  g=22,  b=30,  code_256=234, code_basic=40)    # Modal backdrop

    # --- Text ---
    text        = Color(r=230, g=232, b=240, code_256=255, code_basic=97)    # Primary text
    text_muted  = Color(r=128, g=132, b=148, code_256=245, code_basic=37)    # Secondary text
    text_dim    = Color(r=80,  g=84,  b=100, code_256=240, code_basic=90)    # Tertiary / disabled
    text_bright = Color(r=255, g=255, b=255, code_256=231, code_basic=97)    # Emphasis text

    # --- Borders ---
    border      = Color(r=60,  g=64,  b=80,  code_256=238, code_basic=90)    # Subtle border
    border_focus= Color(r=0,   g=180, b=190, code_256=37,  code_basic=36)    # Focused border

    # --- Special ---
    gradient_start = Color(r=0,  g=140, b=170, code_256=30, code_basic=36)
    gradient_end   = Color(r=0,  g=90,  b=130, code_256=24, code_basic=34)


# Singleton palette instance
PALETTE = Palette()


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
      - Disabled elements are clearly dimmed
    """

    # --- Typography Hierarchy ---
    header       = Style(fg=PALETTE.text_bright, bg=PALETTE.primary, bold=True)
    subheader    = Style(fg=PALETTE.text, bg=PALETTE.surface_alt, bold=False)
    title        = Style(fg=PALETTE.primary, bold=True)
    subtitle     = Style(fg=PALETTE.text_muted)
    body         = Style(fg=PALETTE.text)
    muted        = Style(fg=PALETTE.text_muted)
    dim          = Style(fg=PALETTE.text_dim)
    emphasis     = Style(fg=PALETTE.text_bright, bold=True)

    # --- Interactive Elements ---
    selected     = Style(fg=PALETTE.text_bright, bg=PALETTE.surface_hl, bold=True)
    cursor       = Style(fg=PALETTE.primary, bold=True)
    link         = Style(fg=PALETTE.accent, underline=True)

    # --- Status ---
    success      = Style(fg=PALETTE.success, bold=True)
    warning      = Style(fg=PALETTE.warning, bold=True)
    error        = Style(fg=PALETTE.error, bold=True)
    info         = Style(fg=PALETTE.info)

    # --- Borders ---
    border       = Style(fg=PALETTE.border)
    border_focus = Style(fg=PALETTE.border_focus, bold=True)

    # --- Footer / StatusBar ---
    footer       = Style(fg=PALETTE.text, bg=PALETTE.surface_alt)
    footer_hint  = Style(fg=PALETTE.text_muted, bg=PALETTE.surface_alt)
    footer_key   = Style(fg=PALETTE.primary, bg=PALETTE.surface_alt, bold=True)

    # --- Overlay / Modal ---
    overlay_bg   = Style(bg=PALETTE.overlay)
    modal_border = Style(fg=PALETTE.primary, bold=True)
    modal_title  = Style(fg=PALETTE.text_bright, bold=True)

    # --- Data Table ---
    table_header = Style(fg=PALETTE.primary, bold=True)
    table_row    = Style(fg=PALETTE.text)
    table_row_alt= Style(fg=PALETTE.text, bg=PALETTE.surface_alt)
    table_sel    = Style(fg=PALETTE.text_bright, bg=PALETTE.surface_hl, bold=True)

    # --- Tree ---
    tree_branch  = Style(fg=PALETTE.text_dim)
    tree_leaf    = Style(fg=PALETTE.text)
    tree_sel     = Style(fg=PALETTE.text_bright, bg=PALETTE.surface_hl, bold=True)

    # --- Badge / Tag ---
    badge_new    = Style(fg=PALETTE.surface, bg=PALETTE.success, bold=True)
    badge_shared = Style(fg=PALETTE.text_muted, dim=True)
    badge_count  = Style(fg=PALETTE.surface, bg=PALETTE.accent, bold=True)

    # --- Progress / Activity ---
    progress_fill  = Style(fg=PALETTE.primary, bold=True)
    progress_empty = Style(fg=PALETTE.text_dim, dim=True)
    spinner        = Style(fg=PALETTE.primary, bold=True)

    # --- Input ---
    input_text   = Style(fg=PALETTE.text)
    input_cursor = Style(fg=PALETTE.primary, bg=PALETTE.primary)
    input_placeholder = Style(fg=PALETTE.text_dim, italic=True)


# Singleton styles instance
STYLES = Styles()


# ==============================================================================
# BOX-DRAWING CHARACTER SETS
# ==============================================================================

@dataclass(frozen=True)
class BoxChars:
    """
    A complete set of box-drawing characters for borders and frames.

    UX Best Practice: Consistent border style across all UI elements creates
    visual cohesion and reduces cognitive overhead.
    """
    tl: str   # top-left corner
    tr: str   # top-right corner
    bl: str   # bottom-left corner
    br: str   # bottom-right corner
    h: str    # horizontal line
    v: str    # vertical line
    t_left: str   # T-junction facing left
    t_right: str  # T-junction facing right
    t_up: str     # T-junction facing up
    t_down: str   # T-junction facing down
    cross: str    # four-way cross


# Named box-drawing presets
BORDER_THIN = BoxChars(
    tl="┌", tr="┐", bl="└", br="┘", h="─", v="│",
    t_left="┤", t_right="├", t_up="┴", t_down="┬", cross="┼",
)

BORDER_THICK = BoxChars(
    tl="┏", tr="┓", bl="┗", br="┛", h="━", v="┃",
    t_left="┫", t_right="┣", t_up="┻", t_down="┳", cross="╋",
)

BORDER_DOUBLE = BoxChars(
    tl="╔", tr="╗", bl="╚", br="╝", h="═", v="║",
    t_left="╣", t_right="╠", t_up="╩", t_down="╦", cross="╬",
)

BORDER_ROUNDED = BoxChars(
    tl="╭", tr="╮", bl="╰", br="╯", h="─", v="│",
    t_left="┤", t_right="├", t_up="┴", t_down="┬", cross="┼",
)

BORDER_NONE = BoxChars(
    tl=" ", tr=" ", bl=" ", br=" ", h=" ", v=" ",
    t_left=" ", t_right=" ", t_up=" ", t_down=" ", cross=" ",
)


# ==============================================================================
# ICON & SYMBOL SETS
# ==============================================================================

class Icons:
    """
    Curated Unicode symbols for semantic UI indicators.

    UX Best Practice: Consistent iconography provides instant visual meaning
    without requiring the user to read text labels.
    """
    # Navigation
    POINTER     = "▸"
    POINTER_DBL = "▶"
    ARROW_UP    = "↑"
    ARROW_DOWN  = "↓"
    ARROW_LEFT  = "←"
    ARROW_RIGHT = "→"
    CHEVRON_R   = "›"
    CHEVRON_D   = "▾"

    # Status
    CHECK       = "✓"
    CROSS       = "✗"
    WARNING     = "⚠"
    INFO        = "ℹ"
    CIRCLE_FILL = "●"
    CIRCLE_OPEN = "○"
    DIAMOND     = "◆"

    # Progress
    BLOCK_FULL  = "█"
    BLOCK_3_4   = "▓"
    BLOCK_HALF  = "▒"
    BLOCK_1_4   = "░"

    # Data
    FOLDER      = "📁"
    FILE        = "📄"
    DATABASE    = "🗄"
    KEY         = "🔑"
    LOCK        = "🔒"
    UNLOCK      = "🔓"

    # Spinners (frame sequences)
    SPINNER_DOTS    = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")
    SPINNER_LINE    = ("—", "\\", "|", "/")
    SPINNER_ARC     = ("◜", "◠", "◝", "◞", "◡", "◟")
    SPINNER_BRAILLE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    SPINNER_PULSE   = ("○", "◔", "◑", "◕", "●", "◕", "◑", "◔")
    SPINNER_BOUNCE  = ("⠁", "⠂", "⠄", "⡀", "⢀", "⠠", "⠐", "⠈")


# ==============================================================================
# GRADIENT UTILITIES
# ==============================================================================

def generate_gradient(
    text: str,
    start: Color,
    end: Color,
    bg: Optional[Color] = None,
    bold: bool = False,
) -> str:
    """
    Apply a character-by-character foreground gradient to text.

    UX Best Practice: Subtle gradients add premium visual appeal without
    sacrificing readability. Use sparingly on headers and accents only.

    Args:
        text: Plain text to colorize.
        start: Starting color of the gradient.
        end: Ending color of the gradient.
        bg: Optional background color applied uniformly.
        bold: Whether to apply bold attribute.

    Returns:
        ANSI-escaped string with gradient applied.
    """
    if not text:
        return ""

    parts: list[str] = []
    n = max(len(text) - 1, 1)
    bg_seq = bg.bg() if bg else ""
    bold_seq = _Ansi.BOLD if bold else ""

    for i, ch in enumerate(text):
        t = i / n
        color = Color.lerp(start, end, t)
        parts.append(f"{color.fg()}{bg_seq}{bold_seq}{ch}")

    parts.append(_Ansi.RESET)
    return "".join(parts)


def gradient_bg_line(width: int, start: Color, end: Color) -> str:
    """
    Create a full-width background gradient bar (spaces with BG color).

    UX Best Practice: Background gradients on header bars create visual depth
    and establish clear section boundaries.
    """
    parts: list[str] = []
    n = max(width - 1, 1)
    for i in range(width):
        t = i / n
        color = Color.lerp(start, end, t)
        parts.append(f"{color.bg()} ")
    parts.append(_Ansi.RESET)
    return "".join(parts)


# ==============================================================================
# UX VALIDATION HELPERS
# ==============================================================================

def contrast_ratio_approx(fg: Color, bg: Color) -> float:
    """
    Approximate contrast ratio between foreground and background.

    UX Best Practice: Text contrast should be at minimum 4.5:1 for normal
    text and 3:1 for large/bold text (WCAG AA guideline adapted for terminals).

    Returns a ratio value >= 1.0.
    """
    def relative_luminance(c: Color) -> float:
        """sRGB relative luminance (simplified for 0-255 range)."""
        rs = c.r / 255.0
        gs = c.g / 255.0
        bs = c.b / 255.0
        # Simplified gamma decompression
        r = rs / 12.92 if rs <= 0.03928 else ((rs + 0.055) / 1.055) ** 2.4
        g = gs / 12.92 if gs <= 0.03928 else ((gs + 0.055) / 1.055) ** 2.4
        b = bs / 12.92 if bs <= 0.03928 else ((bs + 0.055) / 1.055) ** 2.4
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
