"""
Pure, stateless rendering functions for the TUI.

Every function takes data and terminal dimensions, and returns ``list[str]``.
No side effects, no I/O.
"""

from __future__ import annotations

import re

from ..core.constants import APP_NAME, VERSION
from ..core.models import (
    DatabaseSnapshot, MergeDiff, ConversationEntry, HealthReport,
    WorkspaceDiagnostic, StorageEntry,
)

class C:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    CYAN = "\x1b[36m"
    BRIGHT_CYAN = "\x1b[96m"
    GREEN = "\x1b[32m"
    BRIGHT_GREEN = "\x1b[92m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    WHITE = "\x1b[97m"
    BG_CYAN = "\x1b[46m"
    BG_GRAY = "\x1b[100m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

def _vis_len(s: str) -> int:
    return len(_ANSI_RE.sub("", s))

def _bg_pad(s: str, w: int, bg: str) -> str:
    return s + " " * max(0, w - _vis_len(s)) + C.RESET

def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _vis_len(s))

def _trunc(s: str, w: int) -> str:
    if _vis_len(s) > w:
        # Walk character-by-character, skipping ANSI sequences
        visible = 0
        i = 0
        while i < len(s) and visible < w - 1:
            m = _ANSI_RE.match(s, i)
            if m:
                i = m.end()
                continue
            visible += 1
            i += 1
        return s[:i] + "…"
    return s

# ==============================================================================
# BASE LAYOUT
# ==============================================================================

def render_header(cols: int, title: str = "") -> list[str]:
    line1 = _bg_pad(f"{C.BG_CYAN}{C.WHITE}{C.BOLD} ◆ {APP_NAME}  v{VERSION}", cols, C.BG_CYAN)
    line2 = _bg_pad(f"{C.BG_GRAY}{C.WHITE} ┤ {title}" if title else f"{C.BG_GRAY}", cols, C.BG_GRAY)
    return [line1, line2]

def render_footer(cols: int, hints: list[str], status: str = "") -> list[str]:
    hint_str = "  ".join(hints)
    content = f"{C.BG_GRAY}{C.WHITE} {hint_str}"
    if status:
        content += f"  {C.DIM}│  {status}"
    return [_bg_pad(content, cols, C.BG_GRAY)]

def render_split_pane(left: list[str], right: list[str], w: int, left_ratio: float = 0.55) -> list[str]:
    lw = int(w * left_ratio)
    rw = w - lw - 1
    h = max(len(left), len(right))
    lines = []
    for i in range(h):
        l_str = _pad(left[i], lw) if i < len(left) else " " * lw
        r_str = _pad(right[i], rw) if i < len(right) else " " * rw
        lines.append(f"{l_str}{C.DIM}│{C.RESET}{r_str}")
    return lines

# ==============================================================================
# DATA TABLES & PANES
# ==============================================================================

def render_snapshot_table(snapshots: list[DatabaseSnapshot], selected: int, w: int, h: int, scroll: int=0) -> list[str]:
    def fmt_size(b: int) -> str:
        return f"{b / (1024 * 1024):.1f} MB"
    lines = [
        f"{C.DIM}{'─'*w}{C.RESET}", 
        f"{C.BOLD}{C.CYAN}  #  {'Label':<20} {'Size':>9} {'Convs':>5}{C.RESET}", 
        f"{C.DIM}{'─'*w}{C.RESET}"
    ]
    for idx, snap in enumerate(list(snapshots)[scroll:scroll+h-3]):
        real_i = idx + scroll
        lbl = f"* {snap.label}" if snap.is_current else snap.label
        lbl = _trunc(lbl, 20)
        
        if snap.error:
            row = f"{real_i:>3}  {lbl:<20} {fmt_size(snap.size_bytes):>9} {C.RED}{snap.error[:10]}{C.RESET}"
        else:
            row = f"{real_i:>3}  {lbl:<20} {fmt_size(snap.size_bytes):>9} {snap.conversation_count:>5}"
            
        prefix = f"{C.BRIGHT_CYAN}{C.BOLD} ▸ " if real_i == selected else "   "
        fmt = f"{C.BG_CYAN}{C.WHITE}{C.BOLD}" if real_i == selected else C.WHITE
        lines.append(f"{prefix}{fmt}{row}{C.RESET}")
    return lines

