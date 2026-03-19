"""
Interactive CLI functions for workspace registration and user prompts.
"""

from __future__ import annotations

import os
import urllib.parse

from .logger import Logger


def prompt_workspace() -> dict:
    """
    Interactively collects the user's project folder path and generates
    all required Workspace URI parameters for the Protobuf schema.
    """
    Logger.header("Project Workspace Registration")
    Logger.info("To reconstruct the IDE indexing schema, we need the absolute")
    Logger.info("path to the project folder whose history was lost.")
    Logger.info("")
    Logger.warn("NOTE: All recovered conversations will be bound to this workspace.")
    Logger.warn("If you have multiple projects, run this tool once for your primary")
    Logger.warn("project. Conversations will be visible from that project's sidebar.")
    Logger.warn("For SSH remote sessions, run this tool ON the remote machine.")

    while True:
        try:
            raw = input(
                "\n[?] Enter the absolute path to your project folder\n"
                "    (e.g., C:\\Projects\\MyProject or /home/user/projects/myproject): "
            ).strip()

            # Strip surrounding quotes (common when users paste from file explorers)
            path = raw.strip("'\"")

            if not path:
                Logger.warn("Path cannot be empty. Please try again or press Ctrl+C to abort.")
                continue

            if not os.path.isabs(path):
                Logger.warn("That does not look like an absolute path. Please provide a full path.")
                continue

            if not os.path.exists(path):
                Logger.warn("Path does not exist on disk. Proceeding anyway (it may have been moved).")

            # Normalize to forward slashes for URI construction
            path_normalized = path.replace("\\", "/").rstrip("/")

            folder_name = os.path.basename(path_normalized) or "RecoveredProject"

            # Use proper URI encoding via urllib for all special characters
            uri_path_encoded = urllib.parse.quote(path_normalized, safe="/")
            uri_encoded = f"file:///{uri_path_encoded}"
            uri_plain = f"file:///{path_normalized}"

            workspace = {
                "uri_encoded": uri_encoded,
                "uri_plain": uri_plain,
                # Corpus and git_remote are synthetic placeholders required by the schema.
                # The IDE uses them for internal grouping but does not validate against
                # any external service. These values are safe defaults.
                "corpus": f"local/{folder_name}",
                "git_remote": f"https://github.com/local/{folder_name}.git",
                "branch": "main",
            }

            Logger.success("Workspace parameters generated:")
            Logger.info(f"  URI (plain):   {uri_plain}")
            Logger.info(f"  URI (encoded): {uri_encoded}")
            Logger.info(f"  Corpus:        {workspace['corpus']}")
            Logger.info(f"  Branch:        {workspace['branch']}")

            confirm = input("\n[?] Does this look correct? (Y/n): ").strip().lower()
            if confirm == "n":
                Logger.info("Let's try again.")
                continue

            return workspace

        except KeyboardInterrupt:
            print()
            Logger.error("Aborted by user.", fatal=True)
            return {}  # Unreachable, but satisfies type checkers
