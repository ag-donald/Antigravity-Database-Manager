"""
Production-Grade TUI Component Library.

A comprehensive collection of reusable, composable UI components built on
the core Component framework. Every component enforces UX/UI best practices.

Components:
  - Header          — Gradient-styled application header
  - StatusBar       — Contextual footer with key hints
  - TextViewer      — Scrollable readonly text pane
  - Modal           — Centered overlay with title and border
  - ConfirmDialog   — Y/N confirmation overlay
  - ActionMenu      — Selectable vertical menu overlay
  - Spinner         — Animated activity indicator
  - Toast           — Auto-dismissing notification
  - WizardPipeline  — Multi-step progress indicator
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .core import Component, visible_len, truncate, pad
from .theme import (
    Style, STYLES, PALETTE, Icons, BoxChars, _Ansi, Glyphs,
    BORDER_ROUNDED, Color,
)
from .capabilities import CAPS


# Severity -> (icon, style) decoration shared by status and toast rendering.
_SEVERITY_DECOR: dict[str, tuple[str, Style]] = {
    "success": (Icons.CHECK, STYLES.success),
    "warning": (Icons.WARNING, STYLES.warning),
    "error":   (Icons.CROSS, STYLES.error),
    "info":    (Icons.INFO, STYLES.info),
}


# ==============================================================================
# HEADER — Premium Application Header
# ==============================================================================

class Header(Component):
    """
    Application header bar with gradient background and branding.

    UX Best Practices enforced:
      - Consistent branding establishes context and trust
      - Gradient backgrounds add premium visual depth
      - Version info visible at all times for support/debugging
      - Subtitle line provides navigational context (breadcrumb effect)
    """

    def __init__(self, app_name: str = "", version: str = "",
                 subtitle: str = "") -> None:
        self.app_name = app_name
        self.version = version
        self.subtitle = subtitle

    def render(self, width: int, height: int) -> list[str]:
        lines: list[str] = []

        # Line 1: Branded header with gradient text on gradient BG
        title_text = f" {Icons.DIAMOND} {self.app_name}"
        if self.version:
            title_text += f"  v{self.version}"

        if CAPS.truecolor and not CAPS.reduce_motion:
            # Premium gradient rendering: per-character gradient background
            title_padded = pad(title_text, width)
            parts: list[str] = []
            n = max(width - 1, 1)
            for i, ch in enumerate(title_padded):
                t = i / n
                bg_color = Color.lerp(PALETTE.gradient_start, PALETTE.gradient_end, t)
                parts.append(f"{bg_color.bg()}{_Ansi.BOLD}{PALETTE.text_bright.fg()}{ch}")
            parts.append(_Ansi.RESET)
            line1 = "".join(parts)
        else:
            title_padded = pad(title_text, width)
            line1 = STYLES.header.apply(title_padded)
        lines.append(line1)

        # Line 2: Accent bar (thin gradient separator)
        if CAPS.truecolor:
            accent_parts: list[str] = []
            n = max(width - 1, 1)
            for i in range(width):
                t = i / n
                c = Color.lerp(PALETTE.primary, PALETTE.accent, t)
                accent_parts.append(f"{c.fg()}{Glyphs.THICK_H}")
            accent_parts.append(_Ansi.RESET)
            lines.append("".join(accent_parts))
        else:
            lines.append(STYLES.accent_bar.apply(Glyphs.THICK_H * width))

        # Line 3: Subtitle / navigation context
        if self.subtitle:
            sub_text = f" {Icons.CHEVRON_R} {self.subtitle}"
        else:
            sub_text = " "
        sub_padded = pad(sub_text, width)
        line3 = STYLES.subheader.apply(sub_padded)
        lines.append(line3)

        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]


# ==============================================================================
# STATUS BAR — Contextual Footer
# ==============================================================================

class StatusBar(Component):
    """
    Bottom status bar with key hints and contextual status message.

    UX Best Practices enforced:
      - Key hints are always visible, reducing learning curve (discoverability)
      - Status messages use color-coded severity
      - Compact layout maximizes usable screen space
      - Hints use key+label format for clarity
    """

    def __init__(self, hints: Optional[list[tuple[str, str]]] = None,
                 status: str = "", status_severity: str = "info") -> None:
        self.hints = hints or []
        self.status = status
        self.status_severity = status_severity

    def render(self, width: int, height: int) -> list[str]:
        # Build hint string with key highlighting
        hint_parts: list[str] = []
        for key_str, label in self.hints:
            hint_parts.append(
                STYLES.footer_key.apply(key_str) + STYLES.footer.apply(f" {label}")
            )
        hint_str = STYLES.footer.apply("  ").join(hint_parts)

        # Build status with severity color
        status_str = ""
        if self.status:
            severity_style = (
                _SEVERITY_DECOR[self.status_severity][1]
                if self.status_severity in _SEVERITY_DECOR else STYLES.muted
            )
            status_str = (
                STYLES.footer.apply(" │ ")
                + severity_style.apply(self.status)
            )

        content = STYLES.footer.apply(" ") + hint_str + status_str
        padded = content + STYLES.footer.apply(" " * max(0, width - visible_len(content)))
        lines = [padded]

        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]


# ==============================================================================
# TEXT VIEWER — Scrollable Readonly Text Pane
# ==============================================================================

class TextViewer(Component):
    """
    Scrollable readonly text viewer with line numbers.

    UX Best Practices enforced:
      - Line numbers aid navigation in large content
      - Smooth scroll tracking keeps context visible
      - Tabs are converted to spaces for consistent rendering
    """

    def __init__(self, content_lines: Optional[list[str]] = None,
                 scroll: int = 0, show_line_numbers: bool = True) -> None:
        self.content_lines = content_lines or []
        self.scroll = scroll
        self.show_line_numbers = show_line_numbers

    def render(self, width: int, height: int) -> list[str]:
        lines: list[str] = []

        total = len(self.content_lines)
        gutter_w = len(str(total)) + 2 if self.show_line_numbers else 0
        content_w = width - gutter_w

        visible = self.content_lines[self.scroll:self.scroll + height]
        for idx, line in enumerate(visible):
            real_idx = idx + self.scroll
            clean = line.replace("\t", "    ")

            if self.show_line_numbers:
                gutter = STYLES.dim.apply(f"{real_idx + 1:>{gutter_w - 1}} ")
            else:
                gutter = ""

            content = truncate(clean, content_w)
            lines.append(gutter + pad(content, content_w))

        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]

# ==============================================================================
# MODAL — Centered Overlay
# ==============================================================================

class Modal(Component):
    """
    Centered overlay box with title, body content, and action hints.

    UX Best Practices enforced:
      - Modals are centered for immediate visual focus
      - Title bar clearly identifies the modal's purpose
      - Rounded borders feel approachable, not threatening
      - Action hints at bottom reduce guesswork
      - Modal width is capped to prevent overwhelming layouts
    """

    def __init__(self, title: str = "", body_lines: Optional[list[str]] = None,
                 hints: str = "", max_width: int = 60,
                 border: BoxChars = BORDER_ROUNDED) -> None:
        self.title = title
        self.body_lines = body_lines or []
        self.hints = hints
        self.max_width = max_width
        self.border = border

    def render(self, width: int, height: int) -> list[str]:
        modal_w = min(self.max_width, width - 4)
        b = self.border
        inner_w = modal_w - 2

        # Build modal frame
        frame: list[str] = []

        # Top border with title
        if self.title:
            title_display = STYLES.modal_title.apply(f" {self.title} ")
            title_vis = visible_len(f" {self.title} ")
            rem = inner_w - title_vis
            left_w = max(2, rem // 4)
            right_w = max(0, rem - left_w)
            top = (
                STYLES.modal_border.apply(b.tl + b.h * left_w)
                + title_display
                + STYLES.modal_border.apply(b.h * right_w + b.tr)
            )
        else:
            top = STYLES.modal_border.apply(b.tl + b.h * inner_w + b.tr)
        frame.append(top)

        # Empty line after title
        frame.append(
            STYLES.modal_border.apply(b.v)
            + " " * inner_w
            + STYLES.modal_border.apply(b.v)
        )

        # Body lines
        for body in self.body_lines:
            content = truncate(f"  {body}", inner_w)
            padded = pad(content, inner_w)
            frame.append(
                STYLES.modal_border.apply(b.v)
                + padded
                + STYLES.modal_border.apply(b.v)
            )

        # Empty line before hints
        frame.append(
            STYLES.modal_border.apply(b.v)
            + " " * inner_w
            + STYLES.modal_border.apply(b.v)
        )

        # Hints line
        if self.hints:
            hint_content = pad(f"  {STYLES.dim.apply(self.hints)}", inner_w)
            frame.append(
                STYLES.modal_border.apply(b.v)
                + hint_content
                + STYLES.modal_border.apply(b.v)
            )

        # Bottom border
        frame.append(STYLES.modal_border.apply(b.bl + b.h * inner_w + b.br))

        # Center the modal vertically and horizontally
        h_center = (width - modal_w) // 2
        h_pad = " " * max(0, h_center)
        centered_frame = [h_pad + line for line in frame]

        v_start = max(0, (height - len(centered_frame)) // 2)
        result: list[str] = [" " * width] * height
        for i, line in enumerate(centered_frame):
            if 0 <= v_start + i < height:
                result[v_start + i] = pad(line, width)

        # Bottom shadow
        bottom_shadow_row = v_start + len(centered_frame)
        if 0 <= bottom_shadow_row < height:
            result[bottom_shadow_row] = pad(
                " " * (h_center + 1) + STYLES.shadow.apply("░" * modal_w),
                width
            )

        return result


# ==============================================================================
# CONFIRM DIALOG — Y/N Confirmation
# ==============================================================================

class ConfirmDialog(Component):
    """
    Y/N confirmation dialog.

    UX Best Practices enforced:
      - Destructive confirmations use warning colors
      - Clear Y/N labeling prevents accidental actions
      - Message explains consequences before asking
    """

    def __init__(self, title: str = "Confirm", message_lines: Optional[list[str]] = None) -> None:
        self.title = title
        self.message_lines = message_lines or []
        self._modal = Modal(
            title=title,
            body_lines=self.message_lines,
            hints="Y = Confirm    N = Cancel",
            border=BORDER_ROUNDED,
        )

    def render(self, width: int, height: int) -> list[str]:
        return self._modal.render(width, height)

# ==============================================================================
# ACTION MENU — Selectable Menu Overlay
# ==============================================================================

class ActionMenu(Component):
    """
    Vertical selectable menu overlay.

    UX Best Practices enforced:
      - Arrow cursor (▸) shows current selection clearly
      - Keyboard navigation mirrors standard menu patterns
      - Selected item has accent color background for visibility
      - Escape always cancels (consistent escape hatch pattern)
    """

    def __init__(self, title: str = "Actions", items: Optional[list[str]] = None,
                 selected: int = 0) -> None:
        self.title = title
        self.items = items or []
        self.selected = selected

    def render(self, width: int, height: int) -> list[str]:
        body: list[str] = []
        for i, item in enumerate(self.items):
            if i == self.selected:
                body.append(STYLES.cursor.apply(f"{Icons.POINTER} ") + STYLES.emphasis.apply(item))
            else:
                body.append(f"  {item}")

        modal = Modal(
            title=self.title,
            body_lines=body,
            hints="↑↓ Select  Enter Confirm  Esc Cancel",
            border=BORDER_ROUNDED,
        )
        return modal.render(width, height)

# ==============================================================================
# SPINNER — Animated Activity Indicator
# ==============================================================================

class Spinner(Component):
    """
    Animated spinner for indeterminate progress.

    UX Best Practices enforced:
      - Activity feedback prevents user from thinking the app is frozen
      - Label explains what's happening during the wait
      - Multiple spinner styles for visual variety
    """

    def __init__(self, label: str = "Working...",
                 frames: tuple[str, ...] = Icons.SPINNER_DOTS) -> None:
        self.label = label
        self.frames = frames
        self.frame_index = 0
        self.last_advance = time.monotonic()

    def advance(self) -> None:
        """Advance to the next frame. Called by the animation loop."""
        now = time.monotonic()
        if now - self.last_advance >= 0.1:
            self.frame_index = (self.frame_index + 1) % len(self.frames)
            self.last_advance = now

    def render(self, width: int, height: int) -> list[str]:
        self.advance()
        frame_char = self.frames[self.frame_index]
        line = f"  {STYLES.spinner.apply(frame_char)} {self.label}"
        lines = [pad(line, width)]
        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]


# ==============================================================================
# TOAST — Auto-Dismissing Notification
# ==============================================================================

@dataclass
class ToastMessage:
    """A single toast notification entry."""
    message: str
    severity: str = "info"
    created_at: float = field(default_factory=time.monotonic)
    duration: float = 5.0

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) >= self.duration


class ToastManager(Component):
    """
    Manages a stack of auto-dismissing notifications.

    UX Best Practices enforced:
      - Non-blocking feedback doesn't interrupt workflow
      - Severity-colored icons provide instant visual categorization
      - Auto-dismiss prevents notification fatigue
      - Newest toasts appear at bottom (natural reading order)
    """

    def __init__(self, max_visible: int = 3) -> None:
        self.toasts: list[ToastMessage] = []
        self.max_visible = max_visible

    def push(self, message: str, severity: str = "info",
             duration: float = 5.0) -> None:
        """Add a new toast notification."""
        self.toasts.append(ToastMessage(
            message=message, severity=severity, duration=duration,
        ))

    def _cleanup(self) -> None:
        """Remove expired toasts."""
        self.toasts = [t for t in self.toasts if not t.is_expired]

    def render(self, width: int, height: int) -> list[str]:
        self._cleanup()
        visible = self.toasts[-self.max_visible:]

        lines: list[str] = []
        for toast in visible:
            icon, style = _SEVERITY_DECOR.get(toast.severity, (Icons.INFO, STYLES.info))
            content = f"  {style.apply(icon)} {toast.message}"
            lines.append(pad(content, width))

        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]

    @property
    def has_active(self) -> bool:
        """Whether there are any visible toasts."""
        self._cleanup()
        return len(self.toasts) > 0


# ==============================================================================
# WIZARD PIPELINE — Multi-Step Progress Indicator
# ==============================================================================

class WizardPipeline(Component):
    """
    Horizontal multi-step progress indicator for wizard-style flows.

    UX Best Practices enforced:
      - Step indicators show position in a multi-step process
      - Completed steps are visually distinct from pending steps
      - Current step is highlighted with accent color
      - Status messages provide context for each step
    """

    def __init__(self, steps: Optional[list[str]] = None,
                 current: int = 0,
                 statuses: Optional[list[str]] = None) -> None:
        self.steps = steps or []
        self.current = current
        self.statuses = statuses or [""] * len(self.steps)

    def render(self, width: int, height: int) -> list[str]:
        lines: list[str] = []

        # Node indicators
        nodes: list[str] = []
        for i in range(len(self.steps)):
            if i < self.current:
                nodes.append(STYLES.success.apply(Icons.CIRCLE_FILL))
            elif i == self.current:
                nodes.append(STYLES.cursor.apply(Icons.CIRCLE_FILL))
            else:
                nodes.append(STYLES.dim.apply(Icons.CIRCLE_OPEN))

        connector = STYLES.dim.apply(" ─ ")
        pipeline = "  " + connector.join(nodes)
        lines.append(pad(pipeline, width))

        # Step labels
        label_parts: list[str] = []
        for step in self.steps:
            label_parts.append(truncate(step, 14))
        labels_line = "  " + "  ".join(label_parts)
        lines.append(STYLES.dim.apply(pad(labels_line, width)))

        # Current step status
        if self.current < len(self.statuses) and self.statuses[self.current]:
            status = f"  {Icons.POINTER} {self.statuses[self.current]}"
            lines.append(STYLES.info.apply(pad(status, width)))

        while len(lines) < height:
            lines.append(" " * width)
        return lines[:height]


# ==============================================================================
# OVERLAY UTILITY — Composites a modal on top of a background
# ==============================================================================

def overlay_on(background: list[str], overlay_lines: list[str]) -> list[str]:
    """
    Composite overlay lines onto background lines, centered vertically.

    UX Best Practice: Overlays should not destroy background content — they
    are composed on top, preserving context beneath.
    """
    result = list(background)
    h = len(result)
    start = max(0, (h - len(overlay_lines)) // 2)
    for i, line in enumerate(overlay_lines):
        if 0 <= start + i < h:
            result[start + i] = line
    return result


# ==============================================================================
# GAUGE — Health Score Indicator
# ==============================================================================

# ==============================================================================
# BAR CHART — Horizontal Data Bars
# ==============================================================================

# ==============================================================================
# KEY-VALUE GRID — Formatted Metadata Display
# ==============================================================================

# ==============================================================================
# SEPARATOR — Themed Horizontal Rule with Label
# ==============================================================================

