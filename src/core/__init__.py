"""
Agmercium Recovery Suite — Core Business Logic Layer.

All modules in this package are UI-agnostic: no print(), input(), or ANSI codes.
Both the TUI and headless frontends consume these modules identically.
"""

from .constants import VERSION

__all__ = ["VERSION"]
