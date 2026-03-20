"""
Database introspection and backup scanning module.
Provides read-only analysis of ``.vscdb`` states and parses their contents.

This module is UI-agnostic — no print(), input(), or ANSI codes.
It uses ``DatabaseSnapshot`` from ``models.py`` as its primary return type.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import sqlite3
import time

from .constants import PB_KEY, JSON_KEY, BACKUP_PREFIX, DB_FILENAME
from .models import DatabaseSnapshot, ConversationEntry, HealthReport, WorkspaceDiagnostic
from .protobuf import ProtobufEncoder


def extract_existing_metadata(decoded: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    """
    Parses the raw SQLite ``trajectorySummaries`` database payload to extract
    human-readable titles and their raw inner Protobuf binary states.

    Returns:
        tuple[dict[str, str], dict[str, bytes]]:
            - titles: mapping ``conversation_uuid`` -> ``title``.
            - inner_blobs: mapping ``conversation_uuid`` -> ``raw_inner_bytes``.
    """
    titles: dict[str, str] = {}
    inner_blobs: dict[str, bytes] = {}
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
        outer_entry = decoded[pos:pos + length]
        pos += length

        ep = 0
        try:
            t, ep = ProtobufEncoder.decode_varint(outer_entry, ep)
            if (t >> 3) == 1 and (t & 7) == 2:
                l, ep = ProtobufEncoder.decode_varint(outer_entry, ep)
                if ep + l == len(outer_entry):
                    entry = outer_entry[ep:ep + l]
                else:
                    entry = outer_entry
            else:
                entry = outer_entry
        except Exception:
            entry = outer_entry

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
                    try:
                        uid = content.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        break
                elif fn == 2:
                    sp = 0
                    try:
                        _, sp = ProtobufEncoder.decode_varint(content, sp)
                        sl, sp = ProtobufEncoder.decode_varint(content, sp)
                        info_b64 = content[sp:sp + sl].decode('utf-8', errors='strict')
                    except (UnicodeDecodeError, Exception):
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
                try:
                    title = raw_inner[ip:ip + il].decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    title = f"Conversation {uid[:8]}"
                if not title.startswith("Conversation (") and not title.startswith("Conversation "):
                    titles[uid] = title
            except Exception:
                pass

    return titles, inner_blobs


def _normalize_workspace_uri(uri: str) -> str:
    """Normalizes a file:/// workspace URI so that Windows drive letters are
    always lowercased, preventing `file:///h%3A/...` and `file:///H%3A/..`
    from being treated as separate workspaces.

    Handles both encoded (``%3A``) and plain (``:``) forms:
      - ``file:///H%3A/path`` → ``file:///h%3A/path``
      - ``file:///H:/path``  → ``file:///h:/path``
    """
    import re
    # Match file:/// followed by a single letter + colon (plain or percent-encoded)
    return re.sub(
        r'^(file:///)(\w)(%3A|:)',
        lambda m: m.group(1) + m.group(2).lower() + m.group(3),
        uri,
        flags=re.IGNORECASE,
    )


def extract_workspace_uri(raw_inner: bytes) -> str:
    """Safely extracts a file:/// workspace URI from a raw Protobuf inner blob.
    It parses the true Field 17 -> Field 7 hierarchical structure to avoid
    false positives from AI messages containing 'file:///' references.
    """
    if b"file:///" not in raw_inner:
        return ""
    try:
        from .protobuf import ProtobufEncoder
        pos = 0
        latest_uri = ""
        while pos < len(raw_inner):
            tag, pos = ProtobufEncoder.decode_varint(raw_inner, pos)
            field_num = tag >> 3
            wire_type = tag & 7
            
            if wire_type == 2:
                length, pos = ProtobufEncoder.decode_varint(raw_inner, pos)
                content = raw_inner[pos:pos+length]
                pos += length
                
                if field_num == 17 or field_num == 9:
                    sub_pos = 0
                    while sub_pos < len(content):
                        try:
                            sub_tag, sub_pos = ProtobufEncoder.decode_varint(content, sub_pos)
                            sub_fn = sub_tag >> 3
                            sub_wt = sub_tag & 7
                            if sub_wt == 2:
                                sub_len, sub_pos = ProtobufEncoder.decode_varint(content, sub_pos)
                                sub_content = content[sub_pos:sub_pos+sub_len]
                                sub_pos += sub_len
                                if field_num == 17 and sub_fn == 7:
                                    latest_uri = sub_content.decode('utf-8', errors='ignore')
                                elif field_num == 9 and sub_fn == 1:
                                    if not latest_uri:
                                        latest_uri = sub_content.decode('utf-8', errors='ignore')
                            else:
                                sub_pos = ProtobufEncoder.skip_protobuf_field(content, sub_pos, sub_wt)
                        except Exception:
                            break
            else:
                pos = ProtobufEncoder.skip_protobuf_field(raw_inner, pos, wire_type)
        if latest_uri:
            return _normalize_workspace_uri(latest_uri)
    except Exception:
        pass
    
    # Fallback to absolute last file:/// substring if it completely fails to decode
    try:
        start = raw_inner.rfind(b"file:///")
        if start != -1:
            ws_bytes = raw_inner[start:]
            for char_idx in range(len(ws_bytes)):
                if ws_bytes[char_idx] < 32 or ws_bytes[char_idx] > 126:
                    ws_bytes = ws_bytes[:char_idx]
                    break
            return _normalize_workspace_uri(ws_bytes.decode('utf-8', errors='ignore'))
    except Exception:
        pass
    return ""


def extract_workspace_count(inner_blobs: dict[str, bytes]) -> int:
    """Counts the number of *unique* workspaces found across all trajectories."""
    unique_ws = set()
    for uid, raw_inner in inner_blobs.items():
        uri = extract_workspace_uri(raw_inner)
        if uri:
            unique_ws.add(uri)
    return len(unique_ws)


def scan_database(db_path: str, label: str, is_current: bool = False) -> DatabaseSnapshot:
    """
    Connects to the given SQLite database in read-only mode, extracts the
    Protobuf and JSON indices, and summarizes their current metrics.
    """
    if not os.path.isfile(db_path):
        return DatabaseSnapshot(db_path, label, 0, 0, 0, 0, 0, 0, is_current, error="File not found")

    try:
        size_bytes = os.path.getsize(db_path)
        modified_at = os.path.getmtime(db_path)
    except Exception as e:
        return DatabaseSnapshot(db_path, label, 0, 0, 0, 0, 0, 0, is_current, error=f"Stat error: {e}")

    conn = None
    try:
        db_uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,))
        row = cursor.fetchone()
        conversation_count = 0
        titled_count = 0
        workspace_count = 0
        if row:
            pb_payload = row["value"]
            if pb_payload:
                decoded = base64.b64decode(pb_payload)
                titles, inner_blobs = extract_existing_metadata(decoded)
                conversation_count = len(inner_blobs)
                titled_count = len(titles)
                workspace_count = extract_workspace_count(inner_blobs)

        cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (JSON_KEY,))
        row_json = cursor.fetchone()
        json_entry_count = 0
        if row_json:
            j_payload = row_json["value"]
            try:
                j_obj = json.loads(j_payload)
                if "entries" in j_obj and isinstance(j_obj["entries"], dict):
                    json_entry_count = len(j_obj["entries"])
            except Exception:
                pass

        return DatabaseSnapshot(
            path=db_path,
            label=label,
            size_bytes=size_bytes,
            modified_at=modified_at,
            conversation_count=conversation_count,
            titled_count=titled_count,
            workspace_count=workspace_count,
            json_entry_count=json_entry_count,
            is_current=is_current
        )
    except Exception as e:
        return DatabaseSnapshot(db_path, label, size_bytes, modified_at, 0, 0, 0, 0, is_current, error=f"DB error: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def health_check(snapshot: DatabaseSnapshot) -> HealthReport:
    """Computes health indicators from a snapshot's metrics."""
    pb_json_synced = (snapshot.conversation_count == snapshot.json_entry_count)
    if snapshot.conversation_count > 0:
        pct = (snapshot.titled_count / snapshot.conversation_count) * 100
    else:
        pct = 100.0
    
    orphan_json = (snapshot.json_entry_count > snapshot.conversation_count)
    orphan_pb = (snapshot.conversation_count > snapshot.json_entry_count)
    
    if pb_json_synced and pct > 90.0 and not orphan_json and not orphan_pb:
        summary = "✓ Healthy"
    elif orphan_pb or orphan_json:
        summary = "⚠ Drifted"
    else:
        summary = "✗ Check Titles"
        
    return HealthReport(
        pb_json_synced=pb_json_synced,
        pb_count=snapshot.conversation_count,
        json_count=snapshot.json_entry_count,
        titled_pct=pct,
        has_orphan_json=orphan_json,
        has_orphan_pb=orphan_pb,
        summary=summary
    )


