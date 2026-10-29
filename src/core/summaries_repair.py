"""
Repairs the new-generation IDE's conversation summaries cache.

The newest IDE builds list sidebar conversations from the Hub summaries
cache (``agyhub_summaries_proto.pb`` under the gemini base directory).
When a crash zeroes that file, the cache is never rebuilt from the intact
conversation databases: the server's directory watcher only refreshes
entries that already exist ("no summary in cache, skipping summary
update"). This module rebuilds missing entries by calling the running
language server's ``JetboxWriteSummary`` RPC, so the server itself
persists the entries and pushes them to the open IDE. Conversation
databases are never modified.

Only conversations whose cascade id is absent from the cache are written
by default (existing, possibly AI-generated summaries are never replaced
unless ``rewrite_all`` is requested), and the cache file is backed up
before the first write.

Wire details observed on language server 2.11.0:
  - connect-JSON over HTTPS on a random localhost port, authenticated
    with the ``x-codeium-csrf-token`` header
  - port and token are logged in the Electron ``logs/main.log``
    (``--csrf_token <uuid>`` and ``https://127.0.0.1:<port>/``)
  - ``CascadeTrajectorySummary`` JSON fields: summary, stepCount,
    trajectoryId, status ("IDLE"), createdTime, lastModifiedTime
    (RFC 3339); the server discards unknown field names silently
"""

from __future__ import annotations

import datetime
import glob
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Callable, Iterable, Optional

from .conversation_store import SUMMARIES_CACHE, collect_conversations
from .db_operations import create_backup, file_times
from .environment import EnvironmentResolver
from .models import ConversationRecord, SummariesCacheStatus, SummariesRepairResult

WRITE_ROUTE = "/exa.language_server_pb.LanguageServerService/JetboxWriteSummary"

_TOKEN_RE = re.compile(r"--csrf_token[ =](\S+)")
_PORT_RE = re.compile(r"https://127\.0\.0\.1:(\d+)/")
_LOG_TAIL_BYTES = 4 * 1024 * 1024


class LanguageServerUnreachable(Exception):
    """The language server endpoint refused or dropped the connection."""


def summaries_cache_status(gem_base: str, cascade_ids: Iterable[str]) -> SummariesCacheStatus:
    """
    Reports which conversations the summaries cache under ``gem_base``
    already lists. Format-agnostic: cascade ids are UUID strings, so an
    entry is present when the id occurs in the cache bytes. A missing,
    empty, or all-NUL (crash-zeroed) cache lists nothing.
    """
    path = os.path.join(gem_base, SUMMARIES_CACHE)
    ids = [c for c in cascade_ids if c]
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return SummariesCacheStatus(path=path, missing=tuple(ids))
    zeroed = not data.strip(b"\x00")
    present = () if zeroed else tuple(c for c in ids if c.encode("ascii", "ignore") in data)
    return SummariesCacheStatus(
        path=path, exists=True, size_bytes=len(data), zeroed=zeroed,
        present=present, missing=tuple(c for c in ids if c not in present),
    )


def _main_log_candidates() -> list[str]:
    """Electron main.log files of every known profile, newest first
    (``logs/main.log`` and VS Code-style ``logs/<session>/main.log``)."""
    paths: set[str] = set()
    for profile in EnvironmentResolver.get_profile_dirs():
        logs = os.path.join(profile, "logs")
        paths.update(p for p in [os.path.join(logs, "main.log"),
                                 *glob.glob(os.path.join(logs, "*", "main.log"))]
                     if os.path.isfile(p))
    return sorted(paths, key=os.path.getmtime, reverse=True)


def find_language_server(log_path: str | None = None) -> tuple[int, str] | None:
    """
    Extracts the running language server's HTTPS port and CSRF token from
    the newest spawn in main.log: the last ``--csrf_token`` and the first
    localhost port logged after it (falling back to the last port logged).
    Returns None when unavailable.
    """
    candidates = [log_path] if log_path else _main_log_candidates()
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as fh:
                fh.seek(max(0, os.path.getsize(path) - _LOG_TAIL_BYTES))
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        tokens = list(_TOKEN_RE.finditer(text))
        if not tokens:
            continue
        last = tokens[-1]
        port = _PORT_RE.search(text, last.end())
        if port is None:
            ports = _PORT_RE.findall(text)
            if not ports:
                continue
            return int(ports[-1]), last.group(1).strip("\"'")
        return int(port.group(1)), last.group(1).strip("\"'")
    return None


