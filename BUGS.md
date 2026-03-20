# Antigravity IDE — Known Bugs & Database Manager Solutions

> **This document catalogs every known failure mode** that causes conversation history loss in the Antigravity IDE. Each bug includes its trigger, symptoms, technical root cause, and how this Database Manager solves it.

---

## Bug #1 — IDE Update Index Wipe

The most commonly reported bug. Both internal indices (`ChatSessionStore.index` and `trajectorySummaries`) are silently reset to empty during or immediately after an IDE version update.

| Detail | Description |
|--------|-------------|
| **Trigger** | Updating the IDE to a new version (v1.18.x → v1.19.x, v1.20.x, etc.) |
| **Symptoms** | All conversations vanish from the sidebar immediately after update. `.pb` files remain on disk untouched. |
| **Root Cause** | The IDE's update migration pipeline does not preserve the `state.vscdb` key `chat.ChatSessionStore.index` — it re-initializes to `{"version":1,"entries":{}}`. The Protobuf `trajectorySummaries` blob is also zeroed. |
| **Our Fix** | Full 6-phase recovery pipeline scans `.pb` files, extracts titles from brain artifacts, and rebuilds both indices byte-accurately. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Chat history lost after Antigravity update — ChatSessionStore index reset](https://discuss.ai.google.dev/t/bug-chat-history-lost-after-antigravity-update-chatsessionstore-index-reset-to-empty/125625) | Daichi_Zaha | Google Dev Forum |
| [Conversations Corrupted & Unrecoverable + Export Broken (macOS)](https://discuss.ai.google.dev/t/bug-critical-v1-20-5-conversations-corrupted-unrecoverable-export-broken-macos/130547) | jc-myths | Google Dev Forum |
| [Chat history completely disabled/lost for "scratch" sessions after upgrade](https://discuss.ai.google.dev/t/bug-help-antigravity-1-18-x-1-19-x-chat-history-completely-disabled-lost-for-scratch-sessions-after-upgrading-from-1-16-5/127132) | Red_Tom | Google Dev Forum |
| [Lost conversation history with early update](https://discuss.ai.google.dev/t/i-have-lost-conversation-history-in-the-with-early-update-app/124337) | Bun_Zie | Google Dev Forum |
| [Fix if you lost your session history with the new upgrade](https://discuss.ai.google.dev/t/fix-if-you-lost-your-session-history-with-the-new-upgrade-per-antigravity/127105) | Jimmy_Harrell | Google Dev Forum |

---

## Bug #2 — Power Outage / Unclean Shutdown Corruption

The IDE performs a non-atomic flush of its two indices during shutdown. If the process is interrupted, the indices are written in an inconsistent state.

| Detail | Description |
|--------|-------------|
| **Trigger** | Power outage, SIGKILL, force-quit, OS crash, or any unclean IDE termination |
| **Symptoms** | Some or all conversations disappear. JSON index may be partially written (truncated JSON). Protobuf blob may be empty or contain orphaned entries. |
| **Root Cause** | The IDE writes `ChatSessionStore.index` and `trajectorySummaries` as separate, non-transactional SQLite updates. If the process dies between writes, one or both can be in an inconsistent state. |
| **Our Fix** | Recovery pipeline rebuilds both indices atomically from the source-of-truth `.pb` files. Diagnostic engine detects and repairs partial writes. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Conversation history lost after power outage — v1.20.5](https://discuss.ai.google.dev/t/bug-conversation-history-lost-after-power-outage-v1-20-5/133550) | MishaSER | Google Dev Forum |
| [Critical Regression — Chat Freeze, History Loss (Windows 10)](https://discuss.ai.google.dev/t/critical-regression-in-latest-antigravity-version-chat-freeze-conversation-history-loss-pro-plan-limit-concerns-windows-10/125651) | ANURAJ_RAI | Google Dev Forum |

---

## Bug #3 — Workspace Rebinding / Project Switch Loss

Conversations are scoped to workspace URIs. When a project folder is moved, renamed, or re-opened via a different path, the workspace URI changes and previously-bound conversations become orphaned.

| Detail | Description |
|--------|-------------|
| **Trigger** | Moving project folder, opening via different path, drive letter change (e.g., `H:` vs `h:` on Windows) |
| **Symptoms** | Sidebar shows conversations from a different workspace or shows no conversations. Conversations still exist but are bound to the old workspace URI. |
| **Root Cause** | The `trajectorySummaries` Protobuf stores a `workspace_uri` inside Field 9 of each entry. When the URI changes, the IDE's renderer filters out entries that don't match the current workspace. On Windows, drive letter casing differences (`H:` vs `h:`) create a permanent mismatch. |
| **Our Fix** | `workspace migrate` subcommand rebinds all conversations from an old URI to a new one. Recovery pipeline normalizes drive letters to lowercase. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Missing conversations (wrong workspace display)](https://discuss.ai.google.dev/t/missing-conversations/127818) | jnchacon | Google Dev Forum |
| Multiple threads on r/GoogleAntigravityIDE | Various | Reddit |

---

## Bug #4 — SSH Remote Development Session Loss

Conversations created during SSH remote development sessions behave differently from local sessions and are frequently lost or invisible when switching between local and remote contexts.

| Detail | Description |
|--------|-------------|
| **Trigger** | Starting/stopping SSH remote sessions, switching between local and remote workspaces, remote server reboot |
| **Symptoms** | Conversations created in SSH sessions are invisible in local mode, and vice versa. Some conversations have workspace URIs prefixed with `vscode-remote://` which are unavailable locally. |
| **Root Cause** | The IDE stores remote workspace URIs as `vscode-remote://ssh-remote+host/path/to/project` which may not resolve when working locally. The `state.vscdb` may also be on the remote machine, not synced to local. |
| **Our Fix** | Full scan detects all `.pb` files regardless of workspace binding. `scan` subcommand reports workspace URI mismatches. `workspace migrate` can rebind remote URIs to local equivalents. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Missing conversation in IDE (SSH)](https://discuss.ai.google.dev/t/missing-conversation-in-ide-ssh/130852/4) | Dark2002 | Google Dev Forum |
| SSH remote IPv6 connectivity & session issues | Various | Google Dev Forum |

---

## Bug #5 — Agent Manager UI Load Error Self-Deletion

The Agent Manager chat window "self-deletes" conversations when it encounters a load error, even though the underlying agent and conversation data survive in the workspace.

| Detail | Description |
|--------|-------------|
| **Trigger** | Agent Manager encounters a Protobuf parsing error, schema mismatch, or corrupted field during conversation load |
| **Symptoms** | Conversation tile disappears from the Agent Manager UI. Agent state files remain on disk. No user-facing error message — silent deletion. |
| **Root Cause** | The IDE's Protobuf parser silently discards entries it cannot decode rather than displaying an error. If a single field is malformed (e.g., Field 15 with invalid wire type), the entire entry is dropped from the rendered list. |
| **Our Fix** | Diagnostic engine performs byte-level Protobuf validation to detect ghost bytes, invalid wire types, and field ordering issues. Repair engine autonomously fixes malformed entries. Recovery pipeline re-creates clean Protobuf entries from the `.pb` source data. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Agent Manager chat window "self-deletes" on load error](https://discuss.ai.google.dev/t/bug-agent-manager-chat-window-self-deletes-on-load-error-but-agent-survives-in-workspace/114186) | Shannon_Green | Google Dev Forum |

---

## Bug #6 — Protobuf Field Ordering / Schema Conflict

The IDE's strict `ChatSessionStore` Protobuf parser expects fields in ascending tag number order. If fields are written out of order (e.g., Field 10 before Field 9), the entire entry is silently rejected.

| Detail | Description |
|--------|-------------|
| **Trigger** | Recovery tools or manual database edits that write Protobuf fields in non-canonical order |
| **Symptoms** | Conversations appear recovered in the JSON index but remain invisible in the sidebar. `trajectorySummaries` contains entries that pass basic validation but fail the IDE's strict parser. |
| **Root Cause** | The IDE's native parser does not implement the Protobuf specification's "fields may appear in any order" rule. Instead, it uses a strict ascending-tag parser that rejects out-of-order fields. Our prior recovery version had Field 10 (last_accessed) emitted before Field 9 (workspace). |
| **Our Fix** | Protobuf encoder (`protobuf.py`) recursively sorts all fields by ascending tag number before serialization. Diagnostic engine validates tag ordering. |

---

## Bug #7 — Windows Path Casing Mismatch

On Windows, drive letters in workspace URIs can be uppercase (`H:`) or lowercase (`h:`), creating a string-level mismatch even though the paths resolve to the same location.

| Detail | Description |
|--------|-------------|
| **Trigger** | Different tools or sessions opening the same project with different drive letter casing (e.g., `H:\project` vs `h:\project`) |
| **Symptoms** | History appears for some sessions but not others. `workspace list` shows duplicate entries for the same physical folder. Conversations are split across different workspace bindings. |
| **Root Cause** | The IDE stores workspace URIs as verbatim strings with no normalization. `file:///H:/project` and `file:///h:/project` are treated as completely different workspaces. |
| **Our Fix** | `build_workspace_dict` enforces lowercase drive letters in all generated URIs. Workspace migration consolidates duplicate entries. |

---

## Bug #8 — Long-Context Conversation Truncation

Extended, deep-context conversations (multi-day agentic sessions with hundreds of steps) can exceed internal buffer limits, causing the conversation to become partially or fully unrenderable in the UI.

| Detail | Description |
|--------|-------------|
| **Trigger** | Conversations with 100+ agent steps, large tool outputs, or extended multi-day sessions |
| **Symptoms** | Conversation loads but shows only the first N messages, or fails to load entirely with a blank chat window. The `.pb` file is large (10+ MB) and intact. |
| **Root Cause** | Backend UI rendering cannot process extremely large Protobuf payloads. The sidebar's trajectory summary may also have truncated or zero step counts, causing the IDE to skip the entry. |
| **Our Fix** | Recovery injects accurate step counts from `.pb` file analysis. Health check reports conversation sizes. Diagnostic engine flags entries with suspicious zero-step counts. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| Long-context "truncation glitch" discussions | Various | Reddit, Google Dev Forum |

---

## Bug #9 — Ghost Bytes and Double-Wrapping Corruption

The `trajectorySummaries` Protobuf blob can accumulate structural corruptions: ghost bytes (U+FFFD replacement characters), double-wrapped Field 1 entries, or orphaned padding where the Field 1 tag consumes the entire entry with no payload.

| Detail | Description |
|--------|-------------|
| **Trigger** | Repeated recovery attempts, non-atomic writes during crashes, character encoding mismatches during IDE updates |
| **Symptoms** | Recovery appears to succeed but conversations still don't appear. Database contains entries but the IDE's parser rejects them silently. |
| **Root Cause** | UTF-8/UTF-16 encoding boundaries can inject replacement characters (U+FFFD) into the binary Protobuf blob. Double-wrapping occurs when a previous recovery tool wraps an already-valid Field 1 entry inside another Field 1, creating a nested structure the IDE cannot parse. |
| **Our Fix** | Universal Corruption Diagnostic Engine performs byte-level scanning for ghost bytes, double-wrapping, UUID mismatches, and invalid wire types. Autonomous Repair Engine strips corruptions and rebuilds clean entries. |

---

## Bug #10 — `storage.json` / Protobuf Index Desynchronization

The IDE maintains three parallel data structures — `storage.json`, the JSON index, and the Protobuf blob — that can fall out of sync with each other, causing inconsistent state.

| Detail | Description |
|--------|-------------|
| **Trigger** | Partial writes, concurrent access, IDE crashes mid-operation, or manual database editing |
| **Symptoms** | Conversations appear in the sidebar but load as blank. Or conversations have titles in the sidebar but no workspace binding. Or `storage.json` references conversations that don't exist in the Protobuf index. |
| **Root Cause** | The three data stores are updated independently without a single transaction boundary. A crash between any two writes leaves them out of sync. |
| **Our Fix** | `storage inspect` subcommand reports the state of `storage.json`. Health check cross-validates all three data stores. Recovery pipeline writes all indices atomically from a single source of truth (the `.pb` files). |

---

## Bug #11 — "Scratch" Session History Disabled After Upgrade

Conversations created in scratchpad / non-project contexts are completely inaccessible after upgrading from older IDE versions (e.g., v1.16.5 → v1.18.x+). The UI displays a red "disabled" icon next to the history panel.

| Detail | Description |
|--------|-------------|
| **Trigger** | Upgrading from IDE versions ≤ v1.16.5 to v1.18.x or later |
| **Symptoms** | History panel shows a red "disabled" icon for scratch sessions. No conversations are accessible, even through the Agent Manager. `.pb` files exist on disk with valid data. |
| **Root Cause** | The v1.18.x update changed how workspace-less ("scratch") conversations are indexed. Conversations without a workspace binding are no longer rendered by the new UI. The migration pathway does not backfill workspace data for existing scratch conversations. |
| **Our Fix** | Recovery pipeline uses workspace auto-inference (parsing `file:///` URLs in brain artifacts) to retroactively bind orphaned conversations to the correct workspace. Interactive batch assignment handles unmapped conversations. |

| Community Reports | Author | Source |
|-------------------|--------|--------|
| [Chat history completely disabled/lost for "scratch" sessions](https://discuss.ai.google.dev/t/bug-help-antigravity-1-18-x-1-19-x-chat-history-completely-disabled-lost-for-scratch-sessions-after-upgrading-from-1-16-5/127132) | Red_Tom | Google Dev Forum |

---

## Community Sources Summary

| Platform | Thread Count | Notable Topics |
|----------|-------------|----------------|
| **Google AI Dev Forum** | 10+ verified | Index reset after update, power outage corruption, SSH session loss, Agent Manager self-deletion, scratch session disabled |
| **Reddit** (r/GoogleAntigravityIDE, r/google_antigravity) | 5+ threads | Random history disappearance, workspace re-binding workarounds, version rollback discussions, long-context truncation |
| **GitHub** | 3+ issues | Gemini CLI history loss after tool updates, token limit restarts, gemini-chat-history.bin recovery |
| **YouTube** | 2+ videos | Gemini 3.1 update history wipe walkthrough, Google One support acknowledgment |

---

## Technical Root Cause

All 11 bugs stem from the same fundamental architectural flaw: the IDE's failure to atomically manage its three internal state stores:

1. **`chat.ChatSessionStore.index`** (JSON) — Gets reset to `{"version":1,"entries":{}}` on failure
2. **`antigravityUnifiedStateSync.trajectorySummaries`** (Protobuf) — Loses UUID-to-conversation mappings
3. **`storage.json`** — Workspace binding metadata falls out of sync

The raw `.pb` data files at `~/.gemini/antigravity/conversations/` and brain artifacts at `~/.gemini/antigravity/brain/` are **never affected**. This means the data is fully recoverable — which is exactly what this Database Manager does.
