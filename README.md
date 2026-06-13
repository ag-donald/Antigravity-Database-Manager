# Antigravity IDE — Database Management Hub

<p align="center">
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager/blob/main/LICENCE.md"><img src="https://img.shields.io/badge/License-Unlicense-blue.svg" alt="License: Unlicense"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager"><img src="https://img.shields.io/badge/Open%20Source-100%25-green.svg" alt="Open Source: 100%"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version"></a>
  <a href="https://github.com/ag-donald/Antigravity-Database-Manager"><img src="https://img.shields.io/badge/Free-Forever-success.svg" alt="Free Forever"></a>
</p>

<p align="center">
  <strong>An unofficial, open-source community database manager and recovery tool for the Google Antigravity IDE.</strong>
</p>

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

<p align="center">
  <a href="#quickstart">Quickstart</a> •
  <a href="#the-bug">The Bug</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#compatibility">Compatibility</a> •
  <a href="#usage">Usage</a> •
  <a href="#faq">FAQ</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

---

## The Bug

Google Antigravity IDE (a heavily modified VS Code fork for agent-first AI development) has a recurring bug where **conversation history disappears** from the UI sidebar after:

- Updating the IDE to a new version
- Restarting the application
- Power outages or unclean shutdowns
- Certain workspace or session transitions

The underlying `.pb` conversation data files remain **intact** on disk at `~/.gemini/antigravity/conversations/`, but the IDE's internal SQLite database (`state.vscdb`) loses its UI index mappings — specifically `ChatSessionStore.index` (JSON) and `trajectorySummaries` (Protobuf) — so the sidebar shows zero history.

**This tool rebuilds those internal indices from your intact `.pb` files, restoring conversation history in the IDE.**

### Community Bug Reports

This is a **widely reported issue** across the Google AI Developers Forum, Reddit, GitHub, and YouTube. We catalog **11 distinct failure modes** with community reports, technical analysis, and how this tool addresses each one:

📋 **[Full Bug Catalog → BUGS_RESEARCH.md](BUGS_RESEARCH.md)**

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
| 10 | storage.json Desync | Parallel data stores fall out of sync |
| 11 | Scratch Session Disabled | Workspace-less conversations hidden after upgrade |

### Root Cause

These bugs stem from the IDE failing to atomically flush its internal indices during shutdown:

1. **`chat.ChatSessionStore.index`** (JSON) — reset to `{"version":1,"entries":{}}`
2. **`antigravityUnifiedStateSync.trajectorySummaries`** (Protobuf) — loses UUID-to-conversation mappings
3. **`storage.json`** — workspace binding metadata falls out of sync

The raw `.pb` files under `~/.gemini/antigravity/conversations/` are **never modified** by this tool. Recovery is possible because the conversation payloads survive on disk.

---

## Quickstart

### Prerequisites

- **Python 3.10+**
- **No external dependencies** — standard library only

### Steps

**Option A — Run from source:**

```bash
# 1. Close Antigravity IDE completely (mandatory)

# 2. Run the recovery script
python antigravity_database_manager.py recover

# 3. Reopen Antigravity IDE — your history should be restored
```

For the full interactive experience (database browser, merge wizard, diagnostics), run without a subcommand:

```bash
python antigravity_database_manager.py
```

**Option B — Portable zipapp (no install needed):**

