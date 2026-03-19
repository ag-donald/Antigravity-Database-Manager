"""
Core recovery pipeline — database backup, injection, and rollback logic.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import sys
import time

from .constants import PB_KEY, JSON_KEY, TOOL_NAME, VERSION, BACKUP_PREFIX
from .logger import Logger
from .protobuf import ProtobufEncoder
from .environment import EnvironmentResolver
from .artifacts import ArtifactParser
from .cli import interactive_workspace_assignment


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
# METADATA EXTRACTION
# ==============================================================================
def extract_existing_metadata(decoded: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    """
    Extracts real titles and intact inner Protobuf blobs from the DB row.
    Returns (titles_dict, inner_blobs_dict).
    """
    titles = {}
    inner_blobs = {}
    pos = 0

    while pos < len(decoded):
        try:
            tag, pos = ProtobufEncoder.decode_varint(decoded, pos)
        except Exception:
            break
        wire_type = tag & 7

        if wire_type != 2:
            break

        length, pos = ProtobufEncoder.decode_varint(decoded, pos)
        entry = decoded[pos:pos + length]
        pos += length

        ep, uid, info_b64 = 0, None, None
        while ep < len(entry):
            try:
                t, ep = ProtobufEncoder.decode_varint(entry, ep)
            except Exception:
                break
            fn, wt = t >> 3, t & 7
            if wt == 2:
                l, ep = ProtobufEncoder.decode_varint(entry, ep)
                content = entry[ep:ep + l]
                ep += l
                if fn == 1:
                    uid = content.decode('utf-8', errors='replace')
                elif fn == 2:
                    sp = 0
                    try:
                        _, sp = ProtobufEncoder.decode_varint(content, sp)
                        sl, sp = ProtobufEncoder.decode_varint(content, sp)
                        info_b64 = content[sp:sp + sl].decode('utf-8', errors='replace')
                    except Exception:
                        pass
            elif wt == 0:
                _, ep = ProtobufEncoder.decode_varint(entry, ep)
            elif wt == 1:
                ep += 8
            elif wt == 5:
                ep += 4
            else:
                break

        if uid and info_b64:
            try:
                raw_inner = base64.b64decode(info_b64)
                inner_blobs[uid] = raw_inner

                ip = 0
                _, ip = ProtobufEncoder.decode_varint(raw_inner, ip)
                il, ip = ProtobufEncoder.decode_varint(raw_inner, ip)
                title = raw_inner[ip:ip + il].decode('utf-8', errors='replace')
                if not title.startswith("Conversation (") and not title.startswith("Conversation "):
                    titles[uid] = title
            except Exception:
                pass

    return titles, inner_blobs


def resolve_title(cid: str, existing_titles: dict[str, str], brain_dir: str, convs_dir: str) -> tuple[str, str]:
    """Determine the best title. Returns (title, source)."""
    brain_title = ArtifactParser.extract_title(cid, brain_dir)
    if brain_title:
        return brain_title, "brain"

    if cid in existing_titles:
        return existing_titles[cid], "preserved"

    pb_path = os.path.join(convs_dir, f"{cid}.pb")
    if os.path.exists(pb_path):
        mod_time = time.strftime("%b %d", time.localtime(os.path.getmtime(pb_path)))
        return f"Conversation ({mod_time}) {cid[:8]}", "fallback"

    return f"Conversation {cid[:8]}", "fallback"


# ==============================================================================
# MAIN EXECUTION ROUTINE
# ==============================================================================
def main() -> None:
    """Five-phase recovery pipeline: preflight → discover → mapping → backup → inject."""

    if "--help" in sys.argv or "-h" in sys.argv:
        print(f"""
================================================================================
                           AGMERCIUM RECOVERY SUITE
                     {TOOL_NAME} v{VERSION}