def render_health_report(snap: DatabaseSnapshot, report: HealthReport | None, w: int) -> list[str]:
    lines = [
        f"{C.BOLD}Database Summary{C.RESET}", 
        "",
        f"  Path: {snap.path}",
        f"  Size: {snap.size_bytes / (1024*1024):.1f} MB",
        f"  Conversations: {snap.conversation_count}",
        f"  JSON Entries:  {snap.json_entry_count}"
    ]
    if report:
        lines.extend([
            f"  Titled:        {snap.titled_count} ({report.titled_pct:.0f}%)",
            f"  Workspaces:    {snap.workspace_count}",
            f"  Health:        {report.summary}"
        ])
    return lines

def render_conversation_table(convs: list[ConversationEntry], selected: int, w: int, h: int, scroll: int=0) -> list[str]:
    lines = [
        f"{C.DIM}{'─'*w}{C.RESET}", 
        f"{C.BOLD}{C.CYAN}  #  Title{C.RESET}", 
        f"{C.DIM}{'─'*w}{C.RESET}"
    ]
    title_w = w - 8
    for idx, c in enumerate(list(convs)[scroll:scroll+h-3]):
        real_i = idx + scroll
        title = _trunc(c.title, title_w)
        prefix = f"{C.BRIGHT_CYAN}{C.BOLD} ▸ " if real_i == selected else "   "
        fmt = f"{C.BG_CYAN}{C.WHITE}{C.BOLD}" if real_i == selected else C.WHITE
        lines.append(f"{prefix}{fmt}{real_i:>3}  {title}{C.RESET}")
    return lines

def render_conversation_detail(c: ConversationEntry | None, w: int) -> list[str]:
    if not c:
        return ["No conversation selected."]
    return [
        f"{C.BOLD}Conversation Details{C.RESET}", "",
        f"  UUID: {c.uuid}",
        f"  Title: {c.title}",
        f"  Workspace: {c.workspace_uri or 'None'}",
        f"  Timestamps: {'✓ Yes' if c.has_timestamps else '✗ No'}",
        f"  JSON Synced: {'✓ Yes' if c.json_synced else '✗ No'}",
        f"  Stale Flag: {'Yes' if c.is_stale else 'No'}"
    ]

def render_text_viewer(lines_txt: list[str], scroll_y: int, w: int, h: int) -> list[str]:
    visible = list(lines_txt)[scroll_y:scroll_y+h]
    lines = []
    for ln in visible:
        clean = ln.replace("\t", "    ")
        lines.append(_pad(_trunc(clean, w), w))
    return lines

# ==============================================================================
# OVERLAYS & MODALS
# ==============================================================================

def render_overlay_box(title: str, body_lines: list[str], cols: int, rows: int) -> list[str]:
    modal_w = min(80, cols - 4)
    sc = (cols - modal_w) // 2
    pad = " " * sc
    title_text = f" {title} " if title else ""
    title_vis = _vis_len(title_text)
    
    frame = [pad + f"{C.BRIGHT_CYAN}┌──{C.WHITE}{C.BOLD}{title_text}{C.RESET}{C.BRIGHT_CYAN}{'─' * max(0, modal_w - 3 - title_vis)}┐{C.RESET}"]
    for b in body_lines:
        c = f"  {b}"
        frame.append(pad + f"{C.BRIGHT_CYAN}│{C.RESET}{C.WHITE}{c}" + " " * max(0, modal_w - 2 - _vis_len(c)) + f"{C.BRIGHT_CYAN}│{C.RESET}")
    frame.append(pad + f"{C.BRIGHT_CYAN}└{'─' * (modal_w - 2)}┘{C.RESET}")
    return frame

def render_action_menu(title: str, items: list[str], sel: int, cols: int, rows: int) -> list[str]:
    body = []
    for i, item in enumerate(items):
        if i == sel:
            body.append(f"{C.BRIGHT_CYAN}{C.BOLD}▸ {item}{C.RESET}")
        else:
            body.append(f"  {item}")
    body.extend(["", f"{C.DIM}↑↓ Select  Enter Confirm  Esc Cancel{C.RESET}"])
    return render_overlay_box(title, body, cols, rows)