Download `AgmerciumRecovery.pyz` from the [latest release](https://github.com/ag-donald/Antigravity-Database-Manager/releases) and run:

```bash
# 1. Close Antigravity IDE completely (mandatory)

# 2. Run the portable binary
python AgmerciumRecovery.pyz recover

# 3. Reopen Antigravity IDE
```

> **Important:** The IDE **must** be fully closed before running this tool. If the IDE is running, it may overwrite the patched database when it shuts down.

---

## How It Works

The Antigravity IDE stores conversation history in two parallel indices inside its SQLite database (`state.vscdb`):

| Index | Format | SQLite Key |
|-------|--------|------------|
| **Trajectory Summaries** | Base64-encoded Protobuf | `antigravityUnifiedStateSync.trajectorySummaries` |
| **Session Store** | JSON | `chat.ChatSessionStore.index` |

When the bug occurs, one or both indices lose their entries while the raw `.pb` conversation files remain on disk.

The recovery pipeline:

1. **Discovers** all local `.pb` files in `~/.gemini/antigravity/conversations/`
2. **Reads** any surviving title and workspace metadata still present in the database
3. **Resolves titles** from preserved database metadata when available; otherwise generates timestamp-based titles from `.pb` file times (for example, `Conversation (Mar 19) a1b2c3d4`)
4. **Assigns workspaces** from existing Protobuf hints, with a dominant-workspace fallback for unmapped conversations
5. **Synthesizes** Protobuf entries with byte-accurate Wire Type 2 nested schemas (Fields 9 and 17)
6. **Backs up** the database before any writes (automatic, timestamped copy)
7. **Merges** new entries into both indices without destroying cloud-only conversations
8. **Rolls back** automatically from the backup if any error occurs during injection

Protobuf field layout is documented in [docs/schema.proto](docs/schema.proto).

### Project Structure

```
antigravity_database_manager.py   ← Entry point
build_release.py                  ← Builds the cross-platform .pyz zipapp
src/
├── core/                         ← Domain logic, models, database operations
│   ├── constants.py
│   ├── models.py
│   ├── protobuf.py
│   ├── environment.py
│   ├── artifacts.py
│   ├── db_scanner.py
│   ├── db_operations.py
│   ├── diagnostic.py
│   ├── storage_manager.py
│   └── lifecycle.py
├── ui_tui/                       ← Full-screen terminal UI
│   ├── capabilities.py           ← Terminal capability detection
│   ├── theme/                    ← Semantic colors, styles, gradients, icons
│   ├── events.py                 ← Event bus, key bindings, focus management
│   ├── core.py                   ← Component base, layout engine
│   ├── components.py             ← Reusable UI components
│   ├── animation.py              ← Easing, animated values, transitions
│   ├── engine.py                 ← Double-buffered terminal I/O
│   ├── app.py                    ← Application event loop
│   └── views.py                  ← Eight screens (home, browse, recovery, merge, …)
└── ui_headless/                  ← CLI parser and interactive menus
    ├── cli_parser.py
    ├── controller.py
    └── logger.py
tests/
├── test_core.py                  ← Core logic tests (63 tests)
└── test_tui.py                   ← TUI framework tests (113 tests)
```

### Recovery Pipeline Phases

| Phase | Description |
|-------|-------------|
| **Discovery** | Scans `~/.gemini/antigravity/conversations/` for `.pb` files and reads surviving database metadata |
| **Build** | Resolves titles and workspace bindings for each conversation |
| **Backup** | Creates a timestamped copy of `state.vscdb` before any writes |
| **Injection** | Rebuilds the Protobuf `trajectorySummaries` blob and synchronizes `ChatSessionStore.index` in a single SQLite transaction |
| **Complete** | Reports statistics: conversations rebuilt, workspaces mapped, JSON entries added or patched |

---

## Compatibility

The tool auto-detects both the **active** and **deprecated** Antigravity IDE database locations. When both exist, the TUI and headless menus let you choose or switch the active database.

| Platform | Active path | Deprecated path |
|----------|-------------|-----------------|
| **Windows** | `%APPDATA%\Antigravity IDE\User\globalStorage\state.vscdb` | `%APPDATA%\antigravity\User\globalStorage\state.vscdb` |
| **macOS** | `~/Library/Application Support/Antigravity IDE/User/globalStorage/state.vscdb` | `~/Library/Application Support/antigravity/User/globalStorage/state.vscdb` |
| **Linux** | `~/.config/Antigravity IDE/User/globalStorage/state.vscdb` | `~/.config/Antigravity/User/globalStorage/state.vscdb` |

The resolver prefers whichever path exists on disk, defaulting to the active `Antigravity IDE` folder.

- **Python:** 3.10+
- **Dependencies:** None (standard library only)
- **Current version:** 8.6.1

---

## Usage

Three interfaces are available — use whichever fits your workflow:

| Interface | Launch Command | Best For |
|-----------|---------------|----------|
| **Full-Screen TUI** | `python antigravity_database_manager.py` | Interactive exploration and visual browsing |
| **Headless Interactive** | `python antigravity_database_manager.py --headless` | Terminals without TUI support, SSH sessions |
| **CLI Subcommands** | `python antigravity_database_manager.py <command>` | Scripting, automation, one-shot tasks |

When stdout is not a TTY (piped output, some CI environments), the tool automatically falls back to headless interactive mode unless a subcommand is provided.

---

### Full-Screen TUI

Launch with no arguments:

```bash
python antigravity_database_manager.py
```

The TUI provides eight screens:

#### 1. Home — Database Dashboard

Split pane: databases (current and backups) on the left, health report on the right.

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between databases |
| `Enter` | Open the action menu for the selected database |
| `S` | Refresh scan |
| `B` | Create a manual backup of the selected database |
| `R` | Open Recovery Wizard |
| `W` | Open Workspace Diagnostics |
| `T` | Open Storage.json Browser |
| `?` | Toggle Help overlay |
| `Q` / `Esc` | Quit |

**Action menu (current database):** Browse Conversations, Run Full Recovery, Create Backup, Merge From Another DB, Workspace Diagnostics, Manage Storage, Reset Database (Empty).

**Action menu (other primary database):** Set as Active Database, Browse Conversations, Compare with Current.

**Action menu (backup database):** Browse Conversations, Restore This Backup, Compare with Current, Delete This Backup.

#### 2. Conversation Browser

Browse, search, rename, and delete conversations. Split pane: list on the left, details (UUID, workspace, timestamps, sync status) on the right.

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between conversations |
| `Enter` | Context menu (Inspect / Rename / Delete) |
| `/` | Search/filter by title |
| `N` | Rename selected conversation |
| `D` | Delete selected conversation (with confirmation) |
| `C` | Copy selected conversation UUID to clipboard |
| `Esc` | Return to previous screen |

#### 3. Raw Payload Inspector

View the raw JSON payload of a conversation.

| Key | Action |
|-----|--------|
| `↑` `↓` / `PgUp` `PgDn` / `Home` `End` | Scroll |
| `Esc` | Return to Conversation Browser |

#### 4. Recovery Wizard

Guided recovery with a progress indicator. Press `Enter` to start.

| Step | Description |
|------|-------------|
| **Backup** | Creates a safety backup of the current database |
| **Discovery** | Scans `~/.gemini/antigravity/conversations/` for `.pb` files |
| **Titles** | Resolves titles from preserved metadata or `.pb` timestamps |
| **Injection** | Rebuilds Protobuf entries in `state.vscdb` |
| **JSON** | Synchronizes `ChatSessionStore.index` |
| **Done** | Displays summary statistics |

#### 5. Merge Wizard

Merge conversations from a source database (backup or external) into the current database:

1. **Source Selection** — Enter the path to the source `.vscdb` file
2. **Diff Preview** — See new, shared, and target-only conversations
3. **Cherry-Pick** — `Space` toggles entries, `A` selects all, `N` clears selection
4. **Strategy** — `1` for Additive (safe), `2` for Overwrite
5. **Execution** — Merge runs with automatic backup

#### 6. Workspace Browser

Inspect workspace URIs with filesystem health checks (`✓` accessible, `⚠` permission issues, `✗` missing path).

#### 7. Storage.json Browser

Browse, edit, and delete keys in the IDE's `storage.json` configuration.

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate between keys |
| `E` | Edit the selected key's value |
| `D` | Delete the selected key (with confirmation) |
| `Esc` | Return to Home |

#### 8. Help Overlay

Press `?` from any screen for keyboard shortcut reference.

---

### Headless Interactive Mode

For environments without TUI support:

```bash
python antigravity_database_manager.py --headless
```

Presents a numbered menu with ten operations:

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
  [11] Switch Active Database
  [Q]  Quit
```

`diagnose` and `repair` are available via CLI subcommands (see below), not in this menu.

---

### CLI Subcommands

For scripting and automation. All subcommands auto-detect the database path and exit with standard codes (`0` = success, non-zero = error).

#### `scan` — Database Overview

```bash
python antigravity_database_manager.py scan
python antigravity_database_manager.py scan --json
```

#### `recover` — Full Recovery Pipeline

```bash
python antigravity_database_manager.py recover
python antigravity_database_manager.py recover --json
```

Runs discovery → build → backup → injection → summary. Use `--json` for machine-readable output.

#### `health` — Database Health Check

```bash
python antigravity_database_manager.py health
python antigravity_database_manager.py health --json
```

Reports size, conversation counts, workspace count, sync status, and orphan detection.

#### `diagnose` — Corruption Diagnostic

```bash
python antigravity_database_manager.py diagnose
python antigravity_database_manager.py diagnose --target path.vscdb
python antigravity_database_manager.py diagnose --json
```

Byte-level Protobuf scanner detects ghost bytes, double-wrapping, UUID mismatches, invalid wire types, and field ordering violations.

#### `repair` — Autonomous Repair

```bash
python antigravity_database_manager.py repair
python antigravity_database_manager.py repair --target path.vscdb
```

Auto-fixes corruptions found by `diagnose`. Creates a backup first.

#### `merge` — Database Merge

```bash
python antigravity_database_manager.py merge --source backup.vscdb
python antigravity_database_manager.py merge --source backup.vscdb --strategy overwrite
python antigravity_database_manager.py merge --source backup.vscdb --cherry-pick "uuid1,uuid2,uuid3"
```

#### `backup` — Backup Management

```bash
python antigravity_database_manager.py backup list
python antigravity_database_manager.py backup create
python antigravity_database_manager.py backup restore 1
```

`restore` uses the backup index from `scan` output (backups only, excluding the current database).

#### `create` — Create Empty Database

```bash
python antigravity_database_manager.py create --output /path/to/new.vscdb
```

#### `conversations` — Conversation Management

```bash
python antigravity_database_manager.py conversations list
python antigravity_database_manager.py conversations list --json
python antigravity_database_manager.py conversations show <uuid>
python antigravity_database_manager.py conversations delete <uuid>
python antigravity_database_manager.py conversations delete <uuid> --force
python antigravity_database_manager.py conversations rename <uuid> "New Title"
```

#### `workspace` — Workspace Diagnostics and Migration

```bash
python antigravity_database_manager.py workspace list
python antigravity_database_manager.py workspace list --json
python antigravity_database_manager.py workspace check
python antigravity_database_manager.py workspace migrate /new/path
```

`migrate` rebinds all conversations to a new workspace path — useful for Bug #3 (workspace rebinding) and Bug #7 (Windows path casing).

#### `storage` — Storage.json Management

```bash
python antigravity_database_manager.py storage inspect
python antigravity_database_manager.py storage inspect --json
python antigravity_database_manager.py storage backup
python antigravity_database_manager.py storage patch "key.path" "value"
python antigravity_database_manager.py storage delete "key.path"
```

---

### Global Flags

| Flag | Description |
|------|-------------|
| `--headless` | Force headless interactive mode (no TUI) |
| `--db-path` | Override the default `state.vscdb` location |
| `--json` | JSON output (supported on `scan`, `recover`, `health`, `diagnose`, `conversations list`, `workspace list`, `storage inspect`) |
| `--version` / `-v` | Display version number |
| `--help` / `-h` | Display help |

### Building the Zipapp

```bash
python build_release.py                 # Outputs dist/AgmerciumRecovery.pyz
python dist/AgmerciumRecovery.pyz scan  # Run the built zipapp
```

### Debug Mode

```bash
# Linux/macOS
AGMERCIUM_DEBUG=1 python antigravity_database_manager.py

# Windows (PowerShell)
$env:AGMERCIUM_DEBUG = "1"; python antigravity_database_manager.py
```

### Running Tests

```bash
python -m unittest discover -s tests -v
```

---

## Safety Guarantees

- **Automatic backup:** A timestamped copy of your database is created before any writes.
- **Non-destructive merge:** Existing index entries are preserved by default; additive merge only injects missing entries.
- **Automatic rollback:** If a database error occurs during recovery, the pre-write backup is restored.
- **Read-only on `.pb` files:** Conversation payload files are never modified.
- **No network access:** The tool operates entirely offline.

---

## Backup and Undo

Backups use this naming pattern:

```
<database_path>.agmercium_recovery_<unix_timestamp>_<reason>
```

For example: `state.vscdb.agmercium_recovery_1710820594_before_recovery`

To undo a recovery, copy the backup over your live database:

```bash
# Windows (PowerShell)
Copy-Item "state.vscdb.agmercium_recovery_1710820594_before_recovery" -Destination "state.vscdb" -Force

# Linux/macOS
cp state.vscdb.agmercium_recovery_1710820594_before_recovery state.vscdb
```

---

## FAQ

### Will I lose any existing history?

No. Recovery and additive merge only add or update missing entries. They do not remove existing index entries unless you explicitly delete conversations or use overwrite merge.

### What if I have conversations from multiple projects?

Run recovery once. The pipeline scans **all** `.pb` files under `~/.gemini/antigravity/conversations/` and rebuilds indices for every conversation it finds, assigning workspaces from preserved metadata or dominant-workspace fallback.

### Can I run this while the IDE is open?

No. The IDE may overwrite the database when it shuts down. Close Antigravity completely before running this tool.

### What if the tool crashes mid-run?

A backup is created before any writes. If injection fails, the tool attempts automatic rollback. You can also restore manually from the backup file.

### Will conversation titles be correct?

Titles are taken from **preserved database metadata** when any fragments remain after the index wipe. When no title survives, the tool generates a readable fallback from the `.pb` file's modification time (for example, `Conversation (Mar 19) a1b2c3d4`). You can rename conversations afterward via the TUI or `conversations rename`.

### Where is the Protobuf schema documented?

See [docs/schema.proto](docs/schema.proto) for the reverse-engineered `trajectorySummaries` wire format.

---

## Reporting the Bug to Google

If you have been affected, please report it through official channels:

1. **In-App (Recommended):** Profile icon → **Report Issue**
2. **In-App (Agent Manager):** **Provide Feedback** in the bottom-left corner
3. **Google Developer Forums:** [discuss.ai.google.dev](https://discuss.ai.google.dev)
4. **Google Bug Hunters:** [bughunters.google.com](https://bughunters.google.com) (security-related issues)
5. **Support:** [antigravityide.help](https://antigravityide.help)

When reporting, include your OS, Antigravity IDE version, whether history loss followed an update/restart/crash, and how many conversations were affected.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

For security issues, see [SECURITY.md](SECURITY.md).

---

## Disclaimer

This is an **unofficial** community workaround project. It is **not** affiliated with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team. All product names, logos, and brands are property of their respective owners. Use at your own discretion. The tool creates automatic backups before modifications to minimize risk.

---

## License

This project is licensed under **The Unlicense** — dedicated to the public domain. See [LICENCE.md](LICENCE.md) for the full text.

You are free to copy, modify, distribute, and use this software for any purpose without restriction.

---

<p align="center">
  Made with ❤️ by <a href="https://agmercium.com">Donald R. Johnson</a> at <a href="https://agmercium.com">Agmercium</a>
</p>
