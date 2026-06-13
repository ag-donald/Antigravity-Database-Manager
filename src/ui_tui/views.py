"""
MVU screen definitions for the TUI.

Each screen implements:
  - `model`: dataclass holding screen state
  - `update(key)`: mutates state or returns a routing command
  - `view(cols, rows)`: returns rendered frame lines
"""
from __future__ import annotations
import os, time
from dataclasses import dataclass, field
from typing import Optional

from .engine import Key, KeyEvent, clipboard_write
from .theme import Style, STYLES, PALETTE, Icons, BORDER_ROUNDED, _Ansi, Glyphs
from .core import (
    visible_len, truncate, pad, pad_center, styled_line, horizontal_rule, Component,
)
from .components import (
    Header, StatusBar, DataTable, TableColumn, TreeView, TreeNode,
    TextInput, TextViewer, Modal, ConfirmDialog, ActionMenu,
    ProgressBar, Spinner, ToastManager, Tabs, Breadcrumb,
    SearchBar, Badge, SplitPane, ScrollView, WizardPipeline,
    Gauge, BarChart, KeyValueGrid, Separator, NotificationBanner,
    overlay_on,
)
from ..core.constants import VERSION, APP_NAME
from ..core.models import (
    DatabaseSnapshot, MergeDiff, ConversationEntry, HealthReport,
    MergeResult, RecoveryResult, WorkspaceDiagnostic, StorageEntry,
)
from ..core import db_operations as ops
from ..core.db_scanner import scan_all, list_conversations, health_check, analyze_workspaces
from ..core.environment import EnvironmentResolver
from ..core import storage_manager as sm


# ==============================================================================
# SHARED RENDERING HELPERS
# ==============================================================================

def _render_header(cols: int, subtitle: str = "") -> list[str]:
    """
    Render the application header using the Header component.

    UX Best Practice: Consistent header across all views establishes
    brand identity and navigation context.
    """
    header = Header(app_name=APP_NAME, version=VERSION, subtitle=subtitle)
    return header.render(cols, 3)


def _render_footer(cols: int, hints: list[tuple[str, str]], status: str = "",
                   severity: str = "info") -> list[str]:
    """
    Render the status bar using the StatusBar component.

    UX Best Practice: Key hints always visible for discoverability.
    """
    bar = StatusBar(hints=hints, status=status, status_severity=severity)
    return bar.render(cols, 1)


def _render_detail_panel(title: str, rows_data: list[tuple[str, str]],
                         width: int) -> list[str]:
    """
    Render a labeled detail panel (key-value pairs).

    UX Best Practice: Consistent detail panels with aligned labels
    improve scannability of metadata.
    """
    lines: list[str] = [
        STYLES.title.apply(title), ""
    ]
    max_label = max((len(k) for k, _ in rows_data), default=0) + 1
    for key, value in rows_data:
        label = pad(f"  {key}:", max_label + 3)
        lines.append(STYLES.muted.apply(label) + STYLES.body.apply(f" {value}"))
    return lines


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
    status_severity: str = "info"