def render_confirm_modal(title: str, message: list[str], cols: int, rows: int) -> list[str]:
    body = message + ["", f"{C.DIM}Y = Yes    N = Cancel{C.RESET}"]
    return render_overlay_box(title, body, cols, rows)

def render_text_input(title: str, prompt: str, value: str, cols: int, rows: int) -> list[str]:
    body = [prompt, f"  {value}█", "", f"{C.DIM}Enter Save    Esc Cancel{C.RESET}"]
    return render_overlay_box(title, body, cols, rows)

# ==============================================================================
# WIZARD WIDGETS
# ==============================================================================

def render_wizard_pipeline(steps: list[str], current: int, statuses: list[str], w: int) -> list[str]:
    """Renders a horizontal step indicator: ●─●─●─○─○ with labels."""
    nodes = []
    for i, step in enumerate(steps):
        if i < current:
            nodes.append(f"{C.BRIGHT_GREEN}●{C.RESET}")
        elif i == current:
            nodes.append(f"{C.BRIGHT_CYAN}{C.BOLD}●{C.RESET}")
        else:
            nodes.append(f"{C.DIM}○{C.RESET}")

    pipe = f" {C.DIM}─{C.RESET} ".join(nodes)
    labels_line = "  ".join([_trunc(s, 14) for s in steps])

    lines = [f"  {pipe}", f"  {C.DIM}{labels_line}{C.RESET}"]
    if current < len(statuses) and statuses[current]:
        lines.append(f"  {C.CYAN}▸ {statuses[current]}{C.RESET}")
    return lines

def render_progress(label: str, current: int, total: int, cols: int) -> list[str]:
    bw = min(40, cols - 24)
    pct = (current / total) if total > 0 else 0.0
    filled = int(bw * pct)
    empty = bw - filled
    bar = f"{C.BRIGHT_GREEN}{'█' * filled}{C.DIM}{'░' * empty}{C.RESET}"
    return [f"    {C.WHITE}{label}: {bar} {pct*100:5.1f}%{C.RESET}"]

# ==============================================================================
# MERGE DIFF TABLE
# ==============================================================================

def render_diff_table(diff: MergeDiff, selected_uuids: set[str], cursor: int, w: int, h: int) -> list[str]:
    """Color-coded diff table with spacebar toggle checkboxes."""
    lines = [
        f"{C.DIM}{'─'*w}{C.RESET}",
        f"{C.BOLD}{C.CYAN}  Source: {diff.source_total} · Target: {diff.target_total} · New: {len(diff.source_only)}{C.RESET}",
        f"{C.DIM}{'─'*w}{C.RESET}",
    ]

    entries: list[tuple[str, str, str]] = []  # (uuid, title, kind)
    for e in diff.source_only_entries:
        entries.append((e.uuid, e.title, "new"))
    for src_e, tgt_e in diff.shared_entries:
        entries.append((src_e.uuid, src_e.title, "shared"))

    for idx, (uid, title, kind) in enumerate(entries[:h-3]):
        check = f"{C.BRIGHT_GREEN}[✓]{C.RESET}" if uid in selected_uuids else f"{C.DIM}[ ]{C.RESET}"
        color = C.GREEN if kind == "new" else C.DIM
        prefix = f"{C.BRIGHT_CYAN}{C.BOLD} ▸ " if idx == cursor else "   "
        label = _trunc(title, w - 16)
        tag = f"{C.GREEN}NEW{C.RESET}" if kind == "new" else f"{C.DIM}SHR{C.RESET}"
        lines.append(f"{prefix}{check} {color}{label}{C.RESET}  {tag}")

    return lines

def render_diff(diff: MergeDiff, cols: int) -> list[str]:
    return [
         f"  Source: {diff.source_total} convs · Target: {diff.target_total} convs",
         f"  {C.GREEN}+ New: {len(diff.source_only)}{C.RESET}",
         f"  {C.CYAN}= Shared: {len(diff.shared)}{C.RESET}",
         f"  {C.YELLOW}- Target only: {len(diff.target_only)}{C.RESET}"
    ]

