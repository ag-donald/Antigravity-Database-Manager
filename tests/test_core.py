"""
Production Readiness Test Suite — Antigravity Database Manager

Comprehensive tests for all core modules using only the standard library.
Run with:  python -m unittest tests.test_core -v

Coverage:
  - Protobuf round-trip encoding/decoding
  - Database lifecycle (create → write → read)
  - Title resolution (preserved metadata, .pb fallbacks, task.md regression)
  - Workspace inference from local file:/// URIs
  - Recovery pipeline title behavior
  - Merge operations (additive, overwrite, selective)
  - Backup and restore lifecycle
  - Diagnostic scanner
  - Repair pipeline
  - Edge cases and input validation
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Add the project root to path for imports.
# NOTE: This is intentional for a zero-dependency project without pyproject.toml.
# Replace with editable install (`pip install -e .`) if packaging is added.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.protobuf import ProtobufEncoder
from src.core.constants import PB_KEY, JSON_KEY, BACKUP_PREFIX, DB_FILENAME
from src.core import db_operations as ops
from src.core import db_scanner as scanner
from src.core import diagnostic
from src.core import uri_fix


# ==============================================================================
# HELPERS
# ==============================================================================

def _create_test_db(path: str, conversations: dict[str, str] | None = None) -> None:
    """Creates a test database with optional conversations.

    Args:
        path: Path for the new database file.
        conversations: Dict of {uuid: title} pairs to inject.
    """
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value TEXT)")

    if conversations:
        pb_blob = b""
        json_entries = {}
        for uuid, title in conversations.items():
            entry = ProtobufEncoder.build_trajectory_entry(
                uuid, title, None, 1700000000, 1700000000,
            )
            pb_blob += entry
            json_entries[uuid] = {
                "sessionId": uuid,
                "title": title,
                "lastModified": 1700000000000,
                "isStale": False,
            }

        encoded_pb = base64.b64encode(pb_blob).decode("utf-8")
        cur.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", (PB_KEY, encoded_pb))

        json_obj = {"version": 1, "entries": json_entries}
        cur.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                    (JSON_KEY, json.dumps(json_obj, ensure_ascii=False)))

    conn.commit()
    conn.close()


# ==============================================================================
# TEST: PROTOBUF ENCODER
# ==============================================================================

class TestProtobufEncoder(unittest.TestCase):
    """Tests for the deterministic Protobuf encoder/decoder."""

    def test_varint_zero(self):
        """write_varint(0) should produce single zero byte."""
        self.assertEqual(ProtobufEncoder.write_varint(0), b"\x00")

    def test_varint_roundtrip_small(self):
        """Small varint values should round-trip correctly."""
        for v in (1, 127, 128, 255, 300, 16384):
            encoded = ProtobufEncoder.write_varint(v)
            decoded, end_pos = ProtobufEncoder.decode_varint(encoded, 0)
            self.assertEqual(decoded, v, f"Round-trip failed for {v}")
            self.assertEqual(end_pos, len(encoded))

    def test_varint_roundtrip_large(self):
        """Large varint values (timestamps) should round-trip correctly."""
        for v in (1700000000, 2**31, 2**32, 2**63 - 1):
            encoded = ProtobufEncoder.write_varint(v)
            decoded, _ = ProtobufEncoder.decode_varint(encoded, 0)
            self.assertEqual(decoded, v)

    def test_varint_negative_guard(self):
        """Negative integers should raise ValueError."""
        with self.assertRaises(ValueError):
            ProtobufEncoder.write_varint(-1)
        with self.assertRaises(ValueError):
            ProtobufEncoder.write_varint(-100)

    def test_string_field_roundtrip(self):
        """String field should encode field number + wire type 2."""
        data = ProtobufEncoder.write_string_field(1, "Hello World")
        # Field 1, wire type 2 (LEN) => tag = (1 << 3) | 2 = 10 = 0x0a
        self.assertEqual(data[0], 0x0A)

    def test_string_field_unicode(self):
        """Unicode strings should encode correctly via UTF-8."""
        data = ProtobufEncoder.write_string_field(1, "Héllo Wörld 🌍")
        tag, pos = ProtobufEncoder.decode_varint(data, 0)
        length, pos = ProtobufEncoder.decode_varint(data, pos)
        decoded_str = data[pos:pos + length].decode("utf-8")
        self.assertEqual(decoded_str, "Héllo Wörld 🌍")

    def test_empty_string_field(self):
        """Empty strings should encode with length 0."""
        data = ProtobufEncoder.write_string_field(1, "")
        tag, pos = ProtobufEncoder.decode_varint(data, 0)
        length, pos = ProtobufEncoder.decode_varint(data, pos)
        self.assertEqual(length, 0)

    def test_strip_field_from_protobuf(self):
        """strip_field_from_protobuf should remove only the specified field."""
        data = (
            ProtobufEncoder.write_string_field(1, "title")
            + ProtobufEncoder.write_varint_field(2, 42)
            + ProtobufEncoder.write_string_field(3, "workspace")
        )
        stripped = ProtobufEncoder.strip_field_from_protobuf(data, 2)
        # Parse remaining — should have fields 1 and 3 only
        pos = 0
        found_fields = []
        while pos < len(stripped):
            tag, pos = ProtobufEncoder.decode_varint(stripped, pos)
            field_num = tag >> 3
            found_fields.append(field_num)
            pos = ProtobufEncoder.skip_protobuf_field(stripped, pos, tag & 7)
        self.assertEqual(found_fields, [1, 3])

    def test_strip_field_empty_blob(self):
        """Stripping from empty blob should return empty."""
        self.assertEqual(ProtobufEncoder.strip_field_from_protobuf(b"", 1), b"")

    def test_has_timestamp_empty(self):
        """Empty blob should not have timestamps."""
        self.assertFalse(ProtobufEncoder.has_timestamp_fields(b""))

    def test_build_trajectory_entry_complete(self):
        """build_trajectory_entry should produce parseable protobuf."""
        entry = ProtobufEncoder.build_trajectory_entry(
            "test-uuid-1234", "Test Title", None, 1700000000, 1700000000,
        )
        self.assertGreater(len(entry), 0)
        # Should contain the UUID as a string field
        self.assertIn(b"test-uuid-1234", entry)


# ==============================================================================
# TEST: DATABASE LIFECYCLE
# ==============================================================================

class TestDatabaseLifecycle(unittest.TestCase):
    """Tests for database create, read, write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_empty_db(self):
        """create_empty_db should create a valid SQLite database with correct schema."""
        result = ops.create_empty_db(self.db_path)
        self.assertTrue(result)
        self.assertTrue(os.path.isfile(self.db_path))

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]
        conn.close()
        self.assertIn("ItemTable", tables)

    def test_scan_empty_db(self):
        """Scanning an empty database should return zero counts."""
        ops.create_empty_db(self.db_path)
        snap = scanner.scan_database(self.db_path, "test")
        self.assertEqual(snap.conversation_count, 0)
        self.assertEqual(snap.json_entry_count, 0)
        self.assertFalse(snap.error)

    def test_scan_populated_db(self):
        """Scanning a populated database should count conversations correctly."""
        convs = {
            "uuid-aaaa-1111": "First Conversation",
            "uuid-bbbb-2222": "Second Conversation",
            "uuid-cccc-3333": "Third Conversation",
        }
        _create_test_db(self.db_path, convs)
        snap = scanner.scan_database(self.db_path, "test")
        self.assertEqual(snap.conversation_count, 3)
        self.assertEqual(snap.json_entry_count, 3)
        self.assertEqual(snap.titled_count, 3)

    def test_list_conversations(self):
        """list_conversations should return all conversations with titles."""
        convs = {"uuid-test-1": "Alpha", "uuid-test-2": "Beta"}
        _create_test_db(self.db_path, convs)
        results = scanner.list_conversations(self.db_path)
        self.assertEqual(len(results), 2)
        titles = {c.title for c in results}
        self.assertIn("Alpha", titles)
        self.assertIn("Beta", titles)

    def test_scan_missing_file(self):
        """Scanning a non-existent file should return error snapshot."""
        snap = scanner.scan_database("/nonexistent/path.vscdb", "ghost")
        self.assertTrue(snap.error)


