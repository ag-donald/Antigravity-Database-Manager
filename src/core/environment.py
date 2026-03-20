"""
Cross-platform path resolution for all Antigravity IDE data stores.

This module is UI-agnostic — it uses no Logger or print() calls.
Detection failures are silently handled and returned as booleans.
"""

from __future__ import annotations

import os
import subprocess
import sys


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
    def get_storage_json_path() -> str:
        """Returns the OS-specific path to the IDE's storage.json (sibling of state.vscdb)."""
        db_path = EnvironmentResolver.get_antigravity_db_path()
        return os.path.join(os.path.dirname(db_path), "storage.json")

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
        except Exception:
            return False
