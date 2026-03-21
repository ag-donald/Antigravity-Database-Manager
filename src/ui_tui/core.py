"""
Core TUI Framework — Component Base & Layout Engine.

Provides the foundational abstractions that all TUI components inherit from:
  - Abstract Component base class with lifecycle hooks
  - Constraint-based sizing system (Fixed, Percent, Fill)
  - Layout containers (Row, Column, Box)
  - ANSI-aware text utilities (visible_len, truncate, pad, center, align)

UX Best Practices enforced:
  - Consistent component lifecycle (mount → render → unmount)
  - Layout containers handle overflow gracefully (no content clipping surprises)
  - All text operations are ANSI-aware (escape codes never corrupt layout math)
  - Padding and alignment enforce whitespace best practices
"""

from __future__ import annotations

import enum
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from .theme import Style, STYLES, PALETTE, BoxChars, BORDER_ROUNDED, _Ansi
from .engine import Key, KeyEvent


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


def strip_ansi(s: str) -> str:
    """Remove all ANSI escape sequences from a string."""
    return _ANSI_RE.sub("", s)


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


def pad_center(s: str, width: int, fill: str = " ") -> str:
    """Center-align a string within ``width`` visible characters."""
    vis = visible_len(s)
    if vis >= width:
        return s
    total_pad = width - vis
    left = total_pad // 2
    right = total_pad - left
    return fill * left + s + fill * right


def pad_right(s: str, width: int, fill: str = " ") -> str:
    """Right-align a string within ``width`` visible characters."""
    vis = visible_len(s)
    if vis >= width:
        return s
    return fill * (width - vis) + s


def styled_line(text: str, style: Style, width: int) -> str:
    """
    Render a styled, padded line that fills the full width.

    UX Best Practice: Full-width styled lines prevent background color
    "holes" that break visual continuity.
    """
    content = truncate(text, width)
    padded = pad(content, width)
    return style.apply(padded)


def horizontal_rule(width: int, char: str = "─", style: Optional[Style] = None) -> str:
    """Render a horizontal divider line."""
    line = char * width
    if style:
        return style.apply(line)
    return STYLES.dim.apply(line)


# ==============================================================================
# CONSTRAINT-BASED SIZING
# ==============================================================================

class SizeMode(enum.Enum):
    """How a component declares its preferred size."""
    FIXED   = "fixed"      # Exact pixel/character count
    PERCENT = "percent"    # Percentage of available space
    FILL    = "fill"       # Take all remaining space
    MIN     = "min"        # Minimum size (content-driven)


@dataclass(frozen=True)
class Constraint:
    """
    A size constraint for layout calculations.

    UX Best Practice: Constraints let components negotiate space with their
    container, preventing hard-coded sizes that break on different terminals.
    """
    mode: SizeMode
    value: float = 0.0    # Meaning depends on mode

    @staticmethod
    def fixed(n: int) -> "Constraint":
        """Fixed size in characters/lines."""
        return Constraint(mode=SizeMode.FIXED, value=float(n))

    @staticmethod
    def percent(pct: float) -> "Constraint":
        """Percentage of available space (0.0–1.0)."""
        return Constraint(mode=SizeMode.PERCENT, value=pct)

    @staticmethod
    def fill() -> "Constraint":
        """Expand to fill all remaining space."""
        return Constraint(mode=SizeMode.FILL)

    @staticmethod
    def min_size(n: int) -> "Constraint":
        """At least ``n`` characters, may grow larger."""
        return Constraint(mode=SizeMode.MIN, value=float(n))

    def resolve(self, available: int) -> int:
        """Resolve this constraint to an actual size given available space."""
        if self.mode == SizeMode.FIXED:
            return max(0, min(int(self.value), available))
        elif self.mode == SizeMode.PERCENT:
            return max(0, min(int(available * self.value), available))
        elif self.mode == SizeMode.MIN:
            return max(int(self.value), 0)
        else:  # FILL
            return available


# ==============================================================================
# ABSTRACT COMPONENT BASE
# ==============================================================================

class Component(ABC):
    """
    Abstract base class for all TUI components.

    Components follow a strict lifecycle:
      1. ``on_mount()``  — Called when component enters the render tree
      2. ``render()``    — Called each frame to produce visual output
      3. ``handle_key()``— Called when a key event reaches this component
      4. ``on_unmount()``— Called when component leaves the render tree

    UX Best Practices enforced:
      - Every component has a unique ``id`` for focus management
      - Components declare whether they are ``focusable``
      - Focus state is always accessible for style differentiation
      - Lifecycle hooks prevent resource leaks
    """

    _id_counter: int = 0

    def __init__(self, component_id: Optional[str] = None,
                 focusable: bool = False) -> None:
        if component_id:
            self.id = component_id
        else:
            Component._id_counter += 1
            self.id = f"component_{Component._id_counter}"
        self.focusable = focusable
        self.focused = False
        self._mounted = False

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

    def handle_key(self, key: KeyEvent) -> Optional[str]:
        """
        Process a key event. Returns an action string or None.

        Override this in interactive components (tables, inputs, etc.).
        The action string is interpreted by the parent view/app.
        """
        return None

    def on_mount(self) -> None:
        """Called when this component enters the render tree. Override for setup."""
        self._mounted = True

    def on_unmount(self) -> None:
        """Called when this component leaves the render tree. Override for cleanup."""
        self._mounted = False

    def on_focus(self) -> None:
        """Called when this component receives keyboard focus."""
        self.focused = True

    def on_blur(self) -> None:
        """Called when this component loses keyboard focus."""
        self.focused = False