# ==============================================================================
# TEST: MERGE OPERATIONS
# ==============================================================================

class TestMergeOperations(unittest.TestCase):
    """Tests for merge, selective merge, and diff computation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.source_db = os.path.join(self.tmpdir, "source.vscdb")
        self.target_db = os.path.join(self.tmpdir, "target.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_compute_merge_diff(self):
        """compute_merge_diff should correctly classify source-only, shared, target-only."""
        _create_test_db(self.source_db, {"shared-uuid": "Shared", "source-only": "Source Only"})
        _create_test_db(self.target_db, {"shared-uuid": "Shared", "target-only": "Target Only"})

        diff = ops.compute_merge_diff(self.source_db, self.target_db)
        self.assertIn("source-only", diff.source_only)
        self.assertIn("target-only", diff.target_only)
        self.assertIn("shared-uuid", diff.shared)

    def test_merge_additive(self):
        """Additive merge should add missing conversations without overwriting."""
        _create_test_db(self.source_db, {"uuid-new": "New Conv", "uuid-shared": "Source Title"})
        _create_test_db(self.target_db, {"uuid-shared": "Target Title"})

        result = ops.execute_merge(self.source_db, self.target_db, "additive")
        self.assertTrue(result.success)
        self.assertEqual(result.added, 1)
        self.assertEqual(result.skipped, 1)

        # Verify target now has both
        snap = scanner.scan_database(self.target_db, "merged")
        self.assertEqual(snap.conversation_count, 2)

    def test_merge_overwrite(self):
        """Overwrite merge should replace shared conversations."""
        _create_test_db(self.source_db, {"uuid-shared": "Updated Title"})
        _create_test_db(self.target_db, {"uuid-shared": "Old Title"})

        result = ops.execute_merge(self.source_db, self.target_db, "overwrite")
        self.assertTrue(result.success)
        self.assertEqual(result.updated, 1)

    def test_selective_merge(self):
        """Selective merge should only merge specified UUIDs."""
        _create_test_db(self.source_db, {"uuid-a": "A", "uuid-b": "B", "uuid-c": "C"})
        _create_test_db(self.target_db, {})

        result = ops.execute_selective_merge(self.source_db, self.target_db, ["uuid-a", "uuid-c"])
        self.assertTrue(result.success)
        self.assertEqual(result.added, 2)

    def test_selective_merge_empty_list(self):
        """Selective merge with empty list should return immediately."""
        _create_test_db(self.source_db, {"uuid-a": "A"})
        _create_test_db(self.target_db, {})

        result = ops.execute_selective_merge(self.source_db, self.target_db, [])
        self.assertTrue(result.success)
        self.assertEqual(result.added, 0)

    def test_merge_creates_backup(self):
        """Merge operations should always create a backup first."""
        _create_test_db(self.source_db, {"uuid-x": "X"})
        _create_test_db(self.target_db, {})

        result = ops.execute_merge(self.source_db, self.target_db)
        self.assertTrue(result.success)
        self.assertTrue(result.backup_path)
        self.assertTrue(os.path.isfile(result.backup_path))


# ==============================================================================
# TEST: BACKUP AND RESTORE
# ==============================================================================

class TestBackupRestore(unittest.TestCase):
    """Tests for backup creation and restoration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_backup(self):
        """create_backup should create an exact copy with timestamped name."""
        _create_test_db(self.db_path, {"uuid-1": "Test"})
        backup = ops.create_backup(self.db_path, reason="test")
        self.assertTrue(os.path.isfile(backup))
        self.assertIn("agmercium_recovery", backup)
        self.assertIn("test", backup)
        # Verify sizes match
        self.assertEqual(os.path.getsize(self.db_path), os.path.getsize(backup))

    def test_restore_backup(self):
        """restore_backup should restore from a backup and create safety snapshot."""
        # Create original with 2 conversations
        _create_test_db(self.db_path, {"uuid-1": "Original 1", "uuid-2": "Original 2"})
        backup = ops.create_backup(self.db_path, reason="test")

        # Modify the live DB
        _create_test_db(self.db_path, {"uuid-3": "Modified"})

        # Restore
        result = ops.restore_backup(backup, self.db_path)
        self.assertTrue(result.success)
        self.assertTrue(result.safety_snapshot_path)
        self.assertTrue(os.path.isfile(result.safety_snapshot_path))

        # Verify restored DB has original conversations
        snap = scanner.scan_database(self.db_path, "restored")
        self.assertEqual(snap.conversation_count, 2)

    def test_restore_missing_backup(self):
        """restore_backup with non-existent file should return failure."""
        ops.create_empty_db(self.db_path)
        result = ops.restore_backup("/nonexistent/backup.vscdb", self.db_path)
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_discover_backups(self):
        """discover_backups should find all backup files sorted newest first."""
        _create_test_db(self.db_path, {"uuid-1": "Test"})
        ops.create_backup(self.db_path, reason="first")
        ops.create_backup(self.db_path, reason="second")
        backups = scanner.discover_backups(self.tmpdir)
        self.assertEqual(len(backups), 2)