# ==============================================================================
# WORKSPACE DIAGNOSTICS
# ==============================================================================

def render_workspace_table(diagnostics: list[WorkspaceDiagnostic], selected: int, w: int, h: int) -> list[str]:
    lines = [
        f"{C.DIM}{'─'*w}{C.RESET}",
        f"{C.BOLD}{C.CYAN}  URI / Path{C.RESET}",
        f"{C.DIM}{'─'*w}{C.RESET}",
    ]
    for idx, d in enumerate(diagnostics[:h-3]):
        if d.exists_on_disk and d.is_accessible:
            icon = f"{C.BRIGHT_GREEN}●{C.RESET}"
        elif d.exists_on_disk:
            icon = f"{C.YELLOW}●{C.RESET}"
        else:
            icon = f"{C.RED}●{C.RESET}"

        path_str = _trunc(d.decoded_path, w - 10)
        prefix = f"{C.BRIGHT_CYAN}{C.BOLD} ▸ " if idx == selected else "   "
        fmt = f"{C.BG_CYAN}{C.WHITE}{C.BOLD}" if idx == selected else C.WHITE
        lines.append(f"{prefix}{icon} {fmt}{path_str}{C.RESET}")
    return lines

def render_workspace_detail(diag: WorkspaceDiagnostic | None, w: int) -> list[str]:
    if not diag:
        return ["No workspace selected."]
    status = f"{C.BRIGHT_GREEN}✓ OK{C.RESET}" if diag.exists_on_disk and diag.is_accessible else (
        f"{C.YELLOW}⚠ Read-Only{C.RESET}" if diag.exists_on_disk else f"{C.RED}✗ Missing{C.RESET}"
    )
    lines = [
        f"{C.BOLD}Workspace Detail{C.RESET}", "",
        f"  URI:    {diag.uri}",
        f"  Path:   {diag.decoded_path}",
        f"  Status: {status}",
        f"  Bound:  {len(diag.bound_conversations)} conversation(s)",
    ]
    for uid in diag.bound_conversations[:5]:
        lines.append(f"    {C.DIM}• {uid[:8]}…{C.RESET}")
    if len(diag.bound_conversations) > 5:
        lines.append(f"    {C.DIM}… and {len(diag.bound_conversations) - 5} more{C.RESET}")
    return lines

# ==============================================================================
# STORAGE.JSON TREE
# ==============================================================================

def render_storage_tree(entries: list[StorageEntry], selected: int, scroll: int, w: int, h: int) -> list[str]:
    lines = [
        f"{C.DIM}{'─'*w}{C.RESET}",
        f"{C.BOLD}{C.CYAN}  Key{C.RESET}",
        f"{C.DIM}{'─'*w}{C.RESET}",
    ]
    visible = list(entries)[scroll:scroll + h - 3]
    for idx, e in enumerate(visible):
        real_i = idx + scroll
        depth = e.key.count(".")
        indent = "  " * depth
        short_key = e.key.rsplit(".", 1)[-1] if "." in e.key else e.key
        display = f"{indent}{short_key}"

        type_badge = ""
        if e.value_type == "object":
            type_badge = f" {C.DIM}{e.value_preview}{C.RESET}"
        elif e.value_type == "array":
            type_badge = f" {C.CYAN}{e.value_preview}{C.RESET}"

        display = _trunc(display, w - 20) + type_badge
        prefix = f"{C.BRIGHT_CYAN}{C.BOLD} ▸ " if real_i == selected else "   "
        fmt = f"{C.BG_CYAN}{C.WHITE}{C.BOLD}" if real_i == selected else C.WHITE
        lines.append(f"{prefix}{fmt}{display}{C.RESET}")
    return lines

def render_storage_detail(entry: StorageEntry | None, w: int) -> list[str]:
    if not entry:
        return ["No key selected."]
    return [
        f"{C.BOLD}Storage Key Detail{C.RESET}", "",
        f"  Key:   {entry.key}",
        f"  Type:  {entry.value_type}",
        f"  Value: {entry.value_preview}",
    ]
