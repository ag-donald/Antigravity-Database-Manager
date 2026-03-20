"""
MVU Screen definitions for the TUI v8.

Each screen class implements the MVU pattern:
  - `model`: dataclass holding the screen's state
  - `update(key)`: mutates state or returns routing command
  - `view(cols, rows)`: returns list[str] frame representing output
"""
from __future__ import annotations
import os, time
from dataclasses import dataclass, field
from typing import Optional

from .engine import Key, KeyEvent
from . import widgets as W
from ..core.constants import VERSION, APP_NAME
from ..core.models import (
    DatabaseSnapshot, MergeDiff, ConversationEntry, HealthReport,
    MergeResult, RecoveryResult, WorkspaceDiagnostic, StorageEntry,
)
from ..core import db_operations as ops
from ..core.db_scanner import scan_all, list_conversations, health_check, analyze_workspaces
from ..core.environment import EnvironmentResolver
from ..core import storage_manager as sm


def _overlay(bg: list[str], modal: list[str]) -> None:
    h = len(bg)
    start = max(0, (h - len(modal)) // 2)
    for i, mline in enumerate(modal):
        if 0 <= start + i < h:
            bg[start + i] = mline


# ==============================================================================
# 1. HOME VIEW
# ==============================================================================
@dataclass
class HomeModel:
    snapshots: list[DatabaseSnapshot] = field(default_factory=list)
    reports: dict[str, HealthReport] = field(default_factory=dict)
    selected: int = 0
    scroll: int = 0
    overlay: str = "none"
    menu_selected: int = 0
    status_msg: str = ""
    status_time: float = 0.0

class HomeView:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.m = HomeModel()

    def on_enter(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.m.snapshots = scan_all(self.db_path)
        if self.m.snapshots:
            self.m.reports[self.m.snapshots[0].path] = health_check(self.m.snapshots[0])
            
    def set_status(self, msg: str) -> None:
        self.m.status_msg = msg
        self.m.status_time = time.time()

    def update(self, key: KeyEvent) -> Optional[str]:
        if self.m.status_msg and time.time() - self.m.status_time > 5.0:
            self.m.status_msg = ""
            
        cur_snap = self.m.snapshots[self.m.selected] if self.m.snapshots else None

        if self.m.overlay == "action_menu" and cur_snap:
            is_current = cur_snap.is_current
            items = (
                ["Browse Conversations", "Run Full Recovery", "Create Backup",
                 "Merge From Another DB", "Workspace Diagnostics",
                 "Manage Storage", "Reset Database (Empty)"]
                if is_current else
                ["Browse Conversations", "Restore This Backup",
                 "Compare with Current", "Delete This Backup"]
            )
            
            if key.key == Key.UP:
                self.m.menu_selected = max(0, self.m.menu_selected - 1)
            elif key.key == Key.DOWN:
                self.m.menu_selected = min(len(items) - 1, self.m.menu_selected + 1)
            elif key.key == Key.ESCAPE:
                self.m.overlay = "none"
            elif key.key == Key.ENTER:
                choice = items[self.m.menu_selected]
                self.m.overlay = "none"
                if choice == "Browse Conversations":
                    return f"push:browse:{cur_snap.path}"
                elif choice == "Run Full Recovery":
                    return "push:recover"
                elif choice == "Create Backup":
                    ops.create_backup(cur_snap.path, reason="manual")
                    self.set_status("✓ Backup created")
                    self._refresh()
                elif choice == "Merge From Another DB":
                    return "push:merge"
                elif choice == "Workspace Diagnostics":
                    return f"push:workspaces:{cur_snap.path}"
                elif choice == "Manage Storage":
                    return "push:storage"
                elif choice == "Reset Database (Empty)":
                    self.m.overlay = "confirm_reset"
                elif choice == "Restore This Backup":
                    self.m.overlay = "confirm_restore"
                elif choice == "Compare with Current":
                    return f"push:merge:{cur_snap.path}"
                elif choice == "Delete This Backup":
                    self.m.overlay = "confirm_delete"
            return None
            
        elif self.m.overlay == "confirm_restore" and cur_snap:
            if key.char.lower() == "y":
                res = ops.restore_backup(cur_snap.path, self.db_path)
                self.set_status("✓ Restored!" if res.success else "✗ Error")
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None
            
        elif self.m.overlay == "confirm_delete" and cur_snap:
            if key.char.lower() == "y":
                try:
                    os.remove(cur_snap.path)
                    self.set_status("✓ Deleted")
                except Exception:
                    self.set_status("✗ Error")
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        elif self.m.overlay == "confirm_reset" and cur_snap:
            if key.char.lower() == "y":
                ops.create_backup(cur_snap.path, reason="before_empty")
                ops.create_empty_db(cur_snap.path)
                self.set_status("✓ Database reset safely")
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        # Base navigation
        if key.key == Key.UP:
            self.m.selected = max(0, self.m.selected - 1)
        elif key.key == Key.DOWN:
            self.m.selected = min(len(self.m.snapshots) - 1, self.m.selected + 1)
        elif key.key == Key.PAGE_UP:
            self.m.selected = max(0, self.m.selected - 10)
        elif key.key == Key.PAGE_DOWN:
            self.m.selected = min(len(self.m.snapshots) - 1, self.m.selected + 10)

        # Lazy-load health reports for newly selected snapshots
        if self.m.snapshots:
            snap = self.m.snapshots[self.m.selected]
            if snap.path not in self.m.reports:
                self.m.reports[snap.path] = health_check(snap)

        # Shortcut keys (independent of selection change)
        if key.char.lower() == "s":
            self._refresh()
            self.set_status("✓ Refreshed")
        elif key.char.lower() == "b" and cur_snap:
            ops.create_backup(cur_snap.path, reason="manual")
            self.set_status("✓ Backup created")
            self._refresh()
        elif key.char.lower() == "r":
            return "push:recover"
        elif key.char.lower() == "w":
            if cur_snap:
                return f"push:workspaces:{cur_snap.path}"
        elif key.char.lower() == "t":
            return "push:storage"
        elif key.char == "?":
            return "push:help"
        elif key.key == Key.ENTER:
            if self.m.snapshots:
                self.m.overlay = "action_menu"
                self.m.menu_selected = 0
        elif key.char.lower() == "q" or key.key == Key.ESCAPE:
            return "quit"
            
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Database Manager")
        main_h = rows - 3
        
        if not self.m.snapshots:
            left = ["No databases found."]
            right: list[str] = []
        else:
            left = W.render_snapshot_table(self.m.snapshots, self.m.selected, int(cols*0.55), main_h, self.m.scroll)
            snap = self.m.snapshots[self.m.selected]
            rep = self.m.reports.get(snap.path)
            right = W.render_health_report(snap, rep, cols - int(cols*0.55) - 1)
            
        pane = W.render_split_pane(left, right, cols, 0.55)
        while len(pane) < main_h:
            pane.append(" " * cols)
        lines.extend(pane[:main_h])
        
        cur_snap = self.m.snapshots[self.m.selected] if self.m.snapshots else None
        if cur_snap:
            if self.m.overlay == "action_menu":
                it = (
                    ["Browse Conversations", "Run Full Recovery", "Create Backup",
                     "Merge From Another DB", "Workspace Diagnostics",
                     "Manage Storage", "Reset Database (Empty)"]
                    if cur_snap.is_current else
                    ["Browse Conversations", "Restore This Backup",
                     "Compare with Current", "Delete This Backup"]
                )
                _overlay(lines, W.render_action_menu(cur_snap.label, it, self.m.menu_selected, cols, rows))
            elif self.m.overlay == "confirm_restore":
                _overlay(lines, W.render_confirm_modal("Restore Backup", [f"Restore {cur_snap.label}?", "A safety backup will be created."], cols, rows))
            elif self.m.overlay == "confirm_delete":
                _overlay(lines, W.render_confirm_modal("Delete Backup", [f"Delete {cur_snap.label}?"], cols, rows))
            elif self.m.overlay == "confirm_reset":
                _overlay(lines, W.render_confirm_modal("Reset Database", [f"⚠ This will ERASE all data in {cur_snap.label}.", "A backup will be created first.", "Are you sure? (Y/N)"], cols, rows))
                
        lines.extend(W.render_footer(cols, ["↑↓ Nav", "Enter Act", "W Workspaces", "T Storage", "? Help", "Q Quit"], self.m.status_msg))
        return lines


# ==============================================================================
# 2. CONVERSATION BROWSER VIEW
# ==============================================================================
@dataclass
class BrowserModel:
    convs: list[ConversationEntry] = field(default_factory=list)
    filtered: list[ConversationEntry] = field(default_factory=list)
    selected: int = 0
    scroll: int = 0
    search: str = ""
    is_searching: bool = False
    overlay: str = "none"
    menu_selected: int = 0
    input_text: str = ""
    status_msg: str = ""

class ConversationBrowserView:
    def __init__(self, target_db: str):
        self.target_db = target_db
        self.m = BrowserModel()

    def on_enter(self) -> None:
        self.m.convs = list_conversations(self.target_db)
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self.m.search:
            self.m.filtered = [c for c in self.m.convs if self.m.search.lower() in c.title.lower()]
        else:
            self.m.filtered = list(self.m.convs)
        self.m.selected = min(self.m.selected, max(0, len(self.m.filtered) - 1))

    def update(self, key: KeyEvent) -> Optional[str]:
        cur_conv = self.m.filtered[self.m.selected] if self.m.filtered else None
        
        if self.m.is_searching:
            if key.key == Key.ENTER or key.key == Key.ESCAPE:
                self.m.is_searching = False
                if key.key == Key.ESCAPE:
                    self.m.search = ""
                self._apply_filter()
            elif key.key == Key.BACKSPACE:
                self.m.search = self.m.search[:-1]
                self._apply_filter()
            elif key.key == Key.CHAR:
                self.m.search += key.char
                self._apply_filter()
            return None

        if self.m.overlay == "action_menu" and cur_conv:
            items = ["Inspect Raw Payload", "Rename", "Delete"]
            if key.key == Key.UP:
                self.m.menu_selected = max(0, self.m.menu_selected - 1)
            elif key.key == Key.DOWN:
                self.m.menu_selected = min(len(items) - 1, self.m.menu_selected + 1)
            elif key.key == Key.ESCAPE:
                self.m.overlay = "none"
            elif key.key == Key.ENTER:
                ch = items[self.m.menu_selected]
                self.m.overlay = "none"
                if ch == "Inspect Raw Payload":
                    return f"push:view:{self.target_db}:{cur_conv.uuid}"
                elif ch == "Rename":
                    self.m.overlay = "rename_input"
                    self.m.input_text = cur_conv.title
                elif ch == "Delete":
                    self.m.overlay = "confirm_delete"
            return None
            
        if self.m.overlay == "rename_input" and cur_conv:
            if key.key == Key.ENTER:
                if self.m.input_text.strip():
                    ops.rename_conversation(self.target_db, cur_conv.uuid, self.m.input_text.strip())
                    self.m.status_msg = "✓ Renamed"
                    self.on_enter()
                self.m.overlay = "none"
            elif key.key == Key.ESCAPE:
                self.m.overlay = "none"
            elif key.key == Key.BACKSPACE:
                self.m.input_text = self.m.input_text[:-1]
            elif key.key == Key.CHAR:
                self.m.input_text += key.char
            return None
            
        if self.m.overlay == "confirm_delete" and cur_conv:
            if key.char.lower() == "y":
                ops.delete_conversation(self.target_db, cur_conv.uuid)
                self.m.status_msg = "✓ Deleted"
                self.m.overlay = "none"
                self.on_enter()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        # Base nav
        if key.key == Key.UP:
            self.m.selected = max(0, self.m.selected - 1)
        elif key.key == Key.DOWN:
            self.m.selected = min(len(self.m.filtered) - 1, self.m.selected + 1)
        elif key.key == Key.PAGE_UP:
            self.m.selected = max(0, self.m.selected - 10)
        elif key.key == Key.PAGE_DOWN:
            self.m.selected = min(len(self.m.filtered) - 1, self.m.selected + 10)
        elif key.char == "/":
            self.m.is_searching = True
        elif key.char.lower() == "d" and cur_conv:
            self.m.overlay = "confirm_delete"
        elif key.char.lower() == "n" and cur_conv:
            self.m.overlay = "rename_input"
            self.m.input_text = cur_conv.title
        elif key.key == Key.ENTER and cur_conv:
            self.m.overlay = "action_menu"
            self.m.menu_selected = 0
        elif key.key == Key.ESCAPE:
            return "back"

        # Keep scroll in sync with selection
        visible_h = max(1, 20)  # approximate visible rows for conversation table
        if self.m.selected < self.m.scroll:
            self.m.scroll = self.m.selected
        elif self.m.selected >= self.m.scroll + visible_h:
            self.m.scroll = self.m.selected - visible_h + 1

        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, f"Browsing {os.path.basename(self.target_db)}")
        main_h = rows - 3
        
        left = W.render_conversation_table(self.m.filtered, self.m.selected, int(cols*0.55), main_h, self.m.scroll)
        cur_conv = self.m.filtered[self.m.selected] if self.m.filtered else None
        right = W.render_conversation_detail(cur_conv, cols - int(cols*0.55) - 1)
            
        pane = W.render_split_pane(left, right, cols, 0.55)
        while len(pane) < main_h:
            pane.append(" " * cols)
        lines.extend(pane[:main_h])
        
        if cur_conv:
            if self.m.overlay == "action_menu":
                _overlay(lines, W.render_action_menu("Options", ["Inspect Raw Payload", "Rename", "Delete"], self.m.menu_selected, cols, rows))
            elif self.m.overlay == "confirm_delete":
                _overlay(lines, W.render_confirm_modal("Delete", [f"Delete '{cur_conv.title}'?"], cols, rows))
            elif self.m.overlay == "rename_input":
                _overlay(lines, W.render_text_input("Rename", "New title:", self.m.input_text, cols, rows))

        stat = f"/ Filter: {self.m.search}█" if self.m.is_searching else self.m.status_msg
        lines.extend(W.render_footer(cols, ["↑↓ Nav", "Enter Act", "/ Search", "Esc Back"], stat))
        return lines


# ==============================================================================
# 3. TEXT VIEWER (PAYLOAD INSPECTION)
# ==============================================================================
@dataclass
class DataViewModel:
    payload_lines: list[str] = field(default_factory=list)
    scroll: int = 0
    uuid: str = ""

class ConversationDataView:
    def __init__(self, db_path: str, uuid: str):
        self.db_path = db_path
        self.uuid = uuid
        self.m = DataViewModel()

    def on_enter(self) -> None:
        self.m.uuid = self.uuid
        raw = ops.get_conversation_payload(self.db_path, self.uuid)
        self.m.payload_lines = raw.split("\n")

    def update(self, key: KeyEvent) -> Optional[str]:
        if key.key == Key.UP:
            self.m.scroll = max(0, self.m.scroll - 1)
        elif key.key == Key.DOWN:
            self.m.scroll = min(len(self.m.payload_lines) - 1, self.m.scroll + 1)
        elif key.key == Key.PAGE_UP:
            self.m.scroll = max(0, self.m.scroll - 20)
        elif key.key == Key.PAGE_DOWN:
            self.m.scroll = min(len(self.m.payload_lines) - 1, self.m.scroll + 20)
        elif key.key == Key.ESCAPE:
            return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, f"Raw JSON Payload: {self.uuid[:8]}")
        main_h = rows - 3
        
        textpane = W.render_text_viewer(self.m.payload_lines, self.m.scroll, cols, main_h)
        while len(textpane) < main_h:
            textpane.append(" " * cols)
        lines.extend(textpane[:main_h])
        
        lines.extend(W.render_footer(cols, ["↑↓ Scroll", "Esc Back"], f"Lines: {len(self.m.payload_lines)}"))
        return lines