# ==============================================================================
# LAYOUT CONTAINERS
# ==============================================================================

@dataclass
class LayoutChild:
    """A child within a layout container, with its sizing constraint."""
    component: Component
    constraint: Constraint = field(default_factory=Constraint.fill)


class Row(Component):
    """
    Horizontal layout container — arranges children side by side.

    UX Best Practice: Row containers distribute space proportionally,
    preventing cramped or oversized columns on any terminal width.

    Usage::

        row = Row(children=[
            LayoutChild(table, Constraint.percent(0.55)),
            LayoutChild(detail, Constraint.fill()),
        ])
        lines = row.render(cols, rows)
    """

    def __init__(self, children: Optional[list[LayoutChild]] = None,
                 separator: str = "│", separator_style: Optional[Style] = None,
                 component_id: Optional[str] = None) -> None:
        super().__init__(component_id=component_id)
        self.children = children or []
        self.separator = separator
        self.separator_style = separator_style or STYLES.dim

    def render(self, width: int, height: int) -> list[str]:
        if not self.children:
            return [" " * width] * height

        # Calculate separator overhead
        sep_count = max(0, len(self.children) - 1)
        sep_width = visible_len(self.separator)
        available = width - (sep_count * sep_width)

        # Resolve widths
        widths = self._resolve_widths(available)

        # Render each child
        child_outputs: list[list[str]] = []
        for child, w in zip(self.children, widths):
            rendered = child.component.render(w, height)
            # Ensure each output has exactly `height` lines, each padded to `w`
            while len(rendered) < height:
                rendered.append(" " * w)
            child_outputs.append([pad(truncate(line, w), w) for line in rendered[:height]])

        # Compose horizontally
        sep_str = self.separator_style.apply(self.separator)
        lines: list[str] = []
        for row_idx in range(height):
            parts = []
            for col_idx, output in enumerate(child_outputs):
                if col_idx > 0:
                    parts.append(sep_str)
                parts.append(output[row_idx])
            lines.append("".join(parts))

        return lines

    def _resolve_widths(self, available: int) -> list[int]:
        """Distribute available width among children based on constraints."""
        widths: list[int] = [0] * len(self.children)
        remaining = available
        fill_indices: list[int] = []

        # First pass: resolve fixed and percent
        for i, child in enumerate(self.children):
            c = child.constraint
            if c.mode == SizeMode.FIXED:
                widths[i] = min(int(c.value), remaining)
                remaining -= widths[i]
            elif c.mode == SizeMode.PERCENT:
                widths[i] = min(int(available * c.value), remaining)
                remaining -= widths[i]
            elif c.mode == SizeMode.MIN:
                widths[i] = min(int(c.value), remaining)
                remaining -= widths[i]
                fill_indices.append(i)
            else:
                fill_indices.append(i)

        # Second pass: distribute remaining to fill children
        if fill_indices and remaining > 0:
            per_fill = remaining // len(fill_indices)
            extra = remaining % len(fill_indices)
            for idx, i in enumerate(fill_indices):
                widths[i] += per_fill + (1 if idx < extra else 0)

        return widths


class Column(Component):
    """
    Vertical layout container — stacks children top to bottom.

    UX Best Practice: Column containers allocate height proportionally,
    ensuring all sections get adequate space on any terminal height.
    """

    def __init__(self, children: Optional[list[LayoutChild]] = None,
                 component_id: Optional[str] = None) -> None:
        super().__init__(component_id=component_id)
        self.children = children or []

    def render(self, width: int, height: int) -> list[str]:
        if not self.children:
            return [" " * width] * height

        # Resolve heights
        heights = self._resolve_heights(height)

        # Render and stack
        lines: list[str] = []
        for child, h in zip(self.children, heights):
            rendered = child.component.render(width, h)
            while len(rendered) < h:
                rendered.append(" " * width)
            lines.extend(rendered[:h])

        # Pad to exact height
        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]

    def _resolve_heights(self, available: int) -> list[int]:
        """Distribute available height among children."""
        heights: list[int] = [0] * len(self.children)
        remaining = available
        fill_indices: list[int] = []

        for i, child in enumerate(self.children):
            c = child.constraint
            if c.mode == SizeMode.FIXED:
                heights[i] = min(int(c.value), remaining)
                remaining -= heights[i]
            elif c.mode == SizeMode.PERCENT:
                heights[i] = min(int(available * c.value), remaining)
                remaining -= heights[i]
            elif c.mode == SizeMode.MIN:
                heights[i] = min(int(c.value), remaining)
                remaining -= heights[i]
                fill_indices.append(i)
            else:
                fill_indices.append(i)

        if fill_indices and remaining > 0:
            per_fill = remaining // len(fill_indices)
            extra = remaining % len(fill_indices)
            for idx, i in enumerate(fill_indices):
                heights[i] += per_fill + (1 if idx < extra else 0)

        return heights