# ==============================================================================
# TEST: CONVERSATION OPERATIONS
# ==============================================================================

class TestConversationOperations(unittest.TestCase):
    """Tests for delete and rename operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_conversation(self):
        """delete_conversation should remove from both PB and JSON."""
        _create_test_db(self.db_path, {"uuid-del": "To Delete", "uuid-keep": "To Keep"})
        result = ops.delete_conversation(self.db_path, "uuid-del")
        self.assertTrue(result)

        convs = scanner.list_conversations(self.db_path)
        uuids = {c.uuid for c in convs}
        self.assertNotIn("uuid-del", uuids)
        self.assertIn("uuid-keep", uuids)

    def test_rename_conversation(self):
        """rename_conversation should update title in both PB and JSON."""
        _create_test_db(self.db_path, {"uuid-rename": "Old Title"})
        result = ops.rename_conversation(self.db_path, "uuid-rename", "New Title")
        self.assertTrue(result)

        convs = scanner.list_conversations(self.db_path)
        self.assertEqual(convs[0].title, "New Title")

    def test_rename_empty_title_rejected(self):
        """Renaming to empty title should be rejected."""
        _create_test_db(self.db_path, {"uuid-test": "Original"})
        result = ops.rename_conversation(self.db_path, "uuid-test", "")
        self.assertFalse(result)
        result = ops.rename_conversation(self.db_path, "uuid-test", "   ")
        self.assertFalse(result)

    def test_get_conversation_payload(self):
        """get_conversation_payload should return JSON payload."""
        _create_test_db(self.db_path, {"uuid-payload": "Payload Test"})
        payload = ops.get_conversation_payload(self.db_path, "uuid-payload")
        self.assertIn("uuid-payload", payload)


# ==============================================================================
# TEST: DIAGNOSTIC SCANNER
# ==============================================================================

class TestDiagnosticScanner(unittest.TestCase):
    """Tests for the diagnostic corruption scanner."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_healthy_db_no_findings(self):
        """A cleanly-built database should have no corruption findings."""
        _create_test_db(self.db_path, {
            "uuid-clean-1": "Clean One",
            "uuid-clean-2": "Clean Two",
        })
        report = diagnostic.diagnose_database(self.db_path)
        self.assertTrue(report.is_healthy)
        self.assertEqual(report.corrupt_entries, 0)
        self.assertEqual(report.warning_entries, 0)

    def test_missing_db(self):
        """Diagnosing non-existent file should return error report."""
        report = diagnostic.diagnose_database("/nonexistent/state.vscdb")
        self.assertTrue(report.error)

    def test_empty_db(self):
        """Diagnosing empty DB (no PB key) should handle gracefully."""
        ops.create_empty_db(self.db_path)
        report = diagnostic.diagnose_database(self.db_path)
        self.assertTrue(report.error or report.total_entries == 0)


# ==============================================================================
# TEST: INPUT VALIDATION
# ==============================================================================

class TestInputValidation(unittest.TestCase):
    """Tests that invalid inputs are rejected gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_restore_nonexistent_backup(self):
        """Restoring a non-existent backup should fail cleanly."""
        ops.create_empty_db(self.db_path)
        result = ops.restore_backup("/does/not/exist.vscdb", self.db_path)
        self.assertFalse(result.success)

    def test_migrate_empty_path(self):
        """migrate_workspace with empty path should return False."""
        _create_test_db(self.db_path, {"uuid-1": "Test"})
        result = ops.migrate_workspace(self.db_path, "")
        self.assertFalse(result)
        result = ops.migrate_workspace(self.db_path, "   ")
        self.assertFalse(result)

    def test_rename_empty_title(self):
        """rename_conversation with empty title should return False."""
        _create_test_db(self.db_path, {"uuid-1": "Test"})
        result = ops.rename_conversation(self.db_path, "uuid-1", "")
        self.assertFalse(result)

    def test_negative_varint(self):
        """Negative varint should raise ValueError."""
        with self.assertRaises(ValueError):
            ProtobufEncoder.write_varint(-42)

    def test_operations_on_missing_db(self):
        """Operations on non-existent database should fail gracefully."""
        fake = "/does/not/exist/state.vscdb"
        self.assertFalse(ops.delete_conversation(fake, "uuid"))
        self.assertFalse(ops.rename_conversation(fake, "uuid", "title"))
        self.assertFalse(ops.migrate_workspace(fake, "/some/path"))
        self.assertEqual(scanner.list_conversations(fake), [])


# ==============================================================================
# TEST: EDGE CASES
# ==============================================================================

class TestEdgeCases(unittest.TestCase):
    """Tests for boundary conditions and edge cases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_merge_empty_source(self):
        """Merging from an empty source should be a no-op."""
        source_db = os.path.join(self.tmpdir, "src.vscdb")
        _create_test_db(source_db, {})
        _create_test_db(self.db_path, {"uuid-1": "Existing"})
        result = ops.execute_merge(source_db, self.db_path)
        self.assertTrue(result.success)
        self.assertEqual(result.added, 0)

    def test_merge_empty_target(self):
        """Merging into an empty target should add all source conversations."""
        _create_test_db(os.path.join(self.tmpdir, "src.vscdb"),
                        {"uuid-a": "A", "uuid-b": "B"})
        ops.create_empty_db(self.db_path)
        result = ops.execute_merge(os.path.join(self.tmpdir, "src.vscdb"), self.db_path)
        self.assertTrue(result.success)
        self.assertEqual(result.added, 2)

    def test_health_check_zero_conversations(self):
        """health_check should not divide by zero on empty snapshot."""
        ops.create_empty_db(self.db_path)
        snap = scanner.scan_database(self.db_path, "empty")
        report = scanner.health_check(snap)
        # Should not raise, titled_pct should be 100 (vacuously true)
        self.assertIsNotNone(report)

    def test_double_backup_filename_collision(self):
        """Two rapid backups should produce distinct filenames (different timestamps or reason)."""
        _create_test_db(self.db_path, {"uuid-1": "Test"})
        b1 = ops.create_backup(self.db_path, reason="first")
        b2 = ops.create_backup(self.db_path, reason="second")
        self.assertNotEqual(b1, b2)
        self.assertTrue(os.path.isfile(b1))
        self.assertTrue(os.path.isfile(b2))

    def test_varint_boundary_values(self):
        """Varint encoding should handle boundary values correctly."""
        for v in (0, 1, 127, 128, 16383, 16384, 2097151, 2097152):
            encoded = ProtobufEncoder.write_varint(v)
            decoded, _ = ProtobufEncoder.decode_varint(encoded, 0)
            self.assertEqual(decoded, v, f"Boundary value {v} failed round-trip")