# ==============================================================================
# 4. RECOVERY WIZARD — Enterprise 6-Phase Pipeline
# ==============================================================================
RECOVERY_PHASES = ["Backup", "Discovery", "Titles", "Injection", "JSON", "Done"]

@dataclass
class RecoveryModel:
    phase: str = "ready"
    phase_idx: int = 0
    phase_statuses: list[str] = field(default_factory=lambda: [""] * 6)
    res: Optional[RecoveryResult] = None

class RecoveryWizardView:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.m = RecoveryModel()

    def _on_progress(self, phase: str, msg: str) -> None:
        phase_map = {"backup": 0, "discovery": 1, "titles": 2, "injection": 3, "json": 4, "done": 5}
        idx = phase_map.get(phase, self.m.phase_idx)
        self.m.phase_idx = idx
        if idx < len(self.m.phase_statuses):
            self.m.phase_statuses[idx] = msg

    def _needs_paint(self) -> bool:
        """Signal that paint() should be called before the next blocking op."""
        return self.m.phase == "running"

    def update(self, key: KeyEvent) -> Optional[str]:
        if self.m.phase == "ready":
            if key.key == Key.ENTER:
                # Set phase to "running" — the view() will render "Working…"
                # and the App loop will call paint() before the next update().
                self.m.phase = "running"
                self.m.phase_idx = 0
            elif key.key == Key.ESCAPE:
                return "back"
        elif self.m.phase == "running":
            # Execute the pipeline on the NEXT update cycle (after paint)
            res = ops.run_recovery_pipeline(
                self.db_path,
                os.path.join(EnvironmentResolver.get_gemini_base_path(), "conversations"),
                os.path.join(EnvironmentResolver.get_gemini_base_path(), "brain"),
                on_progress=self._on_progress,
            )
            self.m.res = res
            self.m.phase = "done" if res.success else "error"
        elif self.m.phase in ("done", "error"):
            if key.key in (Key.ENTER, Key.ESCAPE):
                return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Full Recovery Pipeline")
        main_h = rows - 3
        pane: list[str] = []

        # Pipeline indicator
        pane.append("")
        pane.extend(W.render_wizard_pipeline(RECOVERY_PHASES, self.m.phase_idx, self.m.phase_statuses, cols))
        pane.append("")

        if self.m.phase == "ready":
            pane.append(f"  Target: {self.db_path}")
            pane.append("")
            pane.append(f"  {W.C.DIM}This will rebuild ALL conversations from .pb files,{W.C.RESET}")
            pane.append(f"  {W.C.DIM}resolve titles from brain artifacts, and synchronize{W.C.RESET}")
            pane.append(f"  {W.C.DIM}the JSON index. A full backup is created first.{W.C.RESET}")
            pane.append("")
            pane.append(f"  {W.C.BRIGHT_CYAN}Press Enter to begin.{W.C.RESET}")
        elif self.m.phase == "running":
            pane.append(f"  {W.C.YELLOW}Running... (Please wait){W.C.RESET}")
        elif self.m.phase == "done" and self.m.res:
            pane.append(f"  {W.C.BRIGHT_GREEN}✓ Recovery Complete{W.C.RESET}")
            pane.append("")
            pane.append(f"  Conversations rebuilt: {self.m.res.conversations_rebuilt}")
            pane.append(f"  Workspaces mapped:    {self.m.res.workspaces_mapped}")
            pane.append(f"  Timestamps injected:  {self.m.res.timestamps_injected}")
            pane.append(f"  JSON entries added:   {self.m.res.json_added}")
            pane.append(f"  JSON entries patched:  {self.m.res.json_patched}")
            pane.append(f"  JSON entries deleted:  {self.m.res.json_deleted}")
            if self.m.res.backup_path:
                pane.append(f"  Backup at: {W.C.DIM}{self.m.res.backup_path}{W.C.RESET}")
        elif self.m.phase == "error" and self.m.res:
            pane.append(f"  {W.C.RED}✗ Recovery Failed{W.C.RESET}")
            pane.append(f"  {self.m.res.error}")
            if self.m.res.backup_path:
                pane.append(f"  Backup preserved at: {W.C.DIM}{self.m.res.backup_path}{W.C.RESET}")
            
        while len(pane) < main_h:
            pane.append(" ")
        lines.extend(pane[:main_h])
        footer_hints = ["Enter Start", "Esc Back"] if self.m.phase == "ready" else ["Enter/Esc Back"]
        lines.extend(W.render_footer(cols, footer_hints))
        return lines


