"""
Shared data models used across the Core, TUI, and Headless layers.

All models are frozen dataclasses — immutable value objects with no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ConversationEntry:
    """A single conversation extracted from a database."""
    uuid: str
    title: str
    workspace_uri: str
    has_timestamps: bool
    json_synced: bool
    is_stale: bool


@dataclass(frozen=True)
class ConversationRecord:
    """One self-contained new-generation conversation SQLite database.

    Newer IDE builds keep every conversation in its own ``<uuid>.db`` file
    under ``~/.gemini/antigravity[-ide]/conversations/`` with no central
    ``state.vscdb`` index; this record mirrors what such a file reveals.
    """
    path: str
    trajectory_id: str = ""
    cascade_id: str = ""
    trajectory_type: int = 0
    source: int = 0
    step_count: int = 0
    workspace_uris: tuple[str, ...] = ()
    workspace_uri_encoded: str = ""
    git_owner_repo: str = ""
    git_remote: str = ""
    git_branch: str = ""
    project_id: str = ""
    timestamp_seconds: int = 0
    timestamp_nanos: int = 0
    is_backup: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class OpResult:
    """Boolean-like outcome of a single write operation.

    Truthiness mirrors ``success`` so existing ``if op(...)`` call sites keep
    working, while ``error`` carries the reason for a failure.
    """
    success: bool
    error: str = ""

    def __bool__(self) -> bool:
        return self.success


@dataclass(frozen=True)
class HealthReport:
    """Health assessment of a database."""
    pb_json_synced: bool
    pb_count: int
    json_count: int
    titled_pct: float
    has_orphan_json: bool
    has_orphan_pb: bool
    summary: str

    @property
    def sync_status(self) -> str:
        if self.pb_json_synced:
            return "Synced"
        return f"Drifted (PB={self.pb_count}, JSON={self.json_count})"

    @property
    def has_orphans(self) -> bool:
        return self.has_orphan_json or self.has_orphan_pb


@dataclass(frozen=True)
class DatabaseSnapshot:
    """Immutable representation of a scanned SQLite database file's metadata."""
    path: str
    label: str
    size_bytes: int
    modified_at: float
    conversation_count: int
    titled_count: int
    workspace_count: int
    json_entry_count: int
    is_current: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class WorkspaceDiagnostic:
    """Physical state of a workspace URI resolved against the filesystem."""
    uri: str
    decoded_path: str
    exists_on_disk: bool
    is_accessible: bool
    bound_conversations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StorageEntry:
    """A flattened key from storage.json for tree display."""
    key: str
    value_type: str
    value_preview: str


@dataclass(frozen=True)
class MergeDiff:
    """Result of comparing two database snapshots for merge analysis."""
    source_only: list[str] = field(default_factory=list)
    target_only: list[str] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)
    source_total: int = 0
    target_total: int = 0
    source_only_entries: list[ConversationEntry] = field(default_factory=list)
    shared_entries: list[tuple[ConversationEntry, ConversationEntry]] = field(default_factory=list)


@dataclass(frozen=True)
class MergeResult:
    """Result of a merge operation."""
    success: bool
    added: int = 0
    updated: int = 0
    skipped: int = 0
    backup_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class RestoreResult:
    """Result of a backup restore operation."""
    success: bool
    safety_snapshot_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class RecoveryResult:
    """Result of the full recovery pipeline (Phases 1-6)."""
    success: bool
    conversations_rebuilt: int = 0
    workspaces_mapped: int = 0
    timestamps_injected: int = 0
    json_added: int = 0
    json_patched: int = 0
    json_deleted: int = 0
    backup_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class RepairResult:
    """Result of an autonomous database repair operation."""
    success: bool
    entries_scanned: int = 0
    entries_repaired: int = 0
    entries_preserved: int = 0
    ghost_bytes_stripped: int = 0
    double_wraps_fixed: int = 0
    uuid_mismatches_fixed: int = 0
    backup_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class SummariesRepairResult:
    """Result of rebuilding the new-generation Hub summaries cache."""
    success: bool
    conversations_found: int = 0
    summaries_written: int = 0
    language_server_url: str = ""
    errors: tuple[str, ...] = ()
    error: Optional[str] = None


@dataclass(frozen=True)
class UriNormalizeResult:
    """Result of the Bug #12 workspace-URI normalization of state.vscdb."""
    success: bool
    db_path: str = ""
    entries_seen: int = 0
    entries_changed: int = 0
    entries_preserved_unparsed: int = 0
    wrote: bool = False
    backup_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class IdePatchResult:
    """Result of patching workbench.desktop.main.js for Bug #12."""
    success: bool
    js_path: str = ""
    patches_applied: tuple[str, ...] = ()
    patches_present: tuple[str, ...] = ()
    patches_missing: tuple[str, ...] = ()
    normalizer_upgraded: bool = False
    wrote: bool = False
    backup_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class ProductChecksumResult:
    """Result of refreshing the workbench bundle checksum in product.json."""
    success: bool
    updated: bool = False
    note: str = ""
    backup_path: str = ""
    error: Optional[str] = None
