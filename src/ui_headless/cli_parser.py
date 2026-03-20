"""
Argparse-based CLI parser exposing all db_operations as subcommands.

Provides headless automation for CI/CD, scripting, and non-interactive use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from ..core.constants import VERSION, TOOL_NAME
from ..core.lifecycle import ApplicationContext
from ..core import db_operations as ops
from ..core.db_scanner import scan_all, format_snapshot_table, list_conversations, health_check, analyze_workspaces
from ..core import storage_manager as sm


def build_parser() -> argparse.ArgumentParser:
    """Construct the full argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="antigravity_database_manager",
        description=f"{TOOL_NAME} v{VERSION} — Agmercium Database Management Hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  antigravity_database_manager.py scan\n"
            "  antigravity_database_manager.py recover\n"
            "  antigravity_database_manager.py merge --source path/to/backup.vscdb\n"
            "  antigravity_database_manager.py backup list\n"
            "  antigravity_database_manager.py backup restore 1\n"
            "  antigravity_database_manager.py workspace list\n"
            "  antigravity_database_manager.py storage inspect\n"
        ),
    )
    parser.add_argument("--version", "-v", action="version", version=f"{TOOL_NAME} v{VERSION}")
    parser.add_argument("--headless", action="store_true",
                        help="Force headless interactive mode (no TUI)")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON (where applicable)")

    subparsers = parser.add_subparsers(dest="command")

    # --- scan ---
    subparsers.add_parser("scan", help="Scan current DB and all backups, print comparison table")

    # --- recover ---
    subparsers.add_parser("recover", help="Run the full 6-phase recovery pipeline")

    # --- merge ---
    merge_parser = subparsers.add_parser("merge", help="Merge conversations from a source DB into current")
    merge_parser.add_argument("--source", required=True, help="Path to the source database")
    merge_parser.add_argument("--strategy", choices=["additive", "overwrite"],
                              default="additive", help="Merge strategy (default: additive)")
    merge_parser.add_argument("--cherry-pick", dest="cherry_pick", default="",
                              help="Comma-separated UUIDs to cherry-pick")

    # --- backup ---
    backup_parser = subparsers.add_parser("backup", help="Manage backups")
    backup_sub = backup_parser.add_subparsers(dest="backup_action")
    backup_sub.add_parser("list", help="List all available backups")
    backup_sub.add_parser("create", help="Create a new backup")
    restore_parser = backup_sub.add_parser("restore", help="Restore a backup by index")
    restore_parser.add_argument("index", type=int, help="Backup index from 'scan' output")

    # --- create ---
    create_parser = subparsers.add_parser("create", help="Create a new empty state.vscdb")
    create_parser.add_argument("--output", required=True, help="Output path for the new database")

    # --- health ---
    subparsers.add_parser("health", help="Run a health check on the current database")

    # --- diagnose ---
    diag_parser = subparsers.add_parser("diagnose", help="Scan database for Protobuf structural corruptions")
    diag_parser.add_argument("--target", default="", help="Path to external database (default: current)")

    # --- repair ---
    rep_parser = subparsers.add_parser("repair", help="Autonomously repair detected corruptions")
    rep_parser.add_argument("--target", default="", help="Path to external database (default: current)")

    # --- conversations ---
    conv_parser = subparsers.add_parser("conversations", help="Manage individual conversations")
    conv_sub = conv_parser.add_subparsers(dest="conv_action")
    conv_sub.add_parser("list", help="List all conversations in the database")
    
    show_parser = conv_sub.add_parser("show", help="Show raw JSON payload for a conversation")
    show_parser.add_argument("uuid", help="Conversation UUID")
    
    del_parser = conv_sub.add_parser("delete", help="Delete a conversation")
    del_parser.add_argument("uuid", help="Conversation UUID")
    del_parser.add_argument("--force", "-f", action="store_true",
                            help="Skip confirmation prompt")
    
    ren_parser = conv_sub.add_parser("rename", help="Rename a conversation")
    ren_parser.add_argument("uuid", help="Conversation UUID")
    ren_parser.add_argument("title", help="New title for the conversation")

    # --- workspace ---
    ws_parser = subparsers.add_parser("workspace", help="Workspace diagnostics")
    ws_sub = ws_parser.add_subparsers(dest="ws_action")
    ws_sub.add_parser("list", help="List all unique workspaces")
    ws_sub.add_parser("check", help="Run filesystem diagnostics on all workspaces")
    mig_parser = ws_sub.add_parser("migrate", help="Migrate all conversations to a new workspace")
    mig_parser.add_argument("path", help="New workspace directory path")

    # --- storage ---
    st_parser = subparsers.add_parser("storage", help="Manage storage.json")
    st_sub = st_parser.add_subparsers(dest="storage_action")
    st_sub.add_parser("inspect", help="Display all keys in storage.json")
    st_sub.add_parser("backup", help="Create a backup of storage.json")
    patch_parser = st_sub.add_parser("patch", help="Set a value by dotted key path")
    patch_parser.add_argument("key", help="Dotted key path (e.g. 'ui.theme.foreground')")
    patch_parser.add_argument("value", help="New value")
    del_st_parser = st_sub.add_parser("delete", help="Delete a key by dotted path")
    del_st_parser.add_argument("key", help="Dotted key path")

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = build_parser()
    return parser.parse_args(argv)


