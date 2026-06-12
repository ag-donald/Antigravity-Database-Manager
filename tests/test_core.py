"""
Production Readiness Test Suite — Antigravity Database Manager

Comprehensive tests for all core modules using only the standard library.
Run with:  python -m unittest tests.test_core -v

Coverage:
  - Protobuf round-trip encoding/decoding
  - Database lifecycle (create → write → read)
  - Merge operations (additive, overwrite, selective)
  - Backup and restore lifecycle
  - Diagnostic scanner
  - Repair pipeline
  - Edge cases and input validation
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

# Add the project root to path for imports.
# NOTE: This is intentional for a zero-dependency project without pyproject.toml.
# Replace with editable install (`pip install -e .`) if packaging is added.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.protobuf import ProtobufEncoder
from src.core.constants import PB_KEY, JSON_KEY
from src.core.models import MergeResult, RestoreResult, MergeDiff
from src.core import db_operations as ops
from src.core import db_scanner as scanner
from src.core import diagnostic


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
# TEST: WIDGET TRUNCATION (ANSI-AWARE)
# ==============================================================================

class TestWidgetTrunc(unittest.TestCase):
    """Tests for the ANSI-aware _trunc function in widgets.py."""

    def test_trunc_plain_string(self):
        """Plain strings should truncate normally."""
        from src.ui_tui.widgets import _trunc
        self.assertEqual(_trunc("Hello World", 5), "Hell…")
        self.assertEqual(_trunc("Hi", 10), "Hi")

    def test_trunc_ansi_string(self):
        """ANSI escape sequences should not count toward visible length."""
        from src.ui_tui.widgets import _trunc
        # Bold + Reset = 8 bytes of escapes, 5 visible chars
        ansi = "\x1b[1mHello\x1b[0m"
        result = _trunc(ansi, 10)
        # 5 visible chars < 10, so no truncation
        self.assertEqual(result, ansi)

    def test_trunc_ansi_forces_cut(self):
        """When visible length exceeds width, ANSI strings should be truncated correctly."""
        from src.ui_tui.widgets import _trunc
        ansi = "\x1b[1mHelloWorld\x1b[0m"
        result = _trunc(ansi, 5)
        # Should have 4 visible chars + ellipsis
        self.assertIn("…", result)


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
        finally:
            # Restore original method
            EnvironmentResolver.get_antigravity_db_paths = original_paths_fn


if __name__ == "__main__":
    unittest.main()
