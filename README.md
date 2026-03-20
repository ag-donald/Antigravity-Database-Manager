# Antigravity IDE — Database Management Hub

<p align="center">
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager/blob/main/LICENCE.md"><img src="https://img.shields.io/badge/License-Unlicense-blue.svg" alt="License: Unlicense"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager"><img src="https://img.shields.io/badge/Open%20Source-100%25-green.svg" alt="Open Source: 100%"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager"><img src="https://img.shields.io/badge/Free-Forever-success.svg" alt="Free Forever"></a>
</p>

<p align="center">
  <strong>An official, open-source database manager and recovery tool for the Google Antigravity IDE.</strong>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> •
  <a href="#the-bug">The Bug</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#compatibility">Compatibility</a> •
  <a href="#faq">FAQ</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

---

## The Bug(s)

Google Antigravity IDE (a heavily modified VS Code fork powering agent-first AI development) suffers from **multiple related bugs** that cause conversation history to disappear from the UI sidebar. The underlying `.pb` conversation data files remain **fully intact** on disk at `~/.gemini/antigravity/conversations/`, but the IDE's internal SQLite database (`state.vscdb`) loses its UI index mappings — specifically the `ChatSessionStore.index` (JSON) and `trajectorySummaries` (Protobuf) — causing the sidebar to display zero history.

**This tool rebuilds those internal indices from your intact `.pb` files, restoring your full conversation history.**

Below is a comprehensive catalog of every known failure mode, the technical root cause, and how this Database Manager solves each one.

---

### 🐛 Bug #1 — IDE Update Index Wipe

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

### 🐛 Bug #2 — Power Outage / Unclean Shutdown Corruption

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

### 🐛 Bug #3 — Workspace Rebinding / Project Switch Loss

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

### 🐛 Bug #4 — SSH Remote Development Session Loss

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

### 🐛 Bug #5 — Agent Manager UI Load Error Self-Deletion

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

### 🐛 Bug #6 — Protobuf Field Ordering / Schema Conflict

The IDE's strict `ChatSessionStore` Protobuf parser expects fields in ascending tag number order. If fields are written out of order (e.g., Field 10 before Field 9), the entire entry is silently rejected.

| Detail | Description |
|--------|-------------|
| **Trigger** | Recovery tools or manual database edits that write Protobuf fields in non-canonical order |
| **Symptoms** | Conversations appear recovered in the JSON index but remain invisible in the sidebar. `trajectorySummaries` contains entries that pass basic validation but fail the IDE's strict parser. |
| **Root Cause** | The IDE's native parser does not implement the Protobuf specification's "fields may appear in any order" rule. Instead, it uses a strict ascending-tag parser that rejects out-of-order fields. Our prior recovery version had Field 10 (last_accessed) emitted before Field 9 (workspace). |
| **Our Fix** | Protobuf encoder (`protobuf.py`) recursively sorts all fields by ascending tag number before serialization. Diagnostic engine validates tag ordering. |

---

### 🐛 Bug #7 — Windows Path Casing Mismatch

On Windows, drive letters in workspace URIs can be uppercase (`H:`) or lowercase (`h:`), creating a string-level mismatch even though the paths resolve to the same location.

| Detail | Description |
|--------|-------------|
| **Trigger** | Different tools or sessions opening the same project with different drive letter casing (e.g., `H:\project` vs `h:\project`) |
| **Symptoms** | History appears for some sessions but not others. `workspace list` shows duplicate entries for the same physical folder. Conversations are split across different workspace bindings. |
| **Root Cause** | The IDE stores workspace URIs as verbatim strings with no normalization. `file:///H:/project` and `file:///h:/project` are treated as completely different workspaces. |
| **Our Fix** | `build_workspace_dict` enforces lowercase drive letters in all generated URIs. Workspace migration consolidates duplicate entries. |

---

### 🐛 Bug #8 — Long-Context Conversation Truncation

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

