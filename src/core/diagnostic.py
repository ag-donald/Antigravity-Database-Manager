"""
Universal Protobuf corruption diagnostic engine for Antigravity IDE databases.

Performs byte-level scanning of ``state.vscdb`` to detect known structural
anomalies without modifying the database. UI-agnostic — returns typed results.
"""

from __future__ import annotations

import base64
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from .constants import PB_KEY
from .protobuf import ProtobufEncoder


# ==============================================================================
# CORRUPTION TYPES
# ==============================================================================

GHOST_BYTES = "GHOST_BYTES"            # U+FFFD (ef bf bd) in binary payload
DOUBLE_WRAP = "DOUBLE_WRAP"            # Field1(Field1(Field1(...))) triple nesting
UUID_MISMATCH = "UUID_MISMATCH"        # Field 4 != parent conversation UUID
INVALID_WIRE_F15 = "INVALID_WIRE_F15"  # String wire type on message-typed Field 15
EMPTY_PAYLOAD = "EMPTY_PAYLOAD"        # Base64 wrapper decodes to zero bytes
MALFORMED_ENTRY = "MALFORMED_ENTRY"    # Entry fails basic structural parsing


@dataclass(frozen=True)
class CorruptionFinding:
    """A single corruption detected in one conversation entry."""
    corruption_type: str
    severity: str           # "CRITICAL", "WARNING", "INFO"
    description: str
    byte_offset: int = -1   # Offset within the raw blob, -1 if N/A


@dataclass(frozen=True)
class EntryDiagnostic:
    """Diagnostic results for a single conversation entry."""
    uuid: str
    title: str
    findings: list[CorruptionFinding] = field(default_factory=list)

    @property
    def is_corrupt(self) -> bool:
        return any(f.severity == "CRITICAL" for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == "WARNING" for f in self.findings)


@dataclass(frozen=True)
class DiagnosticReport:
    """Complete diagnostic report for a database."""
    db_path: str
    total_entries: int
    corrupt_entries: int
    warning_entries: int
    clean_entries: int
    entry_diagnostics: list[EntryDiagnostic] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def is_healthy(self) -> bool:
        return self.corrupt_entries == 0 and self.warning_entries == 0


# ==============================================================================
# BYTE-LEVEL SCANNERS
# ==============================================================================

def _scan_ghost_bytes(data: bytes) -> list[CorruptionFinding]:
    """Scan for U+FFFD replacement character (ef bf bd) in raw protobuf binary."""
    findings: list[CorruptionFinding] = []
    search = b"\xef\xbf\xbd"
    pos = 0
    while True:
        idx = data.find(search, pos)
        if idx == -1:
            break
        findings.append(CorruptionFinding(
            corruption_type=GHOST_BYTES,
            severity="CRITICAL",
            description=f"UTF-8 replacement character (U+FFFD) at byte offset {idx}",
            byte_offset=idx,
        ))
        pos = idx + 3
    return findings


def _scan_double_wrap(raw_entry: bytes) -> list[CorruptionFinding]:
    """Detect triple Field 1 nesting indicating the double-wrap bug."""
    findings: list[CorruptionFinding] = []
    try:
        # Level 1: outer should be Field 1
        tag, pos = ProtobufEncoder.decode_varint(raw_entry, 0)
        if (tag >> 3) != 1 or (tag & 7) != 2:
            return findings
        length, pos = ProtobufEncoder.decode_varint(raw_entry, pos)
        inner1 = raw_entry[pos:pos + length]

        # Level 2: check if this is ALSO a single Field 1
        tag2, pos2 = ProtobufEncoder.decode_varint(inner1, 0)
        if (tag2 >> 3) != 1 or (tag2 & 7) != 2:
            return findings  # Normal — this is the TrajectorySummary fields
        length2, pos2 = ProtobufEncoder.decode_varint(inner1, pos2)

        # If level 2 consumes the entire inner1, it's a wrap layer
        if pos2 + length2 == len(inner1):
            findings.append(CorruptionFinding(
                corruption_type=DOUBLE_WRAP,
                severity="CRITICAL",
                description="Entry has an extra Field 1 nesting layer (double-wrap bug)",
            ))
    except Exception:
        pass
    return findings


def _scan_uuid_mismatch(parent_uuid: str, inner_blob: bytes) -> list[CorruptionFinding]:
    """Verify that Field 4 inside the TrajectoryPayload matches the parent UUID."""
    findings: list[CorruptionFinding] = []
    try:
        pos = 0
        while pos < len(inner_blob):
            tag, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
            fn, wt = tag >> 3, tag & 7
            if wt == 2:
                length, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
                content = inner_blob[pos:pos + length]
                pos += length
                if fn == 4:
                    try:
                        field4_uuid = content.decode('utf-8', errors='strict')
                        if field4_uuid != parent_uuid:
                            findings.append(CorruptionFinding(
                                corruption_type=UUID_MISMATCH,
                                severity="CRITICAL",
                                description=(
                                    f"Field 4 UUID '{field4_uuid[:12]}...' "
                                    f"does not match parent '{parent_uuid[:12]}...'"
                                ),
                            ))
                    except UnicodeDecodeError:
                        findings.append(CorruptionFinding(
                            corruption_type=UUID_MISMATCH,
                            severity="CRITICAL",
                            description="Field 4 contains non-UTF-8 bytes",
                        ))
                    return findings  # Only one F4 per payload
            elif wt == 0:
                _, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
            elif wt == 1:
                pos += 8
            elif wt == 5:
                pos += 4
            else:
                break
    except Exception:
        pass
    return findings


