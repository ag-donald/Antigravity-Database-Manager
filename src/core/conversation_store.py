"""
Read-only access to the new-generation Antigravity conversation store.

Newer IDE builds no longer maintain a central ``state.vscdb`` index. Each
conversation is a self-contained SQLite database under
``~/.gemini/antigravity[-ide]/conversations/<uuid>.db`` whose
``trajectory_metadata_blob`` row carries the metadata the old index held.
This module parses those files lossily and never writes to them.

Reverse-engineered ``trajectory_metadata_blob`` field map:
  1  workspace container {1: uri, 2: uri, 3: git {1: owner/repo, 2: remote}, 4: branch}
  2  timestamp           {1: epoch seconds, 2: nanos}
  3  event uuid          (skipped)
  6  cascade id
  7  percent-encoded workspace uri
  15 step summaries      (skipped)
  18 project id
"""

from __future__ import annotations

import os
import sqlite3

from .environment import EnvironmentResolver
from .models import ConversationRecord
from .protobuf import ProtobufEncoder

_LIVE_DIR = "conversations"
_BACKUP_DIR = "conversations_backup"


def _decode_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _parse_workspace_container(raw: bytes, fields: dict) -> None:
    pos = 0
    while pos < len(raw):
        tag, pos = ProtobufEncoder.decode_varint(raw, pos)
        field_num, wire_type = tag >> 3, tag & 7
        if wire_type != 2:
            new_pos = ProtobufEncoder.skip_protobuf_field(raw, pos, wire_type)
            if new_pos <= pos:
                break
            pos = new_pos
            continue
        length, pos = ProtobufEncoder.decode_varint(raw, pos)
        content = raw[pos:pos + length]
        pos += length
        if field_num in (1, 2):
            fields["workspace_uris"].append(_decode_text(content))
        elif field_num == 3:
            _parse_git_info(content, fields)
        elif field_num == 4:
            fields["git_branch"] = _decode_text(content)


def _parse_git_info(raw: bytes, fields: dict) -> None:
    pos = 0
    while pos < len(raw):
        tag, pos = ProtobufEncoder.decode_varint(raw, pos)
        field_num, wire_type = tag >> 3, tag & 7
        if wire_type != 2:
            new_pos = ProtobufEncoder.skip_protobuf_field(raw, pos, wire_type)
            if new_pos <= pos:
                break
            pos = new_pos
            continue
        length, pos = ProtobufEncoder.decode_varint(raw, pos)
        content = raw[pos:pos + length]
        pos += length
        text = _decode_text(content)
        if field_num == 1:
            fields["git_owner_repo"] = text
        elif field_num == 2:
            fields["git_remote"] = text


def _parse_timestamp(raw: bytes, fields: dict) -> None:
    pos = 0
    while pos < len(raw):
        tag, pos = ProtobufEncoder.decode_varint(raw, pos)
        field_num, wire_type = tag >> 3, tag & 7
        if wire_type != 0:
            new_pos = ProtobufEncoder.skip_protobuf_field(raw, pos, wire_type)
            if new_pos <= pos:
                break
            pos = new_pos
            continue
        value, pos = ProtobufEncoder.decode_varint(raw, pos)
        if field_num == 1:
            fields["timestamp_seconds"] = value
        elif field_num == 2:
            fields["timestamp_nanos"] = value


def _parse_metadata_blob(blob: bytes, fields: dict) -> None:
    pos = 0
    while pos < len(blob):
        tag, pos = ProtobufEncoder.decode_varint(blob, pos)
        field_num, wire_type = tag >> 3, tag & 7
        if wire_type != 2:
            new_pos = ProtobufEncoder.skip_protobuf_field(blob, pos, wire_type)
            if new_pos <= pos:
                break
            pos = new_pos
            continue
        length, pos = ProtobufEncoder.decode_varint(blob, pos)
        content = blob[pos:pos + length]
        pos += length
        if field_num == 1:
            _parse_workspace_container(content, fields)
        elif field_num == 2:
            _parse_timestamp(content, fields)
        elif field_num == 6:
            fields["cascade_id"] = _decode_text(content)
        elif field_num == 7:
            fields["workspace_uri_encoded"] = _decode_text(content)
        elif field_num == 18:
            fields["project_id"] = _decode_text(content)