================================================================================

  Author:       Donald R. Johnson
  Organization: Agmercium (https://agmercium.com)
  License:      The Unlicense (Public Domain)
  Python:       3.7+
  Dependencies: None (standard library only)

  A production-ready, enterprise-grade utility to securely rebuild the internal
  SQLite UI indices of the Google Antigravity IDE from local Protobuf (.pb)
  cache files.

  Usage:
    1. Close the Antigravity IDE completely.
    2. Run: python antigravity_recover.py
    3. Follow the interactive prompts.
    4. Restart the Antigravity IDE.

  Options:
    --help, -h       Show this help message
    --version, -v    Show version number

  Environment Variables:
    AGMERCIUM_DEBUG=1    Enable verbose debug logging

  GitHub:  https://github.com/agmercium/antigravity-recovery
  Issues:  https://github.com/agmercium/antigravity-recovery/issues
================================================================================
""")
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
    # Phase 2: Conversation Discovery & Metadata Extraction
    # ------------------------------------------------------------------
    Logger.header("Phase 2: Discovery & Metadata Extraction")
    
    try:
        raw_files = os.listdir(convs_dir)
    except OSError as exc:
        Logger.error(f"Cannot read conversations directory: {exc}", fatal=True)

    all_pbs = sorted([f[:-3] for f in raw_files if f.endswith(".pb")],
                     key=lambda f: os.path.getmtime(os.path.join(convs_dir, f"{f}.pb")), reverse=True)

    if not all_pbs:
        Logger.success("No local .pb files found. Your history is already clean.")
        sys.exit(0)

    Logger.info(f"Discovered {len(all_pbs)} conversation(s) on disk.")
    Logger.info("Extracting existing metadata from database...")

    existing_titles = {}
    existing_inner_blobs = {}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key=?", (PB_KEY,))
        row = cur.fetchone()
        conn.close()
        
        if row and row[0]:
            decoded = base64.b64decode(row[0])
            existing_titles, existing_inner_blobs = extract_existing_metadata(decoded)
    except Exception as e:
        Logger.warn(f"Failed to extract metadata (normal on fresh installs): {e}")

    ws_count = sum(1 for v in existing_inner_blobs.values() if ProtobufEncoder.extract_workspace_hint(v))
    Logger.success(f"Discovered {len(existing_titles)} preserved titles and {ws_count} workspace hints.")

    resolved = []
    stats = {"brain": 0, "preserved": 0, "fallback": 0}
    markers = {"brain": "+", "preserved": "~", "fallback": "?"}

    for i, cid in enumerate(all_pbs, 1):
        title, source = resolve_title(cid, existing_titles, brain_dir, convs_dir)
        inner_data = existing_inner_blobs.get(cid)
        has_ws = bool(inner_data and ProtobufEncoder.extract_workspace_hint(inner_data))
        resolved.append((cid, title, source, inner_data, has_ws))
        stats[source] += 1
        marker = markers[source]
        ws_flag = " [WS]" if has_ws else ""
        print(f"    [{i:3d}] {marker} {title[:50]}{ws_flag}")

    print(f"  Legend: [+] brain  [~] preserved  [?] fallback  [WS] workspace")
    
    # ------------------------------------------------------------------
    # Phase 3: Workspace Mapping
    # ------------------------------------------------------------------
    Logger.header("Phase 3: Workspace Mapping")
    
    unmapped = [(i, cid, title) for i, (cid, title, _, inner_data, has_ws) in enumerate(resolved, 1) if not has_ws]
    ws_assignments = {}

    if unmapped:
        Logger.info(f"{len(unmapped)} conversation(s) have no workspace assigned.")
        print("  Press Enter or 1: Auto-assign workspaces (recommended)")
        print("  Press 2:          Auto-assign + manually assign the rest")
        print()
        choice = input("  Your choice: ").strip()

        Logger.info("Auto-assigning workspaces from brain artifacts...")
        auto_count = 0
        from .cli import build_workspace_dict
        
        for idx, cid, title in unmapped:
            inferred = ArtifactParser.infer_workspace_from_brain(cid, brain_dir)
            if inferred and os.path.isdir(inferred):
                ws_assignments[cid] = build_workspace_dict(inferred)
                auto_count += 1
                print(f"    [{idx:3d}] -> {os.path.basename(inferred)}")
        
        Logger.success(f"Auto-assigned {auto_count} workspace(s).")

        if choice == '2':
            still_unmapped = [(idx, cid, title) for idx, cid, title in unmapped if cid not in ws_assignments]
            if still_unmapped:
                user_assignments = interactive_workspace_assignment(still_unmapped)
                ws_assignments.update(user_assignments)
            else:
                Logger.info("All conversations were auto-assigned — nothing left to assign manually.")

    # ------------------------------------------------------------------
    # Phase 4: Secure Backup
    # ------------------------------------------------------------------
    Logger.header("Phase 4: Secure Database Backup")

    backup_db = f"{db_path}.{BACKUP_PREFIX}_{int(time.time())}"
    try:
        shutil.copy2(db_path, backup_db)
        Logger.success(f"Backup created: {backup_db}")
    except Exception as exc:
        Logger.error(f"Backup failed: {exc}", fatal=True)

    # ------------------------------------------------------------------
    # Phase 5: Database Injection
    # ------------------------------------------------------------------
    Logger.header("Phase 5: Database Injection")

    result_bytes = b""
    ws_total = 0
    ts_injected = 0
    stats_json = {"json_added": 0, "json_patched": 0}

    # Prepare for JSON index injection
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key=?", (JSON_KEY,))
    idx_row = cur.fetchone()
    try:
        chat_idx = json.loads(idx_row[0]) if idx_row else {"version": 1, "entries": {}}
    except (json.JSONDecodeError, TypeError):
        Logger.warn("JSON index was corrupt or missing. Initializing empty index.")
        chat_idx = {"version": 1, "entries": {}}

    try:
        for cid, title, source, inner_data, has_ws in resolved:
            ws_map = ws_assignments.get(cid)
            pb_path = os.path.join(convs_dir, f"{cid}.pb")
            
            pb_mtime = int(os.path.getmtime(pb_path)) if os.path.exists(pb_path) else int(time.time())
            pb_ctime = int(os.path.getctime(pb_path)) if os.path.exists(pb_path) else int(time.time())
            
            entry = ProtobufEncoder.build_trajectory_entry(
                cid, title, ws_map, pb_ctime, pb_mtime, existing_inner_data=inner_data
            )
            result_bytes += ProtobufEncoder.write_bytes_field(1, entry)

            if has_ws or ws_map:
                ws_total += 1
            if pb_mtime and (not inner_data or not ProtobufEncoder.has_timestamp_fields(inner_data)):
                ts_injected += 1
                
            # JSON 
            mtime_ms = pb_mtime * 1000
            if cid not in chat_idx.setdefault("entries", {}):
                chat_idx["entries"][cid] = {
                    "sessionId": cid,
                    "title": title,
                    "lastModified": mtime_ms,
                    "isStale": False,
                }
                stats_json["json_added"] += 1
            else:
                chat_idx["entries"][cid]["title"] = title
                chat_idx["entries"][cid]["lastModified"] = mtime_ms
                stats_json["json_patched"] += 1

        encoded_pb = base64.b64encode(result_bytes).decode('utf-8')

        cur.execute("SELECT value FROM ItemTable WHERE key=?", (PB_KEY,))
        if cur.fetchone():
            cur.execute("UPDATE ItemTable SET value=? WHERE key=?", (encoded_pb, PB_KEY))
        else:
            cur.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)", (PB_KEY, encoded_pb))
            
        cur.execute(
            "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
            (JSON_KEY, json.dumps(chat_idx, ensure_ascii=False)),
        )

        conn.commit()
        Logger.success("All changes committed successfully.")
        
    except sqlite3.Error as exc:
        Logger.error(f"SQLite error: {exc}")
        safe_rollback(backup_db, db_path)
        Logger.error("Recovery aborted after database rollback.", fatal=True)
    except Exception as exc:
        Logger.error(f"Unexpected error: {exc}")
        safe_rollback(backup_db, db_path)
        Logger.error("Recovery aborted after database rollback.", fatal=True)
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # Phase 6: Summary
    # ------------------------------------------------------------------
    Logger.header("Recovery Complete")
    print()
    Logger.success(f"Conversations rebuilt:      {len(resolved)}")
    Logger.success(f"Workspaces mapped:          {ws_total}")
    Logger.success(f"Timestamps injected:        {ts_injected}")
    Logger.success(f"JSON entries added:         {stats_json['json_added']}")
    Logger.success(f"JSON entries patched:       {stats_json['json_patched']}")
    print()
    Logger.info(f"Backup preserved at: {backup_db}")
    Logger.info("You may now launch the Antigravity IDE. Your history should be fully restored.")
    print()