# ==============================================================================
# 5. MERGE WIZARD — Enterprise Diff & Cherry-Pick
# ==============================================================================
@dataclass
class MergeModel:
    step: str = "source_select"
    source_path: str = ""
    diff: Optional[MergeDiff] = None
    selected_uuids: set[str] = field(default_factory=set)
    cursor: int = 0
    strategy: str = "additive"
    res: Optional[MergeResult] = None

class MergeWizardView:
    def __init__(self, target_db: str, source_db: str = ""):
        self.target_db = target_db
        self.m = MergeModel()
        if source_db:
            self.m.source_path = source_db
            self.m.step = "loading"

    def on_enter(self) -> None:
        if self.m.step == "loading":
            self._load_diff()

    def _load_diff(self) -> None:
        self.m.diff = ops.compute_merge_diff(self.m.source_path, self.target_db)
        # Auto-select all source-only (new) conversations
        self.m.selected_uuids = set(self.m.diff.source_only)
        self.m.step = "diff_preview"
        self.m.cursor = 0

    def _all_entries(self) -> list[tuple[str, str]]:
        if not self.m.diff:
            return []
        entries: list[tuple[str, str]] = []
        for e in self.m.diff.source_only_entries:
            entries.append((e.uuid, e.title))
        for src_e, tgt_e in self.m.diff.shared_entries:
            entries.append((src_e.uuid, src_e.title))
        return entries

    def update(self, key: KeyEvent) -> Optional[str]:
        if key.key == Key.ESCAPE:
            if self.m.step in ("diff_preview", "confirm"):
                self.m.step = "source_select"
                return None
            return "back"

        if self.m.step == "source_select":
            if key.key == Key.ENTER and self.m.source_path:
                if os.path.isfile(self.m.source_path):
                    self.m.step = "loading"
                    self._load_diff()
            elif key.key == Key.BACKSPACE:
                self.m.source_path = self.m.source_path[:-1]
            elif key.key == Key.CHAR:
                self.m.source_path += key.char

        elif self.m.step == "diff_preview":
            all_e = self._all_entries()
            if key.key == Key.UP:
                self.m.cursor = max(0, self.m.cursor - 1)
            elif key.key == Key.DOWN:
                self.m.cursor = min(len(all_e) - 1, self.m.cursor + 1)
            elif key.char == " " and all_e:
                uid = all_e[self.m.cursor][0]
                if uid in self.m.selected_uuids:
                    self.m.selected_uuids.discard(uid)
                else:
                    self.m.selected_uuids.add(uid)
            elif key.char.lower() == "a":
                self.m.selected_uuids = {e[0] for e in all_e}
            elif key.char.lower() == "n":
                self.m.selected_uuids.clear()
            elif key.key == Key.ENTER:
                self.m.step = "confirm"

        elif self.m.step == "confirm":
            if key.char == "1":
                self.m.strategy = "additive"
            elif key.char == "2":
                self.m.strategy = "overwrite"
            elif key.key == Key.ENTER:
                if self.m.selected_uuids:
                    self.m.res = ops.execute_selective_merge(
                        self.m.source_path, self.target_db,
                        list(self.m.selected_uuids), self.m.strategy
                    )
                else:
                    self.m.res = ops.execute_merge(
                        self.m.source_path, self.target_db, self.m.strategy
                    )
                self.m.step = "done"

        elif self.m.step == "done":
            if key.key == Key.ENTER:
                return "back"

        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Merge Databases")
        main_h = rows - 3
        pane: list[str] = []

        if self.m.step == "source_select":
            pane.append("  Enter Source DB Path:")
            pane.append(f"  {self.m.source_path}█")
            pane.append("")
            pane.append(f"  {W.C.DIM}Paste or type the full path to a backup or other state.vscdb{W.C.RESET}")

        elif self.m.step == "loading":
            pane.append("  Loading diff...")

        elif self.m.step == "diff_preview" and self.m.diff:
            pane.extend(W.render_diff_table(
                self.m.diff, self.m.selected_uuids, self.m.cursor,
                cols, main_h - 2
            ))
            pane.append("")
            pane.append(f"  {W.C.DIM}Space=Toggle  A=All  N=None  Enter=Confirm{W.C.RESET}")

        elif self.m.step == "confirm":
            count = len(self.m.selected_uuids)
            pane.append(f"  {W.C.BOLD}Ready to Merge{W.C.RESET}")
            pane.append(f"  Selected: {count} conversation(s)")
            pane.append("")
            strat_1 = f"{W.C.BRIGHT_CYAN}▸{W.C.RESET}" if self.m.strategy == "additive" else " "
            strat_2 = f"{W.C.BRIGHT_CYAN}▸{W.C.RESET}" if self.m.strategy == "overwrite" else " "
            pane.append(f"  {strat_1} [1] Additive  — only add missing (safe)")
            pane.append(f"  {strat_2} [2] Overwrite — replace shared entries (destructive)")
            pane.append("")
            pane.append(f"  {W.C.BRIGHT_CYAN}Press Enter to execute merge.{W.C.RESET}")

        elif self.m.step == "done" and self.m.res:
            if self.m.res.success:
                pane.append(f"  {W.C.BRIGHT_GREEN}✓ Merge Complete{W.C.RESET}")
                pane.append(f"  Added: {self.m.res.added}  Updated: {self.m.res.updated}  Skipped: {self.m.res.skipped}")
            else:
                pane.append(f"  {W.C.RED}✗ Merge Failed{W.C.RESET}")
                pane.append(f"  {self.m.res.error}")
            if self.m.res.backup_path:
                pane.append(f"  Backup: {W.C.DIM}{self.m.res.backup_path}{W.C.RESET}")

        while len(pane) < main_h:
            pane.append(" ")
        lines.extend(pane[:main_h])
        lines.extend(W.render_footer(cols, ["Enter Next", "Esc Back"]))
        return lines


