# [Unofficial Community Report] Google Antigravity IDE — Zeroed Hub Summaries Cache Hides All Conversations After a Crash (Bug #13)

> **Disclaimer:** This is an **unofficial**, independent, third-party report. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

> **Component:** `language_server.exe` — `jetbox_summaries_store` (Hub summaries persistence)  
> **Platform:** Windows 10/11 verified (mechanism is platform-independent)  
> **Severity:** High (conversation history appears completely lost; data remains intact but invisible)  
> **Reported By:** Elvis33LE  
> **Affected Versions:** Antigravity IDE / language server 2.11.0 (current generation, no `state.vscdb`)

---

## Executive Summary

After an unclean shutdown (crash or power loss), the Agent Manager sidebar shows **"No conversations
yet"** for every project — as if the entire conversation history were gone. The conversation
databases themselves are fully intact: each `<uuid>.db` under
`~/.gemini/antigravity[-ide]/conversations/` still contains all steps, workspace, git, and project
metadata, and `GetConversationMetadata` returns complete data. Only the sidebar cache file
`agyhub_summaries_proto.pb` was zeroed by the crash, and the language server never rebuilds it.
Users experience this as total history loss.

---

## Technical Root Cause Analysis

### 1. The sidebar list comes from a single cache file

The new IDE generation lists conversations from the Hub summaries cache persisted at
`~/.gemini/antigravity[-ide]/agyhub_summaries_proto.pb` (unencrypted Protobuf, written by
`jetbox_summaries_store.Store.persist`). The UI subscribes via the `JetboxSubscribeToSummaries`
RPC; `GetConversationMetadata` reads the trajectory databases directly and works fine.

### 2. The crash leaves the file zeroed (non-atomic write)

After a crash on 2026-09-02 at 13:31 the file contained **675 pure NUL bytes** (observed hexdump:
all zero). The write path truncates/allocates the file before content is flushed, so an unclean
shutdown mid-persist leaves an all-zero file of the intended length. This is the same
non-atomic-flush class as the previously reported index-wipe bugs on `state.vscdb`.

### 3. The server never rebuilds missing entries

Go symbols in `language_server.exe` show the store design:
`Init → Start → runWatcher → scanAndRefresh / handleFileEvent → recomputeAndStore → persist`,
plus `sanitizeSummaryOnStartup`. The refresh path only updates entries that already exist —
embedded log string:

```
Conversation %s has no summary in cache, skipping summary update
```

With an empty/zeroed cache there is nothing to refresh, and no code path repopulates the cache
from the intact trajectory databases. Touching conversation files, deleting the zeroed cache
file, or resetting the projects-migration markers in `antigravity_state.pbtxt` does **not**
trigger a rebuild (all verified on a live installation). Every server start logs a flood of:

```
projects store: project_store_get_file_missing: missing project file:
open C:/Users/<user>/.gemini/config/projects/.json
```

because the runtime resolution of the (missing) summary entries produces empty project ids.

### 4. Evidence summary (live installation, language server 2.11.0)

- `agyhub_summaries_proto.pb`: 675 NUL bytes, mtime = last conversation activity (13:16:55),
  crash log in `~/.gemini/antigravity/crashes/` at 13:31
- `conversations/11df4615-….db`: intact — `trajectory_meta`, 11,638 steps,
  `trajectory_metadata_blob` with workspace, git remote/branch, timestamps, `project_id`
- `language_server.log`: migration ran and reported
  `Found 1 conversations … Skipped 1 already-assigned conversations` (trajectory layer healthy)
- `JetboxSubscribeToSummaries` returned an empty `updates` map before the workaround

---

## Recommended Official Fix (For Google Antigravity Engineering Team)

1. **Atomic persistence** — write the summaries file via temp-file + `os.rename` (or equivalent)
   so a crash can never leave a truncated/zeroed cache behind.
2. **Rebuild on cache miss** — in `scanAndRefresh`/`sanitizeSummaryOnStartup`, when a trajectory
   database exists under `conversations/` but has no summary entry, reconstruct the entry from the
   trajectory's own `trajectory_metadata_blob` (it already contains workspace, git, timestamps,
   cascade id, and `project_id`). The data for self-healing is fully present on disk.
3. Optionally surface cache-integrity problems in the UI instead of rendering an empty sidebar.

---

## Community Workaround (`repair`)

The community tool **Antigravity Database Manager** (unofficial) rebuilds missing summaries by
calling the running language server's `JetboxWriteSummary` RPC (endpoint and CSRF token parsed
from `logs/main.log`), so the server itself persists and pushes the repaired entries to the open
IDE. This restored the affected conversation live during this investigation.
See `src/core/summaries_repair.py` in https://github.com/ag-donald/Antigravity-Database-Manager/pull/10.

---

## Reproducer

1. Use an IDE build of the new generation (no `state.vscdb`) with at least one conversation.
2. Kill the IDE/language server processes while they are running (simulating the unclean
   shutdown), or zero out `~/.gemini/antigravity/agyhub_summaries_proto.pb`.
3. Restart the IDE: the sidebar shows "No conversations yet" for every project, indefinitely.
4. `GetConversationMetadata` for the conversation id still returns full metadata (data intact).