class HomeView:
    """
    Home Dashboard — primary navigation hub.

    UX Best Practices enforced:
      - Master-detail layout (list on left, details on right)
      - Selected item is immediately highlighted
      - Keyboard shortcuts prominently displayed in footer
      - Status messages with semantic color coding
      - Empty state handling with clear guidance
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.m = HomeModel()

    def on_enter(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.m.snapshots = scan_all(self.db_path)
        if self.m.snapshots:
            self.m.reports[self.m.snapshots[0].path] = health_check(self.m.snapshots[0])

    def set_status(self, msg: str, severity: str = "success") -> None:
        self.m.status_msg = msg
        self.m.status_time = time.time()
        self.m.status_severity = severity

    def update(self, key: KeyEvent) -> Optional[str]:
        # Auto-dismiss status after 5 seconds
        if self.m.status_msg and time.time() - self.m.status_time > 5.0:
            self.m.status_msg = ""

        cur_snap = self.m.snapshots[self.m.selected] if self.m.snapshots else None

        # --- Overlay handlers ---
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
                    self.set_status(f"{Icons.CHECK} Backup created")
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
                self.set_status(
                    f"{Icons.CHECK} Restored!" if res.success else f"{Icons.CROSS} Error",
                    "success" if res.success else "error"
                )
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        elif self.m.overlay == "confirm_delete" and cur_snap:
            if key.char.lower() == "y":
                try:
                    os.remove(cur_snap.path)
                    self.set_status(f"{Icons.CHECK} Deleted")
                except Exception:
                    self.set_status(f"{Icons.CROSS} Error", "error")
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        elif self.m.overlay == "confirm_reset" and cur_snap:
            if key.char.lower() == "y":
                ops.create_backup(cur_snap.path, reason="before_empty")
                ops.create_empty_db(cur_snap.path)
                self.set_status(f"{Icons.CHECK} Database reset safely")
                self.m.overlay = "none"
                self._refresh()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        # --- Base navigation ---
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

        # Shortcut keys
        if key.char.lower() == "s":
            self._refresh()
            self.set_status(f"{Icons.CHECK} Refreshed")
        elif key.char.lower() == "b" and cur_snap:
            ops.create_backup(cur_snap.path, reason="manual")
            self.set_status(f"{Icons.CHECK} Backup created")
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
        lines = _render_header(cols, "Database Manager")
        main_h = rows - 4

        if not self.m.snapshots:
            # Empty state with guidance
            left = [STYLES.muted.apply(pad("  No databases found.", int(cols * 0.55)))]
            right: list[str] = []
        else:
            left = self._render_db_table(int(cols * 0.55), main_h)
            snap = self.m.snapshots[self.m.selected]
            rep = self.m.reports.get(snap.path)
            right = self._render_detail(snap, rep, cols - int(cols * 0.55) - 1)

        pane = SplitPane()
        lw = int(cols * 0.55)
        rw = cols - lw - 1
        # Manual composition since we have pre-rendered lines
        while len(left) < main_h:
            left.append(" " * lw)
        while len(right) < main_h:
            right.append(" " * rw)
        sep = STYLES.dim.apply("│")
        for i in range(main_h):
            l = pad(truncate(left[i] if i < len(left) else "", lw), lw)
            r = pad(truncate(right[i] if i < len(right) else "", rw), rw)
            lines.append(l + sep + r)

        # Overlays
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
                menu = ActionMenu(title=cur_snap.label, items=it, selected=self.m.menu_selected)
                lines = overlay_on(lines, menu.render(cols, rows))
            elif self.m.overlay == "confirm_restore":
                dlg = ConfirmDialog("Restore Backup", [f"Restore {cur_snap.label}?", "A safety backup will be created."])
                lines = overlay_on(lines, dlg.render(cols, rows))
            elif self.m.overlay == "confirm_delete":
                dlg = ConfirmDialog("Delete Backup", [f"Delete {cur_snap.label}?"])
                lines = overlay_on(lines, dlg.render(cols, rows))
            elif self.m.overlay == "confirm_reset":
                dlg = ConfirmDialog("Reset Database", [
                    f"{Icons.WARNING} This will ERASE all data in {cur_snap.label}.",
                    "A backup will be created first.",
                    "Are you sure?"
                ])
                lines = overlay_on(lines, dlg.render(cols, rows))

        lines.extend(_render_footer(
            cols,
            [("↑↓", "Nav"), ("Enter", "Act"), ("W", "Workspaces"), ("T", "Storage"), ("?", "Help"), ("Q", "Quit")],
            self.m.status_msg, self.m.status_severity
        ))
        return lines

    def _render_db_table(self, w: int, h: int) -> list[str]:
        """Render database snapshot table using themed rendering."""
        def fmt_size(b: int) -> str:
            return f"{b / (1024 * 1024):.1f} MB"

        lines: list[str] = [
            STYLES.dim.apply("─" * w),
            STYLES.table_header.apply(pad(f"  #  {'Label':<20} {'Size':>9} {'Convs':>5}", w)),
            STYLES.dim.apply("─" * w)
        ]

        data_h = h - 3
        self._sync_scroll(data_h)

        for idx, snap in enumerate(list(self.m.snapshots)[self.m.scroll:self.m.scroll + data_h]):
            real_i = idx + self.m.scroll
            lbl = f"* {snap.label}" if snap.is_current else snap.label
            lbl = truncate(lbl, 20)

            if snap.error:
                row = f"{real_i:>3}  {lbl:<20} {fmt_size(snap.size_bytes):>9} " + STYLES.error.apply(truncate(snap.error, 10))
            else:
                row = f"{real_i:>3}  {lbl:<20} {fmt_size(snap.size_bytes):>9} {snap.conversation_count:>5}"

            if real_i == self.m.selected:
                prefix = STYLES.cursor.apply(f" {Icons.POINTER} ")
                lines.append(prefix + STYLES.table_sel.apply(pad(row, w - 3)))
            else:
                lines.append("   " + STYLES.body.apply(pad(row, w - 3)))

        return lines

    def _sync_scroll(self, visible_h: int) -> None:
        if self.m.selected < self.m.scroll:
            self.m.scroll = self.m.selected
        elif self.m.selected >= self.m.scroll + visible_h:
            self.m.scroll = self.m.selected - visible_h + 1

    def _render_detail(self, snap: DatabaseSnapshot, report: HealthReport | None,
                       w: int) -> list[str]:
        """Render the health report detail panel."""
        rows_data = [
            ("Path", snap.path),
            ("Size", f"{snap.size_bytes / (1024*1024):.1f} MB"),
            ("Conversations", str(snap.conversation_count)),
            ("JSON Entries", str(snap.json_entry_count)),
        ]
        if report:
            rows_data.extend([
                ("Titled", f"{snap.titled_count} ({report.titled_pct:.0f}%)"),
                ("Workspaces", str(snap.workspace_count)),
                ("Health", report.summary),
            ])
        return _render_detail_panel("Database Summary", rows_data, w)


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
    status_severity: str = "info"


class ConversationBrowserView:
    """
    Conversation Browser — master-detail list with search and actions.

    UX Best Practices enforced:
      - Live search filters results as you type
      - Master-detail layout shows context without navigation
      - Action menu on Enter for discoverable operations
      - Consistent keyboard patterns across all views
    """

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
                    self.m.status_msg = f"{Icons.CHECK} Renamed"
                    self.m.status_severity = "success"
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
                self.m.status_msg = f"{Icons.CHECK} Deleted"
                self.m.status_severity = "success"
                self.m.overlay = "none"
                self.on_enter()
            elif key.char.lower() == "n" or key.key == Key.ESCAPE:
                self.m.overlay = "none"
            return None

        # Base navigation
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
        elif key.char.lower() == "c" and cur_conv:
            if clipboard_write(cur_conv.uuid):
                self.m.status_msg = f"{Icons.CHECK} UUID copied to clipboard"
                self.m.status_severity = "success"
            else:
                self.m.status_msg = f"{Icons.CROSS} Copy failed"
                self.m.status_severity = "error"

        # Keep scroll in sync
        visible_h = max(1, 20)
        if self.m.selected < self.m.scroll:
            self.m.scroll = self.m.selected
        elif self.m.selected >= self.m.scroll + visible_h:
            self.m.scroll = self.m.selected - visible_h + 1

        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = _render_header(cols, f"Browsing {os.path.basename(self.target_db)}")
        main_h = rows - 4

        left = self._render_conv_table(int(cols * 0.55), main_h)
        cur_conv = self.m.filtered[self.m.selected] if self.m.filtered else None
        right = self._render_conv_detail(cur_conv, cols - int(cols * 0.55) - 1)

        lw = int(cols * 0.55)
        rw = cols - lw - 1
        while len(left) < main_h:
            left.append(" " * lw)
        while len(right) < main_h:
            right.append(" " * rw)
        sep = STYLES.dim.apply("│")
        for i in range(main_h):
            l = pad(truncate(left[i], lw), lw)
            r = pad(truncate(right[i], rw), rw)
            lines.append(l + sep + r)

        if cur_conv:
            if self.m.overlay == "action_menu":
                menu = ActionMenu(title="Options", items=["Inspect Raw Payload", "Rename", "Delete"], selected=self.m.menu_selected)
                lines = overlay_on(lines, menu.render(cols, rows))
            elif self.m.overlay == "confirm_delete":
                dlg = ConfirmDialog("Delete", [f"Delete '{cur_conv.title}'?"])
                lines = overlay_on(lines, dlg.render(cols, rows))
            elif self.m.overlay == "rename_input":
                modal = Modal(
                    title="Rename", body_lines=["New title:", f"  {self.m.input_text}{STYLES.cursor.apply('█')}"],
                    hints="Enter Save    Esc Cancel"
                )
                lines = overlay_on(lines, modal.render(cols, rows))

        stat = f"/ Filter: {self.m.search}{STYLES.cursor.apply('█')}" if self.m.is_searching else self.m.status_msg
        sev = "info" if self.m.is_searching else self.m.status_severity
        lines.extend(_render_footer(
            cols,
            [("↑↓", "Nav"), ("Enter", "Act"), ("/", "Search"), ("Esc", "Back")],
            stat, sev
        ))
        return lines

    def _render_conv_table(self, w: int, h: int) -> list[str]:
        lines = [
            STYLES.dim.apply("─" * w),
            STYLES.table_header.apply(pad(f"  #  Title", w)),
            STYLES.dim.apply("─" * w)
        ]
        title_w = w - 8
        data_h = h - 3
        for idx, c in enumerate(list(self.m.filtered)[self.m.scroll:self.m.scroll + data_h]):
            real_i = idx + self.m.scroll
            title = truncate(c.title, title_w)
            if real_i == self.m.selected:
                prefix = STYLES.cursor.apply(f" {Icons.POINTER} ")
                lines.append(prefix + STYLES.table_sel.apply(pad(f"{real_i:>3}  {title}", w - 3)))
            else:
                lines.append("   " + STYLES.body.apply(pad(f"{real_i:>3}  {title}", w - 3)))
        return lines

    def _render_conv_detail(self, c: ConversationEntry | None, w: int) -> list[str]:
        if not c:
            return [STYLES.muted.apply("No conversation selected.")]
        tstamp = f"{Icons.CHECK} Yes" if c.has_timestamps else f"{Icons.CROSS} No"
        jsync = f"{Icons.CHECK} Yes" if c.json_synced else f"{Icons.CROSS} No"
        return _render_detail_panel("Conversation Details", [
            ("UUID", c.uuid),
            ("Title", c.title),
            ("Workspace", c.workspace_uri or "None"),
            ("Timestamps", tstamp),
            ("JSON Synced", jsync),
            ("Stale Flag", "Yes" if c.is_stale else "No"),
        ], w)


# ==============================================================================
# 3. TEXT VIEWER (PAYLOAD INSPECTION)
# ==============================================================================

@dataclass
class DataViewModel:
    payload_lines: list[str] = field(default_factory=list)
    scroll: int = 0
    uuid: str = ""


class ConversationDataView:
    """Raw JSON payload viewer with line numbers and scrolling."""

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
        elif key.key == Key.HOME:
            self.m.scroll = 0
        elif key.key == Key.END:
            self.m.scroll = max(0, len(self.m.payload_lines) - 1)
        elif key.key == Key.ESCAPE:
            return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = _render_header(cols, f"Raw JSON Payload: {self.uuid[:8]}")
        main_h = rows - 3

        viewer = TextViewer(content_lines=self.m.payload_lines, scroll=self.m.scroll)
        textpane = viewer.render(cols, main_h)
        lines.extend(textpane)

        lines.extend(_render_footer(
            cols,
            [("↑↓", "Scroll"), ("PgUp/Dn", "Page"), ("Home/End", "Jump"), ("Esc", "Back")],
            f"Lines: {len(self.m.payload_lines)}"
        ))
        return lines


# ==============================================================================
# 4. RECOVERY WIZARD
# ==============================================================================

RECOVERY_PHASES = ["Backup", "Discovery", "Titles", "Injection", "JSON", "Done"]


@dataclass
class RecoveryModel:
    phase: str = "ready"
    phase_idx: int = 0
    phase_statuses: list[str] = field(default_factory=lambda: [""] * 6)
    res: Optional[RecoveryResult] = None


class RecoveryWizardView:
    """Recovery pipeline wizard with animated progress indicator."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.m = RecoveryModel()

    def _on_progress(self, phase: str, msg: str) -> None:
        phase_map = {"backup": 0, "discovery": 1, "titles": 2, "injection": 3, "json": 4, "done": 5}
        idx = phase_map.get(phase, self.m.phase_idx)
        self.m.phase_idx = idx
        if idx < len(self.m.phase_statuses):
            self.m.phase_statuses[idx] = msg

    def update(self, key: KeyEvent) -> Optional[str]:
        if self.m.phase == "ready":
            if key.key == Key.ENTER:
                self.m.phase = "running"
                self.m.phase_idx = 0
            elif key.key == Key.ESCAPE:
                return "back"
        elif self.m.phase == "running":
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
        lines = _render_header(cols, "Full Recovery Pipeline")
        main_h = rows - 3
        pane: list[str] = []

        # Pipeline indicator using WizardPipeline component
        pane.append("")
        pipeline = WizardPipeline(
            steps=RECOVERY_PHASES,
            current=self.m.phase_idx,
            statuses=self.m.phase_statuses,
        )
        pane.extend(pipeline.render(cols, 3))
        pane.append("")

        if self.m.phase == "ready":
            pane.append(f"  Target: {self.db_path}")
            pane.append("")
            pane.append(STYLES.dim.apply("  This will rebuild ALL conversations from .pb files,"))
            pane.append(STYLES.dim.apply("  resolve titles from preserved metadata or .pb timestamps, and synchronize"))
            pane.append(STYLES.dim.apply("  the JSON index. A full backup is created first."))
            pane.append("")
            pane.append(STYLES.info.apply(f"  {Icons.POINTER} Press Enter to begin."))
        elif self.m.phase == "running":
            spinner = Spinner(label="Running pipeline... (Please wait)")
            pane.extend(spinner.render(cols, 1))
        elif self.m.phase == "done" and self.m.res:
            pane.append(STYLES.success.apply(f"  {Icons.CHECK} Recovery Complete"))
            pane.append("")
            pane.append(f"  Conversations rebuilt: {self.m.res.conversations_rebuilt}")
            pane.append(f"  Workspaces mapped:    {self.m.res.workspaces_mapped}")
            pane.append(f"  Timestamps injected:  {self.m.res.timestamps_injected}")
            pane.append(f"  JSON entries added:   {self.m.res.json_added}")
            pane.append(f"  JSON entries patched:  {self.m.res.json_patched}")
            pane.append(f"  JSON entries deleted:  {self.m.res.json_deleted}")
            if self.m.res.backup_path:
                pane.append(f"  Backup at: {STYLES.dim.apply(self.m.res.backup_path)}")
        elif self.m.phase == "error" and self.m.res:
            pane.append(STYLES.error.apply(f"  {Icons.CROSS} Recovery Failed"))
            pane.append(f"  {self.m.res.error}")
            if self.m.res.backup_path:
                pane.append(f"  Backup preserved at: {STYLES.dim.apply(self.m.res.backup_path)}")

        while len(pane) < main_h:
            pane.append(" ")
        lines.extend(pane[:main_h])

        footer_hints = [("Enter", "Start"), ("Esc", "Back")] if self.m.phase == "ready" else [("Enter/Esc", "Back")]
        lines.extend(_render_footer(cols, footer_hints))
        return lines