def _scan_invalid_f15(inner_blob: bytes) -> list[CorruptionFinding]:
    """Detect empty string emission for Field 15 (should be a message or absent)."""
    findings: list[CorruptionFinding] = []
    try:
        pos = 0
        while pos < len(inner_blob):
            tag, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
            fn, wt = tag >> 3, tag & 7
            if wt == 2:
                length, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
                if fn == 15 and length == 0:
                    findings.append(CorruptionFinding(
                        corruption_type=INVALID_WIRE_F15,
                        severity="WARNING",
                        description="Field 15 emitted as empty LEN-delimited (should be omitted or valid TimestampWrapper)",
                    ))
                pos += length
            elif wt == 0:
                _, pos = ProtobufEncoder.decode_varint(inner_blob, pos)
            elif wt == 1:
                pos += 8
            elif wt == 5:
                pos += 4
            else:
                break
    except Exception:
        pass
    return findings


# ==============================================================================
# MAIN DIAGNOSTIC FUNCTION
# ==============================================================================

def diagnose_database(db_path: str) -> DiagnosticReport:
    """
    Performs a comprehensive byte-level diagnostic scan on a state.vscdb file.

    Detects:
      - Ghost bytes (U+FFFD injection from errors='replace')
      - Double-wrapping (extra Field 1 nesting)
      - UUID mismatches (Field 4 != parent UUID)
      - Invalid wire types on Field 15
      - Empty/malformed payloads

    Returns a DiagnosticReport without modifying the database.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key = ?", (PB_KEY,))
        row = cur.fetchone()
        conn.close()

        if not row or not row[0]:
            return DiagnosticReport(
                db_path=db_path, total_entries=0, corrupt_entries=0,
                warning_entries=0, clean_entries=0,
                error="No trajectorySummaries key found in database",
            )

        decoded = base64.b64decode(row[0])
    except Exception as exc:
        return DiagnosticReport(
            db_path=db_path, total_entries=0, corrupt_entries=0,
            warning_entries=0, clean_entries=0, error=str(exc),
        )

    # Parse each entry from the concatenated protobuf blob
    entry_diagnostics: list[EntryDiagnostic] = []
    pos = 0

    while pos < len(decoded):
        try:
            tag, pos = ProtobufEncoder.decode_varint(decoded, pos)
        except Exception:
            break
        wire_type = tag & 7
        if wire_type != 2:
            break

        length, pos = ProtobufEncoder.decode_varint(decoded, pos)
        raw_entry = decoded[pos:pos + length]
        pos += length

        # Check for double-wrapping at the raw entry level
        wrap_findings = _scan_double_wrap(raw_entry)

        # Unwrap the entry (handle both single and double-wrapped)
        entry_data = raw_entry
        try:
            t, ep = ProtobufEncoder.decode_varint(entry_data, 0)
            if (t >> 3) == 1 and (t & 7) == 2:
                l, ep = ProtobufEncoder.decode_varint(entry_data, ep)
                candidate = entry_data[ep:ep + l]
                # Check if this is a wrapping layer (single Field 1 consuming everything)
                if ep + l == len(entry_data):
                    entry_data = candidate
        except Exception:
            pass

        # Extract UUID and base64 payload
        uid = ""
        inner_blob = b""
        title = "Unknown"
        ep = 0
        while ep < len(entry_data):
            try:
                t, ep = ProtobufEncoder.decode_varint(entry_data, ep)
            except Exception:
                break
            fn, wt = t >> 3, t & 7
            if wt == 2:
                l, ep = ProtobufEncoder.decode_varint(entry_data, ep)
                content = entry_data[ep:ep + l]
                ep += l
                if fn == 1:
                    try:
                        uid = content.decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        uid = f"corrupted-{len(entry_diagnostics)}"
                elif fn == 2:
                    # Extract base64 from wrapper
                    try:
                        sp = 0
                        _, sp = ProtobufEncoder.decode_varint(content, sp)
                        sl, sp = ProtobufEncoder.decode_varint(content, sp)
                        b64_str = content[sp:sp + sl].decode('utf-8', errors='strict')
                        inner_blob = base64.b64decode(b64_str)

                        # Extract title from Field 1 of inner blob
                        ip = 0
                        _, ip = ProtobufEncoder.decode_varint(inner_blob, ip)
                        il, ip = ProtobufEncoder.decode_varint(inner_blob, ip)
                        title = inner_blob[ip:ip + il].decode('utf-8', errors='strict')
                    except Exception:
                        pass
            elif wt == 0:
                _, ep = ProtobufEncoder.decode_varint(entry_data, ep)
            elif wt == 1:
                ep += 8
            elif wt == 5:
                ep += 4
            else:
                break

        # Run all scanners
        findings: list[CorruptionFinding] = list(wrap_findings)

        if inner_blob:
            findings.extend(_scan_ghost_bytes(inner_blob))
            findings.extend(_scan_uuid_mismatch(uid, inner_blob))
            findings.extend(_scan_invalid_f15(inner_blob))
        else:
            findings.append(CorruptionFinding(
                corruption_type=EMPTY_PAYLOAD,
                severity="WARNING",
                description="Inner payload is empty or could not be decoded",
            ))

        entry_diagnostics.append(EntryDiagnostic(
            uuid=uid or f"unknown-{len(entry_diagnostics)}",
            title=title,
            findings=findings,
        ))

    corrupt = sum(1 for e in entry_diagnostics if e.is_corrupt)
    warning = sum(1 for e in entry_diagnostics if e.has_warnings and not e.is_corrupt)
    clean = len(entry_diagnostics) - corrupt - warning

    return DiagnosticReport(
        db_path=db_path,
        total_entries=len(entry_diagnostics),
        corrupt_entries=corrupt,
        warning_entries=warning,
        clean_entries=clean,
        entry_diagnostics=entry_diagnostics,
    )
