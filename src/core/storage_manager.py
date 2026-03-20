"""
Atomic read/write manager for the IDE's ``storage.json`` configuration file.

Provides backup-first safety, recursive key flattening for TUI tree display,
and dotted-path patch/delete operations.

This module is UI-agnostic — no print(), input(), or ANSI codes.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

from .constants import STORAGE_FILENAME, BACKUP_PREFIX
from .models import StorageEntry


def _storage_path(user_data_dir: str) -> str:
    """Returns the absolute path to storage.json within a globalStorage directory."""
    return os.path.join(user_data_dir, STORAGE_FILENAME)


def read_storage(user_data_dir: str) -> dict[str, Any]:
    """
    Atomically reads and parses the IDE's storage.json file.

    Returns an empty dict if the file is missing or corrupt.
    """
    path = _storage_path(user_data_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def write_storage(user_data_dir: str, data: dict[str, Any], reason: str = "manual") -> str:
    """
    Writes the given data back to storage.json, creating a backup first.

    Returns the backup file path.
    """
    path = _storage_path(user_data_dir)
    backup_path = f"{path}.{BACKUP_PREFIX}_{int(time.time())}_{reason}"

    if os.path.isfile(path):
        shutil.copy2(path, backup_path)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    return backup_path


def flatten_keys(data: dict[str, Any], prefix: str = "") -> list[StorageEntry]:
    """
    Recursively flattens a nested dict into a list of ``StorageEntry`` objects
    suitable for TUI tree display.
    """
    entries: list[StorageEntry] = []
    for key, val in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            entries.append(StorageEntry(key=full_key, value_type="object", value_preview=f"{{{len(val)} keys}}"))
            entries.extend(flatten_keys(val, full_key))
        elif isinstance(val, list):
            entries.append(StorageEntry(key=full_key, value_type="array", value_preview=f"[{len(val)} items]"))
        elif isinstance(val, bool):
            entries.append(StorageEntry(key=full_key, value_type="bool", value_preview=str(val).lower()))
        elif isinstance(val, (int, float)):
            entries.append(StorageEntry(key=full_key, value_type="number", value_preview=str(val)))
        elif val is None:
            entries.append(StorageEntry(key=full_key, value_type="null", value_preview="null"))
        else:
            preview = str(val)
            if len(preview) > 60:
                preview = preview[:57] + "..."
            entries.append(StorageEntry(key=full_key, value_type="string", value_preview=preview))
    return entries


def _resolve_path(data: dict[str, Any], parts: list[str]) -> tuple[dict[str, Any], str]:
    """Traverses a dotted path and returns the parent dict and the final key."""
    current = data
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(f"Path segment '{part}' not found")
    return current, parts[-1]


def patch_key(data: dict[str, Any], json_path: str, value: Any) -> dict[str, Any]:
    """
    Updates a nested key by dotted path. Returns the mutated data dict.

    Example: ``patch_key(data, "ui.theme.foreground", "#ffffff")``
    """
    parts = json_path.split(".")
    parent, final_key = _resolve_path(data, parts)
    if isinstance(parent, dict):
        parent[final_key] = value
    return data


def delete_key(data: dict[str, Any], json_path: str) -> dict[str, Any]:
    """
    Removes a nested key by dotted path. Returns the mutated data dict.
    """
    parts = json_path.split(".")
    parent, final_key = _resolve_path(data, parts)
    if isinstance(parent, dict) and final_key in parent:
        del parent[final_key]
    return data