def list_conversations(db_path: str) -> list[ConversationEntry]:
    """Extracts all conversations from the PB and JSON indices."""
    if not os.path.isfile(db_path):
        return []

    conn = None
    try:
        db_uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,))
        row = cursor.fetchone()
        titles, inner_blobs = {}, {}
        if row and row["value"]:
            decoded = base64.b64decode(row["value"])
            titles, inner_blobs = extract_existing_metadata(decoded)

        cursor.execute("SELECT value FROM ItemTable WHERE key = ?", (JSON_KEY,))
        row_json = cursor.fetchone()
        json_entries = {}
        if row_json and row_json["value"]:
            try:
                j_obj = json.loads(row_json["value"])
                json_entries = j_obj.get("entries", {})
            except Exception:
                pass

        results = []
        for uid, raw_inner in inner_blobs.items():
            title = titles.get(uid, "(Untitled)")
            workspace_uri = ""
            has_timestamps = ProtobufEncoder.has_timestamp_fields(raw_inner)
            
            workspace_uri = extract_workspace_uri(raw_inner)

            j_entry = json_entries.get(uid)
            json_synced = j_entry is not None
            if isinstance(j_entry, dict):
                is_stale = j_entry.get("isStale", False)
            else:
                is_stale = False
            
            results.append(ConversationEntry(
                uuid=uid, title=title, workspace_uri=workspace_uri,
                has_timestamps=has_timestamps, modified_epoch=0,
                json_synced=json_synced, is_stale=is_stale
            ))

        # Sort newest first (since we don't have true epoch, we rely on the order in JSON/PB or leave it)
        return results
    except Exception:
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def discover_backups(db_dir: str) -> list[str]:
    """Finds all recovery backups within the globalStorage directory, sorted newest first."""
    pattern = os.path.join(db_dir, f"{DB_FILENAME}.{BACKUP_PREFIX}_*")
    matches = glob.glob(pattern)
    matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return matches


