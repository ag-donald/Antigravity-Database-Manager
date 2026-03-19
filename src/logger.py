"""
Unified, consistently-formatted console logging for all severity levels.
"""

from __future__ import annotations

import os
import sys

from .constants import TOOL_NAME, VERSION


class Logger:
    """Centralized, consistently-formatted console output for all severity levels."""

    _TAG_WIDTH = 6  # Visual alignment width for log tags

    @staticmethod
    def info(msg: str) -> None:
        print(f"[INFO ] {msg}")

    @staticmethod
    def success(msg: str) -> None:
        print(f"[ OK  ] {msg}")

    @staticmethod
    def warn(msg: str) -> None:
        print(f"[WARN ] {msg}")

    @staticmethod
    def debug(msg: str) -> None:
        """Only printed when AGMERCIUM_DEBUG=1 is set in the environment."""
        if os.environ.get("AGMERCIUM_DEBUG") == "1":
            print(f"[DEBUG] {msg}")

    @staticmethod
    def error(msg: str, fatal: bool = False) -> None:
        print(f"[ERROR] {msg}")
        if fatal:
            print("\n[FATAL] Execution halted due to an unrecoverable error.")
            sys.exit(1)

    @staticmethod
    def header(msg: str) -> None:
        bar = "=" * 80
        print(f"\n{bar}")
        print(f"  {msg}")
        print(bar)

    @staticmethod
    def banner() -> None:
        print()
        print("=" * 80)
        print("    AGMERCIUM RECOVERY SUITE")
        print(f"    {TOOL_NAME} v{VERSION}")
        print("    by Donald R. Johnson | https://agmercium.com")
        print("=" * 80)
