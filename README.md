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

This is a **widely reported issue** across the Google AI Developers Forum, Reddit, GitHub, and YouTube. We have cataloged **11 distinct bug categories** with verified community reports, technical root cause analysis, and how this Database Manager solves each one:

📋 **[Full Bug Catalog → BUGS.md](BUGS.md)**

| # | Bug | Trigger |
|---|-----|---------|
| 1 | IDE Update Index Wipe | IDE version update resets indices to empty |
| 2 | Power Outage Corruption | Non-atomic flush during unclean shutdown |
| 3 | Workspace Rebinding Loss | Project folder moved, renamed, or path changed |
| 4 | SSH Remote Session Loss | Switching between local and remote contexts |
| 5 | Agent Manager Self-Deletion | Protobuf parsing error silently drops entries |
| 6 | Protobuf Field Ordering | Out-of-order fields rejected by strict parser |
| 7 | Windows Path Casing | Drive letter `H:` vs `h:` mismatch |
| 8 | Long-Context Truncation | Large conversations exceed rendering limits |
| 9 | Ghost Bytes / Double-Wrapping | Encoding corruption in Protobuf blob |
| 10 | storage.json Desync | Three parallel data stores fall out of sync |
| 11 | Scratch Session Disabled | Workspace-less conversations hidden after upgrade |

### Root Cause

All 11 bugs stem from the IDE's failure to atomically flush its internal indices during shutdown:

1. **`chat.ChatSessionStore.index`** (JSON) — Gets reset to `{"version":1,"entries":{}}` 
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

## Usage

This tool provides **three interfaces** — choose whichever fits your workflow:

| Interface | Launch Command | Best For |
|-----------|---------------|----------|
| **Full-Screen TUI** | `python antigravity_database_manager.py` | Interactive exploration, visual browsing |
| **Headless Interactive** | `python antigravity_database_manager.py --headless` | Terminals without TUI support, SSH sessions |
| **CLI Subcommands** | `python antigravity_database_manager.py <command>` | Scripting, CI/CD automation, one-shot tasks |

---

### Full-Screen TUI (Terminal User Interface)

Launch with no arguments to enter the full-screen split-pane database manager:

```bash
python antigravity_database_manager.py
```

The TUI uses an **MVU (Model-View-Update) architecture** with 8 screens:

#### 1. Home — Database Dashboard

The default landing screen. Shows a split pane with all databases (current + backups) on the left and a health report on the right.

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between databases |
| `Enter` | Open the Action Menu for the selected database |
| `S` | Refresh scan (re-scan all databases) |
| `B` | Create a manual backup of the selected database |
| `R` | Jump directly to Recovery Wizard |
| `W` | Jump directly to Workspace Diagnostics |
| `T` | Jump directly to Storage.json Browser |
| `?` | Toggle Help overlay |
| `Q` / `Esc` | Quit |

**Action Menu (current database):**

| Option | Description |
|--------|-------------|
| Browse Conversations | Open the Conversation Browser for this database |
| Run Full Recovery | Launch the 6-phase Recovery Wizard |
| Create Backup | Create a timestamped backup copy |
| Merge From Another DB | Launch the Merge Wizard |
| Workspace Diagnostics | Inspect workspace URI bindings and filesystem health |
| Manage Storage | Open the Storage.json Browser |
| Create Empty Database | Reset the database (backup created first) |

**Action Menu (backup database):**

| Option | Description |
|--------|-------------|
| Browse Conversations | Inspect conversations in this backup |
| Restore This Backup | Replace current database with this backup |
| Compare with Current | Open Merge Wizard pre-loaded with this backup as source |
| Delete This Backup | Remove this backup file |

#### 2. Conversation Browser

Browse, search, rename, and delete individual conversations. Split pane shows the conversation list on the left and details (UUID, workspace, timestamps, sync status) on the right.

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between conversations |
| `Enter` | Open the context menu (Inspect / Rename / Delete) |
| `/` | Activate search/filter mode — type to filter by title |
| `N` | Rename the selected conversation |
| `D` | Delete the selected conversation (with confirmation) |
| `Esc` | Return to previous screen |

#### 3. Raw Payload Inspector

View the raw JSON payload of a specific conversation, scrollable with line counts.

| Key | Action |
|-----|--------|
| `↑` `↓` | Scroll through the payload |
| `Esc` | Return to Conversation Browser |

#### 4. Recovery Wizard

Visual, guided execution of the 6-phase recovery pipeline with a real-time progress indicator:

| Phase | Description |
|-------|-------------|
| **Backup** | Creates a safety backup of the current database |
| **Discovery** | Scans `~/.gemini/antigravity/conversations/` for `.pb` files |
| **Titles** | Extracts titles from brain artifacts (`task.md`, `implementation_plan.md`, etc.) |
| **Injection** | Synthesizes Protobuf entries and injects into `state.vscdb` |
| **JSON** | Synchronizes the JSON `ChatSessionStore.index` |
| **Done** | Displays summary statistics |

Press `Enter` to begin. After completion, a full results summary is displayed.

#### 5. Merge Wizard

Merge conversations from a source database (backup or external) into the current database with cherry-pick support:

1. **Source Selection** — Type or paste the path to the source `.vscdb` file
2. **Diff Preview** — See which conversations are new, shared, or target-only
3. **Cherry-Pick** — Use `Space` to toggle individual conversations, `A` to select all, `N` to select none
4. **Strategy Selection** — Choose `Additive` (safe, only add missing) or `Overwrite` (replace shared entries)
5. **Execution** — Merge runs with automatic backup