class Box(Component):
    """
    A decorative wrapper that draws a border around its child component.

    UX Best Practices enforced:
      - Titled boxes create clear visual grouping (Gestalt: Common Region)
      - Rounded corners feel friendlier and more modern
      - Padding inside borders prevents content from touching edges
      - Border style changes with focus state for clear affordance

    Usage::

        boxed = Box(child=table, title="Conversations", padding=1)
        lines = boxed.render(60, 20)
    """

    def __init__(
        self,
        child: Optional[Component] = None,
        title: str = "",
        border: BoxChars = BORDER_ROUNDED,
        border_style: Optional[Style] = None,
        title_style: Optional[Style] = None,
        padding: int = 0,
        component_id: Optional[str] = None,
        shadow: bool = False,
    ) -> None:
        super().__init__(component_id=component_id)
        self.child = child
        self.title = title
        self.border = border
        self.border_style = border_style or STYLES.border
        self.title_style = title_style or STYLES.emphasis
        self.padding = padding
        self.shadow = shadow

    def render(self, width: int, height: int) -> list[str]:
        b = self.border
        bs = self.border_style

        # Calculate inner dimensions
        inner_w = width - 2 - (self.padding * 2)  # Left/right border + padding
        inner_h = height - 2 - (self.padding * 2)  # Top/bottom border + padding
        inner_w = max(0, inner_w)
        inner_h = max(0, inner_h)

        # Render child content
        if self.child and inner_w > 0 and inner_h > 0:
            content = self.child.render(inner_w, inner_h)
        else:
            content = []

        # Pad content to inner_h
        while len(content) < inner_h:
            content.append(" " * inner_w)
        content = content[:inner_h]

        lines: list[str] = []

        # Top border with optional title
        if self.title:
            title_text = self.title_style.apply(f" {self.title} ")
            title_vis = visible_len(f" {self.title} ")
            remaining = width - 2 - title_vis
            left_border = max(2, remaining // 4)
            right_border = max(0, remaining - left_border)
            top = (
                bs.apply(b.tl + b.h * left_border)
                + title_text
                + bs.apply(b.h * right_border + b.tr)
            )
        else:
            top = bs.apply(b.tl + b.h * (width - 2) + b.tr)
        lines.append(top)

        # Top padding rows
        for _ in range(self.padding):
            lines.append(bs.apply(b.v) + " " * (width - 2) + bs.apply(b.v))

        # Content rows
        for row in content:
            padding_str = " " * self.padding
            padded_row = pad(truncate(row, inner_w), inner_w)
            lines.append(
                bs.apply(b.v) + padding_str + padded_row + padding_str + bs.apply(b.v)
            )

        # Bottom padding rows
        for _ in range(self.padding):
            lines.append(bs.apply(b.v) + " " * (width - 2) + bs.apply(b.v))

        # Bottom border
        lines.append(bs.apply(b.bl + b.h * (width - 2) + b.br))

        # Pad to height
        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]


# ==============================================================================
# SIMPLE CONTENT COMPONENTS
# ==============================================================================

class StaticText(Component):
    """
    A non-interactive text block.

    UX Best Practice: Static text components enforce consistent padding and
    alignment, preventing ad-hoc whitespace management.
    """

    def __init__(self, lines: Optional[list[str]] = None,
                 style: Optional[Style] = None,
                 component_id: Optional[str] = None) -> None:
        super().__init__(component_id=component_id)
        self.lines = lines or []
        self.style = style or STYLES.body

    def render(self, width: int, height: int) -> list[str]:
        output: list[str] = []
        for line in self.lines[:height]:
            content = truncate(line, width)
            output.append(self.style.apply(pad(content, width)))
        while len(output) < height:
            output.append(" " * width)
        return output[:height]


class Spacer(Component):
    """
    An empty component that fills space.

    UX Best Practice: Explicit spacers make layout intent clear, preventing
    accidental content collision.
    """

    def render(self, width: int, height: int) -> list[str]:
        return [" " * width] * height


class Divider(Component):
    """
    A horizontal or vertical divider line.

    UX Best Practice: Dividers create clear visual separation between
    sections (Gestalt: Proximity principle).
    """

    def __init__(self, char: str = "─", style: Optional[Style] = None,
                 component_id: Optional[str] = None) -> None:
        super().__init__(component_id=component_id)
        self.char = char
        self.style = style or STYLES.dim

    def render(self, width: int, height: int) -> list[str]:
        line = self.style.apply(self.char * width)
        result = [line]
        while len(result) < height:
            result.append(" " * width)
        return result[:height]
