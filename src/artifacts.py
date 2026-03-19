"""
Extracts human-readable conversation titles from brain artifacts.
"""

from __future__ import annotations

import os

from .constants import MIN_TITLE_LENGTH, MAX_TITLE_LENGTH, TITLE_ARTIFACT_FILES, OVERVIEW_SUBPATH
from .logger import Logger


class ArtifactParser:
    """Extracts human-readable conversation titles from brain artifacts."""

    @staticmethod
    def extract_title(conv_uuid: str, brain_dir: str) -> str | None:
        """
        Attempts to extract a meaningful title from the brain artifacts
        for a given conversation UUID, using a priority-ordered fallback chain:
          1. First Markdown heading in task.md / implementation_plan.md / walkthrough.md
          2. First meaningful line in .system_generated/logs/overview.txt
          3. None (caller generates a timestamp-based fallback)
        """
        target_dir = os.path.join(brain_dir, conv_uuid)
        if not os.path.isdir(target_dir):
            return None

        # Priority 1: Markdown artifact headings
        for artifact_file in TITLE_ARTIFACT_FILES:
            filepath = os.path.join(target_dir, artifact_file)
            if os.path.isfile(filepath):
                title = ArtifactParser._read_first_heading(filepath)
                if title:
                    return title

        # Priority 2: System-generated overview log
        overview_path = os.path.join(target_dir, OVERVIEW_SUBPATH)
        if os.path.isfile(overview_path):
            try:
                with open(overview_path, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        clean = line.strip()
                        if clean and not clean.startswith("#") and len(clean) > MIN_TITLE_LENGTH:
                            return clean[:MAX_TITLE_LENGTH]
            except OSError:
                Logger.debug(f"Could not read overview log for {conv_uuid}")

        return None

    @staticmethod
    def _read_first_heading(filepath: str) -> str | None:
        """Extracts the first Markdown heading (# ...) from a file."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        # Remove all leading '#' characters, then strip whitespace
                        title = stripped.lstrip("#").strip()
                        if title:
                            return title[:MAX_TITLE_LENGTH]
        except OSError:
            pass
        return None