def _open_read_only(path: str) -> sqlite3.Connection:
    """
    Opens a conversation DB read-only.

    ``immutable=1`` is the fallback for backup copies whose WAL sidecars
    would need recovery — it never writes but may read a stale snapshot.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.DatabaseError:
        conn.close()
        conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True, timeout=5)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn


def read_conversation_db(path: str, is_backup: bool = False) -> ConversationRecord:
    """
    Reads one new-generation conversation DB. Never raises — failures,
    missing tables and unparsable blobs degrade into defaults and ``error``.
    """
    fields: dict = {"workspace_uris": []}
    conn = None
    try:
        conn = _open_read_only(path)
        meta = conn.execute(
            "SELECT trajectory_id, cascade_id, trajectory_type, source FROM trajectory_meta"
        ).fetchone()
        if meta:
            fields.update(
                trajectory_id=meta[0] or "",
                cascade_id=meta[1] or "",
                trajectory_type=meta[2] or 0,
                source=meta[3] or 0,
            )
        steps = conn.execute("SELECT COUNT(*) FROM steps").fetchone()
        fields["step_count"] = steps[0] if steps else 0
        try:
            blob = conn.execute(
                "SELECT data FROM trajectory_metadata_blob WHERE id='main'"
            ).fetchone()
        except sqlite3.OperationalError:
            blob = None  # table absent — the blob is optional metadata
        if blob and blob[0]:
            _parse_metadata_blob(blob[0], fields)
    except (sqlite3.DatabaseError, OSError) as exc:
        fields["error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()

    fields["workspace_uris"] = tuple(fields["workspace_uris"])
    return ConversationRecord(path=path, is_backup=is_backup, **fields)


def list_conversation_dbs(gem_base: str) -> list[str]:
    """Lists conversation DBs — live directory first, then backups, sorted by name."""
    paths: list[str] = []
    for sub in (_LIVE_DIR, _BACKUP_DIR):
        directory = os.path.join(gem_base, sub)
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(n for n in os.listdir(directory) if n.endswith(".db"))
        except OSError:
            continue
        paths.extend(os.path.join(directory, n) for n in names)
    return paths


def collect_conversations(gem_base: str) -> list[ConversationRecord]:
    """Reads every conversation DB found under a gem base, marking backups."""
    backup_dir = os.path.join(gem_base, _BACKUP_DIR)
    return [
        read_conversation_db(p, is_backup=os.path.dirname(p) == backup_dir)
        for p in list_conversation_dbs(gem_base)
    ]


def detect_generation() -> str:
    """
    Returns the IDE data generation: ``"legacy"`` (central state.vscdb),
    ``"new"`` (self-contained conversation DBs), or ``"none"``.
    """
    if any(os.path.isfile(p) for p in EnvironmentResolver.get_antigravity_db_paths()):
        return "legacy"
    for base in EnvironmentResolver.get_gemini_base_paths():
        if list_conversation_dbs(base):
            return "new"
    return "none"


def legacy_missing_notice() -> str | None:
    """
    Guidance text when no legacy state.vscdb exists but new-generation
    conversation databases do; ``None`` when the legacy model applies.
    """
    if any(os.path.isfile(p) for p in EnvironmentResolver.get_antigravity_db_paths()):
        return None
    for base in EnvironmentResolver.get_gemini_base_paths():
        conv_dbs = list_conversation_dbs(base)
        if conv_dbs:
            return (
                "No state.vscdb found — this IDE generation stores each "
                f"conversation as its own database under {os.path.dirname(conv_dbs[0])} "
                f"({len(conv_dbs)} found). Run "
                "'antigravity_database_manager.py inspect' for a read-only "
                "overview; the legacy scan and recovery views do not apply."
            )
    return None
