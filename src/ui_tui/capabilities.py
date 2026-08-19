"""
Terminal Capability Detection.

Probes the runtime environment to determine which visual features the
terminal supports, then exposes a singleton ``CAPS`` object that the rest
of the TUI can query.

Detected features:
  - Truecolor (24-bit) RGB support
  - 256-color palette support
  - Basic 16-color support
  - Light vs dark background heuristic
  - Reduced-motion preference

UX Best Practice: Graceful degradation ensures the TUI looks good on
every terminal — from modern GPU-accelerated emulators to SSH over tmux.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


# ==============================================================================
# CAPABILITY DETECTION
# ==============================================================================

@dataclass
class TerminalCapabilities:
    """
    Runtime terminal feature flags.

    Populated once at startup via ``detect()``.  Other modules read these
    flags to choose the best rendering path (e.g., truecolor gradients
    vs plain bold text).
    """
    truecolor: bool = False       # 24-bit RGB (16 million colors)
    colors_256: bool = False      # 8-bit palette (256 colors)
    colors_basic: bool = True     # 4-bit palette (16 colors) — always available
    light_bg: bool = False        # Terminal has a light background
    reduce_motion: bool = False   # User prefers reduced motion


def detect() -> TerminalCapabilities:
    """
    Probe the runtime environment and return a populated capabilities object.

    Detection heuristics (ordered by confidence):
      1. ``COLORTERM`` env var (``truecolor`` or ``24bit``)
      2. ``TERM_PROGRAM`` env var (known modern emulators)
      3. ``TERM`` env var (xterm-256color, etc.)
      4. Windows 10+ conhost / Windows Terminal (VT support)
      5. ``NO_COLOR`` convention (https://no-color.org)
      6. ``AGMERCIUM_REDUCE_MOTION`` env var
    """
    caps = TerminalCapabilities()

    # --- NO_COLOR convention (https://no-color.org): keep the color-off
    # defaults exactly as constructed ---
    if os.environ.get("NO_COLOR") is not None:
        return caps

    # --- Truecolor detection ---
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        caps.truecolor = True
        caps.colors_256 = True

    # Known truecolor terminal emulators
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    truecolor_programs = {
        "iterm.app", "hyper", "wezterm", "alacritty", "kitty",
        "vscode", "ghostty", "contour", "rio", "warp",
    }
    if term_program in truecolor_programs:
        caps.truecolor = True
        caps.colors_256 = True

    # Windows Terminal always supports truecolor
    if os.environ.get("WT_SESSION") or os.environ.get("WT_PROFILE_ID"):
        caps.truecolor = True
        caps.colors_256 = True

    # --- 256-color fallback ---
    term = os.environ.get("TERM", "").lower()
    if "256color" in term:
        caps.colors_256 = True
    if not caps.colors_256 and not caps.truecolor:
        # Windows 10+ conhost supports 256 colors via VT
        if sys.platform == "win32":
            caps.colors_256 = True  # Conservative default for Win10+

    # --- Light background heuristic ---
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        parts = colorfgbg.split(";")
        if len(parts) >= 2:
            try:
                bg_code = int(parts[-1])
                # Colors 0-6 and 8 are dark, 7 and 9-15 are light
                caps.light_bg = bg_code in (7, 9, 10, 11, 12, 13, 14, 15)
            except ValueError:
                pass
    if term_program == "apple_terminal":
        caps.light_bg = True  # Default Apple Terminal is light

    # --- Reduce motion ---
    if os.environ.get("AGMERCIUM_REDUCE_MOTION", "").lower() in ("1", "true", "yes"):
        caps.reduce_motion = True
    # Respect macOS accessibility setting
    if os.environ.get("REDUCE_MOTION", "").lower() in ("1", "true"):
        caps.reduce_motion = True

    return caps


# ==============================================================================
# SINGLETON — Detect once at import time
# ==============================================================================

CAPS = detect()

