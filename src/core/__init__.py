"""
Agmercium Recovery Suite — Core Business Logic Layer.

All modules in this package are 100% UI-agnostic. They contain no print(),
input(), or ANSI escape codes. Both the TUI and Headless frontends consume
these modules identically.
"""

from .constants import VERSION

__all__ = ["VERSION"]