#### 6. Workspace Browser

Inspect all unique workspace URIs in the database with filesystem health checks:

| Column | Description |
|--------|-------------|
| **✓** | Workspace exists and is accessible |
| **⚠** | Workspace exists but has permission issues |
| **✗** | Workspace path does not exist on disk |
| **Convs** | Number of conversations bound to this workspace |

#### 7. Storage.json Browser

Browse, edit, and manage the IDE's `storage.json` configuration file:

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between keys |
| `E` | Edit the value of the selected key |
| `D` | Delete the selected key (with confirmation) |
| `Esc` | Return to Home |

#### 8. Help Overlay

Press `?` from any screen to view a complete keyboard shortcut reference.

---

### Headless Interactive Mode

For environments without TUI support (SSH, minimal terminals, screen readers):

```bash
python antigravity_database_manager.py --headless
```

Presents a numbered menu with all 10 operations:

```
  AGMERCIUM DB MANAGER — Main Menu
  ═══════════════════════════════════
  [1]  Scan & Compare Databases
  [2]  Restore a Backup
  [3]  Run Full Recovery Pipeline
  [4]  Merge Two Databases
  [5]  Create Empty Database
  [6]  Create Manual Backup
  [7]  Browse Conversations
  [8]  Health Check
  [9]  Workspace Diagnostics
  [10] Manage Storage.json
  [Q]  Quit
```

Each menu provides guided, step-by-step interactive prompts with confirmation dialogs.

---

### CLI Subcommands (Non-Interactive)

For scripting, automation, and CI/CD. All subcommands auto-detect the database path and exit with standard codes (`0` = success, `1` = error).

#### `scan` — Database Overview

```bash
python antigravity_database_manager.py scan           # Human-readable table
python antigravity_database_manager.py scan --json     # JSON output
```

#### `recover` — Full 6-Phase Recovery Pipeline

```bash
python antigravity_database_manager.py recover
```

Runs backup → discovery → title extraction → Protobuf injection → JSON sync → summary. Outputs progress messages to stdout.

#### `health` — Database Health Check

```bash
python antigravity_database_manager.py health          # Human-readable report
python antigravity_database_manager.py health --json   # JSON output
```

Reports: size, conversation/titled counts, workspace count, sync status, orphan detection.

#### `diagnose` — Corruption Diagnostic Engine

```bash
python antigravity_database_manager.py diagnose                      # Scan current DB
python antigravity_database_manager.py diagnose --target path.vscdb   # Scan external DB
python antigravity_database_manager.py diagnose --json               # JSON output
```

Byte-level Protobuf scanner detects: ghost bytes (U+FFFD), double-wrapping, UUID mismatches, invalid wire types, field ordering violations.

#### `repair` — Autonomous Repair Engine

```bash
python antigravity_database_manager.py repair                      # Repair current DB
python antigravity_database_manager.py repair --target path.vscdb   # Repair external DB
```

Auto-fixes all corruptions found by `diagnose`. Creates a backup first. Reports: entries scanned, repaired, preserved, ghost bytes stripped, double wraps fixed, UUID mismatches fixed.

#### `merge` — Database Merge

```bash
# Additive merge (safe — only add missing conversations)
python antigravity_database_manager.py merge --source backup.vscdb

# Overwrite merge (replace shared entries with source versions)
python antigravity_database_manager.py merge --source backup.vscdb --strategy overwrite

# Cherry-pick specific conversations by UUID
python antigravity_database_manager.py merge --source backup.vscdb --cherry-pick "uuid1,uuid2,uuid3"
```

#### `backup` — Backup Management

```bash
python antigravity_database_manager.py backup list        # List all backups (same as scan)
python antigravity_database_manager.py backup create      # Create a new backup
python antigravity_database_manager.py backup restore 1   # Restore backup #1 (from scan output)
```

#### `create` — Create Empty Database

```bash
python antigravity_database_manager.py create --output /path/to/new.vscdb
```

#### `conversations` — Conversation Management

```bash
python antigravity_database_manager.py conversations list                      # List all conversations
python antigravity_database_manager.py conversations list --json               # JSON output
python antigravity_database_manager.py conversations show <uuid>               # Show raw JSON payload
python antigravity_database_manager.py conversations delete <uuid>             # Delete a conversation
python antigravity_database_manager.py conversations rename <uuid> "New Title" # Rename a conversation
```

#### `workspace` — Workspace Diagnostics & Migration

```bash
python antigravity_database_manager.py workspace list                  # List all workspaces
python antigravity_database_manager.py workspace list --json           # JSON output
python antigravity_database_manager.py workspace check                 # Filesystem health check
python antigravity_database_manager.py workspace migrate /new/path     # Rebind all conversations to new path
```

The `migrate` command is critical for Bug #3 (workspace rebinding) and Bug #7 (Windows path casing).

#### `storage` — Storage.json Management

```bash
python antigravity_database_manager.py storage inspect                    # List all keys
python antigravity_database_manager.py storage inspect --json             # JSON output
python antigravity_database_manager.py storage backup                     # Create a backup
python antigravity_database_manager.py storage patch "key.path" "value"   # Set a value
python antigravity_database_manager.py storage delete "key.path"          # Delete a key
```

---

### Global Flags

| Flag | Description |
|------|-------------|
| `--headless` | Force headless interactive mode (no TUI) |
| `--json` | Output results as JSON (available for `scan`, `health`, `diagnose`, `conversations list`, `workspace list`, `storage inspect`) |
| `--version` / `-v` | Display version number |
| `--help` / `-h` | Display help documentation |

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
