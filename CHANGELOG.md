# Changelog

All notable changes to this project are recorded here.

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Release dates use ISO 8601 (`YYYY-MM-DD`). File paths are relative to the repository root.

## [8.9.0] - 2026-09-02

### Added
- **`inspect` command — new-generation conversation store** — The newest IDE builds no longer create a central `state.vscdb`: each conversation is a self-contained SQLite database under `~/.gemini/antigravity[-ide]/conversations/<uuid>.db` whose `trajectory_metadata_blob` row carries the workspace, git, timestamp, cascade and project metadata the old index held, and IDE-made copies live in a `conversations_backup/` directory. `inspect` detects the installed data generation (legacy / new / none), lists every conversation DB across all gemini bases (backup copies flagged) with cascade id, step count, workspace URI and git branch, and flags conversations without a cascade id — the new generation's invisible-history signal. Fully read-only (`mode=ro` with an `immutable=1` fallback for backup copies whose WAL sidecars would need recovery); `--json` supported. Adds `src/core/conversation_store.py`, the `ConversationRecord` model, and `get_gemini_base_paths()` (`src/core/conversation_store.py`, `src/core/models.py`, `src/core/environment.py`, `src/ui_headless/cli_parser.py`).
- **`repair` — Hub summaries cache rebuild for the new generation (Bug #13)** — The new IDE generation lists sidebar conversations from the Hub summaries cache (`agyhub_summaries_proto.pb`); a crash can zero that file (observed: 675 NUL bytes after an unclean shutdown) and the server never rebuilds it — its directory watcher only refreshes entries that already exist, so intact conversation databases become invisible ("no conversations yet"). `repair` now detects this generation and rebuilds every missing summary entry by calling the running language server's `JetboxWriteSummary` RPC (port and CSRF token are parsed from the IDE's `logs/main.log`; connect-JSON with the `x-codeium-csrf-token` header). The server persists the entries itself and pushes them to the open IDE live; conversation databases are never modified. Reverse-engineered against language server 2.11.0 (`src/core/summaries_repair.py`, `src/ui_headless/cli_parser.py`).
- **Tests** — 25 new cases: metadata-blob wire-format parsing (workspace/git/timestamp/cascade/project fields, garbage and missing-table tolerance), sidecar skipping, backup flagging and deterministic ordering, read-only guarantees (no journal/WAL left behind), generation detection, CLI grammar including `--json` placement, new-generation guidance notices, main.log endpoint parsing, RPC payload/header construction, and the summaries repair pipeline (`tests/test_core.py`).

### Fixed
- **Phantom "Antigravity IDE … File not found" row on new-generation installs** — With no `state.vscdb` anywhere, the TUI home screen, `scan`, `health`, and the headless scanner menu fabricated a dead database row from the nonexistent default path. All surfaces now detect the new generation and show guidance (conversations location, entry count, `inspect` hint) instead; `scan`/`health` exit non-zero and `--json` emits `{"generation": "new", "note": …}` (`src/ui_tui/views.py`, `src/ui_headless/cli_parser.py`, `src/ui_headless/controller.py`).
- **`UnicodeDecodeError` traceback on Windows startup** — `is_antigravity_running()` ran `tasklist` with locale decoding (cp1252 on German Windows) while `tasklist` emits OEM-codepage bytes (`ü` = 0x81, undefined in cp1252), killing the subprocess reader thread with a `UnicodeDecodeError` traceback before every run; both platform probes now pass `errors="replace"` (`src/core/environment.py`).
- **Cryptic `[WinError 3]` when no database exists** — With no `state.vscdb` candidate on disk, `recover` ran its Discovery and Build phases against a nonexistent path and died with `Backup failed: [WinError 3] Das System kann den angegebenen Pfad nicht finden`. The pipeline now fails fast with `Database not found: <path>` (including guidance to start the IDE once or pass `--db-path`), and `create_backup()` raises a clear `FileNotFoundError` for every caller (recover, repair, merge, menus) (`src/core/db_operations.py`).
- **`%APPDATA%\Antigravity` profile candidate** — Newer IDE builds name their Electron profile folder `Antigravity` (no ` IDE` suffix); added as a third Windows and macOS `state.vscdb` candidate (`src/core/environment.py`).
- **`--json` after the subcommand was rejected** — Every documented form like `recover --json`, `health --json`, or `conversations list --json` exited with `error: unrecognized arguments: --json`; only `--json <command>` parsed. All subparsers now share the flag through a parent parser, so both positions work (`src/ui_headless/cli_parser.py`).

## [8.8.0] - 2026-08-19

### Added
- **`fix-uris` command (Bug #12)** (PRs #7/#8) — Fixes the Windows "Select where to open the conversation" dialog caused by raw-vs-percent-encoded drive-letter colons. Patches the three strict URI comparisons in `workbench.desktop.main.js` with a case-aware normalizer and refreshes the bundle's SHA-256 checksum in `product.json`; the IDE installation is auto-detected on Windows, macOS, and Linux (`--ide-path` override; re-run after IDE updates, no-op when already patched). Optional `--db` step surgically canonicalizes workspace URIs already stored in `state.vscdb`: only the URI string values in Protobuf Fields 9.1/9.2/17.7 are rewritten — titles, git metadata, timestamps, and unparseable entries are preserved byte-for-byte, a before/after identity check aborts on any drift, and a discoverable `agmercium_recovery_*_uri_fix` backup is created only when a write happens. `--dry-run` previews everything; `--force` overrides the running-IDE guard. `fix_workspace_uri.py` at the repository root is a thin wrapper for community links (`src/core/uri_fix.py`, `src/ui_headless/cli_parser.py`). Root-cause analysis contributed by Abhishek Khanra; `BUGREPORT_Google_Antigravity_WorkspaceURI_Bug12.md` documents the bug for upstream.
- **Tests** — 31 new cases: Field 17 encoding schema regression guard, canonical URI forms, surgical normalization guarantees (titles/metadata/timestamps preserved, torn and garbage entries kept verbatim, idempotency), SQLite integration with discoverable backups, and bundle patching (idempotency, dry-run, v2-helper upgrade, checksum formatting preservation) (`tests/test_core.py`).

### Fixed
- **`is_antigravity_running()` false positives (POSIX)** — Process detection now lists processes via `ps` and excludes this tool's own command line; the previous `pgrep -f antigravity` matched the manager itself on Linux/macOS and missed the capitalized `Antigravity IDE.app` bundle on macOS (`src/core/environment.py`).
- **Write operations now report why they failed** — `create_empty_db`, `delete_conversation`, `rename_conversation`, and `migrate_workspace` return an `OpResult` (truthy on success) carrying the failure reason instead of a bare `False`; both headless UIs display it. `migrate_workspace` no longer claims success when the database has no `trajectorySummaries` index, and the TUI's backup-delete handler surfaces the OS error instead of a generic "Error" (`src/core/db_operations.py`, `src/core/models.py`, `src/ui_tui/views.py`).
- **SQLite connections closed on error paths** — `get_conversation_payload`, `diagnose_database`, and the repair pipeline's write step now close their connections in `finally` blocks (`src/core/db_operations.py`, `src/core/diagnostic.py`).
- **Workspace URI dedup counting** — the read-side normalizer now canonicalizes drive-letter separators (`file:///C:/x`, `file:///c%3a/x` → `file:///c%3A/x`), so one workspace stored under mixed encodings no longer counts as several (`src/core/db_scanner.py`).
- **POSIX `file:///` decoding** — workspace-path inference no longer drops the leading slash on POSIX URIs; both decode sites share `file_uri_to_path()` (`src/core/db_scanner.py`, `src/core/db_operations.py`).

### Changed
- **Duplication consolidated project-wide** — `execute_selective_merge` is a thin wrapper over `execute_merge(only_uuids=...)` instead of a 90-line copy; recovery/merge summaries render through shared `Logger.recovery_summary`/`merge_summary`; workspace-health classification, DB-install labels, path canonicalization, `file:///` decoding, drive-letter canonicalization, fallback-title formatting (`placeholder_title` + `PLACEHOLDER_TITLE_PREFIX`), and backup naming each have one implementation; the TUI's four hand-rolled split-pane compositions and three scroll-clamp copies now share `_compose_split`/`_clamp_scroll`; the severity→icon/style map is defined once; `build_release.py` bundles the repository's real `__main__.py` instead of re-hardcoding it; `--version`, the banner, and the TUI header all use the single `APP_NAME` identity.
- **`engine.paint()`** normalizes each frame line once per frame instead of twice.

### Removed
- **Dead TUI surface** (nothing referenced by the running product): the unused `widgets.py` and `events.py` modules; the constraint-layout subsystem (`SizeMode`, `Constraint`, `LayoutChild`, `Row`, `Column`, `Box`, `StaticText`, `Spacer`, `Divider`); components with no consumer (`DataTable`, `TreeView`, `TextInput`, `ProgressBar`, `Tabs`, `Breadcrumb`, `SearchBar`, `Badge`, `Sparkline`, `SplitPane`, `ScrollView`, `Gauge`, `BarChart`, `KeyValueGrid`, `Separator`, `NotificationBanner`); the never-called `handle_key`/lifecycle-hook layer; the vacuous `AnimationManager`/`AnimatedValue`/`Transition` machinery and 25 unused easing/effect functions (screen transitions keep `ease_out_cubic`); unused theme entries (17 styles, 30+ icons/glyphs, 4 border presets, gradient utilities, `Style.merge`/`prefix`/`reset`); capability flags that no code read (`unicode_box`, `unicode_emoji`, `mouse_sgr`, `bracketed_paste`) and `color_mode_label()`; inert render statements in `Header`/`Modal`; and the adaptive-FPS remnants (`frame_delay`, FPS constants, write-only frame counters).
- **Dead core/CLI code**: `EnvironmentResolver.get_storage_json_path()`, `ConversationEntry.modified_epoch` (always 0, never read), `lifecycle`'s orphaned `.tmp`-file cleanup (nothing creates such files since the ACID-write strategy), the unused `UUID_PATTERN` constant, `Logger._TAG_WIDTH`, redundant local imports throughout, and the recovery pipeline's write-only stats dict. TUI framework tests for removed code went with it (141 tests total).

## [8.7.0] - 2026-07-09

### Added
- **Multi-database support** (PR #3) — `get_antigravity_db_paths()` discovers active `Antigravity IDE` and deprecated `Antigravity` folders; `scan_all()` consolidates both; `--db-path` CLI override; headless `[11] Switch Active Database`; TUI **Set as Active Database** action. Review feedback addressed: active DB always at `snapshots[0]`, normalized path deduplication, preflight warnings on switch.
- **Tests** — Added `TestResolveTitle`, `TestWorkspaceInference`, and `TestRecoveryPipelineTitles` (9 tests) covering title resolution, task.md regression guard, workspace inference, and recovery integration.

### Fixed
- **Latest IDE compatibility** (PR #5) — Newer Antigravity IDE builds moved data from `~/.gemini/antigravity/` to `~/.gemini/antigravity-ide/`, store conversations as SQLite `.db` files instead of Protobuf `.pb`, and keep dynamically updated chat titles in the JSON session index rather than the Protobuf blob. `get_gemini_base_path()` now prefers the new directory with a legacy fallback; the recovery pipeline discovers both `.pb` and `.db` conversations (ignoring `.db-shm`/`.db-wal` sidecars) and preserves real file timestamps for `.db`-only conversations; `list_conversations()` prefers titles from the JSON index, fixing the `(Untitled)` display bug (`src/core/environment.py`, `src/core/db_operations.py`, `src/core/db_scanner.py`).

### Changed
- **Documentation** — Aligned `README.md`, `BUGS_RESEARCH.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `BUGREPORT_Google_Antigravity_ChatSessionStore.md` with actual recovery behavior: titles from preserved database metadata or `.pb` timestamps; backup naming pattern; current project structure and test counts (176 total). Removed inaccurate brain-artifact file references from user-facing docs.
- **Documentation (latest IDE format)** — Updated all Markdown docs for the new `~/.gemini/antigravity-ide/` data directory and SQLite `.db` conversation format: README recovery/pipeline/FAQ sections, `SECURITY.md` scope, `BUGS_RESEARCH.md` fix descriptions, and a July 2026 update note in `BUGREPORT_Google_Antigravity_ChatSessionStore.md`. Restored TUI screenshots to the README, corrected the headless menu operation count (eleven), added `widgets.py` to project-structure listings, and corrected Bug #8's fix description to match implemented behavior.
- **`src/core/artifacts.py`** — Removed hallucinated title-extraction paths (`task.md`, `implementation_plan.md`, `walkthrough.md`). Module now only infers workspace paths from local `file:///` URIs.
- **`resolve_title`** — Titles resolve from preserved database metadata, then `.pb` timestamp fallbacks.
- **Entry point / TUI** — Trimmed marketing language from module docstrings.

## [8.6.1] - 2026-04-07

### Fixed
- **Linux config directory casing** — Resolver and documentation use `~/.config/Antigravity/` (capital **A**), matching the IDE layout on Linux (`src/core/environment.py`, `README.md`). Merged to `main` as PR #2.

### Added
- **`src/ui_tui/capabilities.py`** — Singleton `CAPS` from one-time terminal detection: truecolor / 256-color / basic tiers; Unicode box-drawing and emoji heuristics; SGR mouse and bracketed-paste flags; light-background inference (`COLORFGBG`, `TERM_PROGRAM`); reduced motion via `NO_COLOR`, `AGMERCIUM_REDUCE_MOTION`, and `REDUCE_MOTION`. `color_mode_label()` returns a short color-mode description.
- **`src/ui_tui/theme/`** — Theme split into `color.py`, `style.py`, `palette.py`, `borders.py`, `icons.py`, and `gradients.py`; `theme/__init__.py` re-exports the public API. Imports of `ui_tui.theme` resolve to this package (the package shadows the sibling `theme.py` module on the import path).
- **`ScreenTransition`** in `src/ui_tui/animation.py` — Vertical-wipe interpolation between full-screen frames for stack push/pop (line-based, ANSI-safe), driven from the application controller.

### Changed
- **`src/ui_tui/theme/color.py`** — `Color.auto_fg()` / `auto_bg()` select ANSI encoding using `CAPS` (truecolor → 256-color → basic).
- **`src/ui_tui/theme/palette.py`** — Default `PALETTE` / `STYLES` depend on capability detection (including light-background selection when `CAPS.light_bg`).
- **`src/ui_tui/components.py`** — Added `Gauge`, `BarChart`, `KeyValueGrid`, `Separator`, and `NotificationBanner`. Header and progress rendering respect truecolor availability and `CAPS.reduce_motion`.
- **`src/ui_tui/app.py`** — Stack transitions use `ScreenTransition` when motion is allowed; transitions are skipped when `CAPS.reduce_motion` is set.
- **`src/ui_tui/engine.py`** — `clipboard_write()` (Windows `clip`, macOS `pbcopy`, X11 `xclip` / `xsel`). `Key.CTRL_P` and Ctrl+P (`\x10`) on Windows and POSIX. `FPS_MAX` (60) caps adaptive frame timing.
- **`src/ui_tui/views.py`** — Three-line `Header` layout; primary pane height uses `rows - 4`. In `ConversationBrowserView`, **`c`** copies the selected conversation UUID to the system clipboard with success or error status.

### Tests
- **`tests/test_tui.py`** — Tests for `CAPS`, `detect()`, `color_mode_label()`, `Color` auto-encoding, `PaletteHighContrast` / `PaletteLight`, and `KeyEvent` for `CTRL_P`.

## [8.6.0] - 2026-03-21

### Added
- **`src/ui_tui/theme.py`** — Semantic palette with truecolor / 256-color / basic fallback; composable `Style`; gradients; box-drawing sets (thin, thick, double, rounded); icon/glyph helpers; approximate contrast helper for terminal-safe choices.
- **`src/ui_tui/events.py`** — Typed event bus, `KeyBindingManager` (global and per-view bindings), `FocusManager` with wrapped tab order.
- **`src/ui_tui/core.py`** — `Component` base class with lifecycle hooks; sizing constraints (`Fixed`, `Percent`, `Fill`); `Row`, `Column`, `Box`; ANSI-aware text helpers (`visible_len`, `truncate`, `pad`, `pad_center`, `pad_right`); `Divider` and related layout primitives.
- **`src/ui_tui/components.py`** — Twenty `Component` implementations, including `Header`, `StatusBar`, `DataTable`, `TreeView`, `TextInput`, `TextViewer`, `Modal`, `ConfirmDialog`, `ActionMenu`, `ProgressBar`, `Spinner`, `ToastManager`, `Tabs`, `Breadcrumb`, `SearchBar`, `Badge`, `Sparkline`, `SplitPane`, `ScrollView`, and `WizardPipeline`.
- **`src/ui_tui/animation.py`** — Thirty scalar easing functions (linear; quad through quint families; bounce; elastic; back; exponential; circular; sine), `AnimatedValue`, transition helpers, `AnimationManager`, and built-in effects (fade-in, slide, typewriter, pulse).
- **`tests/test_tui.py`** — Seventy-five tests for theme, layout, components, animation, events, and focus behavior.

### Changed
- **`src/ui_tui/engine.py`** — Double-buffered rendering with line-level diffing; non-blocking `poll_key(timeout_ms)`; adaptive frame timing (30 FPS when active, 5 FPS when idle); resize handling; extended keys (Ctrl combinations, F1–F5, Shift+Tab, Home/End, Page Up/Down, Delete); terminal title updates.
- **`src/ui_tui/app.py`** — Animation-aware loop (blocking when idle, ~30 FPS polling when animating); `AnimationManager`; global `ToastManager` overlay; terminal title; invalidation hooks for transitions.
- **`src/ui_tui/views.py`** — Eight views rebuilt on the component model: `HomeView`, `ConversationBrowserView`, `ConversationDataView`, `RecoveryWizardView`, `MergeWizardView`, `WorkspaceBrowserView`, `StorageBrowserView`, and `HelpOverlay`.
- **`src/ui_tui/__init__.py`** — Package docstring updated for the layered layout.

### Notes (accessibility & UX)
- Intent-based color tokens (`success`, `warning`, `error`) instead of raw color names where practical.
- Named style ladder: `header` → `subheader` → `body` → `muted`.
- Status bar shows key hints; focus order wraps with visible focus treatment.
- Master–detail layouts in browse flows; toasts are non-blocking with severity cues.
- Frame rate drops when idle to limit CPU use; animation path uses higher refresh when needed.

## [8.5.1] - 2026-03-20

### Fixed
- **BUG-002** — `widgets.py`: `_trunc()` uses ANSI-aware visible width (avoids corrupting escape sequences).
- **BUG-003** — `HomeView`: `elif` chain ordered so shortcuts do not depend on selection side effects.
- **BUG-004** — Recovery path shows a working state before the blocking recovery call.
- **BUG-005** — Merge diff load shows a loading state before the blocking diff work.
- **BUG-007** — Scroll offsets tracked in Conversation, Home, and Storage views.
- **BUG-009** — `storage_manager.py`: `patch_key` coerces JSON types for booleans, numbers, and null.
- **BUG-012** — “Create Empty Database” renamed to “Reset Database (Empty)” with a second confirmation step.
- **BUG-014** — Page Up / Page Down in scrollable TUI views.

### Added
- **`recover` CLI** — `--json` for machine-readable output (BUG-015).
- **`conversations delete` CLI** — `--force` to skip confirmation (BUG-016).
- **Headless UI** — Paginated “Browse Conversations” (previously capped at 20 items) (BUG-017).
- **Tests** — Nine new tests: `TestStorageManager` (six), `TestWidgetTrunc` (three).

### Changed
- **BUG-001** — Removed misleading `__all__` from `src/core/__init__.py`.
- **BUG-006** — Removed unused `ws_assignments` / `ws_choice` from headless `_menu_recover`.
- **BUG-008** — `build_release.py`: zipapp `interpreter=None` for portable shebang behavior.
- **BUG-010** — `README.md`: link target corrected after `BUGS.md` → `BUGS_RESEARCH.md` rename.
- **BUG-013** — `tests/test_core.py`: documented rationale for the `sys.path` adjustment.
- **Headless** — `_browse_conversation_detail` extracted in `controller.py`.
- **Docs** — Unofficial disclaimer applied consistently across markdown files.

## [8.5.0] - 2026-03-20

### Fixed
- **`db_scanner.py`** — `extract_existing_metadata` no longer truncates entries to the UUID field when the payload should be preserved; double-wrap handling runs only when field 1 fully consumes the entry (restores conversation discovery).
- **`protobuf.py`** — `build_trajectory_entry` used an undefined `parent_uuid` when patching workspace data; corrected to use `conv_uuid`.
- **Version metadata** — Aligned version strings across `src/core/constants.py`, `antigravity_database_manager.py`, and `README.md`.

### Changed
- **`protobuf.py`** — Removed unused `uuid` import.
- **`CONTRIBUTING.md`** — Project structure lists `diagnostic.py` and `storage_manager.py`.

## [8.0.0] - 2026-03-19

### Added
- **`src/core/diagnostic.py`** — Byte-oriented Protobuf scan for common damage patterns (replacement characters, double wrapping, UUID mismatches, invalid field 15 wire types).
- **Repair path** — Automatic fixes for several detected issues (strip spurious bytes, unwrap double wraps, re-bind UUIDs where applicable).
- **`src/core/storage_manager.py`** — Atomic read/write for `storage.json` with backup-before-write, flattened keys, and dotted-path patch/delete.
- **`RepairResult`** (`src/core/models.py`) — Structured outcome type for repair operations.

### Changed
- **`protobuf.py`** — Encoder orders tags recursively to avoid field 9 / 10 ordering conflicts.
- **Workspace paths** — Windows drive letters normalized to lowercase in `build_workspace_dict`.

## [7.0.0] - 2026-03-19

### Added
- **TUI** — Split-pane database manager hub replacing the earlier menu-only flow.
- **Inspection** — `ConversationBrowserView` and `ConversationDataView` for browsing conversations and raw JSON payloads.
- **Editing** — Delete and rename conversations from the UI with pre-write backups.
- **Headless CLI** — Interactive menus aligned with major TUI flows (including browse and health reporting).
- **Models** — Immutable `ConversationEntry` and `HealthReport` dataclasses.

### Changed
- **Backups** — Destructive actions create timestamped backups with explicit reason suffixes (e.g. `_before_conv_del`).
- **Layout** — Eight UI surfaces (home, conversation browser, conversation data, recovery wizard, merge wizard, workspace browser, storage browser, help overlay) implemented with MVU-style modules (`widgets.py`, `views.py`).

## [1.3.0] - 2026-03-19

### Added
- **Partial-record recovery** — Titles and tool state recovered from partially damaged Protobuf records when possible.
- **Workspace inference** — Workspace paths inferred from surviving Protobuf hints and dominant-workspace fallback during recovery.
- **Batch workspace assignment** — Interactive menu for unmapped conversations, including apply-to-all style actions.
- **Timestamp repair** — Injects missing modification/creation timestamps when the IDE omitted them.

### Changed
- **`src/recovery.py`** — Six-phase pipeline: pre-flight → discovery/extraction → workspace mapping → backup → injection → summary.
- **`src/protobuf.py`** — Length-delimited and varint parsing for non-destructive field updates.
- **`src/cli.py`** — Formatting updates for dynamic interactive lists.

## [1.2.0] - 2026-03-19

### Fixed
- **`run.sh`** — Replaced GNU-specific `grep -oP` with `sed` and `cut` for macOS BSD `grep`.

### Added
- **Launchers** — `run.bat`, `run.ps1`, and `run.sh` for Windows CMD, PowerShell, and Unix shells.
- **`src/` package** — Modules: `constants`, `logger`, `protobuf`, `environment`, `artifacts`, `cli`, `recovery`.
- **`CONTRIBUTING.md`** — Project structure section.

### Changed
- **Code organization** — Monolithic script split into seven modules plus a thin entry point.
- **`README.md`** — Architecture section updated for the `src/` layout.
- **`CONTRIBUTING.md`** — Validation commands cover all modules.

## [1.1.0] - 2026-03-19

### Fixed
- **Missing keys** — If `trajectorySummaries` is absent, the tool initializes it instead of failing.
- **Writes** — Protobuf and JSON index persistence use `INSERT OR REPLACE` instead of `UPDATE`-only paths so empty or damaged databases can be repaired.
- **License text** — Docstring license reference aligned with `LICENCE.md` (Unlicense).

### Added
- **Warnings** — Multi-workspace limitations surfaced during workspace registration.
- **Documentation** — SSH remote-session notes in the interactive flow; README section on common failure categories (community-sourced references).

## [1.0.0] - 2026-03-19

### Added
- Initial public release: Antigravity IDE chat history recovery and database utilities.
- **Platforms** — Windows, macOS, and Linux.
- **CLI** — Interactive workspace registration and recovery workflow.
- **Safety** — Timestamped database backups before writes.
- **Protobuf** — Wire-type-2 encoder for nested trajectory fields (including fields 9 and 17).
- **JSON index** — Non-destructive merge of `chat.ChatSessionStore.index` entries.
- **Titles** — Resolved from preserved database metadata when available; timestamp-based fallbacks from `.pb` modification times.
- **Errors** — Rollback to backup on database write failures; `--help` and `--version`; debug logging via `AGMERCIUM_DEBUG=1`.
- **`Logger`** — Shared severity-tagged logging helper.
- **Reporting** — Phase summary table at end of recovery run.
- **Repository** — `README.md` (FAQ, architecture overview, official reporting links), `LICENCE.md` (Unlicense), `CONTRIBUTING.md`, `SECURITY.md`.
