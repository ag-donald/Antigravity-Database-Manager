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
import re
import sqlite3
import time
import urllib.parse

from .constants import PB_KEY, JSON_KEY, BACKUP_PREFIX, DB_FILENAME, PLACEHOLDER_TITLE_PREFIX
from .environment import EnvironmentResolver
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
                try:
                    title = raw_inner[ip:ip + il].decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    title = f"{PLACEHOLDER_TITLE_PREFIX} {uid[:8]}"
                if not title.startswith(f"{PLACEHOLDER_TITLE_PREFIX} ") and \
                        not title.startswith(f"{PLACEHOLDER_TITLE_PREFIX} ("):
                    titles[uid] = title
            except Exception:
                pass

    return titles, inner_blobs


# Anchored: these values hold a single URI, so embedded occurrences are never
# rewritten. Matches raw ':' and both hex cases of the percent-encoded colon.
_DRIVE_URI_RE = re.compile(r"^file:///([A-Za-z])(:|%3[Aa])(?=/|$)")


def canonicalize_drive_uri(uri: str) -> str:
    """
    Normalizes a ``file:///`` URI's Windows drive-letter separator to the
    canonical frontend form: lowercase letter + uppercase-hex ``%3A``
    (``file:///C:/x`` / ``file:///c%3a/x`` -> ``file:///c%3A/x``), so one
    workspace never appears under several spellings. URIs without a drive
    letter (macOS/Linux paths) are returned unchanged.
    """
    return _DRIVE_URI_RE.sub(lambda m: f"file:///{m.group(1).lower()}%3A", uri)


def file_uri_to_path(uri: str) -> str:
    """Decodes a ``file:///`` URI into an OS path (drive-letter or POSIX)."""
    if not uri.startswith("file:///"):
        return uri
    decoded = urllib.parse.unquote(uri[len("file:///"):])
    if len(decoded) >= 2 and decoded[1] == ":":
        return decoded       # Windows drive path (c:/...)
    return "/" + decoded     # POSIX absolute path


def extract_workspace_uri(raw_inner: bytes) -> str:
    """Safely extracts a file:/// workspace URI from a raw Protobuf inner blob.
    It parses the true Field 17 -> Field 7 hierarchical structure to avoid
    false positives from AI messages containing 'file:///' references.
    """
    if b"file:///" not in raw_inner:
        return ""
    try:
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
            return canonicalize_drive_uri(latest_uri)
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
            return canonicalize_drive_uri(ws_bytes.decode('utf-8', errors='ignore'))
    except Exception:
        pass
    return ""


def normalize_path(p: str) -> str:
    """Canonicalizes a filesystem path for identity comparison."""
    return os.path.abspath(os.path.realpath(os.path.expanduser(p))) if p else ""


def db_install_label(path: str) -> str:
    """Human label for the IDE installation a database path belongs to."""
    if "Antigravity IDE" in path:
        return "Antigravity IDE"
    return "Antigravity (deprecated)"


def summarize_workspace_health(diagnostics: list[WorkspaceDiagnostic]) -> tuple[int, int, int]:
    """Classifies workspaces as (healthy, warn, missing): accessible on disk /
    present but inaccessible / absent from the filesystem."""
    healthy = sum(1 for d in diagnostics if d.exists_on_disk and d.is_accessible)
    missing = sum(1 for d in diagnostics if not d.exists_on_disk)
    return healthy, len(diagnostics) - healthy - missing, missing


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

            j_entry = json_entries.get(uid)
            json_synced = j_entry is not None

            # Newer IDE versions keep dynamically updated titles in the JSON
            # index rather than the Protobuf blob; prefer the JSON title.
            if isinstance(j_entry, dict) and j_entry.get("title"):
                title = j_entry["title"]

            has_timestamps = ProtobufEncoder.has_timestamp_fields(raw_inner)
            workspace_uri = extract_workspace_uri(raw_inner)

            if isinstance(j_entry, dict):
                is_stale = j_entry.get("isStale", False)
            else:
                is_stale = False
            
            results.append(ConversationEntry(
                uuid=uid, title=title, workspace_uri=workspace_uri,
                has_timestamps=has_timestamps,
                json_synced=json_synced, is_stale=is_stale
            ))

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
    convs = list_conversations(db_path)
    ws_map: dict[str, list[str]] = {}
    for c in convs:
        if c.workspace_uri:
            ws_map.setdefault(c.workspace_uri, []).append(c.uuid)

    results: list[WorkspaceDiagnostic] = []
    for uri, uuids in ws_map.items():
        decoded = file_uri_to_path(uri)

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
    Scans the current DB, any other detected primary DBs, and all of their backups.
    """
    norm_current = normalize_path(current_db_path)

    # 1. Get all candidate primary DB paths, ensuring current_db_path is first and unique
    primary_paths = [current_db_path]
    seen_norms = {norm_current}

    candidates = EnvironmentResolver.get_antigravity_db_paths()
    for c in candidates:
        if os.path.isfile(c):
            norm_c = normalize_path(c)
            if norm_c not in seen_norms:
                primary_paths.append(c)
                seen_norms.add(norm_c)

    snapshots: list[DatabaseSnapshot] = []
    scanned_paths = set(seen_norms)

    # 2. Scan primary DBs
    for p in primary_paths:
        norm_p = normalize_path(p)
        is_current = (norm_p == norm_current)

        sn = scan_database(p, db_install_label(p), is_current=is_current)
        snapshots.append(sn)

    # 3. Discover backups for each of the primary directories
    discovered_backups = []
    for p in primary_paths:
        db_dir = os.path.dirname(p)
        if os.path.isdir(db_dir):
            for b in discover_backups(db_dir):
                norm_b = normalize_path(b)
                if norm_b not in scanned_paths:
                    scanned_paths.add(norm_b)
                    prefix = "IDE Backup" if "Antigravity IDE" in p else "Depr Backup"
                    discovered_backups.append((b, prefix))

    # Sort backups newest first by modification time
    discovered_backups.sort(key=lambda item: os.path.getmtime(item[0]), reverse=True)

    for b, prefix in discovered_backups:
        try:
            basename = os.path.basename(b)
            ts_str = basename.rsplit(f"{BACKUP_PREFIX}_", 1)[-1]
            if "_" in ts_str:
                epoch_str, reason = ts_str.split("_", 1)
                epoch = int(epoch_str)
                time_str = time.strftime('%b %d %H:%M', time.localtime(epoch))
                label = f"{prefix}: {time_str} ({reason})"
            else:
                epoch = int(ts_str)
                label = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(epoch))
        except Exception:
            label = f"{prefix}: Unknown"

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
