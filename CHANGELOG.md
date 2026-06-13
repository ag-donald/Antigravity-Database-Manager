# Changelog

All notable changes to this project are recorded here.

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Release dates use ISO 8601 (`YYYY-MM-DD`). File paths are relative to the repository root.

## [Unreleased]

### Changed
- **Documentation** — Aligned `README.md`, `BUGS_RESEARCH.md`, `CONTRIBUTING.md`, `SECURITY.md`, and `BUGREPORT_Google_Antigravity_ChatSessionStore.md` with actual recovery behavior: titles from preserved database metadata or `.pb` timestamps; backup naming pattern; current project structure and test counts (165 total). Removed inaccurate brain-artifact file references from user-facing docs.

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