### 🐛 Bug #9 — Ghost Bytes and Double-Wrapping Corruption

The `trajectorySummaries` Protobuf blob can accumulate structural corruptions: ghost bytes (U+FFFD replacement characters), double-wrapped Field 1 entries, or orphaned padding where the Field 1 tag consumes the entire entry with no payload.

| Detail | Description |
|--------|-------------|
| **Trigger** | Repeated recovery attempts, non-atomic writes during crashes, character encoding mismatches during IDE updates |
| **Symptoms** | Recovery appears to succeed but conversations still don't appear. Database contains entries but the IDE's parser rejects them silently. |
| **Root Cause** | UTF-8/UTF-16 encoding boundaries can inject replacement characters (U+FFFD) into the binary Protobuf blob. Double-wrapping occurs when a previous recovery tool wraps an already-valid Field 1 entry inside another Field 1, creating a nested structure the IDE cannot parse. |
| **Our Fix** | Universal Corruption Diagnostic Engine performs byte-level scanning for ghost bytes, double-wrapping, UUID mismatches, and invalid wire types. Autonomous Repair Engine strips corruptions and rebuilds clean entries. |

---

### 🐛 Bug #10 — `storage.json` / Protobuf Index Desynchronization

The IDE maintains three parallel data structures — `storage.json`, the JSON index, and the Protobuf blob — that can fall out of sync with each other, causing inconsistent state.

| Detail | Description |
|--------|-------------|
| **Trigger** | Partial writes, concurrent access, IDE crashes mid-operation, or manual database editing |
| **Symptoms** | Conversations appear in the sidebar but load as blank. Or conversations have titles in the sidebar but no workspace binding. Or `storage.json` references conversations that don't exist in the Protobuf index. |
| **Root Cause** | The three data stores are updated independently without a single transaction boundary. A crash between any two writes leaves them out of sync. |
| **Our Fix** | `storage inspect` subcommand reports the state of `storage.json`. Health check cross-validates all three data stores. Recovery pipeline writes all indices atomically from a single source of truth (the `.pb` files). |

---

### 🐛 Bug #11 — "Scratch" Session History Disabled After Upgrade

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

### Community Sources Summary

| Platform | Thread Count | Notable Topics |
|----------|-------------|----------------|
| **Google AI Dev Forum** | 10+ verified | Index reset after update, power outage corruption, SSH session loss, Agent Manager self-deletion, scratch session disabled |
| **Reddit** (r/GoogleAntigravityIDE, r/google_antigravity) | 5+ threads | Random history disappearance, workspace re-binding workarounds, version rollback discussions, long-context truncation |
| **GitHub** | 3+ issues | Gemini CLI history loss after tool updates, token limit restarts, gemini-chat-history.bin recovery |
| **YouTube** | 2+ videos | Gemini 3.1 update history wipe walkthrough, Google One support acknowledgment |

### Technical Root Cause

All 11 bugs stem from the same fundamental architectural flaw: the IDE's failure to atomically manage its three internal state stores:

1. **`chat.ChatSessionStore.index`** (JSON) — Gets reset to `{"version":1,"entries":{}}` on failure
2. **`antigravityUnifiedStateSync.trajectorySummaries`** (Protobuf) — Loses UUID-to-conversation mappings
3. **`storage.json`** — Workspace binding metadata falls out of sync

The raw `.pb` data files at `~/.gemini/antigravity/conversations/` and brain artifacts at `~/.gemini/antigravity/brain/` are **never affected**. This means the data is fully recoverable — which is exactly what this tool does.

---

## Quickstart

### Prerequisites

- **Python 3.10+** (ships with most operating systems)
- **No external dependencies** — standard library only

### Steps

```bash
# 1. Close Antigravity IDE completely (mandatory!)

# 2. Run the recovery script
python antigravity_database_manager.py

# 3. Follow the interactive prompts

# 4. Reopen Antigravity IDE — your history is back!
```

