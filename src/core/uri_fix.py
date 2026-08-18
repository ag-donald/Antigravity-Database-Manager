"""
Bug #12 fix — Windows drive-letter URI encoding mismatch.

The IDE backend (jetskiAgent) writes workspace URIs with a raw drive-letter
colon (``file:///c:/...``) while the frontend compares against the
percent-encoded form (``file:///c%3A/...``) with strict ``===``, so every
conversation shows the "Select where to open the conversation" dialog on
Windows. This module provides both halves of the workaround:

1. ``patch_workbench_js()`` / ``update_product_checksum()`` — wraps the
   three failing comparisons in ``workbench.desktop.main.js`` with a
   normalizer that canonicalizes drive-letter encoding (including case)
   before comparing, and refreshes the bundle's SHA-256 checksum in
   ``product.json``. This is the load-bearing fix: it covers past and
   future conversations regardless of how either side encodes URIs.

2. ``normalize_database()`` — optionally canonicalizes URIs already stored
   in the ``trajectorySummaries`` Protobuf blob. The rewrite is surgical:
   only URI string values inside Fields 9.1/9.2 and 17.7 are touched
   (Field 17.1 stays plain per docs/schema.proto); titles, git metadata,
   timestamps, and any entry that cannot be strictly parsed are preserved
   byte-for-byte, and nothing is written unless the before/after entry
   sets are identical.

IDE installation discovery covers Windows, macOS, and Linux; the encoding
defect itself only occurs with drive-letter URIs, so on macOS/Linux
databases the normalization is naturally a no-op.

This module is UI-agnostic — no print(), input(), or ANSI codes.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from .constants import PB_KEY
from .models import IdePatchResult, ProductChecksumResult, UriNormalizeResult
from .protobuf import ProtobufEncoder


# ==============================================================================
# CANONICAL URI FORM
# ==============================================================================

# Anchored: these fields hold a single URI, so embedded occurrences are never
# rewritten. Matches raw ':' and both hex cases of the percent-encoded colon.
_DRIVE_URI_RE = re.compile(r"^file:///([A-Za-z])(:|%3[Aa])(?=/|$)")


def canonicalize_drive_uri(uri: str) -> str:
    """
    Normalizes a ``file:///`` URI's Windows drive-letter separator to the
    canonical frontend form: lowercase letter + uppercase-hex ``%3A``
    (``file:///C:/x`` / ``file:///c%3a/x`` -> ``file:///c%3A/x``).

    URIs without a drive letter (macOS/Linux paths) are returned unchanged.
    """
    return _DRIVE_URI_RE.sub(lambda m: f"file:///{m.group(1).lower()}%3A", uri)


# ==============================================================================
# STRICT PROTOBUF WALKING
#
# ProtobufEncoder.decode_varint() is deliberately lenient (recovery paths must
# make progress on damaged data). Rewriting healthy data needs the opposite
# bias: any structural anomaly raises, and the caller preserves the original
# bytes untouched.
# ==============================================================================

class _EntryParseError(Exception):
    """Raised when a Protobuf structure cannot be walked with certainty."""


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result, shift = 0, 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise _EntryParseError("varint exceeds 64 bits")
    raise _EntryParseError("truncated varint")


def _read_tag(data: bytes, pos: int) -> tuple[int, int, int]:
    tag, pos = _read_varint(data, pos)
    field_num, wire_type = tag >> 3, tag & 7
    if field_num == 0:
        raise _EntryParseError("field number 0 is invalid")
    return field_num, wire_type, pos


def _read_len_payload(data: bytes, pos: int) -> tuple[bytes, int]:
    length, pos = _read_varint(data, pos)
    end = pos + length
    if end > len(data):
        raise _EntryParseError("length-delimited field overruns buffer")
    return data[pos:end], end


def _skip_value(data: bytes, pos: int, wire_type: int) -> int:
    if wire_type == 0:
        _, pos = _read_varint(data, pos)
        return pos
    if wire_type == 1:
        if pos + 8 > len(data):
            raise _EntryParseError("truncated 64-bit field")
        return pos + 8
    if wire_type == 5:
        if pos + 4 > len(data):
            raise _EntryParseError("truncated 32-bit field")
        return pos + 4
    if wire_type == 2:
        _, pos = _read_len_payload(data, pos)
        return pos
    raise _EntryParseError(f"unsupported wire type {wire_type}")


# ==============================================================================
# SURGICAL BLOB NORMALIZATION (Step: state.vscdb)
# ==============================================================================

# The encoded-URI fields per docs/schema.proto: WorkspaceInfo.primary_uri /
# secondary_uri (9.1/9.2) and SessionContext.workspace_uri_encoded (17.7).
# Field 17.1 (SessionWorkspace) deliberately holds plain URIs and is never
# rewritten here.
_FIELD9_URI_SUBS = frozenset({1, 2})
_FIELD17_URI_SUBS = frozenset({7})


def _rewrite_uri_strings(message: bytes, uri_fields: frozenset[int]) -> tuple[bytes, bool]:
    """Rewrites the string values of the given sub-field numbers through
    ``canonicalize_drive_uri()``; every other sub-field is copied verbatim."""
    out = bytearray()
    changed = False
    pos = 0
    while pos < len(message):
        start = pos
        field_num, wire_type, pos = _read_tag(message, pos)
        if wire_type == 2:
            payload, pos = _read_len_payload(message, pos)
            if field_num in uri_fields:
                try:
                    text = payload.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise _EntryParseError(f"URI field is not UTF-8: {exc}") from exc
                fixed = canonicalize_drive_uri(text)
                if fixed != text:
                    out += ProtobufEncoder.write_string_field(field_num, fixed)
                    changed = True
                    continue
            out += message[start:pos]
        else:
            pos = _skip_value(message, pos, wire_type)
            out += message[start:pos]
    return bytes(out), changed


def _transform_inner(inner: bytes) -> tuple[bytes, bool]:
    """Rewrites the URI strings inside Fields 9 and 17 of a TrajectoryPayload;
    all other fields (title, counts, timestamps, steps, ...) pass through
    verbatim."""
    out = bytearray()
    changed = False
    pos = 0
    while pos < len(inner):
        start = pos
        field_num, wire_type, pos = _read_tag(inner, pos)
        if wire_type == 2:
            payload, pos = _read_len_payload(inner, pos)
            if field_num == 9:
                new_payload, ch = _rewrite_uri_strings(payload, _FIELD9_URI_SUBS)
            elif field_num == 17:
                new_payload, ch = _rewrite_uri_strings(payload, _FIELD17_URI_SUBS)
            else:
                new_payload, ch = payload, False
            if ch:
                out += ProtobufEncoder.write_bytes_field(field_num, new_payload)
                changed = True
            else:
                out += inner[start:pos]
        else:
            pos = _skip_value(inner, pos, wire_type)
            out += inner[start:pos]
    return bytes(out), changed


def _transform_wrapper(wrapper: bytes) -> tuple[bytes, bool]:
    """Transforms the Base64-encoded inner payload held in the wrapper's
    Field 1; the Base64 is re-encoded only when the inner payload changed."""
    out = bytearray()
    changed = False
    pos = 0
    while pos < len(wrapper):
        start = pos
        field_num, wire_type, pos = _read_tag(wrapper, pos)
        if wire_type == 2:
            payload, pos = _read_len_payload(wrapper, pos)
            if field_num == 1:
                try:
                    inner = base64.b64decode(payload, validate=True)
                except Exception as exc:
                    raise _EntryParseError(f"inner payload is not valid Base64: {exc}") from exc
                new_inner, ch = _transform_inner(inner)
                if ch:
                    out += ProtobufEncoder.write_bytes_field(1, base64.b64encode(new_inner))
                    changed = True
                    continue
            out += wrapper[start:pos]
        else:
            pos = _skip_value(wrapper, pos, wire_type)
            out += wrapper[start:pos]
    return bytes(out), changed


def _transform_entry_fields(entry: bytes) -> tuple[bytes, bool]:
    """Transforms an entry (Field 1: uuid, Field 2: wrapper); the uuid and
    any unrecognized sibling fields are copied verbatim."""
    out = bytearray()
    changed = False
    pos = 0
    while pos < len(entry):
        start = pos
        field_num, wire_type, pos = _read_tag(entry, pos)
        if wire_type == 2:
            payload, pos = _read_len_payload(entry, pos)
            if field_num == 2:
                new_wrapper, ch = _transform_wrapper(payload)
                if ch:
                    out += ProtobufEncoder.write_bytes_field(2, new_wrapper)
                    changed = True
                    continue
            out += entry[start:pos]
        else:
            pos = _skip_value(entry, pos, wire_type)
            out += entry[start:pos]
    return bytes(out), changed


def _transform_entry_payload(payload: bytes) -> tuple[bytes, bool]:
    """Transforms one top-level entry payload, handling the optional extra
    Field 1 wrap that some IDE builds emit (mirrors the detection in
    ``db_scanner.extract_existing_metadata``)."""
    field_num, wire_type, pos = _read_tag(payload, 0)
    if field_num == 1 and wire_type == 2:
        body, end = _read_len_payload(payload, pos)
        if end == len(payload):
            new_body, changed = _transform_entry_fields(body)
            if changed:
                return bytes(ProtobufEncoder.write_bytes_field(1, new_body)), True
            return payload, False
    return _transform_entry_fields(payload)


def normalize_blob(decoded: bytes) -> tuple[bytes, int, int, int]:
    """
    Canonicalizes drive-letter URI encoding across a decoded
    ``trajectorySummaries`` blob.

    Returns:
        tuple: (new_blob, entries_seen, entries_changed, entries_preserved_unparsed).
        Entries that cannot be strictly parsed — and any undecodable trailing
        bytes — are preserved verbatim, never dropped.
    """
    out = bytearray()
    pos = 0
    seen = changed_count = preserved = 0

    while pos < len(decoded):
        start = pos
        try:
            field_num, wire_type, pos = _read_tag(decoded, pos)
            if wire_type != 2:
                pos = _skip_value(decoded, pos, wire_type)
                out += decoded[start:pos]
                continue
            payload, pos = _read_len_payload(decoded, pos)
        except _EntryParseError:
            # Undecodable remainder (e.g. a torn final entry): keep it as-is.
            out += decoded[start:]
            break

        if field_num != 1:
            out += decoded[start:pos]
            continue

        seen += 1
        try:
            new_payload, changed = _transform_entry_payload(payload)
        except _EntryParseError:
            preserved += 1
            out += decoded[start:pos]
            continue

        if changed:
            out += ProtobufEncoder.write_bytes_field(1, new_payload)
            changed_count += 1
        else:
            out += decoded[start:pos]

    return bytes(out), seen, changed_count, preserved


def normalize_database(db_path: str, dry_run: bool = False) -> UriNormalizeResult:
    """
    Canonicalizes the workspace-URI encoding stored in ``state.vscdb``.

    Safety contract:
      - Nothing is written when no entry needs a change (and no backup is
        created either).
      - Before writing, the before/after blobs must parse to identical
        conversation UUID and title sets, or the write is aborted.
      - The backup uses ``db_operations.create_backup(reason="uri_fix")`` so
        it appears in the tool's own backup discovery and restore menus.
    """
    if not os.path.isfile(db_path):
        return UriNormalizeResult(success=False, db_path=db_path,
                                  error=f"Database file not found: {db_path}")

    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,))
        row = cur.fetchone()
        if not row or not row[0]:
            return UriNormalizeResult(success=False, db_path=db_path,
                                      error="No trajectorySummaries index found in this database.")
        raw = base64.b64decode(row[0])
    except Exception as exc:
        if conn is not None:
            conn.close()
        return UriNormalizeResult(success=False, db_path=db_path,
                                  error=f"Could not read the database: {exc}")

    try:
        new_blob, seen, changed, preserved = normalize_blob(raw)

        if changed == 0:
            return UriNormalizeResult(success=True, db_path=db_path, entries_seen=seen,
                                      entries_changed=0, entries_preserved_unparsed=preserved)

        # Identity check: the rewrite must not add, drop, or retitle anything.
        from .db_scanner import extract_existing_metadata
        titles_before, blobs_before = extract_existing_metadata(raw)
        titles_after, blobs_after = extract_existing_metadata(new_blob)
        if set(blobs_before) != set(blobs_after) or titles_before != titles_after:
            return UriNormalizeResult(
                success=False, db_path=db_path, entries_seen=seen,
                entries_preserved_unparsed=preserved,
                error="Safety check failed: the rewritten index does not round-trip "
                      "to the same conversations. No changes were written.",
            )

        if dry_run:
            return UriNormalizeResult(success=True, db_path=db_path, entries_seen=seen,
                                      entries_changed=changed,
                                      entries_preserved_unparsed=preserved)

        from .db_operations import create_backup
        backup_path = create_backup(db_path, reason="uri_fix")

        cur.execute("UPDATE ItemTable SET value = ? WHERE key = ?",
                    (base64.b64encode(new_blob).decode("utf-8"), PB_KEY))
        conn.commit()
        return UriNormalizeResult(success=True, db_path=db_path, entries_seen=seen,
                                  entries_changed=changed,
                                  entries_preserved_unparsed=preserved,
                                  wrote=True, backup_path=backup_path)
    except Exception as exc:
        return UriNormalizeResult(success=False, db_path=db_path,
                                  error=f"Normalization failed: {exc}")
    finally:
        conn.close()


# ==============================================================================
# IDE INSTALLATION DISCOVERY (Windows / macOS / Linux)
# ==============================================================================

# Path of the workbench bundle below an "app root" (the directory that also
# holds product.json): resources/app on Windows and Linux, and
# <name>.app/Contents/Resources/app on macOS.
_JS_RELPATH = Path("out") / "vs" / "workbench" / "workbench.desktop.main.js"

_INSTALL_NAMES = ("Antigravity IDE", "antigravity-ide", "Antigravity",
                  "Google Antigravity IDE")


def _candidate_app_roots() -> list[Path]:
    """Yields known per-platform app-root candidates plus a shallow scan of
    the usual install locations for anything named like Antigravity."""
    home = Path.home()
    roots: list[Path] = []

    def _scan(base: Path, suffix: tuple[str, ...]) -> None:
        try:
            for d in base.iterdir():
                if d.is_dir() and "antigravity" in d.name.lower():
                    roots.append(d.joinpath(*suffix))
        except OSError:
            pass

    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        programs = local / "Programs"
        for name in _INSTALL_NAMES:
            roots.append(programs / name / "resources" / "app")
        for pf in (Path("C:/Program Files"), Path("C:/Program Files (x86)")):
            for name in _INSTALL_NAMES:
                roots.append(pf / name / "resources" / "app")
        _scan(programs, ("resources", "app"))
    elif sys.platform.startswith("darwin"):
        for base in (Path("/Applications"), home / "Applications"):
            for name in _INSTALL_NAMES:
                roots.append(base / f"{name}.app" / "Contents" / "Resources" / "app")
            _scan(base, ("Contents", "Resources", "app"))
    else:  # Linux / BSD
        for base in (Path("/usr/share"), Path("/opt"), home / ".local" / "share"):
            for name in _INSTALL_NAMES:
                roots.append(base / name / "resources" / "app")
            _scan(base, ("resources", "app"))

    deduped: list[Path] = []
    for r in roots:
        if r not in deduped:
            deduped.append(r)
    return deduped


def find_ide_app_root() -> Path | None:
    """Auto-detects the IDE's app root (the directory holding product.json
    and the workbench bundle) on the current platform."""
    for root in _candidate_app_roots():
        if (root / _JS_RELPATH).is_file():
            return root
    return None


def resolve_app_root(explicit_path: str) -> Path | None:
    """Resolves a user-supplied installation path to the app root, accepting
    the install directory, the .app bundle, or the app root itself."""
    p = Path(explicit_path).expanduser()
    for cand in (p, p / "resources" / "app", p / "Contents" / "Resources" / "app"):
        if (cand / _JS_RELPATH).is_file():
            return cand
    return None


# ==============================================================================
# WORKBENCH BUNDLE PATCHING (Step: workbench.desktop.main.js)
# ==============================================================================

_NORM = "_aUF"

# v3 normalizer: anchored to whole-value URIs, canonicalizes both the raw
# colon and either hex case of %3A, and lowercases the drive letter — the
# same canonical form normalize_database() writes.
_NORM_DEF_V3 = (
    'var _aUF=function(s){return typeof s==="string"?'
    's.replace(/^file:\\/\\/\\/([a-zA-Z])(:|%3[aA])/,'
    'function(m,d){return"file:///"+d.toLowerCase()+"%3A"}):s};'
)
PATCH_MARKER = "/* ANTIGRAVITY_URI_FIX_v3 */"

# Exact artifacts written by the original standalone script (PR #7 head),
# upgraded in place when found: the v2 helper neither lowercased the drive
# letter nor handled a lowercase-hex %3a.
_NORM_DEF_V2 = (
    'var _aUF=function(s){return typeof s==="string"'
    '?s.replace(/file:\\/\\/\\/([a-zA-Z]):/g,"file:///$1%3A"):s};'
)
_PATCH_MARKER_V2 = "/* ANTIGRAVITY_URI_FIX_v2 */"

# Each site: (name, [(search_regex, replacement_template)], applied_regex).
# Minified identifiers change per build, hence the capture groups; the
# replacement templates use \g<N> backreferences.
_PATCH_SITES: tuple[tuple[str, tuple[tuple[str, str], ...], str], ...] = (
    (
        "dialog comparison",
        ((r"F\[0\]===([A-Za-z0-9_$]+)\.workspaceUris\[0\]",
          r"_aUF(F[0])===_aUF(\g<1>.workspaceUris[0])"),),
        r"_aUF\(F\[0\]\)===_aUF\([A-Za-z0-9_$]+\.workspaceUris\[0\]\)",
    ),
    (
        "sidebar workspace filter",
        ((r"n\.workspaces\.map\(r=>r\.workspaceFolderAbsoluteUri\)\.some\(r=>e\.includes\(r\)\)",
          r"n.workspaces.map(r=>r.workspaceFolderAbsoluteUri).some(r=>e.some(w=>_aUF(w)===_aUF(r)))"),
         (r'function ([A-Za-z0-9_$]+)\(t,e\)\{return t===e\|\|t\.startsWith\(e\+"/"\)\}',
          r'function \g<1>(t,e){var a=_aUF(t),b=_aUF(e);return a===b||a.startsWith(b+"/")}')),
        r"_aUF\(w\)===_aUF\(r\)|var a=_aUF\(t\),b=_aUF\(e\)",
    ),
    (
        "state sync comparison",
        ((r"l\.workspaceFolderAbsoluteUri===n\.toString\(\)",
          r"_aUF(l.workspaceFolderAbsoluteUri)===_aUF(n.toString())"),),
        r"_aUF\(l\.workspaceFolderAbsoluteUri\)",
    ),
)


def patch_workbench_js(app_root: Path, dry_run: bool = False) -> IdePatchResult:
    """
    Applies the three comparison patches to ``workbench.desktop.main.js``.

    Idempotent: already-patched sites are detected and counted separately;
    the file is backed up and rewritten only when something actually changes
    this run. All file I/O is done in binary mode so line endings pass
    through untouched on every platform.
    """
    js_path = app_root / _JS_RELPATH
    if not js_path.is_file():
        return IdePatchResult(success=False, js_path=str(js_path),
                              error=f"Workbench bundle not found: {js_path}")

    try:
        content = js_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return IdePatchResult(success=False, js_path=str(js_path),
                              error=f"Could not read the workbench bundle: {exc}")

    upgraded = False
    if _NORM_DEF_V2 in content:
        content = content.replace(_NORM_DEF_V2, _NORM_DEF_V3, 1)
        content = content.replace(_PATCH_MARKER_V2, PATCH_MARKER, 1)
        upgraded = True

    applied: list[str] = []
    present: list[str] = []
    missing: list[str] = []

    for name, patterns, applied_re in _PATCH_SITES:
        if re.search(applied_re, content):
            present.append(name)
            continue
        for search, replacement in patterns:
            new_content, count = re.subn(search, replacement, content, count=1)
            if count:
                content = new_content
                applied.append(name)
                break
        else:
            missing.append(name)

    needs_norm_def = (applied or present) and PATCH_MARKER not in content
    if needs_norm_def:
        content = f";{_NORM_DEF_V3}{PATCH_MARKER}\n" + content

    wrote = False
    backup_path = ""
    if applied or upgraded or needs_norm_def:
        if not dry_run:
            backup = js_path.with_name(f"{js_path.name}.agmercium_urifix_{int(time.time())}")
            try:
                shutil.copy2(js_path, backup)
                js_path.write_bytes(content.encode("utf-8"))
            except OSError as exc:
                return IdePatchResult(success=False, js_path=str(js_path),
                                      patches_applied=tuple(applied),
                                      patches_present=tuple(present),
                                      patches_missing=tuple(missing),
                                      error=f"Could not write the patched bundle "
                                            f"(elevated permissions may be required): {exc}")
            backup_path = str(backup)
            wrote = True

    return IdePatchResult(success=True, js_path=str(js_path),
                          patches_applied=tuple(applied),
                          patches_present=tuple(present),
                          patches_missing=tuple(missing),
                          normalizer_upgraded=upgraded,
                          wrote=wrote, backup_path=backup_path)


_CHECKSUM_KEY_RE = re.compile(
    r'("vs/workbench/workbench\.desktop\.main\.js"\s*:\s*")([^"]*)(")'
)


def update_product_checksum(app_root: Path, dry_run: bool = False) -> ProductChecksumResult:
    """
    Refreshes the workbench bundle's integrity checksum in ``product.json``
    (SHA-256, Base64, padding stripped — the format the IDE verifies).

    Only the checksum value is substituted; the rest of the file's bytes and
    formatting are left untouched.
    """
    js_path = app_root / _JS_RELPATH
    product_path = app_root / "product.json"

    if not product_path.is_file():
        return ProductChecksumResult(success=True, updated=False,
                                     note="product.json not found — nothing to update.")

    try:
        digest = hashlib.sha256(js_path.read_bytes()).digest()
        checksum = base64.b64encode(digest).decode("ascii").rstrip("=")
        text = product_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ProductChecksumResult(success=False,
                                     error=f"Could not read product.json or the bundle: {exc}")

    match = _CHECKSUM_KEY_RE.search(text)
    if not match:
        return ProductChecksumResult(success=True, updated=False,
                                     note="No integrity entry for the workbench bundle — "
                                          "nothing to update.")
    if match.group(2) == checksum:
        return ProductChecksumResult(success=True, updated=False,
                                     note="Checksum already up to date.")

    if dry_run:
        return ProductChecksumResult(success=True, updated=True,
                                     note=f"Would update checksum to {checksum[:24]}...")

    new_text = _CHECKSUM_KEY_RE.sub(lambda m: m.group(1) + checksum + m.group(3), text, count=1)
    backup = product_path.with_name(f"{product_path.name}.agmercium_urifix_{int(time.time())}")
    try:
        shutil.copy2(product_path, backup)
        product_path.write_bytes(new_text.encode("utf-8"))
    except OSError as exc:
        return ProductChecksumResult(success=False,
                                     error=f"Could not write product.json "
                                           f"(elevated permissions may be required): {exc}")
    return ProductChecksumResult(success=True, updated=True,
                                 note=f"Checksum updated to {checksum[:24]}...",
                                 backup_path=str(backup))