# ==============================================================================
# 5. MERGE WIZARD
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
    """Merge wizard with diff preview, cherry-pick, and strategy selection."""

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
        lines = _render_header(cols, "Merge Databases")
        main_h = rows - 3
        pane: list[str] = []

        if self.m.step == "source_select":
            pane.append(STYLES.body.apply("  Enter Source DB Path:"))
            pane.append(f"  {self.m.source_path}{STYLES.cursor.apply('█')}")
            pane.append("")
            pane.append(STYLES.dim.apply("  Paste or type the full path to a backup or other state.vscdb"))

        elif self.m.step == "loading":
            spinner = Spinner(label="Loading diff...")
            pane.extend(spinner.render(cols, 1))

        elif self.m.step == "diff_preview" and self.m.diff:
            pane.extend(self._render_diff_table(cols, main_h - 2))
            pane.append("")
            pane.append(STYLES.dim.apply(f"  Space=Toggle  A=All  N=None  Enter=Confirm"))

        elif self.m.step == "confirm":
            count = len(self.m.selected_uuids)
            pane.append(STYLES.emphasis.apply(f"  Ready to Merge"))
            pane.append(f"  Selected: {count} conversation(s)")
            pane.append("")
            strat_1 = STYLES.cursor.apply(Icons.POINTER) if self.m.strategy == "additive" else " "
            strat_2 = STYLES.cursor.apply(Icons.POINTER) if self.m.strategy == "overwrite" else " "
            pane.append(f"  {strat_1} [1] Additive  — only add missing (safe)")
            pane.append(f"  {strat_2} [2] Overwrite — replace shared entries (destructive)")
            pane.append("")
            pane.append(STYLES.info.apply(f"  {Icons.POINTER} Press Enter to execute merge."))

        elif self.m.step == "done" and self.m.res:
            if self.m.res.success:
                pane.append(STYLES.success.apply(f"  {Icons.CHECK} Merge Complete"))
                pane.append(f"  Added: {self.m.res.added}  Updated: {self.m.res.updated}  Skipped: {self.m.res.skipped}")
            else:
                pane.append(STYLES.error.apply(f"  {Icons.CROSS} Merge Failed"))
                pane.append(f"  {self.m.res.error}")
            if self.m.res.backup_path:
                pane.append(f"  Backup: {STYLES.dim.apply(self.m.res.backup_path)}")

        while len(pane) < main_h:
            pane.append(" ")
        lines.extend(pane[:main_h])
        lines.extend(_render_footer(cols, [("Enter", "Next"), ("Esc", "Back")]))
        return lines

    def _render_diff_table(self, w: int, h: int) -> list[str]:
        """Render the color-coded diff table with checkboxes."""
        diff = self.m.diff
        if not diff:
            return []

        lines = [
            STYLES.dim.apply("─" * w),
            STYLES.table_header.apply(
                pad(f"  Source: {diff.source_total} · Target: {diff.target_total} · New: {len(diff.source_only)}", w)
            ),
            STYLES.dim.apply("─" * w),
        ]

        entries: list[tuple[str, str, str]] = []
        for e in diff.source_only_entries:
            entries.append((e.uuid, e.title, "new"))
        for src_e, tgt_e in diff.shared_entries:
            entries.append((src_e.uuid, src_e.title, "shared"))

        for idx, (uid, title, kind) in enumerate(entries[:h - 3]):
            check = STYLES.success.apply(f"[{Icons.CHECK}]") if uid in self.m.selected_uuids else STYLES.dim.apply("[ ]")
            label = truncate(title, w - 16)
            tag = STYLES.badge_new.apply(" NEW ") if kind == "new" else STYLES.badge_shared.apply(" SHR ")

            if idx == self.m.cursor:
                prefix = STYLES.cursor.apply(f" {Icons.POINTER} ")
                lines.append(f"{prefix}{check} {STYLES.emphasis.apply(label)}  {tag}")
            else:
                lines.append(f"   {check} {label}  {tag}")

        return lines