def analyze_workspaces(db_path: str) -> list[WorkspaceDiagnostic]:
    """
    Extracts all unique workspace URIs from a database and validates
    their physical existence on the filesystem.
    """
    import urllib.parse

    convs = list_conversations(db_path)
    ws_map: dict[str, list[str]] = {}
    for c in convs:
        if c.workspace_uri:
            ws_map.setdefault(c.workspace_uri, []).append(c.uuid)

    results: list[WorkspaceDiagnostic] = []
    for uri, uuids in ws_map.items():
        # Decode file:/// URI to local path
        decoded = uri
        if uri.startswith("file:///"):
            raw_path = uri[len("file:///"):]
            decoded = urllib.parse.unquote(raw_path)
            # On Windows, preserve the drive letter (e.g. C:/...)
            if len(decoded) >= 2 and decoded[1] == ':':
                pass  # Already good
            else:
                decoded = "/" + decoded  # POSIX absolute path

        exists = os.path.isdir(decoded)
        accessible = os.access(decoded, os.R_OK) if exists else False

        results.append(WorkspaceDiagnostic(
            uri=uri,
            decoded_path=decoded,
            exists_on_disk=exists,
            is_accessible=accessible,
            bound_conversations=uuids,
        ))

    return results


def scan_all(current_db_path: str) -> list[DatabaseSnapshot]:
    """
    Scans the current DB and all available backups.
    Returns the current DB at index 0, followed by backups newest-first.
    """
    snapshots: list[DatabaseSnapshot] = []

    sn_current = scan_database(current_db_path, "CURRENT", is_current=True)
    snapshots.append(sn_current)

    db_dir = os.path.dirname(current_db_path)
    backups = discover_backups(db_dir)

    for b in backups:
        try:
            basename = os.path.basename(b)
            ts_str = basename.rsplit(f"{BACKUP_PREFIX}_", 1)[-1]
            if "_" in ts_str:
                epoch_str, reason = ts_str.split("_", 1)
                epoch = int(epoch_str)
                time_str = time.strftime('%b %d %H:%M', time.localtime(epoch))
                label = f"{time_str} ({reason})"
            else:
                epoch = int(ts_str)
                label = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(epoch))
        except Exception:
            label = "Unknown Backup"

        sn = scan_database(b, label, is_current=False)
        snapshots.append(sn)

    return snapshots


def format_snapshot_table(snapshots: list[DatabaseSnapshot]) -> list[str]:
    """Generates the formatted terminal analysis table (ASCII-safe)."""
    def format_size(b: int) -> str:
        mb = b / (1024 * 1024)
        return f"{mb:.1f} MB"

    lines: list[str] = []
    lines.append("  +-----+----------------------+----------+-------+--------+------+------------+")
    lines.append("  |  #  | Label                | Size     | Convs | Titled |  WS  | JSON Index |")
    lines.append("  +-----+----------------------+----------+-------+--------+------+------------+")

    for idx, snap in enumerate(snapshots):
        if snap.is_current:
            lbl = f"* {snap.label}"
        else:
            lbl = snap.label

        if snap.error:
            lines.append(f"  | {idx:^3} | {lbl:<20} | {format_size(snap.size_bytes):>8} | {snap.error:<42} |")
        else:
            lines.append(f"  | {idx:^3} | {lbl:<20} | {format_size(snap.size_bytes):>8} | {snap.conversation_count:>5} | {snap.titled_count:>6} | {snap.workspace_count:>4} | {snap.json_entry_count:>10} |")

    lines.append("  +-----+----------------------+----------+-------+--------+------+------------+")
    return lines
