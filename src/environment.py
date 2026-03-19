"""
Cross-platform path resolution for all Antigravity IDE data stores.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .logger import Logger


class EnvironmentResolver:
    """Cross-platform path resolution for all Antigravity IDE data stores."""

    @staticmethod
    def get_antigravity_db_path() -> str:
        """Returns the OS-specific absolute path to the IDE's state.vscdb."""
        home = os.path.expanduser("~")
        if sys.platform.startswith("win"):
            appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            return os.path.join(appdata, "antigravity", "User", "globalStorage", "state.vscdb")
        elif sys.platform.startswith("darwin"):
            return os.path.join(
                home, "Library", "Application Support", "antigravity",
                "User", "globalStorage", "state.vscdb",
            )
        else:  # Linux / BSD / WSL
            return os.path.join(home, ".config", "antigravity", "User", "globalStorage", "state.vscdb")

    @staticmethod
    def get_gemini_base_path() -> str:
        """Returns the path to ~/.gemini/antigravity/."""
        return os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")

    @staticmethod
    def is_antigravity_running() -> bool:
        """Best-effort detection of whether the Antigravity IDE process is active."""
        try:
            if sys.platform.startswith("win"):
                res = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq Antigravity.exe", "/NH"],
                    capture_output=True, text=True, timeout=10,
                )
                return "Antigravity.exe" in res.stdout
            else:
                res = subprocess.run(
                    ["pgrep", "-f", "antigravity"],
                    capture_output=True, text=True, timeout=10,
                )
                return bool(res.stdout.strip())
        except Exception as exc:
            Logger.debug(f"Process detection skipped: {exc}")
            return False