# ==============================================================================
# 6. WORKSPACE BROWSER VIEW
# ==============================================================================
@dataclass
class WorkspaceModel:
    diagnostics: list[WorkspaceDiagnostic] = field(default_factory=list)
    selected: int = 0

class WorkspaceBrowserView:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.m = WorkspaceModel()

    def on_enter(self) -> None:
        self.m.diagnostics = analyze_workspaces(self.db_path)

    def update(self, key: KeyEvent) -> Optional[str]:
        if key.key == Key.UP:
            self.m.selected = max(0, self.m.selected - 1)
        elif key.key == Key.DOWN:
            self.m.selected = min(len(self.m.diagnostics) - 1, self.m.selected + 1)
        elif key.key == Key.ESCAPE:
            return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Workspace Diagnostics")
        main_h = rows - 3

        if not self.m.diagnostics:
            left = ["  No workspaces found."]
            right: list[str] = []
        else:
            left = W.render_workspace_table(self.m.diagnostics, self.m.selected, int(cols * 0.55), main_h)
            diag = self.m.diagnostics[self.m.selected] if self.m.diagnostics else None
            right = W.render_workspace_detail(diag, cols - int(cols * 0.55) - 1)

        pane = W.render_split_pane(left, right, cols, 0.55)
        while len(pane) < main_h:
            pane.append(" " * cols)
        lines.extend(pane[:main_h])

        healthy = sum(1 for d in self.m.diagnostics if d.exists_on_disk and d.is_accessible)
        total = len(self.m.diagnostics)
        stat = f"Healthy: {healthy}/{total}"
        lines.extend(W.render_footer(cols, ["↑↓ Nav", "Esc Back"], stat))
        return lines