def has_subcommand(args: argparse.Namespace) -> bool:
    """Check if a subcommand was provided."""
    return bool(getattr(args, "command", None))


def execute(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    """
    Execute the requested subcommand. Returns an exit code (0=success).
    """
    cmd = args.command

    if cmd == "scan":
        return _cmd_scan(args, ctx)
    elif cmd == "recover":
        return _cmd_recover(args, ctx)
    elif cmd == "merge":
        return _cmd_merge(args, ctx)
    elif cmd == "backup":
        return _cmd_backup(args, ctx)
    elif cmd == "create":
        return _cmd_create(args, ctx)
    elif cmd == "health":
        return _cmd_health(args, ctx)
    elif cmd == "diagnose":
        return _cmd_diagnose(args, ctx)
    elif cmd == "repair":
        return _cmd_repair(args, ctx)
    elif cmd == "conversations":
        return _cmd_conversations(args, ctx)
    elif cmd == "workspace":
        return _cmd_workspace(args, ctx)
    elif cmd == "storage":
        return _cmd_storage(args, ctx)
    else:
        build_parser().print_help()
        return 1


# ==============================================================================
# COMMAND IMPLEMENTATIONS
# ==============================================================================

def _cmd_scan(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    snapshots = scan_all(ctx.db_path)
    if getattr(args, "json", False):
        data = [{
            "label": s.label, "path": s.path, "size_bytes": s.size_bytes,
            "conversations": s.conversation_count, "titled": s.titled_count,
            "workspaces": s.workspace_count, "json_entries": s.json_entry_count,
            "is_current": s.is_current, "error": s.error,
        } for s in snapshots]
        print(json.dumps(data, indent=2))
    else:
        for line in format_snapshot_table(snapshots):
            print(line)
    return 0


def _cmd_recover(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    use_json = getattr(args, "json", False)
    if not use_json:
        Logger.banner()
    result = ops.run_recovery_pipeline(
        ctx.db_path, ctx.convs_dir, ctx.brain_dir,
        on_progress=lambda phase, msg: (Logger.info(f"[{phase}] {msg}") if not use_json else None),
    )
    if use_json:
        import json as _json
        print(_json.dumps({
            "success": result.success,
            "conversations_rebuilt": result.conversations_rebuilt,
            "workspaces_mapped": result.workspaces_mapped,
            "timestamps_injected": result.timestamps_injected,
            "json_added": result.json_added,
            "json_patched": result.json_patched,
            "json_deleted": result.json_deleted,
            "backup_path": result.backup_path or "",
            "error": result.error or "",
        }, indent=2))
        return 0 if result.success else 1
    if result.success:
        Logger.header("Recovery Complete")
        Logger.success(f"Conversations rebuilt:  {result.conversations_rebuilt}")
        Logger.success(f"Workspaces mapped:     {result.workspaces_mapped}")
        Logger.success(f"Timestamps injected:   {result.timestamps_injected}")
        Logger.success(f"JSON entries added:    {result.json_added}")
        Logger.success(f"JSON entries patched:  {result.json_patched}")
        Logger.success(f"JSON entries deleted:  {result.json_deleted}")
        Logger.info(f"Backup at: {result.backup_path}")
        return 0
    else:
        Logger.error(f"Recovery failed: {result.error}")
        return 1


def _cmd_merge(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    cherry = getattr(args, "cherry_pick", "")
    if cherry:
        uuids = [u.strip() for u in cherry.split(",") if u.strip()]
        result = ops.execute_selective_merge(args.source, ctx.db_path, uuids, args.strategy)
    else:
        result = ops.execute_merge(args.source, ctx.db_path, args.strategy)
    if result.success:
        Logger.success(f"Merge complete: +{result.added} added, ~{result.updated} updated, ={result.skipped} skipped")
        Logger.info(f"Backup at: {result.backup_path}")
        return 0
    else:
        Logger.error(f"Merge failed: {result.error}")
        return 1


def _cmd_backup(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    action = getattr(args, "backup_action", None)

    if action == "list":
        return _cmd_scan(args, ctx)
    elif action == "create":
        try:
            path = ops.create_backup(ctx.db_path, reason="manual")
            Logger.success(f"Backup created: {path}")
            return 0
        except OSError as exc:
            Logger.error(f"Backup failed: {exc}")
            return 1
    elif action == "restore":
        snapshots = scan_all(ctx.db_path)
        idx = args.index
        backup_snaps = [s for s in snapshots if not s.is_current]
        if idx < 1 or idx > len(backup_snaps):
            Logger.error(f"Invalid backup index. Valid: 1-{len(backup_snaps)}")
            return 1
        result = ops.restore_backup(backup_snaps[idx - 1].path, ctx.db_path)
        if result.success:
            Logger.success("Backup restored successfully.")
            return 0
        else:
            Logger.error(f"Restore failed: {result.error}")
            return 1
    else:
        print("Usage: antigravity_database_manager.py backup {list|create|restore}")
        return 1


def _cmd_create(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    if ops.create_empty_db(args.output):
        Logger.success(f"Created empty database: {args.output}")
        return 0
    else:
        Logger.error("Failed to create database.")
        return 1


def _cmd_health(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    snapshots = scan_all(ctx.db_path)
    if not snapshots:
        Logger.error("No database found.")
        return 1
    
    current = snapshots[0]
    report = health_check(current)
    
    if getattr(args, "json", False):
        print(json.dumps({
            "path": current.path,
            "size_bytes": current.size_bytes,
            "conversations": current.conversation_count,
            "titled": current.titled_count,
            "workspaces": current.workspace_count,
            "json_entries": current.json_entry_count,
            "titled_pct": report.titled_pct,
            "has_orphans": report.has_orphans,
            "sync_status": report.sync_status,
            "summary": report.summary
        }, indent=2))
    else:
        Logger.header("Database Health Report")
        Logger.info(f"Target: {current.path}")
        Logger.info(f"Size: {current.size_bytes / (1024*1024):.1f} MB")
        Logger.info(f"Sync Status: {report.sync_status}")
        Logger.info(f"Titled: {current.titled_count} / {current.conversation_count} ({report.titled_pct:.1f}%)")
        Logger.info(f"Orphaned Data: {'Yes' if report.has_orphans else 'No'}")
        Logger.success(f"Summary: {report.summary}")
    return 0


def _cmd_conversations(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    action = getattr(args, "conv_action", None)
    
    if action == "list":
        convs = list_conversations(ctx.db_path)
        if getattr(args, "json", False):
            print(json.dumps([{"uuid": c.uuid, "title": c.title, "workspace": c.workspace_uri} for c in convs], indent=2))
        else:
            Logger.header(f"Conversations ({len(convs)})")
            for c in convs:
                ws_str = f" [{c.workspace_uri}]" if c.workspace_uri else ""
                print(f"  {c.uuid[:8]}...  {c.title}{ws_str}")
        return 0
        
    elif action == "show":
        payload = ops.get_conversation_payload(ctx.db_path, args.uuid)
        print(payload)
        return 0
        
    elif action == "delete":
        force = getattr(args, "force", False)
        if not force:
            try:
                confirm = input(f"Delete conversation {args.uuid}? (y/N): ").strip().lower()
                if confirm != "y":
                    Logger.info("Cancelled.")
                    return 0
            except (KeyboardInterrupt, EOFError):
                return 0
        if ops.delete_conversation(ctx.db_path, args.uuid):
            Logger.success(f"Conversation {args.uuid} deleted.")
            return 0
        Logger.error(f"Failed to delete {args.uuid}.")
        return 1
        
    elif action == "rename":
        if ops.rename_conversation(ctx.db_path, args.uuid, args.title):
            Logger.success(f"Conversation renamed to '{args.title}'.")
            return 0
        Logger.error(f"Failed to rename {args.uuid}.")
        return 1
        
    else:
        print("Usage: antigravity_database_manager.py conversations {list|show|delete|rename}")
        return 1


def _cmd_workspace(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    action = getattr(args, "ws_action", None)

    if action == "list":
        diagnostics = analyze_workspaces(ctx.db_path)
        if getattr(args, "json", False):
            print(json.dumps([{
                "uri": d.uri, "decoded_path": d.decoded_path,
                "exists": d.exists_on_disk, "accessible": d.is_accessible,
                "conversations": len(d.bound_conversations)
            } for d in diagnostics], indent=2))
        else:
            Logger.header(f"Workspaces ({len(diagnostics)})")
            for d in diagnostics:
                icon = "✓" if d.exists_on_disk and d.is_accessible else ("⚠" if d.exists_on_disk else "✗")
                print(f"  {icon} {d.decoded_path}  ({len(d.bound_conversations)} convs)")
        return 0

    elif action == "check":
        diagnostics = analyze_workspaces(ctx.db_path)
        healthy = sum(1 for d in diagnostics if d.exists_on_disk and d.is_accessible)
        missing = sum(1 for d in diagnostics if not d.exists_on_disk)
        Logger.header("Workspace Diagnostics")
        Logger.info(f"Total workspaces: {len(diagnostics)}")
        Logger.info(f"Healthy: {healthy}")
        if missing:
            Logger.warn(f"Missing: {missing}")
            for d in diagnostics:
                if not d.exists_on_disk:
                    Logger.warn(f"  ✗ {d.decoded_path}")
        else:
            Logger.success("All workspaces accessible.")
        return 0

    elif action == "migrate":
        if ops.migrate_workspace(ctx.db_path, args.path):
            Logger.success(f"Successfully migrated workspace to '{args.path}'.")
            return 0
        Logger.error("Failed to migrate workspace.")
        return 1

    else:
        print("Usage: antigravity_database_manager.py workspace {list|check|migrate}")
        return 1


def _cmd_storage(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    action = getattr(args, "storage_action", None)
    storage_dir = os.path.dirname(ctx.db_path)

    if action == "inspect":
        data = sm.read_storage(storage_dir)
        entries = sm.flatten_keys(data)
        if getattr(args, "json", False):
            print(json.dumps([{"key": e.key, "type": e.value_type, "preview": e.value_preview} for e in entries], indent=2))
        else:
            Logger.header(f"Storage Keys ({len(entries)})")
            for e in entries:
                print(f"  {e.key}  [{e.value_type}]  {e.value_preview}")
        return 0

    elif action == "backup":
        data = sm.read_storage(storage_dir)
        bp = sm.write_storage(storage_dir, data, reason="cli_backup")
        Logger.success(f"Storage backup: {bp}")
        return 0

    elif action == "patch":
        data = sm.read_storage(storage_dir)
        try:
            sm.patch_key(data, args.key, args.value)
            sm.write_storage(storage_dir, data, reason="cli_patch")
            Logger.success(f"Patched '{args.key}' = '{args.value}'")
            return 0
        except KeyError as exc:
            Logger.error(str(exc))
            return 1

    elif action == "delete":
        data = sm.read_storage(storage_dir)
        try:
            sm.delete_key(data, args.key)
            sm.write_storage(storage_dir, data, reason="cli_delete")
            Logger.success(f"Deleted key '{args.key}'")
            return 0
        except KeyError as exc:
            Logger.error(str(exc))
            return 1

    else:
        print("Usage: antigravity_database_manager.py storage {inspect|backup|patch|delete}")
        return 1


def _cmd_diagnose(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger
    from ..core.diagnostic import diagnose_database

    target = getattr(args, "target", "") or ctx.db_path
    Logger.header("Database Corruption Diagnostic")
    Logger.info(f"Target: {target}")

    report = diagnose_database(target)
    if report.error:
        Logger.error(f"Scan failed: {report.error}")
        return 1

    if getattr(args, "json", False):
        data = {
            "db_path": report.db_path,
            "total_entries": report.total_entries,
            "corrupt": report.corrupt_entries,
            "warnings": report.warning_entries,
            "clean": report.clean_entries,
            "entries": [{
                "uuid": e.uuid, "title": e.title,
                "findings": [{"type": f.corruption_type, "severity": f.severity,
                              "description": f.description} for f in e.findings],
            } for e in report.entry_diagnostics if e.findings],
        }
        print(json.dumps(data, indent=2))
    else:
        Logger.info(f"Entries scanned: {report.total_entries}")
        Logger.info(f"Clean: {report.clean_entries}  |  Warnings: {report.warning_entries}  |  Corrupt: {report.corrupt_entries}")

        for entry in report.entry_diagnostics:
            if not entry.findings:
                continue
            icon = "✗" if entry.is_corrupt else "⚠"
            print(f"\n  {icon} {entry.uuid[:12]}...  {entry.title[:40]}")
            for f in entry.findings:
                sev = "CRIT" if f.severity == "CRITICAL" else "WARN"
                print(f"    [{sev}] {f.corruption_type}: {f.description}")

        if report.is_healthy:
            Logger.success("Database is HEALTHY — no corruptions detected.")
        else:
            Logger.warn(f"{report.corrupt_entries + report.warning_entries} entries require attention.")

    return 0


def _cmd_repair(args: argparse.Namespace, ctx: ApplicationContext) -> int:
    from .logger import Logger

    target = getattr(args, "target", "") or ctx.db_path
    Logger.header("Autonomous Database Repair")
    Logger.info(f"Target: {target}")

    result = ops.repair_database(target)
    if result.success:
        Logger.success("Repair complete.")
        Logger.info(f"Entries scanned:    {result.entries_scanned}")
        Logger.info(f"Entries repaired:   {result.entries_repaired}")
        Logger.info(f"Entries preserved:  {result.entries_preserved}")
        if result.ghost_bytes_stripped:
            Logger.info(f"Ghost bytes fixed:  {result.ghost_bytes_stripped}")
        if result.double_wraps_fixed:
            Logger.info(f"Double wraps fixed: {result.double_wraps_fixed}")
        if result.uuid_mismatches_fixed:
            Logger.info(f"UUID fixes:         {result.uuid_mismatches_fixed}")
        if result.backup_path:
            Logger.info(f"Backup at: {result.backup_path}")
        if result.entries_repaired == 0:
            Logger.success("Database was already healthy — no repairs needed.")
        return 0
    else:
        Logger.error(f"Repair failed: {result.error}")
        return 1