# ==============================================================================
# 6. WORKSPACE BROWSER VIEW
# ==============================================================================

@dataclass
class WorkspaceModel:
    diagnostics: list[WorkspaceDiagnostic] = field(default_factory=list)
    selected: int = 0


class WorkspaceBrowserView:
    """Workspace diagnostic viewer with health indicators."""

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
        lines = _render_header(cols, "Workspace Diagnostics")
        main_h = rows - 3

        if not self.m.diagnostics:
            left = [STYLES.muted.apply("  No workspaces found.")]
            right: list[str] = []
        else:
            left = self._render_ws_table(int(cols * 0.55), main_h)
            diag = self.m.diagnostics[self.m.selected] if self.m.diagnostics else None
            right = self._render_ws_detail(diag, cols - int(cols * 0.55) - 1)

        lw = int(cols * 0.55)
        rw = cols - lw - 1
        while len(left) < main_h:
            left.append(" " * lw)
        while len(right) < main_h:
            right.append(" " * rw)
        sep = STYLES.dim.apply("│")
        for i in range(main_h):
            l = pad(truncate(left[i], lw), lw)
            r = pad(truncate(right[i], rw), rw)
            lines.append(l + sep + r)

        healthy = sum(1 for d in self.m.diagnostics if d.exists_on_disk and d.is_accessible)
        total = len(self.m.diagnostics)
        lines.extend(_render_footer(
            cols,
            [("↑↓", "Nav"), ("Esc", "Back")],
            f"Healthy: {healthy}/{total}"
        ))
        return lines

    def _render_ws_table(self, w: int, h: int) -> list[str]:
        lines = [
            STYLES.dim.apply("─" * w),
            STYLES.table_header.apply(pad("  URI / Path", w)),
            STYLES.dim.apply("─" * w),
        ]
        for idx, d in enumerate(self.m.diagnostics[:h - 3]):
            if d.exists_on_disk and d.is_accessible:
                icon = STYLES.success.apply(Icons.CIRCLE_FILL)
            elif d.exists_on_disk:
                icon = STYLES.warning.apply(Icons.CIRCLE_FILL)
            else:
                icon = STYLES.error.apply(Icons.CIRCLE_FILL)

            path_str = truncate(d.decoded_path, w - 10)
            if idx == self.m.selected:
                prefix = STYLES.cursor.apply(f" {Icons.POINTER} ")
                lines.append(f"{prefix}{icon} {STYLES.table_sel.apply(pad(path_str, w - 6))}")
            else:
                lines.append(f"   {icon} {STYLES.body.apply(pad(path_str, w - 6))}")
        return lines

    def _render_ws_detail(self, diag: WorkspaceDiagnostic | None, w: int) -> list[str]:
        if not diag:
            return [STYLES.muted.apply("No workspace selected.")]
        if diag.exists_on_disk and diag.is_accessible:
            status = STYLES.success.apply(f"{Icons.CHECK} OK")
        elif diag.exists_on_disk:
            status = STYLES.warning.apply(f"{Icons.WARNING} Read-Only")
        else:
            status = STYLES.error.apply(f"{Icons.CROSS} Missing")

        detail_lines = _render_detail_panel("Workspace Detail", [
            ("URI", diag.uri),
            ("Path", diag.decoded_path),
            ("Status", status),
            ("Bound", f"{len(diag.bound_conversations)} conversation(s)"),
        ], w)
        for uid in diag.bound_conversations[:5]:
            detail_lines.append(STYLES.dim.apply(f"    {Icons.CIRCLE_OPEN} {uid[:8]}…"))
        if len(diag.bound_conversations) > 5:
            detail_lines.append(STYLES.dim.apply(f"    … and {len(diag.bound_conversations) - 5} more"))
        return detail_lines


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
    status_severity: str = "info"


