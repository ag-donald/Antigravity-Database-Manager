"""
Cross-platform path resolution for all Antigravity IDE data stores.

This module is UI-agnostic — it uses no Logger or print() calls.
Detection failures are silently handled and returned as booleans.
"""

from __future__ import annotations

import os
import subprocess
import sys

from .constants import DB_FILENAME


# Electron profile folder names, in preference order. "Antigravity" is the
# Antigravity 2.0 standalone app's profile; "antigravity" is the original
# (deprecated) IDE's. They are the same folder on case-insensitive
# filesystems (Windows, default macOS), which _dedupe() collapses.
_PROFILE_NAMES = ("Antigravity IDE", "Antigravity", "antigravity")

# Windows image names: the VS Code-based IDE and the standalone app
# (Antigravity 2.0, also the original IDE's name).
_WINDOWS_IMAGES = ("antigravity ide.exe", "antigravity.exe")


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _dedupe(paths: list[str]) -> list[str]:
    """Drops paths that name the same location as an earlier one, by
    normalized spelling or, for existing paths, by file identity."""
    kept: list[str] = []
    seen: set[str] = set()
    for p in paths:
        key = os.path.normcase(p)
        if key in seen:
            continue
        if os.path.exists(p) and any(_same_file(p, k) for k in kept if os.path.exists(k)):
            continue
        seen.add(key)
        kept.append(p)
    return kept


class EnvironmentResolver:
    """Cross-platform path resolution for all Antigravity IDE data stores."""

    @staticmethod
    def get_profile_dirs() -> list[str]:
        """Returns the OS-specific Electron profile directories (deduplicated)."""
        home = os.path.expanduser("~")
        if sys.platform.startswith("win"):
            base = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        elif sys.platform.startswith("darwin"):
            base = os.path.join(home, "Library", "Application Support")
        else:  # Linux / BSD / WSL
            base = os.path.join(home, ".config")
        return _dedupe([os.path.join(base, name) for name in _PROFILE_NAMES])

    @staticmethod
    def get_antigravity_db_paths() -> list[str]:
        """Returns the list of OS-specific candidate paths to the IDE's state.vscdb."""
        return _dedupe([
            os.path.join(d, "User", "globalStorage", DB_FILENAME)
            for d in EnvironmentResolver.get_profile_dirs()
        ])

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
        """Best-effort detection of whether an Antigravity IDE or app process is active."""
        try:
            if sys.platform.startswith("win"):
                res = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, errors="replace", timeout=10,
                )
                for line in res.stdout.splitlines():
                    image = line.split('","', 1)[0].strip().strip('"').lower()
                    if image in _WINDOWS_IMAGES:
                        return True
                return False
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
