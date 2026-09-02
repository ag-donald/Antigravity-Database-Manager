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
    def get_antigravity_db_paths() -> list[str]:
        """Returns the list of OS-specific candidate paths to the IDE's state.vscdb."""
        home = os.path.expanduser("~")
        candidates = []
        if sys.platform.startswith("win"):
            appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
            candidates.append(os.path.join(appdata, "Antigravity IDE", "User", "globalStorage", "state.vscdb"))
            candidates.append(os.path.join(appdata, "Antigravity", "User", "globalStorage", "state.vscdb"))
            candidates.append(os.path.join(appdata, "antigravity", "User", "globalStorage", "state.vscdb"))
        elif sys.platform.startswith("darwin"):
            candidates.append(os.path.join(
                home, "Library", "Application Support", "Antigravity IDE",
                "User", "globalStorage", "state.vscdb",
            ))
            candidates.append(os.path.join(
                home, "Library", "Application Support", "Antigravity",
                "User", "globalStorage", "state.vscdb",
            ))
            candidates.append(os.path.join(
                home, "Library", "Application Support", "antigravity",
                "User", "globalStorage", "state.vscdb",
            ))
        else:  # Linux / BSD / WSL
            candidates.append(os.path.join(home, ".config", "Antigravity IDE", "User", "globalStorage", "state.vscdb"))
            candidates.append(os.path.join(home, ".config", "Antigravity", "User", "globalStorage", "state.vscdb"))
        return candidates

    @staticmethod
    def get_antigravity_db_path() -> str:
        """Returns the OS-specific absolute path to the IDE's state.vscdb, preferring existing files."""
        paths = EnvironmentResolver.get_antigravity_db_paths()
        for p in paths:
            if os.path.isfile(p):
                return p
        return paths[0]

    @staticmethod
    def get_gemini_base_paths() -> list[str]:
        """Returns all gemini base candidates, preferring the modern layout."""
        home = os.path.expanduser("~")
        return [
            os.path.join(home, ".gemini", "antigravity-ide"),
            os.path.join(home, ".gemini", "antigravity"),
        ]

    @staticmethod
    def get_gemini_base_path() -> str:
        """Returns the path to ~/.gemini/antigravity/ or ~/.gemini/antigravity-ide/."""
        for base in EnvironmentResolver.get_gemini_base_paths():
            if os.path.isdir(base):
                return base
        return EnvironmentResolver.get_gemini_base_paths()[-1]

    @staticmethod
    def is_antigravity_running() -> bool:
        """Best-effort detection of whether the Antigravity IDE process is active."""
        try:
            if sys.platform.startswith("win"):
                res = subprocess.run(
                    ["tasklist", "/FI", "IMAGENAME eq Antigravity.exe", "/NH"],
                    capture_output=True, text=True, errors="replace", timeout=10,
                )
                return "Antigravity.exe" in res.stdout
            else:
                # `ps` is used instead of `pgrep -f` because pgrep's flags for
                # full-commandline listing differ between procps (Linux) and
                # BSD (macOS), and a bare match on "antigravity" is both
                # case-sensitive (missing "Antigravity IDE.app" on macOS) and
                # a false positive on this tool's own command line.
                res = subprocess.run(
                    ["ps", "-eo", "pid=,args="],
                    capture_output=True, text=True, errors="replace", timeout=10,
                )
                own_pid = str(os.getpid())
                self_markers = ("antigravity_database_manager", "fix_workspace_uri",
                                "antigravity-database-manager")
                for line in res.stdout.splitlines():
                    pid, _, cmd = line.strip().partition(" ")
                    cmd_lower = cmd.lower()
                    if pid == own_pid or "antigravity" not in cmd_lower:
                        continue
                    if any(marker in cmd_lower for marker in self_markers):
                        continue
                    return True
                return False
        except Exception:
            return False