class StorageBrowserView:
    """Storage.json browser with tree display and inline editing."""

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
                    self.m.status_msg = f"{Icons.CHECK} Saved"
                    self.m.status_severity = "success"
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
                    self.m.status_msg = f"{Icons.CHECK} Deleted"
                    self.m.status_severity = "success"
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

        # Keep scroll in sync
        visible_h = max(1, 20)
        if self.m.selected < self.m.scroll:
            self.m.scroll = self.m.selected
        elif self.m.selected >= self.m.scroll + visible_h:
            self.m.scroll = self.m.selected - visible_h + 1

        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = _render_header(cols, "Storage.json Browser")
        main_h = rows - 3

        if not self.m.entries:
            left = [STYLES.muted.apply("  storage.json is empty or missing.")]
            right: list[str] = []
        else:
            left = self._render_tree(int(cols * 0.55), main_h)
            entry = self.m.entries[self.m.selected] if self.m.entries else None
            right = self._render_entry_detail(entry, cols - int(cols * 0.55) - 1)

        lw = int(cols * 0.55)
        rw = cols - lw - 1
        while len(left) < main_h:
            left.append(" " * lw)
        while len(right) < main_h:
            right.append(" " * rw)
        sep = STYLES.dim.apply("│")
        for i in range(main_h):
            l = pad(truncate(left[i], lw), lw)
            r = pad(truncate(right[i], rw), rw)
            lines.append(l + sep + r)

        if self.m.overlay == "edit_value":
            modal = Modal(
                title="Edit Value", body_lines=["New value:", f"  {self.m.input_text}{STYLES.cursor.apply('█')}"],
                hints="Enter Save    Esc Cancel"
            )
            lines = overlay_on(lines, modal.render(cols, rows))
        elif self.m.overlay == "confirm_delete":
            entry = self.m.entries[self.m.selected] if self.m.entries else None
            key_name = entry.key if entry else "?"
            dlg = ConfirmDialog("Delete Key", [f"Delete '{key_name}'?"])
            lines = overlay_on(lines, dlg.render(cols, rows))

        lines.extend(_render_footer(
            cols,
            [("↑↓", "Nav"), ("E", "Edit"), ("D", "Delete"), ("Esc", "Back")],
            self.m.status_msg, self.m.status_severity
        ))
        return lines

    def _render_tree(self, w: int, h: int) -> list[str]:
        lines = [
            STYLES.dim.apply("─" * w),
            STYLES.table_header.apply(pad("  Key", w)),
            STYLES.dim.apply("─" * w),
        ]
        visible = list(self.m.entries)[self.m.scroll:self.m.scroll + h - 3]
        for idx, e in enumerate(visible):
            real_i = idx + self.m.scroll
            depth = e.key.count(".")
            indent = "  " * depth
            short_key = e.key.rsplit(".", 1)[-1] if "." in e.key else e.key
            display = f"{indent}{short_key}"

            type_badge = ""
            if e.value_type == "object":
                type_badge = STYLES.dim.apply(f" {e.value_preview}")
            elif e.value_type == "array":
                type_badge = STYLES.info.apply(f" {e.value_preview}")

            display = truncate(display, w - 20) + type_badge

            if real_i == self.m.selected:
                prefix = STYLES.cursor.apply(f" {Icons.POINTER} ")
                lines.append(f"{prefix}{STYLES.tree_sel.apply(pad(display, w - 3))}")
            else:
                lines.append(f"   {STYLES.tree_leaf.apply(pad(display, w - 3))}")
        return lines

    def _render_entry_detail(self, entry: StorageEntry | None, w: int) -> list[str]:
        if not entry:
            return [STYLES.muted.apply("No key selected.")]
        return _render_detail_panel("Storage Key Detail", [
            ("Key", entry.key),
            ("Type", entry.value_type),
            ("Value", entry.value_preview),
        ], w)


