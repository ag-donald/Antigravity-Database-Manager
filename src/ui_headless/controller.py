"""
Interactive headless controller — standard print()/input() menus.

Provides 100% feature parity with the TUI for users who cannot or
choose not to use the full-screen interface.
"""

from __future__ import annotations

import os
import sys

from ..core.lifecycle import ApplicationContext
from ..core import db_operations as ops
from ..core.db_scanner import scan_all, format_snapshot_table, list_conversations, health_check, analyze_workspaces
from ..core import storage_manager as sm
from .logger import Logger


def run_interactive(ctx: ApplicationContext) -> int:
    """
    Launch the full interactive headless experience.
    Returns an exit code.
    """
    Logger.banner()

    # Pre-flight warnings
    warnings = ctx.perform_preflight_checks()
    for w in warnings:
        Logger.warn(w)

    if ctx.ide_running:
        try:
            ans = input("  The IDE appears to be running. Proceed? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return 0
        if ans != "y":
            Logger.info("Aborted.")
            return 0

    while True:
        print()
        print("=" * 60)
        print("  AGMERCIUM DB MANAGER — Main Menu")
        print("=" * 60)
        print()
        print("  [1]  Scan & Compare Databases")
        print("  [2]  Restore a Backup")
        print("  [3]  Run Full Recovery Pipeline")
        print("  [4]  Merge Two Databases")
        print("  [5]  Create Empty Database")
        print("  [6]  Create Manual Backup")
        print("  [7]  Browse Conversations")
        print("  [8]  Health Check")
        print("  [9]  Workspace Diagnostics")
        print("  [10] Manage Storage.json")
        print("  [Q]  Quit")
        print()

        try:
            choice = input("  Your choice: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if choice == "1":
            _menu_scan(ctx)
        elif choice == "2":
            _menu_restore(ctx)
        elif choice == "3":
            _menu_recover(ctx)
        elif choice == "4":
            _menu_merge(ctx)
        elif choice == "5":
            _menu_create(ctx)
        elif choice == "6":
            _menu_backup(ctx)
        elif choice == "7":
            _menu_browse(ctx)
        elif choice == "8":
            _menu_health(ctx)
        elif choice == "9":
            _menu_workspaces(ctx)
        elif choice == "10":
            _menu_storage(ctx)
        elif choice in ("q", ""):
            break
        else:
            Logger.warn(f"Invalid choice: '{choice}'")

    Logger.info("Goodbye.")
    return 0


# ==============================================================================
# MENU IMPLEMENTATIONS
# ==============================================================================

def _menu_scan(ctx: ApplicationContext) -> None:
    """Display the scan/compare table."""
    Logger.header("Database Scanner")
    snapshots = scan_all(ctx.db_path)
    for line in format_snapshot_table(snapshots):
        print(line)
    print()
    _pause()


def _menu_restore(ctx: ApplicationContext) -> None:
    """Interactive backup restore."""
    Logger.header("Restore a Backup")
    snapshots = scan_all(ctx.db_path)
    backup_snaps = [s for s in snapshots if not s.is_current]

    if not backup_snaps:
        Logger.info("No backups found.")
        _pause()
        return

    for line in format_snapshot_table(snapshots):
        print(line)
    print()

    try:
        raw = input(f"  Enter backup # to restore (1-{len(backup_snaps)}, or Enter to cancel): ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    if not raw:
        return

    try:
        idx = int(raw)
    except ValueError:
        Logger.warn("Invalid number.")
        return

    if idx < 1 or idx > len(backup_snaps):
        Logger.warn(f"Index out of range. Must be 1-{len(backup_snaps)}.")
        return

    selected = backup_snaps[idx - 1]
    if selected.error:
        Logger.warn(f"That backup has an error: {selected.error}")
        return

    Logger.info(f"Selected: [{idx}] {selected.label}")
    Logger.info(f"  Conversations: {selected.conversation_count}  |  "
                f"Titled: {selected.titled_count}  |  "
                f"Workspaces: {selected.workspace_count}")

    try:
        confirm = input("  Restore this backup? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return

    if confirm != "y":
        Logger.info("Cancelled.")
        return

    result = ops.restore_backup(selected.path, ctx.db_path)
    if result.success:
        Logger.success("Backup restored successfully.")
        if result.safety_snapshot_path:
            Logger.info(f"Safety snapshot at: {result.safety_snapshot_path}")
    else:
        Logger.error(f"Restore failed: {result.error}")


def _menu_recover(ctx: ApplicationContext) -> None:
    """Run the full recovery pipeline with progress output."""
    Logger.header("Full Recovery Pipeline")

    if not os.path.isdir(ctx.convs_dir):
        Logger.error(f"Conversations directory not found: {ctx.convs_dir}")
        _pause()
        return

    result = ops.run_recovery_pipeline(
        ctx.db_path, ctx.convs_dir, ctx.brain_dir,
        on_progress=lambda phase, msg: Logger.info(f"[{phase}] {msg}"),
    )

    if result.success:
        Logger.header("Recovery Complete")
        Logger.success(f"Conversations rebuilt:  {result.conversations_rebuilt}")
        Logger.success(f"Workspaces mapped:     {result.workspaces_mapped}")
        Logger.success(f"Timestamps injected:   {result.timestamps_injected}")
        Logger.success(f"JSON entries added:    {result.json_added}")
        Logger.success(f"JSON entries patched:  {result.json_patched}")
        Logger.success(f"JSON entries deleted:  {result.json_deleted}")
        Logger.info(f"Backup at: {result.backup_path}")
    else:
        Logger.error(f"Recovery failed: {result.error}")

    _pause()


def _menu_merge(ctx: ApplicationContext) -> None:
    """Interactive merge wizard with per-conversation diff."""
    Logger.header("Merge Databases")

    try:
        source = input("  Source database path: ").strip().strip('"').strip("'")
    except (KeyboardInterrupt, EOFError):
        return

    if not source or not os.path.isfile(source):
        Logger.warn("File not found or empty path.")
        return

    # Show enriched diff
    diff = ops.compute_merge_diff(source, ctx.db_path)
    print()
    Logger.info(f"Source: {diff.source_total} conversations")
    Logger.info(f"Target: {diff.target_total} conversations")
    Logger.info(f"  New (source only):  {len(diff.source_only)}")
    Logger.info(f"  Shared:             {len(diff.shared)}")
    Logger.info(f"  Target only:        {len(diff.target_only)}")
    print()

    if diff.source_only_entries:
        Logger.header("New Conversations (source only)")
        for e in diff.source_only_entries[:20]:
            print(f"  + {e.uuid[:8]}...  {e.title}")
        if len(diff.source_only_entries) > 20:
            print(f"  ... and {len(diff.source_only_entries) - 20} more")
        print()

    print("  Strategy:")
    print("    [1] Additive — only add missing conversations (safe)")
    print("    [2] Overwrite — replace shared entries with source (destructive)")
    try:
        strat_choice = input("  Choice (1): ").strip()
    except (KeyboardInterrupt, EOFError):
        return

    strategy = "overwrite" if strat_choice == "2" else "additive"

    try:
        confirm = input(f"  Merge using '{strategy}' strategy? (y/N): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return

    if confirm != "y":
        Logger.info("Merge cancelled.")
        return

    result = ops.execute_merge(source, ctx.db_path, strategy)
    if result.success:
        Logger.success(f"Merge complete: +{result.added} added, ~{result.updated} updated, ={result.skipped} skipped")
        Logger.info(f"Backup at: {result.backup_path}")
    else:
        Logger.error(f"Merge failed: {result.error}")

    _pause()


def _menu_create(ctx: ApplicationContext) -> None:
    """Create an empty database."""
    Logger.header("Create Empty Database")
    try:
        path = input("  Output path: ").strip().strip('"').strip("'")
    except (KeyboardInterrupt, EOFError):
        return

    if not path:
        Logger.warn("No path provided.")
        return

    if ops.create_empty_db(path):
        Logger.success(f"Created empty database: {path}")
    else:
        Logger.error("Failed to create database.")

    _pause()


def _menu_backup(ctx: ApplicationContext) -> None:
    """Create a manual backup."""
    Logger.header("Create Backup")
    try:
        backup_path = ops.create_backup(ctx.db_path, reason="manual")
        Logger.success(f"Backup created: {backup_path}")
    except OSError as exc:
        Logger.error(f"Backup failed: {exc}")
    _pause()


def _browse_conversation_detail(ctx: ApplicationContext, sel) -> None:
    """Display detail and actions for a single conversation."""
    Logger.header(f"Conversation: {sel.title}")
    print(f"  UUID: {sel.uuid}")
    print(f"  Workspace: {sel.workspace_uri}")
    print(f"  Timestamps: {'Yes' if sel.has_timestamps else 'No'}")
    print(f"  JSON Synced: {'Yes' if sel.json_synced else 'No'}")
    print()
    act = input("  [V]iew Payload  [D]elete  [R]ename  [Enter] Back: ").strip().lower()
    if act == 'v':
        print(ops.get_conversation_payload(ctx.db_path, sel.uuid))
    elif act == 'd':
        if ops.delete_conversation(ctx.db_path, sel.uuid):
            Logger.success("Deleted successfully.")
        else:
            Logger.error("Failed to delete.")
    elif act == 'r':
        new_title = input("  New title: ").strip()
        if new_title and ops.rename_conversation(ctx.db_path, sel.uuid, new_title):
            Logger.success("Renamed successfully.")
        else:
            Logger.error("Failed to rename.")


def _menu_browse(ctx: ApplicationContext) -> None:
    """Browse and manage conversations."""
    Logger.header("Browse Conversations")
    convs = list_conversations(ctx.db_path)
    if not convs:
        Logger.info("No conversations found.")
        _pause()
        return

    for i, c in enumerate(convs[:20]):
        ws_str = f" [{c.workspace_uri}]" if c.workspace_uri else ""
        print(f"  [{i+1:>2}] {c.uuid[:8]}...  {c.title[:40]}{ws_str}")
    
    if len(convs) > 20:
        print(f"  ... and {len(convs) - 20} more. Enter 'n' to see next page.")
        
    print()
    try:
        idx_str = input("  Select conversation # to inspect, 'n' for next page, or Enter to go back: ").strip()
        if not idx_str:
            return
        if idx_str.lower() == 'n' and len(convs) > 20:
            # Show remaining conversations in pages of 20
            page = 1
            while page * 20 < len(convs):
                start = page * 20
                end = min(start + 20, len(convs))
                for i, c in enumerate(convs[start:end], start=start):
                    ws_str = f" [{c.workspace_uri}]" if c.workspace_uri else ""
                    print(f"  [{i+1:>2}] {c.uuid[:8]}...  {c.title[:40]}{ws_str}")
                if end < len(convs):
                    print(f"  ... and {len(convs) - end} more.")
                page_choice = input("  Select # to inspect, 'n' for next page, or Enter to go back: ").strip()
                if not page_choice:
                    _pause()
                    return
                if page_choice.lower() == 'n':
                    page += 1
                    continue
                idx = int(page_choice) - 1
                if 0 <= idx < len(convs):
                    sel = convs[idx]
                    _browse_conversation_detail(ctx, sel)
                else:
                    Logger.warn("Invalid selection.")
                _pause()
                return
            _pause()
            return
        idx = int(idx_str) - 1
        if 0 <= idx < len(convs):
            sel = convs[idx]
            _browse_conversation_detail(ctx, sel)
        else:
            Logger.warn("Invalid selection.")
    except (KeyboardInterrupt, EOFError, ValueError):
        pass
    _pause()


def _menu_health(ctx: ApplicationContext) -> None:
    """Display database health check."""
    Logger.header("Health Check")
    snapshots = scan_all(ctx.db_path)
    if not snapshots:
        Logger.error("No database found.")
        _pause()
        return
        
    current = snapshots[0]
    report = health_check(current)
    
    Logger.info(f"Target: {current.path}")
    Logger.info(f"Size: {current.size_bytes / (1024*1024):.1f} MB")
    Logger.info(f"Sync Status: {report.sync_status}")
    Logger.info(f"Conversations: {current.conversation_count}")
    Logger.info(f"Titled: {current.titled_count} ({report.titled_pct:.1f}%)")
    Logger.info(f"Workspaces: {current.workspace_count}")
    Logger.info(f"JSON Entries: {current.json_entry_count}")
    Logger.info(f"Orphaned Data: {'Yes' if report.has_orphans else 'No'}")
    print()
    Logger.success(f"Summary: {report.summary}")
    print()
    _pause()


def _menu_workspaces(ctx: ApplicationContext) -> None:
    """Workspace diagnostics."""
    Logger.header("Workspace Diagnostics")
    diagnostics = analyze_workspaces(ctx.db_path)
    if not diagnostics:
        Logger.info("No workspaces found.")
        _pause()
        return

    healthy = 0
    for d in diagnostics:
        if d.exists_on_disk and d.is_accessible:
            icon = "✓"
            healthy += 1
        elif d.exists_on_disk:
            icon = "⚠"
        else:
            icon = "✗"
        print(f"  {icon} {d.decoded_path}  ({len(d.bound_conversations)} convs)")

    print()
    Logger.info(f"Total: {len(diagnostics)} workspaces, {healthy} healthy")
    missing = len(diagnostics) - healthy
    if missing:
        Logger.warn(f"{missing} workspace(s) have issues.")
    _pause()


def _menu_storage(ctx: ApplicationContext) -> None:
    """Manage storage.json interactively."""
    Logger.header("Storage.json Manager")
    storage_dir = os.path.dirname(ctx.db_path)
    data = sm.read_storage(storage_dir)

    if not data:
        Logger.info("storage.json is empty or not found.")
        _pause()
        return

    entries = sm.flatten_keys(data)
    Logger.info(f"Found {len(entries)} keys.")
    print()

    for i, e in enumerate(entries[:30]):
        print(f"  [{i+1:>3}] {e.key}  [{e.value_type}]  {e.value_preview}")
    if len(entries) > 30:
        print(f"  ... and {len(entries) - 30} more")
    print()

    try:
        act = input("  [B]ackup  [P]atch key  [D]elete key  [Enter] Back: ").strip().lower()
        if act == 'b':
            bp = sm.write_storage(storage_dir, data, reason="manual_backup")
            Logger.success(f"Backup created: {bp}")
        elif act == 'p':
            key = input("  Key (dotted path): ").strip()
            value = input("  New value: ").strip()
            if key and value:
                try:
                    sm.patch_key(data, key, value)
                    sm.write_storage(storage_dir, data, reason="manual_patch")
                    Logger.success(f"Patched '{key}' = '{value}'")
                except KeyError as exc:
                    Logger.error(str(exc))
        elif act == 'd':
            key = input("  Key (dotted path): ").strip()
            if key:
                try:
                    sm.delete_key(data, key)
                    sm.write_storage(storage_dir, data, reason="manual_delete")
                    Logger.success(f"Deleted '{key}'")
                except KeyError as exc:
                    Logger.error(str(exc))
    except (KeyboardInterrupt, EOFError):
        pass
    _pause()


def _pause() -> None:
    """Wait for user to press Enter."""
    try:
        input("  Press Enter to continue...")
    except (KeyboardInterrupt, EOFError):
        pass
