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
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

from .conversation_store import collect_conversations
from .environment import EnvironmentResolver
from .models import ConversationRecord, SummariesRepairResult

WRITE_ROUTE = "/exa.language_server_pb.LanguageServerService/JetboxWriteSummary"


def _main_log_candidates() -> list[str]:
    """Platform-specific main.log candidates of the Electron shell."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        return [os.path.join(appdata, "Antigravity", "logs", "main.log")]
    if sys.platform.startswith("darwin"):
        return [
            os.path.join(home, "Library", "Application Support", "Antigravity", "logs", "main.log"),
        ]
    return [os.path.join(home, ".config", "Antigravity", "logs", "main.log")]


def find_language_server(log_path: str | None = None) -> tuple[int, str] | None:
    """
    Extracts the running language server's HTTPS port and CSRF token from
    the newest spawn lines in main.log. Returns None when unavailable.
    """
    candidates = [log_path] if log_path else _main_log_candidates()
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        tokens = re.findall(r"--csrf_token (\S+)", text)
        ports = re.findall(r"https://127\.0\.0\.1:(\d+)/", text)
        if tokens and ports:
            return int(ports[-1]), tokens[-1]
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
        modified = record.timestamp_seconds or os.path.getmtime(record.path)
        created = os.path.getctime(record.path)
    except OSError:
        modified = record.timestamp_seconds or 0
        created = modified

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
    """Posts one JetboxWriteSummary call to the running language server."""
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
    except OSError as exc:
        return False, str(exc)


def repair_new_generation(gem_base: str | None = None,
                          on_progress=None) -> SummariesRepairResult:
    """
    Rebuilds missing Hub summaries entries for every live conversation DB.

    Requires a running language server (start the IDE); the server persists
    the repaired entries itself, so no local file is written by this tool.
    """
    def _progress(phase: str, msg: str) -> None:
        if on_progress:
            on_progress(phase, msg)

    endpoint = find_language_server()
    if endpoint is None:
        return SummariesRepairResult(
            success=False,
            error="Language server not reachable — start the Antigravity IDE, "
                  "then re-run repair so the rebuilt summaries can be persisted.",
        )
    port, token = endpoint

    records = []
    if gem_base:
        records = [r for r in collect_conversations(gem_base) if not r.is_backup]
    else:
        for base in EnvironmentResolver.get_gemini_base_paths():
            records.extend(r for r in collect_conversations(base) if not r.is_backup)
    records = [r for r in records if r.cascade_id]

    _progress("discovery", f"Found {len(records)} live conversation(s).")
    _progress("injection", f"Writing summaries via language server on port {port}…")

    errors: list[str] = []
    written = 0
    for record in records:
        ok, err = write_summary(port, token, build_summary_payload(record))
        if ok:
            written += 1
            _progress("injection", f"Rebuilt summary for {record.cascade_id[:8]}…")
        else:
            errors.append(f"{record.cascade_id}: {err}")

    return SummariesRepairResult(
        success=written == len(records) and bool(records),
        conversations_found=len(records),
        summaries_written=written,
        language_server_url=f"https://127.0.0.1:{port}",
        errors=tuple(errors),
        error="; ".join(errors) if errors else None,
    )
