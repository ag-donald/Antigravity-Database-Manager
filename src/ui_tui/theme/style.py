"""
Composable Style System.

Provides the ``Style`` dataclass for combining foreground, background,
and text attributes into reusable visual tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .color import Color, _Ansi


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
        """Build the ANSI prefix for this style, auto-degrading per terminal caps."""
        parts: list[str] = []
        if self.fg:
            parts.append(self.fg.auto_fg())
        if self.bg:
            parts.append(self.bg.auto_bg())
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

