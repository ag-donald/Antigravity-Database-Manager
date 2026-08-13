#!/usr/bin/env python3
"""
Antigravity IDE — Workspace URI Encoding Fix
=============================================

Fixes the known Windows bug where every conversation shows the
"Select where to open the conversation" disambiguation dialog,
even when you are already in the correct workspace.

**Root cause (Bug #12):**
The IDE's backend (jetskiAgent) stores workspace URIs with a raw colon
(``file:///c:/...``), while the frontend expects percent-encoded colons
(``file:///c%3A/...``).  Three strict ``===`` comparisons in the IDE's
JavaScript fail silently, causing the dialog to appear every time.

**What this script does:**

1. Normalizes all workspace URIs in the ``state.vscdb`` Protobuf index
   from ``file:///c:/`` to ``file:///c%3A/`` so existing conversations
   match the frontend format.

2. Patches ``workbench.desktop.main.js`` at three comparison points to
   normalize drive-letter encoding before comparing, so *future*
   conversations also work regardless of how the backend writes them.

3. Updates the SHA-256 checksum in ``product.json`` (base64 format) to
   prevent the "Your Antigravity IDE installation appears to be corrupt"
   toast.

**Usage:**
    python fix_workspace_uri.py          # auto-detect everything
    python fix_workspace_uri.py --db-only   # only fix the database
    python fix_workspace_uri.py --js-only   # only patch the JS

**Re-run after every IDE update/reinstall** — updates replace the JS file.

References:
    https://discuss.ai.google.dev/t/bug-v2-0-1-windows-conversations-still-not-associated-with-workspace/166926
    https://discuss.ai.google.dev/t/bug-fix-conversations-disappear-from-the-sidebar-windows/168613
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Imports from the Agmercium recovery tool (sibling modules)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from src.core.db_scanner import extract_existing_metadata, extract_workspace_uri
from src.core.protobuf import ProtobufEncoder
from src.core.constants import PB_KEY
from src.core.environment import EnvironmentResolver

# ---------------------------------------------------------------------------
# Patch marker — checked before patching to avoid double-application
# ---------------------------------------------------------------------------
PATCH_MARKER = "/* ANTIGRAVITY_URI_FIX_v2 */"


# ===================================================================
# Step 1 — Find the IDE installation
# ===================================================================

def find_ide_installation() -> Path | None:
    """Auto-detect the Antigravity IDE installation directory on Windows."""
    if platform.system() != "Windows":
        return None

    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "Programs" / "Antigravity IDE",
        home / "AppData" / "Local" / "Programs" / "antigravity-ide",
        home / "AppData" / "Local" / "Programs" / "Google Antigravity IDE",
        Path("C:/Program Files/Antigravity IDE"),
        Path("C:/Program Files (x86)/Antigravity IDE"),
    ]

    for candidate in candidates:
        js = candidate / "resources" / "app" / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
        if js.is_file():
            return candidate

    # Brute-force search in AppData\Local\Programs
    programs = home / "AppData" / "Local" / "Programs"
    if programs.is_dir():
        for d in programs.iterdir():
            if d.is_dir() and "antigravity" in d.name.lower():
                js = d / "resources" / "app" / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
                if js.is_file():
                    return d

    return None


# ===================================================================
# Step 2 — Patch workbench.desktop.main.js
# ===================================================================

def patch_workbench_js(ide_dir: Path) -> bool:
    """
    Apply three surgical patches to ``workbench.desktop.main.js``.

    Each patch wraps a strict ``===`` comparison with a normalizer function
    that converts ``file:///X:`` to ``file:///X%3A`` before comparing.
    """
    js_path = ide_dir / "resources" / "app" / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
    if not js_path.is_file():
        print(f"  ERROR: {js_path} not found")
        return False

    # Backup
    backup = js_path.with_suffix(f".js.uri_fix_backup_{int(time.time())}")
    shutil.copy2(js_path, backup)
    print(f"  Backup: {backup.name}")

    content = js_path.read_text(encoding="utf-8")

    NORM = "_aUF"  # short name for minified context
    NORM_DEF = (
        f'var {NORM}=function(s){{return typeof s==="string"'
        f'?s.replace(/file:\\/\\/\\/([a-zA-Z]):/g,"file:///$1%3A"):s}};'
    )

    patches_applied = 0

    # PATCH 1: The dialog comparison — decides whether to show "Select where to open"
    p1_pattern = r"F\[0\]===([a-zA-Z0-9_]+)\.workspaceUris\[0\]"
    m1 = re.search(p1_pattern, content)
    if m1:
        old1 = m1.group(0)
        var_name = m1.group(1)
        new1 = f"{NORM}(F[0])==={NORM}({var_name}.workspaceUris[0])"
        content = content.replace(old1, new1, 1)
        patches_applied += 1
        print(f"  PATCH 1/3: Dialog comparison — applied ({old1} -> {new1})")
    elif f"{NORM}(F[0])" in content:
        patches_applied += 1
        print("  PATCH 1/3: Dialog comparison — already applied")
    else:
        print("  PATCH 1/3: Dialog comparison — not found (may differ in this version)")

    # PATCH 2: Workspace filtering in sidebar / prefix-match helper
    p2_pattern1 = r"n\.workspaces\.map\(r=>r\.workspaceFolderAbsoluteUri\)\.some\(r=>e\.includes\(r\)\)"
    p2_pattern2 = r"function LEo\(t,e\)\{return t===e\|\|t\.startsWith\(e\+\"\/\"\)\}"
    m2_1 = re.search(p2_pattern1, content)
    m2_2 = re.search(p2_pattern2, content)

    if m2_1:
        old2 = m2_1.group(0)
        new2 = f"n.workspaces.map(r=>r.workspaceFolderAbsoluteUri).some(r=>e.some(w=>{NORM}(w)==={NORM}(r)))"
        content = content.replace(old2, new2, 1)
        patches_applied += 1
        print("  PATCH 2/3: Workspace filter — applied")
    elif m2_2:
        old2 = m2_2.group(0)
        new2 = (
            f"function LEo(t,e){{var a={NORM}(t),b={NORM}(e);"
            f"return a===b||a.startsWith(b+\"/\")}}"
        )
        content = content.replace(old2, new2, 1)
        patches_applied += 1
        print("  PATCH 2/3: LEo function — applied")
    elif f"{NORM}(w)==={NORM}(r)" in content:
        patches_applied += 1
        print("  PATCH 2/3: Workspace filter — already applied")
    else:
        print("  PATCH 2/3: LEo function — not found (may differ in this version)")

    # PATCH 3: State sync comparison in the unified-state transformer.
    p3_pattern = r"l\.workspaceFolderAbsoluteUri===n\.toString\(\)"
    m3 = re.search(p3_pattern, content)
    if m3:
        old3 = m3.group(0)
        new3 = f"{NORM}(l.workspaceFolderAbsoluteUri)==={NORM}(n.toString())"
        content = content.replace(old3, new3, 1)
        patches_applied += 1
        print("  PATCH 3/3: State sync comparison — applied")
    elif f"{NORM}(l.workspaceFolderAbsoluteUri)" in content:
        patches_applied += 1
        print("  PATCH 3/3: State sync comparison — already applied")
    else:
        print("  PATCH 3/3: State sync comparison — not found (may differ in this version)")

    if patches_applied == 0:
        print("  WARNING: No patches could be applied. The IDE version may have changed.")
        print("  The minified function/variable names change with each build.")
        return False

    # Prepend the normalizer function definition (must come before usage) if not present
    if PATCH_MARKER not in content:
        content = f";{NORM_DEF}{PATCH_MARKER}\n" + content

    js_path.write_text(content, encoding="utf-8")
    print(f"  {patches_applied}/3 patches applied")
    return True


# ===================================================================
# Step 3 — Update product.json checksum
# ===================================================================

def update_checksum(ide_dir: Path) -> bool:
    """
    Recalculate the SHA-256 of the patched JS file and write it to
    ``product.json`` in **base64** format (matching the IDE's expectation).
    """
    js_path = ide_dir / "resources" / "app" / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
    product_path = ide_dir / "resources" / "app" / "product.json"

    if not product_path.is_file():
        print("  WARNING: product.json not found — skipping checksum.")
        return False

    # SHA-256 of patched file → base64 (no trailing =)
    sha = hashlib.sha256(js_path.read_bytes()).digest()
    b64 = base64.b64encode(sha).decode("ascii").rstrip("=")

    # Backup + update
    backup = product_path.with_suffix(f".json.uri_fix_backup_{int(time.time())}")
    shutil.copy2(product_path, backup)

    with open(product_path, "r", encoding="utf-8") as f:
        product = json.load(f)

    key = "vs/workbench/workbench.desktop.main.js"
    checksums = product.get("checksums", {})
    if key not in checksums:
        print(f"  No checksum entry for {key} — skipping.")
        return True

    checksums[key] = b64
    product["checksums"] = checksums
    with open(product_path, "w", encoding="utf-8") as f:
        json.dump(product, f, indent="\t")

    print(f"  Checksum updated (base64): {b64[:24]}...")
    return True


# ===================================================================
# Step 4 — Normalize Protobuf workspace URIs in state.vscdb
# ===================================================================

def normalize_database_uris(db_path: str) -> int:
    """
    Convert every ``file:///X:/`` workspace URI in the Protobuf
    ``trajectorySummaries`` blob to ``file:///x%3A/``.

    Returns the number of entries that were fixed.
    """
    # Backup
    backup = db_path + f".uri_fix_{int(time.time())}"
    shutil.copy2(db_path, backup)
    print(f"  Backup: {os.path.basename(backup)}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,))
    row = cur.fetchone()
    if not row:
        print("  ERROR: No trajectorySummaries found.")
        conn.close()
        return 0

    raw = base64.b64decode(row[0])
    titles, blobs = extract_existing_metadata(raw)

    raw_count = enc_count = no_count = 0
    for inner in blobs.values():
        ws = extract_workspace_uri(inner)
        if not ws:
            no_count += 1
        elif "%3A" in ws or "%3a" in ws:
            enc_count += 1
        else:
            raw_count += 1

    print(f"  Before: {raw_count} raw-colon, {enc_count} encoded, {no_count} no-workspace")

    # Rebuild all entries with normalized URIs
    new_blob = b""
    fixed = 0

    for uuid, inner in blobs.items():
        ws_uri = extract_workspace_uri(inner)
        title = titles.get(uuid, "Untitled")
        ws_config = None

        if ws_uri:
            normalized = re.sub(
                r"file:///([a-zA-Z]):/",
                lambda m: f"file:///{m.group(1).lower()}%3A/",
                ws_uri,
            )
            if normalized != ws_uri:
                fixed += 1

            ws_config = {
                "uri_encoded": normalized,
                "uri_plain": normalized,  # intentionally use encoded form everywhere
                "corpus": "",
                "git_remote": "",
                "branch": "",
            }

        entry = ProtobufEncoder.build_trajectory_entry(
            conv_uuid=uuid,
            title=title,
            workspace=ws_config,
            create_epoch=int(time.time()),
            modify_epoch=int(time.time()),
            existing_inner_data=inner,
        )
        new_blob += entry

    cur.execute(
        "UPDATE ItemTable SET value = ? WHERE key = ?",
        (base64.b64encode(new_blob).decode("utf-8"), PB_KEY),
    )
    conn.commit()
    conn.close()

    print(f"  Fixed {fixed} entries (raw colon -> percent-encoded)")
    return fixed


# ===================================================================
# Main
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix Antigravity IDE workspace URI encoding mismatch (Bug #12)."
    )
    parser.add_argument("--db-only", action="store_true", help="Only fix the database")
    parser.add_argument("--js-only", action="store_true", help="Only patch the JS")
    parser.add_argument("--ide-path", type=str, help="Manual IDE installation path")
    args = parser.parse_args()

    if platform.system() != "Windows":
        print("This fix is Windows-only (the bug is caused by drive-letter URI encoding).")
        sys.exit(1)

    print("=" * 60)
    print("  Antigravity IDE — Workspace URI Encoding Fix (Bug #12)")
    print("=" * 60)
    print()

    do_js = not args.db_only
    do_db = not args.js_only

    # --- JS patch ---
    if do_js:
        print("[1/3] Finding Antigravity IDE installation...")
        ide_dir = Path(args.ide_path) if args.ide_path else find_ide_installation()
        if ide_dir:
            print(f"  Found: {ide_dir}")
        else:
            print("  Not found. Use --ide-path to specify manually.")
            ide_dir = None
        print()

        if ide_dir:
            print("[2/3] Patching workbench.desktop.main.js...")
            js_ok = patch_workbench_js(ide_dir)
            print()

            if js_ok:
                print("[3/3] Updating product.json checksum...")
                update_checksum(ide_dir)
                print()
        else:
            print("[2/3] Skipped (IDE not found).")
            print("[3/3] Skipped.")
            print()
    else:
        print("[1/3] Skipped (--db-only)")
        print("[2/3] Skipped (--db-only)")
        print("[3/3] Skipped (--db-only)")
        print()

    # --- Database normalization ---
    if do_db:
        print("[4/4] Normalizing workspace URIs in state.vscdb...")
        try:
            db_path = EnvironmentResolver.get_antigravity_db_path()
            print(f"  Database: {db_path}")
            normalize_database_uris(db_path)
        except Exception as e:
            print(f"  ERROR: {e}")
        print()
    else:
        print("[4/4] Skipped (--js-only)")
        print()

    print("=" * 60)
    print("  Done. Close and reopen Antigravity IDE to see the fix.")
    print()
    print("  NOTE: Re-run this script after every IDE update or reinstall,")
    print("  as updates replace the patched JavaScript file.")
    print("=" * 60)


if __name__ == "__main__":
    main()
