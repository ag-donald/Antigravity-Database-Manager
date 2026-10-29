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

from .db_scanner import sqlite_uri
from .environment import EnvironmentResolver
from .models import ConversationRecord
from .protobuf import ProtobufEncoder

_LIVE_DIR = "conversations"
_BACKUP_DIR = "conversations_backup"

# Sidebar summaries cache of the new generation, directly under a gemini base.
SUMMARIES_CACHE = "agyhub_summaries_proto.pb"


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


def _open_read_only(path: str, allow_immutable: bool = False) -> sqlite3.Connection:
    """
    Opens a conversation DB read-only.

    ``immutable=1`` is the fallback for backup copies whose WAL sidecars
    would need recovery — it never writes but may read a stale snapshot.
    It is never used for live databases, which the IDE may be writing:
    an immutable read of a changing file can return corrupt results.
    """
    conn = sqlite3.connect(sqlite_uri(path), uri=True, timeout=5)
    try:
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return conn
    except sqlite3.DatabaseError:
        conn.close()
        if not allow_immutable:
            raise
        conn = sqlite3.connect(sqlite_uri(path, "immutable=1"), uri=True, timeout=5)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.DatabaseError:
            conn.close()
            raise
        return conn


def read_conversation_db(path: str, is_backup: bool = False) -> ConversationRecord:
    """
    Reads one new-generation conversation DB. Never raises — failures,
    missing tables and unparsable blobs degrade into defaults and ``error``.
    """
    fields: dict = {"workspace_uris": []}
    conn = None
    try:
        conn = _open_read_only(path, allow_immutable=is_backup)
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
            data = blob[0]
            if isinstance(data, str):  # TEXT affinity: recover the raw bytes
                data = data.encode("utf-8", "surrogateescape")
            _parse_metadata_blob(bytes(data), fields)
    except Exception as exc:  # never raise: a bad file is a health signal
        fields["error"] = str(exc)
    finally:
        if conn is not None:
            conn.close()

    fields["workspace_uris"] = tuple(fields["workspace_uris"])
    return ConversationRecord(path=path, is_backup=is_backup, **fields)


def list_conversation_dbs(gem_base: str, include_backups: bool = True) -> list[str]:
    """Lists conversation DBs — live directory first, then backups, sorted by name."""
    paths: list[str] = []
    for sub in (_LIVE_DIR, _BACKUP_DIR) if include_backups else (_LIVE_DIR,):
        directory = os.path.join(gem_base, sub)
        if not os.path.isdir(directory):
            continue
        try:
            names = sorted(n for n in os.listdir(directory) if n.endswith(".db"))
        except OSError:
            continue
        paths.extend(os.path.join(directory, n) for n in names)
    return paths


def collect_conversations(gem_base: str, include_backups: bool = True) -> list[ConversationRecord]:
    """Reads every conversation DB found under a gem base, marking backups."""
    backup_dir = os.path.join(gem_base, _BACKUP_DIR)
    return [
        read_conversation_db(p, is_backup=os.path.dirname(p) == backup_dir)
        for p in list_conversation_dbs(gem_base, include_backups)
    ]


def _legacy_present(db_path: str = "") -> bool:
    """True when the given (or any default) state.vscdb exists."""
    if db_path and os.path.isfile(db_path):
        return True
    return any(os.path.isfile(p) for p in EnvironmentResolver.get_antigravity_db_paths())


def _new_store_bases() -> list[str]:
    """Gemini bases that hold a new-generation store: conversation DBs next
    to the summaries cache. The cache is the distinguishing marker — the
    VS Code-based IDE also keeps ``.db`` conversations, but never this file."""
    return [
        base for base in EnvironmentResolver.get_gemini_base_paths()
        if os.path.isfile(os.path.join(base, SUMMARIES_CACHE)) and list_conversation_dbs(base)
    ]


def detect_generation(db_path: str = "") -> str:
    """
    Returns the IDE data generation: ``"legacy"`` (central state.vscdb),
    ``"new"`` (self-contained conversation DBs), ``"mixed"`` (both — e.g.
    Antigravity IDE installed alongside Antigravity 2.0, or a leftover
    state.vscdb in the shared profile folder), or ``"none"``.
    """
    legacy = _legacy_present(db_path)
    new_bases = _new_store_bases()
    if legacy:
        return "mixed" if new_bases else "legacy"
    if new_bases or any(list_conversation_dbs(b) for b in EnvironmentResolver.get_gemini_base_paths()):
        return "new"
    return "none"


def legacy_missing_notice(db_path: str = "") -> str | None:
    """
    Guidance text when no state.vscdb exists (neither ``db_path`` nor any
    default candidate) but new-generation conversation databases do;
    ``None`` when the legacy model applies.
    """
    if _legacy_present(db_path):
        return None
    for base in EnvironmentResolver.get_gemini_base_paths():
        conv_dbs = list_conversation_dbs(base)
        if conv_dbs:
            return (
                "No state.vscdb found — this Antigravity generation (Antigravity 2.0 "
                "and newer builds) stores each conversation as its own database under "
                f"{os.path.dirname(conv_dbs[0])} ({len(conv_dbs)} found) and lists them "
                "from its summaries cache. Run 'antigravity_database_manager.py inspect' "
                "for a read-only overview, or 'repair --summaries' to rebuild missing "
                "sidebar entries; the legacy scan and recovery views do not apply."
            )
    return None