> **⚠️ Important:** The IDE **must** be fully closed before running this tool. If the IDE is running, it will overwrite the patched database when it shuts down.

---

## How It Works

The Antigravity IDE stores conversation history in two parallel indices inside its SQLite database (`state.vscdb`):

| Index | Format | Key |
|-------|--------|-----|
| **Trajectory Summaries** | Base64-encoded Protobuf | `antigravityUnifiedStateSync.trajectorySummaries` |
| **Session Store** | JSON | `chat.ChatSessionStore.index` |

When the bug occurs, one or both of these indices lose their entries, even though the raw `.pb` conversation files remain on disk.

This tool:

1. **Discovers** all local `.pb` conversation files in `~/.gemini/antigravity/conversations/`
2. **Extracts titles** from brain artifacts (`task.md`, `implementation_plan.md`, `walkthrough.md`)
3. **Synthesizes** Protobuf entries with byte-accurate Wire Type 2 nested schemas (Fields 9 and 17)
4. **Merges** new entries into the existing indices without destroying cloud-only conversations
5. **Backs up** the database before any modifications (automatic, timestamped backup)
6. **Rolls back** automatically if any error occurs during the injection process

### Architecture

```
antigravity_database_manager.py        ← Thin entry point
build_release.py              ← Builds the cross-platform .pyz zipapp
├── src/
│   ├── core/                 ← Domain logic, models, and robust database operations
│   │   ├── constants.py
│   │   ├── models.py
│   │   ├── protobuf.py
│   │   ├── environment.py
│   │   ├── artifacts.py
│   │   ├── db_scanner.py
│   │   ├── db_operations.py
│   │   ├── diagnostic.py
│   │   ├── storage_manager.py
│   │   └── lifecycle.py
│   ├── ui_tui/               ← Full-screen Terminal UI (MVU Architecture)
│   │   ├── app.py
│   │   ├── engine.py
│   │   ├── widgets.py
│   │   └── views.py
│   └── ui_headless/          ← Command-line Interface and Interactive Prompts
│       ├── cli_parser.py
│       ├── controller.py
│       └── logger.py
└── dist/
    └── AgmerciumRecovery.pyz ← Portable zipapp (built)
```

### Execution Phases

| Phase | Description |
|-------|-------------|
| **0. Backup Scanner** | Discovers existing backups, displays comparison table, offers restore or proceed |
| **1. Pre-flight Checks** | Verifies IDE is closed, database exists, permissions are correct |
| **2. Conversation Discovery** | Scans for `.pb` files and counts recoverable conversations |
| **3. Secure Backup** | Creates a timestamped copy of `state.vscdb` before any writes |
| **4. Database Injection** | Synthesizes Protobuf + JSON entries and commits to SQLite |
| **5. Summary Report** | Displays statistics: injected, skipped, total |

---

## Compatibility

| Platform | Database Path | Status |
|----------|---------------|--------|
| **Windows** | `%APPDATA%\antigravity\User\globalStorage\state.vscdb` | ✅ Tested |
| **macOS** | `~/Library/Application Support/antigravity/User/globalStorage/state.vscdb` | ✅ Supported |
| **Linux** | `~/.config/antigravity/User/globalStorage/state.vscdb` | ✅ Supported |

- **Python**: 3.10+
- **Dependencies**: None (uses only Python standard library)

---

## CLI Options

```bash
python antigravity_database_manager.py           # Interactive TUI (full-screen database manager)
python antigravity_database_manager.py --headless # Headless interactive mode (no TUI)
python antigravity_database_manager.py scan      # Scan current DB and all backups
python antigravity_database_manager.py recover   # Run the full 6-phase recovery pipeline
python antigravity_database_manager.py health    # Run a health check on the current database
python antigravity_database_manager.py diagnose  # Scan database for Protobuf structural corruptions
python antigravity_database_manager.py repair    # Autonomously repair detected corruptions
python antigravity_database_manager.py --help    # Display help documentation
python antigravity_database_manager.py --version # Display version number (v8.5.0)
```

