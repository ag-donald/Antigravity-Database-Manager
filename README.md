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

## The Bug

Google Antigravity IDE (a heavily modified VS Code fork powering agent-first AI development) has a recurring bug where **all conversation history disappears** from the UI sidebar after:

- Updating the IDE to a new version
- Restarting the application
- Power outages or unclean shutdowns
- Certain workspace/session transitions

The underlying `.pb` conversation data files remain **fully intact** on disk at `~/.gemini/antigravity/conversations/`, but the IDE's internal SQLite database (`state.vscdb`) loses its UI index mappings — specifically the `ChatSessionStore.index` (JSON) and `trajectorySummaries` (Protobuf) — causing the sidebar to display zero history.

**This tool rebuilds those internal indices from your intact `.pb` files, restoring your full conversation history.**

### Community Bug Reports

This is a **widely reported issue** across the Google AI Developers Forum, Reddit, and in-app feedback channels. Below are verified, direct links to community threads documenting this exact behavior:

#### Google AI Developers Forum (discuss.ai.google.dev)

| Thread | Author | Description |
|--------|--------|-------------|
| [[BUG] Chat history lost after Antigravity update — ChatSessionStore index reset to empty](https://discuss.ai.google.dev/t/bug-chat-history-lost-after-antigravity-update-chatsessionstore-index-reset-to-empty/125625) | Daichi_Zaha | History disappeared after update on macOS; `ChatSessionStore.index` reset |
| [[BUG] Conversation history lost after power outage — v1.20.5](https://discuss.ai.google.dev/t/bug-conversation-history-lost-after-power-outage-v1-20-5/133550) | MishaSER | 4 conversations (18.5 MB) intact on disk but UI shows zero after power loss |
| [[BUG] [CRITICAL] v1.20.5 — Conversations Corrupted & Unrecoverable + Export Broken (macOS)](https://discuss.ai.google.dev/t/bug-critical-v1-20-5-conversations-corrupted-unrecoverable-export-broken-macos/130547) | jc-myths | All new conversations lost after auto-update to v1.20.5 on macOS |
| [🚨 Critical Regression — Chat Freeze, Conversation History Loss & Pro Plan Limit Concerns (Windows 10)](https://discuss.ai.google.dev/t/critical-regression-in-latest-antigravity-version-chat-freeze-conversation-history-loss-pro-plan-limit-concerns-windows-10/125651) | ANURAJ_RAI | Disappearing history + session persistence issues after Feb 2026 update |
| [[Bug/Help] Antigravity 1.18.x/1.19.x: Chat history completely disabled/lost for "scratch" sessions](https://discuss.ai.google.dev/t/bug-help-antigravity-1-18-x-1-19-x-chat-history-completely-disabled-lost-for-scratch-sessions-after-upgrading-from-1-16-5/127132) | Red_Tom | All history inaccessible after upgrading from v1.16.5; red "disabled" icon |
| [I have lost conversation history in the with early update app](https://discuss.ai.google.dev/t/i-have-lost-conversation-history-in-the-with-early-update-app/124337) | Bun_Zie | History only remembers sessions from before the update |
| [Missing conversations](https://discuss.ai.google.dev/t/missing-conversations/127818) | jnchacon | Sidebar shows conversations from wrong workspaces |
| [Missing conversation in IDE (SSH)](https://discuss.ai.google.dev/t/missing-conversation-in-ide-ssh/130852/4) | Dark2002 | Conversations missing when using SSH remote development |
| [Fix if you lost your session history with the new upgrade](https://discuss.ai.google.dev/t/fix-if-you-lost-your-session-history-with-the-new-upgrade-per-antigravity/127105) | Jimmy_Harrell | Community discussion on workarounds for post-update history loss |
| [[BUG] Agent Manager chat window "self-deletes" on load error](https://discuss.ai.google.dev/t/bug-agent-manager-chat-window-self-deletes-on-load-error-but-agent-survives-in-workspace/114186) | Shannon_Green | Conversations disappear from Agent Manager UI on load errors |

#### Reddit

This issue is also widely discussed across multiple Reddit communities:

- **r/GoogleAntigravityIDE** — Multiple threads about "chat history randomly disappears" and "losing prompt history"
- **r/google_antigravity** — Discussions of workarounds including workspace re-binding and version rollbacks

#### Root Cause

The bug stems from the IDE's failure to atomically flush its two internal indices during shutdown:

1. **`chat.ChatSessionStore.index`** (JSON) — Gets reset to `{"version":1,"entries":{}}` 
2. **`antigravityUnifiedStateSync.trajectorySummaries`** (Protobuf) — Loses UUID-to-conversation mappings

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
