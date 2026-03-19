#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
================================================================================
                           AGMERCIUM RECOVERY SUITE
                     Antigravity IDE History Recovery Tool
================================================================================

  Author:       Donald R. Johnson
  Organization: Agmercium (https://agmercium.com)
  License:      The Unlicense (Public Domain)
  Version:      1.0.0
  Python:       3.7+
  Dependencies: None (standard library only)

  A production-ready, enterprise-grade utility to securely rebuild the internal
  SQLite UI indices of the Google Antigravity IDE from local Protobuf (.pb)
  cache files.

  This resolves the critical data-loss bug where the IDE fails to correctly
  flush its JSON/Protobuf conversation indices during shutdown, resulting in
  complete loss of UI history upon restart or update.

  Usage:
    1. Close the Antigravity IDE completely.
    2. Run: python antigravity_recover.py
    3. Follow the interactive prompts.
    4. Restart the Antigravity IDE.

  For help:  python antigravity_recover.py --help

  GitHub:  https://github.com/agmercium/antigravity-recovery
  Issues:  https://github.com/agmercium/antigravity-recovery/issues

================================================================================
"""

# ==============================================================================
# IMPORTS (Standard Library Only — Zero External Dependencies)
# ==============================================================================
import sqlite3
import base64
import os
import re
import json
import time
import sys
import shutil
import subprocess
import uuid
import urllib.parse

# ==============================================================================
# CONSTANTS
# ==============================================================================
VERSION = "1.1.0"
TOOL_NAME = "Agmercium Antigravity Recovery Tool"
MIN_TITLE_LENGTH = 5           # Minimum chars for a line to qualify as a title
MAX_TITLE_LENGTH = 80          # Truncation limit for extracted titles
BACKUP_PREFIX = "agmercium_recovery"
UUID_PATTERN = rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

PB_KEY = "antigravityUnifiedStateSync.trajectorySummaries"
JSON_KEY = "chat.ChatSessionStore.index"

TITLE_ARTIFACT_FILES = ["task.md", "implementation_plan.md", "walkthrough.md"]
OVERVIEW_SUBPATH = os.path.join(".system_generated", "logs", "overview.txt")


# ==============================================================================
# UNIFIED LOGGING SYSTEM
# ==============================================================================
class Logger:
    """Centralized, consistently-formatted console output for all severity levels."""

    _TAG_WIDTH = 6  # Visual alignment width for log tags

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
    def banner() -> None:
        print()
        print("=" * 80)
        print("    AGMERCIUM RECOVERY SUITE")
        print(f"    {TOOL_NAME} v{VERSION}")
        print("    by Donald R. Johnson | https://agmercium.com")
        print("=" * 80)


# ==============================================================================
# PROTOBUF ENCODING ENGINE
# ==============================================================================
class ProtobufEncoder:
    """
    Deterministic Protobuf Wire Format encoder for Wire Type 0 (Varint)
    and Wire Type 2 (Length-delimited) fields.

    Implements the exact nested schema required by the Antigravity IDE's
    internal `trajectorySummaries` Protobuf parser, including the deeply
    nested Tag 3 (Field 9) and Tag 1 (Field 17) sub-messages.
    """

    @staticmethod
    def write_varint(v: int) -> bytes:
        """Encode a non-negative integer as a Protobuf base-128 varint."""
        if v == 0:
            return b"\x00"
        result = bytearray()
        while v > 0x7F:
            result.append((v & 0x7F) | 0x80)
            v >>= 7
        result.append(v & 0x7F)
        return bytes(result)

    @classmethod
    def write_string_field(cls, field_num: int, value: str | bytes) -> bytes:
        """Encode a string or raw bytes as a length-delimited Protobuf field."""
        b = value.encode("utf-8") if isinstance(value, str) else value
        return cls.write_varint((field_num << 3) | 2) + cls.write_varint(len(b)) + b

    @classmethod
    def write_bytes_field(cls, field_num: int, value: bytes) -> bytes:
        """Encode raw bytes as a length-delimited Protobuf field."""
        return cls.write_varint((field_num << 3) | 2) + cls.write_varint(len(value)) + value

    @classmethod
    def write_varint_field(cls, field_num: int, value: int) -> bytes:
        """Encode an integer as a Protobuf varint field."""
        return cls.write_varint((field_num << 3) | 0) + cls.write_varint(value)

    @classmethod
    def write_timestamp(cls, field_num: int, epoch_seconds: int, nanos: int = 0) -> bytes:
        """Encode a Protobuf Timestamp message (seconds + nanos)."""
        inner = cls.write_varint_field(1, epoch_seconds) + cls.write_varint_field(2, nanos)
        return cls.write_bytes_field(field_num, inner)

    @classmethod
    def build_workspace_field9(cls, ws: dict) -> bytes:
        """
        Constructs the deeply nested Field 9 workspace metadata.
        Schema: Field 9 { Field 1: uri, Field 2: uri, Field 3 { Field 1: corpus, Field 2: git_remote }, Field 4: branch }
        """
        sub3_inner = (
            cls.write_string_field(1, ws["corpus"])
            + cls.write_string_field(2, ws["git_remote"])
        )
        inner = (
            cls.write_string_field(1, ws["uri_encoded"])
            + cls.write_string_field(2, ws["uri_encoded"])
            + cls.write_bytes_field(3, sub3_inner)
            + cls.write_string_field(4, ws["branch"])
        )
        return cls.write_bytes_field(9, inner)

    @classmethod
    def build_workspace_field17(cls, ws: dict, session_uuid: str, epoch_seconds: int, nanos: int = 0) -> bytes:
        """
        Constructs the deeply nested Field 17 workspace URI parameters.
        Schema: Field 17 { Field 1 { Field 1: uri, Field 2: uri }, Field 2 { Field 1: seconds, Field 2: nanos }, Field 3: session_uuid, Field 7: uri_encoded }
        """
        sub1_inner = (
            cls.write_string_field(1, ws["uri_plain"])
            + cls.write_string_field(2, ws["uri_plain"])
        )
        sub2 = cls.write_varint_field(1, epoch_seconds) + cls.write_varint_field(2, nanos)
        inner = (
            cls.write_bytes_field(1, sub1_inner)
            + cls.write_bytes_field(2, sub2)
            + cls.write_string_field(3, session_uuid)
            + cls.write_string_field(7, ws["uri_encoded"])
        )
        return cls.write_bytes_field(17, inner)

    @classmethod
    def build_trajectory_entry(
        cls,
        conv_uuid: str,
        title: str,
        workspace: dict,
        create_epoch: int,
        modify_epoch: int,
        step_count: int = 1,
    ) -> bytes:
        """
        Generates a complete trajectorySummaries entry with Base64-wrapped
        inner Protobuf payload, matching the IDE's exact parsing expectations.
        """
        parent_uuid = str(uuid.uuid4())

        inner_pb = (
            cls.write_string_field(1, title)
            + cls.write_varint_field(2, step_count)
            + cls.write_timestamp(3, create_epoch)
            + cls.write_string_field(4, parent_uuid)
            + cls.write_varint_field(5, 1)       # Status: ACTIVE
            + cls.write_timestamp(7, modify_epoch)
            + cls.build_workspace_field9(workspace)
            + cls.write_timestamp(10, modify_epoch)
            + cls.write_string_field(15, "")
            + cls.write_varint_field(16, 0)
            + cls.build_workspace_field17(workspace, parent_uuid, modify_epoch)
        )

        inner_b64 = base64.b64encode(inner_pb).decode("utf-8")
        wrapper = cls.write_string_field(1, inner_b64)
        entry = cls.write_string_field(1, conv_uuid) + cls.write_bytes_field(2, wrapper)
        return cls.write_bytes_field(1, entry)


# ==============================================================================
# ENVIRONMENT RESOLUTION & DISCOVERY
# ==============================================================================
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


# ==============================================================================
# ARTIFACT TITLE EXTRACTION
# ==============================================================================
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


# ==============================================================================
# INTERACTIVE CLI
# ==============================================================================
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


# ==============================================================================
# DATABASE ROLLBACK HELPER
# ==============================================================================
def safe_rollback(backup_path: str, target_path: str) -> None:
    """
    Attempts to restore the database from a backup mirror.
    Logs the outcome but never raises — this is a last-resort recovery path.
    """
    try:
        shutil.copy2(backup_path, target_path)
        Logger.warn("Database has been rolled back to the pre-recovery backup.")
    except Exception as rollback_err:
        Logger.error(f"CRITICAL: Rollback also failed: {rollback_err}")
        Logger.error(f"Your original backup is preserved at: {backup_path}")
        Logger.error("Please manually copy it back over your state.vscdb file.")


# ==============================================================================
# MAIN EXECUTION ROUTINE
# ==============================================================================
def main() -> None:
    # Handle --help and --version before anything else
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"{TOOL_NAME} v{VERSION}")
        sys.exit(0)

    Logger.banner()

    # ------------------------------------------------------------------
    # Phase 1: Pre-flight Checks
    # ------------------------------------------------------------------
    Logger.header("Phase 1: Pre-flight Checks")

    if EnvironmentResolver.is_antigravity_running():
        Logger.warn("Antigravity IDE appears to be running!")
        Logger.warn("The IDE will OVERWRITE our patches when it shuts down.")
        try:
            ans = input("   Are you absolutely sure you want to proceed? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print()
            Logger.error("Aborted.", fatal=True)
        if ans != "y":
            Logger.info("Operation safely aborted. Close the IDE first, then retry.")
            sys.exit(0)

    db_path = EnvironmentResolver.get_antigravity_db_path()
    gem_base = EnvironmentResolver.get_gemini_base_path()
    convs_dir = os.path.join(gem_base, "conversations")
    brain_dir = os.path.join(gem_base, "brain")

    Logger.info(f"Database path:      {db_path}")
    Logger.info(f"Conversations dir:  {convs_dir}")
    Logger.info(f"Brain artifacts:    {brain_dir}")

    if not os.path.isfile(db_path):
        Logger.error(f"Database not found at: {db_path}", fatal=True)

    if not os.path.isdir(convs_dir):
        Logger.error(f"Conversations directory not found at: {convs_dir}", fatal=True)

    if not os.access(db_path, os.R_OK | os.W_OK):
        Logger.error(f"Insufficient read/write permissions on: {db_path}", fatal=True)

    # ------------------------------------------------------------------
    # Phase 2: Conversation Discovery
    # ------------------------------------------------------------------
    Logger.header("Phase 2: Conversation Discovery")
    Logger.info("Scanning for local .pb conversation cache files...")

    try:
        raw_files = os.listdir(convs_dir)
    except OSError as exc:
        Logger.error(f"Cannot read conversations directory: {exc}", fatal=True)

    all_pbs = sorted([f[:-3] for f in raw_files if f.endswith(".pb")])

    if not all_pbs:
        Logger.success("No local .pb files found. Your history is already clean — nothing to recover.")
        sys.exit(0)

    Logger.success(f"Discovered {len(all_pbs)} conversation(s) on disk.")

    workspace = prompt_workspace()

    # ------------------------------------------------------------------
    # Phase 3: Secure Backup
    # ------------------------------------------------------------------
    Logger.header("Phase 3: Secure Database Backup")

    backup_db = f"{db_path}.{BACKUP_PREFIX}_{int(time.time())}"
    try:
        shutil.copy2(db_path, backup_db)
        Logger.success(f"Backup created: {backup_db}")
    except Exception as exc:
        Logger.error(f"Backup failed: {exc}", fatal=True)

    # ------------------------------------------------------------------
    # Phase 4: Database Injection
    # ------------------------------------------------------------------
    Logger.header("Phase 4: Database Injection")

    stats = {"pb_injected": 0, "pb_skipped": 0, "json_added": 0, "json_skipped": 0}
    conn = None

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # ---- Phase 4A: Protobuf Index (trajectorySummaries) ----
        Logger.info("Reading Protobuf trajectory index...")
        cur.execute("SELECT value FROM ItemTable WHERE key=?", (PB_KEY,))
        row = cur.fetchone()

        if not row:
            Logger.warn(f"Key '{PB_KEY}' not found in database. Creating it from scratch.")
            Logger.info("This is expected on fresh installs or databases where the key was wiped.")

        if row:
            try:
                decoded = base64.b64decode(row[0])
            except Exception as exc:
                Logger.error(f"Failed to decode Protobuf payload (corrupt base64): {exc}", fatal=False)
                safe_rollback(backup_db, db_path)
                Logger.error("Recovery aborted after rollback.", fatal=True)
        else:
            decoded = b""  # Start with empty payload; all entries will be injected

        existing_uuids = set(
            match.decode() for match in re.findall(UUID_PATTERN, decoded)
        )
        Logger.info(f"Existing Protobuf entries: {len(existing_uuids)}")

        missing_pbs = [cid for cid in all_pbs if cid not in existing_uuids]
        stats["pb_skipped"] = len(all_pbs) - len(missing_pbs)

        Logger.info(f"Missing from Protobuf index: {len(missing_pbs)}")

        if missing_pbs:
            result = decoded
            for cid in missing_pbs:
                title = ArtifactParser.extract_title(cid, brain_dir)
                pb_path = os.path.join(convs_dir, f"{cid}.pb")

                # Use file timestamps when available; fall back to current time
                # Note: On Linux, os.path.getctime() returns metadata change time,
                # not true creation time. This is acceptable for our use case.
                if os.path.isfile(pb_path):
                    modify_epoch = int(os.path.getmtime(pb_path))
                    create_epoch = int(os.path.getctime(pb_path))
                else:
                    modify_epoch = create_epoch = int(time.time())

                if not title:
                    date_str = time.strftime("%b %d", time.localtime(modify_epoch))
                    title = f"Conversation ({date_str}) {cid[:8]}"

                entry_bytes = ProtobufEncoder.build_trajectory_entry(
                    cid, title, workspace, create_epoch, modify_epoch,
                )
                result += entry_bytes
                stats["pb_injected"] += 1

            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (PB_KEY, base64.b64encode(result).decode()),
            )
            Logger.success(f"Injected {stats['pb_injected']} Protobuf entries.")

        # ---- Phase 4B: JSON UI Index (ChatSessionStore.index) ----
        Logger.info("Reading JSON session index...")
        cur.execute("SELECT value FROM ItemTable WHERE key=?", (JSON_KEY,))
        idx_row = cur.fetchone()

        try:
            chat_idx = json.loads(idx_row[0]) if idx_row else {"version": 1, "entries": {}}
        except (json.JSONDecodeError, TypeError):
            Logger.warn("JSON index was corrupt or missing. Initializing empty index.")
            chat_idx = {"version": 1, "entries": {}}

        entries_before = len(chat_idx.get("entries", {}))

        for cid in all_pbs:
            if cid not in chat_idx.setdefault("entries", {}):
                title = ArtifactParser.extract_title(cid, brain_dir) or f"Conversation {cid[:8]}"
                pb_path = os.path.join(convs_dir, f"{cid}.pb")

                if os.path.isfile(pb_path):
                    mtime_ms = int(os.path.getmtime(pb_path) * 1000)
                else:
                    mtime_ms = int(time.time() * 1000)

                chat_idx["entries"][cid] = {
                    "sessionId": cid,
                    "title": title,
                    "lastModified": mtime_ms,
                    "isStale": False,
                }
                stats["json_added"] += 1
            else:
                stats["json_skipped"] += 1

        entries_after = len(chat_idx["entries"])
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            (JSON_KEY, json.dumps(chat_idx, ensure_ascii=False)),
        )
        Logger.success(f"JSON index updated: {entries_before} -> {entries_after} entries.")

        # ---- Commit ----
        conn.commit()
        Logger.success("All changes committed successfully.")

    except sqlite3.Error as exc:
        Logger.error(f"SQLite error: {exc}")
        safe_rollback(backup_db, db_path)
        Logger.error("Recovery aborted after database rollback.", fatal=True)

    except SystemExit:
        raise  # Allow sys.exit() to propagate cleanly

    except Exception as exc:
        Logger.error(f"Unexpected error: {exc}")
        safe_rollback(backup_db, db_path)
        Logger.error("Recovery aborted after database rollback.", fatal=True)

    finally:
        if conn is not None:
            conn.close()

    # ------------------------------------------------------------------
    # Phase 5: Summary
    # ------------------------------------------------------------------
    Logger.header("Recovery Complete")
    print()
    Logger.success(f"Conversations discovered on disk:  {len(all_pbs)}")
    Logger.success(f"Protobuf entries injected:         {stats['pb_injected']}")
    Logger.success(f"Protobuf entries already present:  {stats['pb_skipped']}")
    Logger.success(f"JSON entries added:                 {stats['json_added']}")
    Logger.success(f"JSON entries already present:       {stats['json_skipped']}")
    print()
    Logger.info(f"Backup preserved at: {backup_db}")
    Logger.info("You may now launch the Antigravity IDE. Your history should be fully restored.")
    print()


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        Logger.error("Interrupted by user.", fatal=True)
