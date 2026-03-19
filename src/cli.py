"""
Interactive CLI functions for workspace registration and user prompts.
"""

from __future__ import annotations

import os
import urllib.parse

from .logger import Logger


def build_workspace_dict(path: str) -> dict:
    """Builds the workspace dictionary required by the Protobuf schema from a local path."""
    path_normalized = path.replace("\\", "/").rstrip("/")
    folder_name = os.path.basename(path_normalized) or "RecoveredProject"
    
    uri_path_encoded = urllib.parse.quote(path_normalized, safe="/")
    uri_encoded = f"file:///{uri_path_encoded}"
    uri_plain = f"file:///{path_normalized}"
    
    return {
        "uri_encoded": uri_encoded,
        "uri_plain": uri_plain,
        "corpus": f"local/{folder_name}",
        "git_remote": f"https://github.com/local/{folder_name}.git",
        "branch": "main",
    }


def _prompt_valid_folder(prompt_text: str) -> str | None:
    """Keep asking for a folder until user gives a valid one or presses Enter."""
    while True:
        try:
            raw = input(prompt_text).strip()
        except KeyboardInterrupt:
            return None
        if raw == "":
            return None
        folder = raw.strip('"').strip("'").rstrip("\\/")
        if os.path.isdir(folder):
            Logger.success(f"Mapped to {folder}")
            return folder
        else:
            Logger.warn(f"Path not found: {folder}")
            Logger.warn("Make sure the folder exists. Try again or press Enter to skip.")


def interactive_workspace_assignment(unmapped_entries: list[tuple[int, str, str]]) -> dict[str, dict]:
    """
    Show unmapped conversations and let user assign workspace paths.
    unmapped_entries: list of (index, conversation_id, title)
    Returns dict mapping conversation_id -> workspace_dict.
    """
    if not unmapped_entries:
        return {}

    print()
    Logger.header("WORKSPACE ASSIGNMENT (optional)")
    Logger.info(f"{len(unmapped_entries)} conversation(s) have no workspace.")
    Logger.info("You can assign each to a workspace folder now,")
    Logger.info("or press Enter to skip and leave them unassigned.")
    print()

    assignments = {}
    batch_workspace = None

    for idx, cid, title in unmapped_entries:
        if batch_workspace:
            assignments[cid] = batch_workspace
            folder_name = os.path.basename(batch_workspace["uri_plain"])
            print(f"    [{idx:3d}] {title[:45]}  -> {folder_name}")
            continue

        print(f"  [{idx:3d}] {title[:55]}")
        while True:
            try:
                raw = input("    Workspace path (Enter=skip, 'all'=batch, 'q'=stop): ").strip()
            except KeyboardInterrupt:
                raw = "q"
                
            if raw == "":
                print("    Skipped.")
                break
            if raw.lower() == "q":
                print("    Stopped — remaining conversations left unmapped.")
                return assignments
            if raw.lower() == "all":
                folder = _prompt_valid_folder("    Path for ALL remaining (Enter=cancel): ")
                if folder is None:
                    continue
                batch_workspace = build_workspace_dict(folder)
                assignments[cid] = batch_workspace
                break
            
            folder = raw.strip('"').strip("'").rstrip("\\/")
            if os.path.isdir(folder):
                Logger.success(f"Mapped to {folder}")
                assignments[cid] = build_workspace_dict(folder)
                break
            else:
                Logger.warn(f"Path not found: {folder}")
                Logger.warn("Try again or press Enter to skip.")

    if assignments:
        print()
        Logger.success(f"Assigned workspace to {len(assignments)} conversation(s)")
    print()
    return assignments