# ==============================================================================
# 7. STORAGE BROWSER VIEW
# ==============================================================================
@dataclass
class StorageModel:
    entries: list[StorageEntry] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)
    selected: int = 0
    scroll: int = 0
    overlay: str = "none"
    input_text: str = ""
    status_msg: str = ""

class StorageBrowserView:
    def __init__(self, storage_dir: str):
        self.storage_dir = storage_dir
        self.m = StorageModel()

    def on_enter(self) -> None:
        self.m.raw_data = sm.read_storage(self.storage_dir)
        self.m.entries = sm.flatten_keys(self.m.raw_data)

    def update(self, key: KeyEvent) -> Optional[str]:
        if self.m.overlay == "edit_value":
            if key.key == Key.ENTER:
                if self.m.entries and self.m.input_text.strip():
                    entry = self.m.entries[self.m.selected]
                    sm.patch_key(self.m.raw_data, entry.key, self.m.input_text.strip())
                    sm.write_storage(self.storage_dir, self.m.raw_data, reason="storage_edit")
                    self.m.status_msg = "✓ Saved"
                    self.on_enter()
                self.m.overlay = "none"
            elif key.key == Key.ESCAPE:
                self.m.overlay = "none"
            elif key.key == Key.BACKSPACE:
                self.m.input_text = self.m.input_text[:-1]
            elif key.key == Key.CHAR:
                self.m.input_text += key.char
            return None

        if self.m.overlay == "confirm_delete":
            if key.char.lower() == "y":
                if self.m.entries:
                    entry = self.m.entries[self.m.selected]
                    sm.delete_key(self.m.raw_data, entry.key)
                    sm.write_storage(self.storage_dir, self.m.raw_data, reason="storage_del")
                    self.m.status_msg = "✓ Deleted"
                    self.on_enter()
                self.m.overlay = "none"
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        if key.key == Key.UP:
            self.m.selected = max(0, self.m.selected - 1)
        elif key.key == Key.DOWN:
            self.m.selected = min(len(self.m.entries) - 1, self.m.selected + 1)
        elif key.key == Key.PAGE_UP:
            self.m.selected = max(0, self.m.selected - 10)
        elif key.key == Key.PAGE_DOWN:
            self.m.selected = min(len(self.m.entries) - 1, self.m.selected + 10)
        elif key.char.lower() == "e" and self.m.entries:
            entry = self.m.entries[self.m.selected]
            self.m.overlay = "edit_value"
            self.m.input_text = entry.value_preview
        elif key.char.lower() == "d" and self.m.entries:
            self.m.overlay = "confirm_delete"
        elif key.key == Key.ESCAPE:
            return "back"

        # Keep scroll in sync with selection
        visible_h = max(1, 20)
        if self.m.selected < self.m.scroll:
            self.m.scroll = self.m.selected
        elif self.m.selected >= self.m.scroll + visible_h:
            self.m.scroll = self.m.selected - visible_h + 1

        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Storage.json Browser")
        main_h = rows - 3

        if not self.m.entries:
            left = ["  storage.json is empty or missing."]
            right: list[str] = []
        else:
            left = W.render_storage_tree(self.m.entries, self.m.selected, self.m.scroll, int(cols * 0.55), main_h)
            entry = self.m.entries[self.m.selected] if self.m.entries else None
            right = W.render_storage_detail(entry, cols - int(cols * 0.55) - 1)

        pane = W.render_split_pane(left, right, cols, 0.55)
        while len(pane) < main_h:
            pane.append(" " * cols)
        lines.extend(pane[:main_h])

        if self.m.overlay == "edit_value":
            _overlay(lines, W.render_text_input("Edit Value", "New value:", self.m.input_text, cols, rows))
        elif self.m.overlay == "confirm_delete":
            entry = self.m.entries[self.m.selected] if self.m.entries else None
            key_name = entry.key if entry else "?"
            _overlay(lines, W.render_confirm_modal("Delete Key", [f"Delete '{key_name}'?"], cols, rows))

        lines.extend(W.render_footer(cols, ["↑↓ Nav", "E Edit", "D Delete", "Esc Back"], self.m.status_msg))
        return lines


# ==============================================================================
# 8. HELP OVERLAY
# ==============================================================================
class HelpOverlay:
    def update(self, key: KeyEvent) -> Optional[str]:
        if key.key in (Key.ESCAPE, Key.ENTER) or key.char == "?":
            return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = W.render_header(cols, "Help & Instructions")
        pane = [
            f"  {W.C.BOLD}Keyboard Shortcuts{W.C.RESET}",
            "  ↑↓ / PgUp PgDn  Navigate",
            "  Enter           Select / Action Menu",
            "  Esc             Back / Cancel",
            "  ?               Toggle Help",
            "  S               Refresh Scan",
            "  B               Create Manual Backup",
            "  R               Run Recovery",
            "  W               Workspace Diagnostics",
            "  T               Storage.json Browser",
            "  /               Search / Filter",
            "  D               Delete item",
            "  N               Rename item",
            "",
            f"  {W.C.BOLD}Merge View{W.C.RESET}",
            "  Space           Toggle conversation selection",
            "  A               Select all",
            "  N               Select none",
        ]
        while len(pane) < rows - 3:
            pane.append(" ")
        lines.extend(pane[:rows-3])
        lines.extend(W.render_footer(cols, ["Esc/Enter Close"]))
        return lines