# ==============================================================================
# 8. HELP OVERLAY
# ==============================================================================

class HelpOverlay:
    """
    Help screen with categorized keyboard shortcuts.

    UX Best Practice: Context-appropriate help is always accessible via
    the universal '?' shortcut. Organized by category for scannability.
    """

    def update(self, key: KeyEvent) -> Optional[str]:
        if key.key in (Key.ESCAPE, Key.ENTER) or key.char == "?":
            return "back"
        return None

    def view(self, cols: int, rows: int) -> list[str]:
        lines = _render_header(cols, "Help & Keyboard Shortcuts")
        pane: list[str] = []

        # Navigation section
        pane.append("")
        pane.append(STYLES.title.apply("  Navigation"))
        pane.append(STYLES.dim.apply("  " + "─" * 40))
        shortcuts_nav = [
            ("↑ / ↓", "Navigate items"),
            ("PgUp / PgDn", "Navigate by page"),
            ("Home / End", "Jump to first/last"),
            ("Enter", "Select / Action menu"),
            ("Esc", "Back / Cancel"),
            ("Tab", "Next focus"),
        ]
        for key, desc in shortcuts_nav:
            pane.append(f"  {STYLES.cursor.apply(pad(key, 14))} {desc}")

        pane.append("")
        pane.append(STYLES.title.apply("  Home View"))
        pane.append(STYLES.dim.apply("  " + "─" * 40))
        shortcuts_home = [
            ("S", "Refresh database scan"),
            ("B", "Create manual backup"),
            ("R", "Run full recovery"),
            ("W", "Workspace diagnostics"),
            ("T", "Storage.json browser"),
            ("?", "Toggle this help"),
            ("Q", "Quit application"),
        ]
        for key, desc in shortcuts_home:
            pane.append(f"  {STYLES.cursor.apply(pad(key, 14))} {desc}")

        pane.append("")
        pane.append(STYLES.title.apply("  Browser View"))
        pane.append(STYLES.dim.apply("  " + "─" * 40))
        shortcuts_browser = [
            ("/", "Search / filter"),
            ("D", "Delete item"),
            ("N", "Rename item"),
        ]
        for key, desc in shortcuts_browser:
            pane.append(f"  {STYLES.cursor.apply(pad(key, 14))} {desc}")

        pane.append("")
        pane.append(STYLES.title.apply("  Merge View"))
        pane.append(STYLES.dim.apply("  " + "─" * 40))
        shortcuts_merge = [
            ("Space", "Toggle conversation"),
            ("A", "Select all"),
            ("N", "Select none"),
        ]
        for key, desc in shortcuts_merge:
            pane.append(f"  {STYLES.cursor.apply(pad(key, 14))} {desc}")

        while len(pane) < rows - 3:
            pane.append(" ")
        lines.extend(pane[:rows - 3])
        lines.extend(_render_footer(cols, [("Esc/Enter", "Close")]))
        return lines
