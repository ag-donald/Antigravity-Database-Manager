"""
Unified, consistently-formatted console logging for all severity levels.
"""

from __future__ import annotations

import os
import sys

from ..core.constants import AGMERCIUM_URL, APP_NAME, VERSION


class Logger:
    """Centralized, consistently-formatted console output for all severity levels."""

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
    def recovery_summary(result) -> None:
        """Standard success summary for the recovery pipeline (headless UIs)."""
        Logger.header("Recovery Complete")
        Logger.success(f"Conversations rebuilt:  {result.conversations_rebuilt}")
        Logger.success(f"Workspaces mapped:     {result.workspaces_mapped}")
        Logger.success(f"Timestamps injected:   {result.timestamps_injected}")
        Logger.success(f"JSON entries added:    {result.json_added}")
        Logger.success(f"JSON entries patched:  {result.json_patched}")
        Logger.success(f"JSON entries deleted:  {result.json_deleted}")
        Logger.info(f"Backup at: {result.backup_path}")

    @staticmethod
    def merge_summary(result) -> None:
        """Standard success summary for a merge operation (headless UIs)."""
        Logger.success(f"Merge complete: +{result.added} added, "
                       f"~{result.updated} updated, ={result.skipped} skipped")
        Logger.info(f"Backup at: {result.backup_path}")

    @staticmethod
    def banner() -> None:
        print()
        print("=" * 80)
        print("    AGMERCIUM RECOVERY SUITE")
        print(f"    {APP_NAME} v{VERSION}")
        print(f"    by Donald R. Johnson | {AGMERCIUM_URL}")
        print("=" * 80)
