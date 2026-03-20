# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [8.5.0] - 2026-03-20

### Fixed
- **CRITICAL: Zero Conversations Bug** — `extract_existing_metadata` in `db_scanner.py` unconditionally sliced entries to just the UUID field, discarding the entire Base64 payload. Added the missing conditional check so double-wrap detection only triggers when Field 1 truly consumes the entire entry.
- **NameError in Protobuf encoder** — `build_trajectory_entry` referenced an undefined `parent_uuid` variable when patching existing entries with workspace data. Replaced with the correct `conv_uuid` parameter.
- **Version inconsistencies** — Synchronized version strings across `constants.py` (was `8.0.0`), `antigravity_recover.py` (was `7.0.0`), and `README.md` (was `v2.0.0`).

### Changed
- Removed dead `import uuid` from `protobuf.py`
- Updated `CONTRIBUTING.md` project structure to include `diagnostic.py` and `storage_manager.py`

## [8.0.0] - 2026-03-19

### Added
- **Universal Corruption Diagnostic Engine** (`diagnostic.py`): Byte-level Protobuf scanner detecting ghost bytes (U+FFFD), double-wrapping, UUID mismatches, and invalid Field 15 wire types.
- **Autonomous Repair Engine**: Auto-fixes detected corruptions (ghost byte stripping, double-wrap removal, UUID re-binding).
- **Storage Manager** (`storage_manager.py`): Atomic read/write for `storage.json` with backup-first safety, recursive key flattening, and dotted-path patch/delete operations.
- **RepairResult** data model for repair operation outcomes.

### Changed
- Protobuf encoder rebuilt with recursive tag-number sorting to prevent Field 9/10 ordering conflicts.
- Windows path casing normalized to lowercase drive letters in `build_workspace_dict`.

## [7.0.0] - 2026-03-19

### Added
- **Unified Database Manager Hub:** Complete architectural redesign of the TUI into a comprehensive split-pane database manager.
- **Deep Inspection:** Added `ConversationBrowserView` and `ConversationDataView` to inspect raw JSON payloads inside databases natively.
- **Safe Management:** Added support for safely deleting and renaming conversations directly from the interface.
- **Headless Parity:** Full interactive CLI menu mirroring the TUI feature set, including Browse and Health Check menus.
- **Robust Data Models:** Introduced immutable `ConversationEntry` and `HealthReport` dataclasses.

### Changed
- **Backup Strategy:** Forced pre-write safety backups for all destructive actions with descriptive reason suffixes (e.g., `_before_conv_del`).
- **UI Architecture:** Flattened the menu-driven system into 6 core views with MVU layout architecture (`widgets.py` + `views.py`).

## [1.3.0] - 2026-03-19

### Added
- **Partial Data Loss Recovery**: Extracts existing titles and preserves tool state from partially corrupt Protobuf records (e.g., missing titles, stripped workspaces, broken timestamps).
- **Workspace Auto-Inference**: Automatically detects the correct workspace path for a conversation by parsing `file:///` URLs inside Markdown brain artifacts.
- **Interactive Batch Assignment**: Provides a robust CLI menu for interactively assigning unmapped conversations to workspaces, including "apply to all" batching.
- **Timestamp Injection**: Automatically injects missing modification and creation timestamps into existing trajectory strings if the IDE stripped them.

### Changed
- Re-architected `src/recovery.py` Core Loop into a 6-phase pipeline (Pre-flight → Discovery & Extraction → Workspace Mapping → Backup → Injection → Summary).
- `src/protobuf.py` now parses raw Varints and Length-delimited fields to enable non-destructive field patching.
- Enhanced standard formatting in `src/cli.py` to support dynamic interactive lists.

## [1.2.0] - 2026-03-19

### Fixed
- **macOS launcher crash**: `run.sh` used GNU-only `grep -oP` which fails on macOS BSD grep — replaced with portable `sed`+`cut`

### Added
- Platform-specific launcher scripts: `run.bat` (Windows CMD), `run.ps1` (PowerShell), `run.sh` (Linux/macOS)
- Modular `src/` package architecture: `constants`, `logger`, `protobuf`, `environment`, `artifacts`, `cli`, `recovery`
- Project Structure section in `CONTRIBUTING.md`

### Changed
- Refactored monolithic script into 7 focused modules for maintainability
- Updated README Architecture section to reflect `src/` package layout
- Updated `CONTRIBUTING.md` syntax validation commands to cover all modules
- Version bumped to 1.2.0

## [1.1.0] - 2026-03-19

### Fixed
- **Missing database keys**: Script no longer dies fatally when `trajectorySummaries` key is missing from database — creates it from scratch instead
- **Silent write failures**: Replaced `UPDATE` statements with `INSERT OR REPLACE` for both Protobuf and JSON index writes, ensuring the script works on completely blank or corrupted databases
- **License reference**: Updated docstring from MIT to Unlicense to match `LICENCE.md`

### Added
- Multi-workspace limitation warning displayed during interactive workspace registration
- SSH remote session guidance in the interactive prompt
- Covers all 11 documented community failure modes (verified against Google AI Dev Forum reports)

### Changed
- Version bumped to 1.1.0

## [1.0.0] - 2026-03-19

### Added
- Initial release of the Antigravity IDE History Recovery Tool
- Cross-platform support (Windows, macOS, Linux)
- Interactive CLI with project workspace registration
- Automatic database backup with timestamped filenames
- Protobuf Wire Type 2 encoder with byte-accurate nested schemas (Fields 9, 17)
- Non-destructive JSON index merge (preserves existing entries)
- Brain artifact title extraction from `task.md`, `implementation_plan.md`, `walkthrough.md`
- Fallback title generation using overview logs and timestamps
- Automatic rollback on database errors via `safe_rollback()` helper
- `--help` and `--version` CLI flags
- Debug mode via `AGMERCIUM_DEBUG=1` environment variable
- Unified `Logger` class with consistent severity tags
- Phase 5 summary statistics table
- Comprehensive README with FAQ, architecture docs, and official bug reporting channels
- LICENCE.md (The Unlicense — public domain)
- CONTRIBUTING.md with code standards and submission guidelines
- SECURITY.md with responsible disclosure policy