# ==============================================================================
# TEST: TITLE RESOLUTION
# ==============================================================================

class TestResolveTitle(unittest.TestCase):
    """Tests for resolve_title — preserved metadata then .pb fallbacks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.convs_dir = os.path.join(self.tmpdir, "conversations")
        os.makedirs(self.convs_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_uses_preserved_title_when_available(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        title, source = ops.resolve_title(cid, {cid: "Preserved Title"}, self.convs_dir)
        self.assertEqual(title, "Preserved Title")
        self.assertEqual(source, "preserved")

    def test_fallback_uses_pb_mtime_when_no_preserved_title(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        pb_path = os.path.join(self.convs_dir, f"{cid}.pb")
        with open(pb_path, "w", encoding="utf-8") as fh:
            fh.write("conversation payload")
        title, source = ops.resolve_title(cid, {}, self.convs_dir)
        self.assertEqual(source, "fallback")
        self.assertTrue(title.startswith("Conversation ("))
        self.assertIn(cid[:8], title)

    def test_generic_fallback_without_pb_file(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        title, source = ops.resolve_title(cid, {}, self.convs_dir)
        self.assertEqual(source, "fallback")
        self.assertEqual(title, f"Conversation {cid[:8]}")

    def test_ignores_task_md_in_brain_directory(self):
        """Regression: task.md headings must not override preserved/fallback titles."""
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        brain_dir = os.path.join(self.tmpdir, "brain")
        brain_conv = os.path.join(brain_dir, cid)
        os.makedirs(brain_conv)
        with open(os.path.join(brain_conv, "task.md"), "w", encoding="utf-8") as fh:
            fh.write("# Hallucinated Title From task.md\n")
        pb_path = os.path.join(self.convs_dir, f"{cid}.pb")
        with open(pb_path, "w", encoding="utf-8") as fh:
            fh.write("conversation payload")
        title, source = ops.resolve_title(cid, {}, self.convs_dir)
        self.assertNotEqual(title, "Hallucinated Title From task.md")
        self.assertEqual(source, "fallback")


class TestWorkspaceInference(unittest.TestCase):
    """Tests for workspace path inference from local Antigravity data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.brain_dir = os.path.join(self.tmpdir, "brain")
        os.makedirs(self.brain_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_infer_workspace_from_file_uri_in_markdown(self):
        from src.core.artifacts import ArtifactParser

        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        conv_dir = os.path.join(self.brain_dir, cid)
        os.makedirs(conv_dir)
        project = os.path.join(self.tmpdir, "myproject")
        os.makedirs(project)
        os.makedirs(os.path.join(project, ".git"))
        uri_path = project.replace("\\", "/")
        with open(os.path.join(conv_dir, "notes.md"), "w", encoding="utf-8") as fh:
            fh.write(f"Edited file:///{uri_path}/src/main.py\n")
        result = ArtifactParser.infer_workspace_from_brain(cid, self.brain_dir)
        self.assertEqual(result, project)

    def test_returns_none_when_conversation_dir_missing(self):
        from src.core.artifacts import ArtifactParser

        result = ArtifactParser.infer_workspace_from_brain(
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", self.brain_dir,
        )
        self.assertIsNone(result)

    def test_returns_none_when_no_file_uris_found(self):
        from src.core.artifacts import ArtifactParser

        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        os.makedirs(os.path.join(self.brain_dir, cid))
        with open(os.path.join(self.brain_dir, cid, "notes.md"), "w", encoding="utf-8") as fh:
            fh.write("# No file URIs here\n")
        result = ArtifactParser.infer_workspace_from_brain(cid, self.brain_dir)
        self.assertIsNone(result)


class TestRecoveryPipelineTitles(unittest.TestCase):
    """Integration tests for title resolution inside the recovery pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "state.vscdb")
        self.convs_dir = os.path.join(self.tmpdir, "conversations")
        self.brain_dir = os.path.join(self.tmpdir, "brain")
        os.makedirs(self.convs_dir)
        os.makedirs(self.brain_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_recovery_uses_preserved_titles_from_database(self):
        cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        _create_test_db(self.db_path, {cid: "Preserved In DB"})
        with open(os.path.join(self.convs_dir, f"{cid}.pb"), "w", encoding="utf-8") as fh:
            fh.write("payload")

        result = ops.run_recovery_pipeline(
            self.db_path, self.convs_dir, self.brain_dir,
        )
        self.assertTrue(result.success)
        convs = scanner.list_conversations(self.db_path)
        titles = {c.uuid: c.title for c in convs}
        self.assertEqual(titles.get(cid), "Preserved In DB")

    def test_recovery_uses_fallback_title_when_metadata_missing(self):
        cid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        ops.create_empty_db(self.db_path)
        with open(os.path.join(self.convs_dir, f"{cid}.pb"), "w", encoding="utf-8") as fh:
            fh.write("payload")

        result = ops.run_recovery_pipeline(
            self.db_path, self.convs_dir, self.brain_dir,
        )
        self.assertTrue(result.success)
        payload = json.loads(ops.get_conversation_payload(self.db_path, cid))
        self.assertTrue(payload["title"].startswith("Conversation ("))
        self.assertIn(cid[:8], payload["title"])


# ==============================================================================
# TEST: STORAGE MANAGER
# ==============================================================================

class TestStorageManager(unittest.TestCase):
    """Tests for storage_manager patch_key, delete_key, and flatten_keys."""

    def test_patch_key_json_coercion_bool(self):
        """patch_key should coerce 'true'/'false' strings to booleans."""
        from src.core.storage_manager import patch_key
        data = {"ui": {"enabled": "placeholder"}}
        patch_key(data, "ui.enabled", "true")
        self.assertIs(data["ui"]["enabled"], True)
        patch_key(data, "ui.enabled", "false")
        self.assertIs(data["ui"]["enabled"], False)

    def test_patch_key_json_coercion_number(self):
        """patch_key should coerce '42' to int and '3.14' to float."""
        from src.core.storage_manager import patch_key
        data = {"config": {"count": 0}}
        patch_key(data, "config.count", "42")
        self.assertEqual(data["config"]["count"], 42)
        self.assertIsInstance(data["config"]["count"], int)
        patch_key(data, "config.count", "3.14")
        self.assertAlmostEqual(data["config"]["count"], 3.14)

    def test_patch_key_json_coercion_null(self):
        """patch_key should coerce 'null' to None."""
        from src.core.storage_manager import patch_key
        data = {"key": "value"}
        patch_key(data, "key", "null")
        self.assertIsNone(data["key"])

    def test_patch_key_string_passthrough(self):
        """patch_key should keep non-JSON strings as strings."""
        from src.core.storage_manager import patch_key
        data = {"theme": {"color": ""}}
        patch_key(data, "theme.color", "#ffffff")
        self.assertEqual(data["theme"]["color"], "#ffffff")
        patch_key(data, "theme.color", "hello world")
        self.assertEqual(data["theme"]["color"], "hello world")

    def test_delete_key(self):
        """delete_key should remove a nested key."""
        from src.core.storage_manager import delete_key
        data = {"a": {"b": 1, "c": 2}}
        delete_key(data, "a.b")
        self.assertNotIn("b", data["a"])
        self.assertIn("c", data["a"])

    def test_flatten_keys(self):
        """flatten_keys should produce entries for all nested keys."""
        from src.core.storage_manager import flatten_keys
        data = {"a": {"b": 1}, "c": "hello"}
        entries = flatten_keys(data)
        keys = [e.key for e in entries]
        self.assertIn("a", keys)
        self.assertIn("a.b", keys)
        self.assertIn("c", keys)


# ==============================================================================
# TEST: MULTIPLE DATABASE RESOLUTION AND SCANNING
# ==============================================================================

class TestMultipleDatabaseResolution(unittest.TestCase):
    """Tests for multiple database resolution and scanner scanning multiple dirs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        
    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_db_paths_contains_candidates(self):
        """get_antigravity_db_paths should return multiple candidate paths."""
        from src.core.environment import EnvironmentResolver
        paths = EnvironmentResolver.get_antigravity_db_paths()
        self.assertGreater(len(paths), 1)
        self.assertTrue(any("Antigravity IDE" in p for p in paths))
        self.assertTrue(any("Antigravity" in p or "antigravity" in p for p in paths))

    def test_scan_all_multiple_directories(self):
        """scan_all should discover databases and backups from both directories."""
        # Create mock directories
        dir_new = os.path.join(self.tmpdir, "Antigravity IDE", "User", "globalStorage")
        dir_old = os.path.join(self.tmpdir, "Antigravity", "User", "globalStorage")
        os.makedirs(dir_new, exist_ok=True)
        os.makedirs(dir_old, exist_ok=True)

        db_new = os.path.join(dir_new, "state.vscdb")
        db_old = os.path.join(dir_old, "state.vscdb")

        # Populate them
        _create_test_db(db_new, {"uuid-new": "New IDE"})
        _create_test_db(db_old, {"uuid-old": "Old Deprecated"})

        # Mock the get_antigravity_db_paths method to return our custom mock dirs
        from src.core.environment import EnvironmentResolver
        original_paths_fn = EnvironmentResolver.get_antigravity_db_paths
        EnvironmentResolver.get_antigravity_db_paths = staticmethod(lambda: [db_new, db_old])

        try:
            # Create a backup inside dir_new
            backup_new = os.path.join(dir_new, "state.vscdb.agmercium_recovery_1700000000_manual")
            _create_test_db(backup_new, {"uuid-new": "New IDE"})

            # Scan all with db_new as current
            snapshots = scanner.scan_all(db_new)

            # Should return 3 snapshots:
            # 1. db_new (is_current=True)
            # 2. db_old (is_current=False)
            # 3. backup_new (is_current=False)
            self.assertEqual(len(snapshots), 3)

            paths = {s.path for s in snapshots}
            self.assertIn(db_new, paths)
            self.assertIn(db_old, paths)
            self.assertIn(backup_new, paths)

            current_snapshots = [s for s in snapshots if s.is_current]
            self.assertEqual(len(current_snapshots), 1)
            self.assertEqual(current_snapshots[0].path, db_new)
            self.assertTrue(snapshots[0].is_current)
            self.assertEqual(snapshots[0].path, db_new)
        finally:
            # Restore original method
            EnvironmentResolver.get_antigravity_db_paths = original_paths_fn


# ==============================================================================
# TEST: BUG #12 URI FIX (src/core/uri_fix.py)
# ==============================================================================

def _pb_fields(msg: bytes) -> dict[int, list]:
    """Minimal independent wire-format walker for assertions: maps field
    number -> list of payloads (bytes for wire 2, int for wire 0)."""
    fields: dict[int, list] = {}
    pos = 0
    while pos < len(msg):
        tag, pos = ProtobufEncoder.decode_varint(msg, pos)
        fn, wt = tag >> 3, tag & 7
        if wt == 2:
            length, pos = ProtobufEncoder.decode_varint(msg, pos)
            fields.setdefault(fn, []).append(msg[pos:pos + length])
            pos += length
        elif wt == 0:
            val, pos = ProtobufEncoder.decode_varint(msg, pos)
            fields.setdefault(fn, []).append(val)
        elif wt == 1:
            fields.setdefault(fn, []).append(msg[pos:pos + 8])
            pos += 8
        elif wt == 5:
            fields.setdefault(fn, []).append(msg[pos:pos + 4])
            pos += 4
        else:
            raise AssertionError(f"unexpected wire type {wt}")
    return fields


_RAW_WS = {
    # The backend writes the raw-colon form everywhere — that is Bug #12.
    "uri_encoded": "file:///c:/Users/alice/proj",
    "uri_plain": "file:///c:/Users/alice/proj",
    "corpus": "local/proj",
    "git_remote": "https://github.com/local/proj.git",
    "branch": "main",
}

_CANONICAL_WS = {
    "uri_encoded": "file:///c%3A/Users/bob/proj",
    "uri_plain": "file:///c:/Users/bob/proj",
    "corpus": "local/proj",
    "git_remote": "https://github.com/local/proj.git",
    "branch": "main",
}


def _workspace_less_entry(uuid: str, text: str) -> bytes:
    """Builds an entry with no workspace fields whose message text mentions
    a file:/// path — the shape that must never gain a workspace binding."""
    inner = (
        ProtobufEncoder.write_string_field(1, "Scratchpad chat")
        + ProtobufEncoder.write_varint_field(2, 1)
        + ProtobufEncoder.write_timestamp(3, 1700000000)
        + ProtobufEncoder.write_string_field(4, uuid)
        + ProtobufEncoder.write_string_field(20, text)
    )
    wrapper = ProtobufEncoder.write_string_field(1, base64.b64encode(inner).decode("utf-8"))
    entry = ProtobufEncoder.write_string_field(1, uuid) + ProtobufEncoder.write_bytes_field(2, wrapper)
    return ProtobufEncoder.write_bytes_field(1, entry)


class TestField17EncodingSchema(unittest.TestCase):
    """Locks the per-field URI encoding to docs/schema.proto: Field 17.1
    carries the plain form, Fields 9.1/9.2 and 17.7 the encoded form."""

    WS = {
        "uri_encoded": "file:///c%3A/Users/x/proj",
        "uri_plain": "file:///c:/Users/x/proj",
        "corpus": "local/proj",
        "git_remote": "https://github.com/local/proj.git",
        "branch": "main",
    }

    def test_field17_sub1_uses_plain_uris(self):
        f17 = ProtobufEncoder.build_workspace_field17(self.WS, "sess-uuid", 1700000000)
        payload = _pb_fields(f17)[17][0]
        subs = _pb_fields(payload)
        session_ws = _pb_fields(subs[1][0])
        self.assertEqual(session_ws[1][0].decode(), self.WS["uri_plain"])
        self.assertEqual(session_ws[2][0].decode(), self.WS["uri_plain"])

    def test_field17_sub7_uses_encoded_uri(self):
        f17 = ProtobufEncoder.build_workspace_field17(self.WS, "sess-uuid", 1700000000)
        subs = _pb_fields(_pb_fields(f17)[17][0])
        self.assertEqual(subs[7][0].decode(), self.WS["uri_encoded"])

    def test_field9_uses_encoded_uris(self):
        f9 = ProtobufEncoder.build_workspace_field9(self.WS)
        subs = _pb_fields(_pb_fields(f9)[9][0])
        self.assertEqual(subs[1][0].decode(), self.WS["uri_encoded"])
        self.assertEqual(subs[2][0].decode(), self.WS["uri_encoded"])


class TestCanonicalizeDriveUri(unittest.TestCase):
    """The canonical form is lowercase drive letter + uppercase-hex %3A."""

    def test_raw_colon_variants(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///C:/Users/x"),
                         "file:///c%3A/Users/x")
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///c:/Users/x"),
                         "file:///c%3A/Users/x")

    def test_encoded_case_variants(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///C%3A/Users/x"),
                         "file:///c%3A/Users/x")
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///c%3a/Users/x"),
                         "file:///c%3A/Users/x")

    def test_already_canonical_unchanged(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///c%3A/Users/x"),
                         "file:///c%3A/Users/x")

    def test_posix_uri_unchanged(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///Users/alice/proj"),
                         "file:///Users/alice/proj")
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///home/bob/c:/odd"),
                         "file:///home/bob/c:/odd")

    def test_embedded_uri_not_rewritten(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("see file:///c:/tmp/x"),
                         "see file:///c:/tmp/x")

    def test_bare_drive_root(self):
        self.assertEqual(uri_fix.canonicalize_drive_uri("file:///c:"), "file:///c%3A")