### Building the Zipapp

To build a portable, single-file zipapp (runs on any platform with Python 3.10+):

```bash
python build_release.py                 # Outputs dist/AgmerciumRecovery.pyz
python dist/AgmerciumRecovery.pyz scan  # Run the built zipapp
```

### Debug Mode

Set the environment variable `AGMERCIUM_DEBUG=1` to enable verbose debug logging:

```bash
# Linux/macOS
AGMERCIUM_DEBUG=1 python antigravity_database_manager.py

# Windows (PowerShell)
$env:AGMERCIUM_DEBUG = "1"; python antigravity_database_manager.py
```

---

## Safety Guarantees

- **Automatic backup**: A timestamped copy of your database is created before any writes.
- **Non-destructive merge**: Existing index entries are preserved; only missing entries are injected.
- **Automatic rollback**: If any database error occurs, the backup is restored immediately.
- **Read-only on `.pb` files**: Your conversation data files are never modified.
- **No network access**: This tool operates entirely offline — zero external requests.

---

## Backup & Undo

After running the tool, your original database backup is preserved at:

```
<database_path>.agmercium_recovery_<timestamp>
```

To undo the recovery, simply copy the backup file over your `state.vscdb`:

```bash
# Example (Windows PowerShell)
Copy-Item "state.vscdb.agmercium_recovery_1710820594" -Destination "state.vscdb" -Force

# Example (Linux/macOS)
cp state.vscdb.agmercium_recovery_1710820594 state.vscdb
```

---

## FAQ

### Q: Will I lose any existing history?
**No.** The tool only *adds* missing entries. It never removes or overwrites existing index entries.

### Q: What if I have conversations from multiple projects?
Run the tool once per project. Each run will prompt you for the project workspace path.

### Q: Can I run this while the IDE is open?
**No.** The IDE will overwrite the database when it shuts down. You must close it first.

### Q: What if the tool crashes mid-run?
The automatic backup is created before any writes. Your database will be intact. You can also restore from the backup file manually.

### Q: Will the conversation titles be correct?
**Yes.** The tool extracts titles from your brain artifacts (`task.md`, `implementation_plan.md`, `walkthrough.md`). If no artifacts exist for a conversation, a clean timestamp-based title is generated (e.g., `Conversation (Mar 19) a1b2c3d4`).

---

## Reporting the Bug to Google

If you've been affected by this bug, please help the community by reporting it to Google through the official channels:

1. **In-App (Recommended)**: Click your profile icon → **Report Issue**
2. **In-App (Agent Manager)**: Click **Provide Feedback** in the bottom-left corner
3. **Google Developer Forums**: Post in the Antigravity IDE section at [google.dev](https://google.dev)
4. **Google Bug Hunters**: For security-related issues, visit [bughunters.google.com](https://bughunters.google.com)
5. **Support Tickets**: Visit the [Antigravity Support Center](https://antigravityide.help) for direct ticket submission

When reporting, include:
- Your OS and Antigravity IDE version
- Whether the history loss occurred after an update, restart, or crash
- The number of conversations affected

---

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## Disclaimer

This is an **unofficial** community tool. It is **not** affiliated with, endorsed by, or supported by Google LLC or the Antigravity IDE team. Use at your own discretion. The tool creates automatic backups before any modifications to minimize risk.

---

## License

This project is licensed under **The Unlicense** — dedicated to the public domain. See [LICENCE.md](LICENCE.md) for the full text.

You are free to copy, modify, distribute, and use this software for any purpose, commercial or non-commercial, without any restrictions whatsoever.

---

<p align="center">
  Made with ❤️ by <a href="https://agmercium.com">Donald R. Johnson</a> at <a href="https://agmercium.com">Agmercium</a>
</p>