def _rfc3339(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def build_summary_payload(record: ConversationRecord) -> dict:
    """Builds the JetboxWriteSummary JSON payload for one conversation DB."""
    if record.workspace_uris:
        folder = record.workspace_uris[0].rstrip("/").rsplit("/", 1)[-1]
    else:
        folder = "conversation"
    summary_text = f"{folder} conversation ({record.step_count} steps)"

    try:
        created, file_modified = file_times(record.path)
        modified = record.timestamp_seconds or file_modified
    except OSError:
        modified = record.timestamp_seconds or 0
        created = modified
    created = min(created, modified) if modified else created

    return {
        "cascadeId": record.cascade_id,
        "summary": {
            "summary": summary_text,
            "stepCount": str(record.step_count),
            "trajectoryId": record.trajectory_id,
            "status": "IDLE",
            "createdTime": _rfc3339(created),
            "lastModifiedTime": _rfc3339(modified),
        },
    }


def write_summary(port: int, token: str, payload: dict, timeout: int = 10) -> tuple[bool, str]:
    """
    Posts one JetboxWriteSummary call to the running language server.
    Returns ``(ok, error)`` for HTTP-level outcomes; raises
    ``LanguageServerUnreachable`` when the endpoint cannot be reached.
    """
    url = f"https://127.0.0.1:{port}{WRITE_ROUTE}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "x-codeium-csrf-token": token,
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            resp.read()
            return resp.status == 200, ""
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {exc.code}: {body}"
    except OSError as exc:  # URLError, refused, reset, timeout
        raise LanguageServerUnreachable(str(getattr(exc, "reason", exc))) from exc


def repair_new_generation(gem_base: str | None = None,
                          rewrite_all: bool = False,
                          dry_run: bool = False,
                          on_progress: Optional[Callable[[str, str], None]] = None,
                          ) -> SummariesRepairResult:
    """
    Rebuilds the Hub summaries entries missing for live conversation DBs
    (all entries with ``rewrite_all``). ``dry_run`` only reports the plan
    and needs no running IDE.

    A real run requires a running language server (start Antigravity); the
    server persists the repaired entries itself. The cache file is backed
    up before the first write; conversation databases are never touched.
    """
    def _progress(phase: str, msg: str) -> None:
        if on_progress:
            on_progress(phase, msg)

    bases = [gem_base] if gem_base else EnvironmentResolver.get_gemini_base_paths()
    found = 0
    already = 0
    todo: list[ConversationRecord] = []
    caches: list[str] = []
    for base in bases:
        records = [r for r in collect_conversations(base, include_backups=False) if r.cascade_id]
        if not records:
            continue
        status = summaries_cache_status(base, [r.cascade_id for r in records])
        if status.format_unknown and not rewrite_all:
            return SummariesRepairResult(
                success=False, conversations_found=len(records),
                error=f"Summaries cache at {status.path} is not empty but none of the "
                      f"{len(records)} conversation id(s) could be located in it — "
                      "refusing to overwrite. Pass --all to rewrite every summary.",
            )
        found += len(records)
        if rewrite_all:
            todo.extend(records)
        else:
            already += len(status.present)
            todo.extend(r for r in records if r.cascade_id in status.missing)
        if status.exists:
            caches.append(status.path)

    planned = tuple(r.cascade_id for r in todo)
    _progress("discovery", f"Found {found} live conversation(s); "
                           f"{len(todo)} summary/summaries to write.")
    if not found:
        return SummariesRepairResult(
            success=False, error="No new-generation conversation databases found.")
    if not todo:
        return SummariesRepairResult(success=True, conversations_found=found,
                                     already_present=already)
    if dry_run:
        return SummariesRepairResult(success=True, conversations_found=found,
                                     already_present=already, to_write=len(todo),
                                     planned=planned, dry_run=True)

    endpoint = find_language_server()
    if endpoint is None:
        return SummariesRepairResult(
            success=False, conversations_found=found, already_present=already,
            to_write=len(todo), planned=planned,
            error="Language server not reachable — start Antigravity (is it open?), "
                  "then re-run repair so the rebuilt summaries can be persisted.",
        )
    port, token = endpoint
    url = f"https://127.0.0.1:{port}"

    backups: list[str] = []
    for cache in caches:
        try:
            backups.append(create_backup(cache, reason="before_summaries_repair"))
        except OSError as exc:
            return SummariesRepairResult(
                success=False, conversations_found=found, already_present=already,
                to_write=len(todo), planned=planned, language_server_url=url,
                error=f"Backup of {cache} failed — nothing was written: {exc}",
            )

    _progress("injection", f"Writing summaries via language server on port {port}…")
    errors: list[str] = []
    written = 0
    for record in todo:
        try:
            ok, err = write_summary(port, token, build_summary_payload(record))
        except LanguageServerUnreachable as exc:
            errors.append(f"Language server not reachable at 127.0.0.1:{port} ({exc}) — "
                          "main.log may be stale; is Antigravity open?")
            break
        if ok:
            written += 1
            _progress("injection", f"Rebuilt summary for {record.cascade_id[:8]}…")
        else:
            errors.append(f"{record.cascade_id}: {err}")

    return SummariesRepairResult(
        success=written == len(todo),
        conversations_found=found,
        summaries_written=written,
        already_present=already,
        to_write=len(todo),
        planned=planned,
        backup_paths=tuple(backups),
        language_server_url=url,
        errors=tuple(errors),
        error="; ".join(errors) if errors else None,
    )
