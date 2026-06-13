"""
Heuristics for inferring workspace paths from local Antigravity data.

UI-agnostic — performs file I/O only and returns data.
"""

from __future__ import annotations

import os
import platform
import re


class ArtifactParser:
    """Infers workspace paths from per-conversation data under ~/.gemini/antigravity/."""

    @staticmethod
    def infer_workspace_from_brain(conv_uuid: str, brain_dir: str) -> str | None:
        """
        Scan Markdown files for file:/// URIs to infer the developer's workspace path.
        """
        target_dir = os.path.join(brain_dir, conv_uuid)
        if not os.path.isdir(target_dir):
            return None

        is_windows = platform.system() == "Windows"
        if is_windows:
            path_pattern = re.compile(r"file:///([A-Za-z](?:%3A|:)/[^)\s\"'\]>]+)")
        else:
            path_pattern = re.compile(r"file:///([^)\s\"'\]>]+)")

        path_counts: dict[str, int] = {}
        try:
            for name in os.listdir(target_dir):
                if not name.endswith(".md") or name.startswith("."):
                    continue
                filepath = os.path.join(target_dir, name)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read(16384)
                    for match in path_pattern.finditer(content):
                        raw = match.group(1)
                        raw = raw.replace("%3A", ":").replace("%3a", ":")
                        raw = raw.replace("%20", " ")
                        parts = raw.replace("\\", "/").split("/")

                        depth_start = 4 if is_windows else 3
                        for d in range(depth_start, len(parts)):
                            ws = "/".join(parts[:d])
                            path_counts[ws] = path_counts.get(ws, 0) + 1
                except OSError:
                    pass
        except OSError:
            return None

        if not path_counts:
            return None

        max_count = max(path_counts.values())
        best = max([k for k, v in path_counts.items() if v == max_count], key=len)

        candidate = best.replace("/", os.sep)
        current = candidate
        while current and os.path.dirname(current) != current:
            if os.path.isdir(os.path.join(current, ".git")):
                return current
            current = os.path.dirname(current)

        return candidate