class TestUriFixNormalizeBlob(unittest.TestCase):
    """The surgical guarantees of normalize_blob()."""

    def setUp(self):
        self.uuid_a = "aaaaaaaa-1111-2222-3333-444444444444"
        self.uuid_b = "bbbbbbbb-1111-2222-3333-444444444444"
        self.uuid_c = "cccccccc-1111-2222-3333-444444444444"
        self.entry_a = ProtobufEncoder.build_trajectory_entry(
            self.uuid_a, "My Project Work", dict(_RAW_WS), 1700000000, 1700000001)
        self.entry_b = ProtobufEncoder.build_trajectory_entry(
            self.uuid_b, "Conversation with support team", dict(_RAW_WS), 1700000000, 1700000001)
        self.entry_c = _workspace_less_entry(
            self.uuid_c, "please clean up file:///c:/temp/notes.txt now")
        self.blob = self.entry_a + self.entry_b + self.entry_c

    def test_normalizes_only_encoded_uri_fields(self):
        new_blob, seen, changed, preserved = uri_fix.normalize_blob(self.blob)
        self.assertEqual((seen, changed, preserved), (3, 2, 0))
        _, blobs = scanner.extract_existing_metadata(new_blob)
        inner_a = blobs[self.uuid_a]
        # Fields 9.1/9.2 and 17.7 canonicalized...
        self.assertEqual(scanner.extract_workspace_uri(inner_a),
                         "file:///c%3A/Users/alice/proj")
        self.assertIn(b"file:///c%3A/Users/alice/proj", inner_a)
        # ...while Field 17.1 keeps the plain form (docs/schema.proto).
        self.assertIn(b"file:///c:/Users/alice/proj", inner_a)

    def test_preserves_titles_metadata_and_timestamps(self):
        new_blob, _, _, _ = uri_fix.normalize_blob(self.blob)
        _, before = scanner.extract_existing_metadata(self.blob)
        _, after = scanner.extract_existing_metadata(new_blob)
        for uuid in (self.uuid_a, self.uuid_b):
            fields_before = _pb_fields(before[uuid])
            fields_after = _pb_fields(after[uuid])
            self.assertEqual(set(fields_before), set(fields_after))
            for fn in fields_before:
                if fn not in (9, 17):
                    self.assertEqual(fields_before[fn], fields_after[fn],
                                     f"field {fn} of {uuid} changed")
        # A real title starting with "Conversation " survives verbatim.
        self.assertEqual(_pb_fields(after[self.uuid_b])[1][0],
                         b"Conversation with support team")
        self.assertIn(b"github.com/local/proj.git", after[self.uuid_a])
        self.assertIn(b"local/proj", after[self.uuid_a])

    def test_workspace_less_entry_untouched(self):
        new_blob, _, _, _ = uri_fix.normalize_blob(self.blob)
        _, after = scanner.extract_existing_metadata(new_blob)
        _, before = scanner.extract_existing_metadata(self.blob)
        self.assertEqual(before[self.uuid_c], after[self.uuid_c])
        self.assertNotIn(b"%3A/temp/notes.txt", after[self.uuid_c])

    def test_canonicalizes_encoded_case_variants(self):
        ws = dict(_RAW_WS)
        ws["uri_encoded"] = "file:///C%3a/Users/kate/proj"
        entry = ProtobufEncoder.build_trajectory_entry(
            "dddddddd-1111-2222-3333-444444444444", "Kate", ws, 1700000000, 1700000001)
        new_blob, _, changed, _ = uri_fix.normalize_blob(entry)
        self.assertEqual(changed, 1)
        _, blobs = scanner.extract_existing_metadata(new_blob)
        self.assertEqual(
            scanner.extract_workspace_uri(blobs["dddddddd-1111-2222-3333-444444444444"]),
            "file:///c%3A/Users/kate/proj")

    def test_idempotent(self):
        once, _, changed_once, _ = uri_fix.normalize_blob(self.blob)
        twice, _, changed_twice, _ = uri_fix.normalize_blob(once)
        self.assertEqual(changed_once, 2)
        self.assertEqual(changed_twice, 0)
        self.assertEqual(once, twice)

    def test_unknown_top_level_field_preserved(self):
        stray = ProtobufEncoder.write_varint_field(5, 7)
        blob = self.entry_a + stray + self.entry_b
        new_blob, seen, changed, preserved = uri_fix.normalize_blob(blob)
        self.assertEqual((seen, changed, preserved), (2, 2, 0))
        top = _pb_fields(new_blob)
        self.assertEqual(len(top[1]), 2)
        self.assertEqual(top[5], [7])

    def test_torn_tail_preserved_verbatim(self):
        torn = self.entry_a[: len(self.entry_a) // 2]
        blob = self.entry_a + self.entry_b + torn
        new_blob, seen, changed, preserved = uri_fix.normalize_blob(blob)
        self.assertEqual((seen, changed), (2, 2))
        self.assertTrue(new_blob.endswith(torn))

    def test_unparseable_entry_preserved_not_dropped(self):
        garbage = ProtobufEncoder.write_bytes_field(1, b"\xff\xff\xff\xff")
        new_blob, seen, changed, preserved = uri_fix.normalize_blob(garbage)
        self.assertEqual((seen, changed, preserved), (1, 0, 1))
        self.assertEqual(new_blob, garbage)


class TestUriFixNormalizeDatabase(unittest.TestCase):
    """SQLite integration: dry-run, discoverable backups, identity checks."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, DB_FILENAME)
        raw_entry = ProtobufEncoder.build_trajectory_entry(
            "aaaaaaaa-0000-0000-0000-000000000001", "Raw One",
            dict(_RAW_WS), 1700000000, 1700000001)
        clean_entry = ProtobufEncoder.build_trajectory_entry(
            "bbbbbbbb-0000-0000-0000-000000000002", "Clean Two",
            dict(_CANONICAL_WS), 1700000000, 1700000001)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        cur.execute("INSERT INTO ItemTable (key, value) VALUES (?, ?)",
                    (PB_KEY, base64.b64encode(raw_entry + clean_entry).decode("utf-8")))
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _db_value(self) -> str:
        conn = sqlite3.connect(self.db_path)
        value = conn.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,)).fetchone()[0]
        conn.close()
        return value

    def _backups(self) -> list[str]:
        return [f for f in os.listdir(self.tmp) if BACKUP_PREFIX in f]

    def test_dry_run_writes_nothing(self):
        before = self._db_value()
        result = uri_fix.normalize_database(self.db_path, dry_run=True)
        self.assertTrue(result.success)
        self.assertFalse(result.wrote)
        self.assertEqual(result.entries_seen, 2)
        self.assertEqual(result.entries_changed, 1)
        self.assertEqual(self._db_value(), before)
        self.assertEqual(self._backups(), [])

    def test_real_run_normalizes_and_backs_up(self):
        result = uri_fix.normalize_database(self.db_path)
        self.assertTrue(result.success)
        self.assertTrue(result.wrote)
        self.assertEqual(result.entries_changed, 1)
        backups = self._backups()
        self.assertEqual(len(backups), 1)
        self.assertIn("_uri_fix", backups[0])
        self.assertIn(result.backup_path, [os.path.join(self.tmp, b) for b in backups])
        # The backup is visible to the tool's own restore discovery.
        self.assertEqual(len(scanner.discover_backups(self.tmp)), 1)

        _, blobs = scanner.extract_existing_metadata(base64.b64decode(self._db_value()))
        self.assertEqual(set(blobs), {"aaaaaaaa-0000-0000-0000-000000000001",
                                      "bbbbbbbb-0000-0000-0000-000000000002"})
        self.assertEqual(
            scanner.extract_workspace_uri(blobs["aaaaaaaa-0000-0000-0000-000000000001"]),
            "file:///c%3A/Users/alice/proj")

    def test_second_run_is_a_no_op(self):
        uri_fix.normalize_database(self.db_path)
        result = uri_fix.normalize_database(self.db_path)
        self.assertTrue(result.success)
        self.assertFalse(result.wrote)
        self.assertEqual(result.entries_changed, 0)
        self.assertEqual(len(self._backups()), 1)

    def test_missing_database(self):
        result = uri_fix.normalize_database(os.path.join(self.tmp, "nope.vscdb"))
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_missing_index_key(self):
        empty_db = os.path.join(self.tmp, "empty.vscdb")
        conn = sqlite3.connect(empty_db)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        result = uri_fix.normalize_database(empty_db)
        self.assertFalse(result.success)
        self.assertIn("trajectorySummaries", result.error)


_FAKE_BUNDLE = (
    '"use strict";var xx=1;\n'
    'if(F.length===1&&F[0]===dR.workspaceUris[0]){o(_.sel),setTimeout(()=>{r()},50);}\n'
    'const ff=n.workspaces.map(r=>r.workspaceFolderAbsoluteUri).some(r=>e.includes(r));\n'
    'if(l.workspaceFolderAbsoluteUri===n.toString()){sync()}\n'
)

_FAKE_PRODUCT = (
    '{\n'
    '  "nameShort": "Antigravity",\n'
    '  "checksums": {\n'
    '    "vs/workbench/workbench.desktop.main.js": "OLDSUM"\n'
    '  },\n'
    '  "other": [1, 2]\n'
    '}\n'
)


class TestIdePatcher(unittest.TestCase):
    """Workbench bundle patching: idempotency, dry-run, checksum, upgrades."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app_root = Path(self.tmp) / "resources" / "app"
        self.js_path = self.app_root / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
        self.js_path.parent.mkdir(parents=True)
        self.js_path.write_bytes(_FAKE_BUNDLE.encode("utf-8"))
        (self.app_root / "product.json").write_bytes(_FAKE_PRODUCT.encode("utf-8"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _backups(self) -> list[str]:
        return [p.name for p in self.js_path.parent.iterdir() if "agmercium_urifix" in p.name]

    def test_applies_all_three_sites(self):
        result = uri_fix.patch_workbench_js(self.app_root)
        self.assertTrue(result.success)
        self.assertEqual(len(result.patches_applied), 3)
        self.assertEqual(result.patches_missing, ())
        self.assertTrue(result.wrote)
        self.assertEqual(len(self._backups()), 1)
        content = self.js_path.read_bytes().decode("utf-8")
        self.assertTrue(content.startswith(";var _aUF="))
        self.assertIn(uri_fix.PATCH_MARKER, content)
        self.assertIn("_aUF(F[0])===_aUF(dR.workspaceUris[0])", content)
        self.assertIn("e.some(w=>_aUF(w)===_aUF(r))", content)
        self.assertIn("_aUF(l.workspaceFolderAbsoluteUri)===_aUF(n.toString())", content)

    def test_second_run_writes_nothing(self):
        uri_fix.patch_workbench_js(self.app_root)
        before = self.js_path.read_bytes()
        result = uri_fix.patch_workbench_js(self.app_root)
        self.assertTrue(result.success)
        self.assertEqual(result.patches_applied, ())
        self.assertEqual(len(result.patches_present), 3)
        self.assertFalse(result.wrote)
        self.assertEqual(self.js_path.read_bytes(), before)
        self.assertEqual(len(self._backups()), 1)

    def test_dry_run_reports_without_writing(self):
        before = self.js_path.read_bytes()
        result = uri_fix.patch_workbench_js(self.app_root, dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual(len(result.patches_applied), 3)
        self.assertFalse(result.wrote)
        self.assertEqual(self.js_path.read_bytes(), before)
        self.assertEqual(self._backups(), [])

    def test_prefix_helper_variant(self):
        bundle = (
            'if(F.length===1&&F[0]===dR.workspaceUris[0]){o()}\n'
            'function Xq$(t,e){return t===e||t.startsWith(e+"/")}\n'
            'if(l.workspaceFolderAbsoluteUri===n.toString()){sync()}\n'
        )
        self.js_path.write_bytes(bundle.encode("utf-8"))
        result = uri_fix.patch_workbench_js(self.app_root)
        self.assertIn("sidebar workspace filter", result.patches_applied)
        content = self.js_path.read_bytes().decode("utf-8")
        self.assertIn('function Xq$(t,e){var a=_aUF(t),b=_aUF(e);'
                      'return a===b||a.startsWith(b+"/")}', content)

    def test_v2_normalizer_upgrade(self):
        v2_content = (
            ";" + uri_fix._NORM_DEF_V2 + "/* ANTIGRAVITY_URI_FIX_v2 */\n"
            'if(F.length===1&&_aUF(F[0])===_aUF(dR.workspaceUris[0])){o()}\n'
            'const ff=n.workspaces.map(r=>r.workspaceFolderAbsoluteUri)'
            '.some(r=>e.some(w=>_aUF(w)===_aUF(r)));\n'
            'if(_aUF(l.workspaceFolderAbsoluteUri)===_aUF(n.toString())){sync()}\n'
        )
        self.js_path.write_bytes(v2_content.encode("utf-8"))
        result = uri_fix.patch_workbench_js(self.app_root)
        self.assertTrue(result.success)
        self.assertTrue(result.normalizer_upgraded)
        self.assertTrue(result.wrote)
        self.assertEqual(len(result.patches_present), 3)
        content = self.js_path.read_bytes().decode("utf-8")
        self.assertIn("d.toLowerCase()", content)
        self.assertIn(uri_fix.PATCH_MARKER, content)
        self.assertNotIn("ANTIGRAVITY_URI_FIX_v2", content)

    def test_missing_bundle(self):
        result = uri_fix.patch_workbench_js(Path(self.tmp) / "nowhere")
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_checksum_update_preserves_formatting(self):
        uri_fix.patch_workbench_js(self.app_root)
        result = uri_fix.update_product_checksum(self.app_root)
        self.assertTrue(result.success)
        self.assertTrue(result.updated)
        expected = base64.b64encode(
            hashlib.sha256(self.js_path.read_bytes()).digest()
        ).decode("ascii").rstrip("=")
        text = (self.app_root / "product.json").read_bytes().decode("utf-8")
        self.assertIn(f'"vs/workbench/workbench.desktop.main.js": "{expected}"', text)
        self.assertNotIn("OLDSUM", text)
        self.assertIn('"other": [1, 2]', text)

        again = uri_fix.update_product_checksum(self.app_root)
        self.assertTrue(again.success)
        self.assertFalse(again.updated)
        self.assertIn("up to date", again.note)

    def test_checksum_without_entry_is_skipped(self):
        (self.app_root / "product.json").write_bytes(b'{"nameShort": "Antigravity"}')
        result = uri_fix.update_product_checksum(self.app_root)
        self.assertTrue(result.success)
        self.assertFalse(result.updated)
        self.assertIn("No integrity entry", result.note)

    def test_resolve_app_root_accepts_common_shapes(self):
        install_dir = Path(self.tmp)
        self.assertEqual(uri_fix.resolve_app_root(str(install_dir)), self.app_root)
        self.assertEqual(uri_fix.resolve_app_root(str(self.app_root)), self.app_root)
        self.assertIsNone(uri_fix.resolve_app_root(os.path.join(self.tmp, "missing")))


if __name__ == "__main__":
    unittest.main()
