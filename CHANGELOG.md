# Changelog

All notable changes to this project are recorded here.

> **Disclaimer:** This is an **unofficial** community workaround project. It is **not** affiliated
> with, endorsed by, sponsored by, or in any way related to Google LLC or the Antigravity IDE team.
> All product names, logos, and brands are property of their respective owners.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Version numbers adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Release dates use ISO 8601 (`YYYY-MM-DD`). File paths are relative to the repository root.

## [8.9.0] - 2026-10-29

### Added
- **Three-generation support** — The tool now recognises three data generations:
  - G1: the original Antigravity, `.pb` conversations and `state.vscdb`.
  - G2: Antigravity IDE (VS Code-based), `.pb`/`.db` conversations and `state.vscdb`.
  - G3: Antigravity 2.0 and newer builds. There is no `state.vscdb`; each conversation is a self-contained `<uuid>.db` under `~/.gemini/antigravity[-ide]/conversations/`, IDE-made copies live in `conversations_backup/`, and the sidebar is fed by `agyhub_summaries_proto.pb`.

  G2 and G3 can be installed side by side, and G3 shares its `Antigravity` profile folder with G1 on case-insensitive filesystems. `detect_generation()` reports `legacy`, `new`, `mixed` or `none`; the summaries cache is the marker that tells a G3 store apart from G2's `.db` conversations. New read-only reader `src/core/conversation_store.py`, contributed by Elvis33LE in PR #10: it reverse-engineers the `trajectory_metadata_blob` wire format (workspace, git, timestamps, cascade id and project id), opens live databases strictly with `mode=ro` (never modifying them; SQLite may leave empty `-wal`/`-shm` sidecars after reading a WAL-mode file), and uses an `immutable=1` fallback only for backup copies (`src/core/conversation_store.py`, `src/core/models.py`, `src/core/environment.py`).
- **`inspect` command** (PR #10) — Lists every conversation database across all gemini bases, with cascade id, step count, workspace URI and git branch; backup copies are flagged. It also reports each summaries cache: not found, zeroed (Bug #13), all conversations listed, N missing, or format not recognised. Exits non-zero only when no Antigravity data exists. `--json` is supported (`src/ui_headless/cli_parser.py`).
- **`repair --summaries` — Hub summaries cache rebuild (Bug #13)** (PR #10, hardened in review) — A crash can zero `agyhub_summaries_proto.pb` (675 NUL bytes observed), and the language server never rebuilds it, so intact conversations vanish from the sidebar.
  - **What it does:** `repair --summaries` rebuilds **only the conversations missing from the cache**, through the running language server's `JetboxWriteSummary` RPC on `127.0.0.1`, so the server persists the entries and the sidebar updates live.
  - **Safety:**
    - the cache file is backed up first;
    - existing summaries are never replaced unless `--all` is given;
    - a non-empty cache with no recognisable conversation id is never overwritten without `--all`;
    - only stores that have the summaries cache are repaired, so the VS Code-based IDE's `.db` conversations are never sent anywhere;
    - conversation files that cannot be read are reported;
    - synthetic titles skip the bare `file:///` placeholder and decode folder names, and millisecond or out-of-range timestamps fall back safely;
    - `--dry-run` previews the plan offline;
    - the run stops at the first connection failure;
    - conversation databases are never modified.
  - **Finding the server:** the endpoint is taken from the newest language-server spawn in Antigravity 2.0's `logs/main.log` or `logs/<session>/main.log` (plus `~/Library/Logs/Antigravity/` on macOS). The port is paired with the last `--csrf_token`. The "Antigravity IDE" profile's logs are never used, so its own language server never receives these writes. Verified on Windows; macOS and Linux use the standard Electron log locations.
  - **When it runs:** `repair` switches to it automatically when no `state.vscdb` exists. `--summaries` reaches it on mixed installs.

  Reverse-engineered against language server 2.11.0 (`src/core/summaries_repair.py`, `src/ui_headless/cli_parser.py`).
- **`repair --dry-run`** — On G1/G2 databases, reports how many entries would be repaired without writing anything.
- **G2 recovery reads conversation `.db` metadata** — During `recover`, a `.db` conversation with no workspace binding left in `state.vscdb` takes it from its own metadata blob when that folder exists, before brain-artifact inference and the dominant-workspace fallback. Idea from the felimz fork, reimplemented on the structured reader (`src/core/db_operations.py`).
- **Tests** — 77 new cases, 218 in total:
  - wire-format parsing;
  - the missing-only, `--all`, dry-run, zeroed-cache, unknown-format and unreachable-server repair paths;
  - endpoint pairing and session-folder discovery;
  - candidate deduplication;
  - Windows process names;
  - mixed and `--db-path`-aware generation detection;
  - JSON validity;
  - every audit fix below;
  - TUI view robustness (`tests/test_core.py`, `tests/test_tui.py`).

### Fixed
- **Duplicate databases on Windows/macOS** — The `Antigravity` profile candidate is the same folder as `antigravity` on case-insensitive filesystems, so it was listed twice: a bogus "Multiple Databases Detected" prompt, duplicate switch-menu rows, and doubled `scan` rows and backups on macOS. Candidates are now derived from one deduplicated profile list (spelling, then file identity) (`src/core/environment.py`).
- **`--db-path` ignored by the new-generation guidance** — `scan`, `health`, `recover`, the TUI home screen and the headless menus refused to run whenever G3 data existed, even with a valid `--db-path`. The guidance now appears only when the active database is missing (`src/core/conversation_store.py`, `src/ui_headless/`, `src/ui_tui/views.py`).
- **Running-IDE detection missed Antigravity IDE on Windows** — Only `Antigravity.exe` was checked. `Antigravity IDE.exe` is now detected too, from one CSV `tasklist` listing. Finding from the felimz fork (`src/core/environment.py`).
- **Crash on console encodings** — Status glyphs (✓ ⚠ ✗) raised `UnicodeEncodeError` on legacy Windows consoles. Output streams now use `errors="replace"`; the idea comes from the felimz fork (`src/core/lifecycle.py`).
- **`UnicodeDecodeError` traceback on Windows startup** (PR #10) — Process listings are decoded with `errors="replace"` (`src/core/environment.py`).
- **Cryptic `[WinError 3]` when no database exists** (PR #10) — `recover` stops early with `Database not found: <path>`, and `create_backup()` raises a clear `FileNotFoundError` (`src/core/db_operations.py`).
- **`--json` after the subcommand was rejected** (PR #10) — Both positions now parse. In addition:
  - `diagnose --json` no longer prints a header before the JSON document, and reports errors as JSON;
  - `repair --json` is honoured on G1/G2;
  - `fix-uris` no longer advertises a `--json` it never produced (`src/ui_headless/cli_parser.py`).
- **Phantom "Antigravity IDE — File not found" row on G3 installs** (PR #10) — Guidance replaces it. `recover` on G3 now points to `inspect` / `repair --summaries` instead of telling users to create a `state.vscdb` (`src/ui_tui/views.py`, `src/ui_headless/`).
- **Headless "Switch Active Database" crashed with a custom path** — It called an undefined `norm()`, raising `NameError`. Quoted, pasted paths now work (`src/ui_headless/controller.py`).
- **TUI crashes and false success reports:**
  - backup, reset and restore errors are shown instead of crashing the TUI or printing a bare "Error";
  - conversation rename/delete report the operation's error instead of always saying "Renamed"/"Deleted";
  - storage edit/delete failures are reported (`src/ui_tui/views.py`).
- **TUI navigation:**
  - `↓`/`PgDn` on an empty list no longer produces index −1;
  - the browser and storage views keep the selection visible at any terminal height (the clamp was hardcoded to 20 rows);
  - the merge diff table now scrolls with its cursor (`src/ui_tui/views.py`).
- **POSIX workspace URIs had four slashes** — `build_workspace_dict("/home/u/p")` produced `file:////home/u/p`, which affected `workspace migrate` and `repair` on macOS/Linux. Windows output is unchanged (`src/core/db_operations.py`).
- **POSIX brain-artifact workspace inference never matched** — The leading `/` was dropped, so real `file:///abs/path` URIs produced relative paths. Percent-encoding is now fully decoded too. Candidates keep three components below the root on every OS, so a home folder (`/home/u`, `/Users/u`) can never win, and paths inside `~/.gemini/` are ignored (`src/core/artifacts.py`).
- **Recovery misread step-blob paths as workspace bindings** — Any `file:///` string inside a top-level field (for example a tool-call path in Field 12) suppressed workspace assignment. Only the structured Fields 9.1/17.7 count now, and the unused loose `extract_workspace_hint` was removed (`src/core/db_operations.py`, `src/core/db_scanner.py`, `src/core/protobuf.py`).
- **Read-only SQLite URIs broke on special characters** — Paths containing `?`, `#`, `%` or spaces are percent-encoded via `sqlite_uri()`, at every read-only call site (`src/core/db_scanner.py`, `src/core/db_operations.py`, `src/core/diagnostic.py`, `src/core/conversation_store.py`).
- **Created-after-modified timestamps** — POSIX `st_ctime` (inode change time) was used as the creation time. Birth time is used where the OS records one, and creation time never exceeds modification time (`src/core/db_operations.py`, `src/core/summaries_repair.py`).
- **Torn final index entries** — A truncated last entry in `trajectorySummaries` is now skipped instead of being parsed from a short slice (`src/core/db_scanner.py`).
- **`storage patch` / `storage delete` problems:**
  - `"NaN"`/`"Infinity"` were stored as floats, producing invalid JSON in `storage.json`;
  - patching under a non-object parent silently did nothing;
  - deleting a missing key reported success.

  All three now behave correctly, including numeric overflows such as `1e999`, which are kept as strings (`src/core/storage_manager.py`).
- **`storage backup/patch/delete` traceback** when the IDE profile directory is missing (`src/ui_headless/cli_parser.py`).
- **`scan` table misalignment** — Long labels and errors are truncated to the column width (`src/core/db_scanner.py`).
- **TUI `R` on new-generation installs** — It now explains that recovery does not apply, instead of opening the legacy wizard (`src/ui_tui/views.py`).
- **Windows UNC workspaces** — `\\server\share\p` keeps the server as the URI authority (`file://server/share/p`) (`src/core/db_operations.py`).
- **`diagnose` / `repair` on an empty index** — An existing but empty `trajectorySummaries` key is reported as healthy with 0 entries instead of "key not found" (`src/core/diagnostic.py`).
- **Leaked SQLite connection** — `fix-uris --db` closed its connection on every path except "no index found" (`src/core/uri_fix.py`).

### Changed
- **TUI "Reset Database (Empty)" → "Reset Conversation Indices"** — The old action reported success without changing anything. The new `reset_conversation_index()` backs up the database, then clears only the `trajectorySummaries` and `ChatSessionStore.index` keys; all other IDE state is kept (`src/core/db_operations.py`, `src/ui_tui/views.py`).
- **`create_empty_db` uses VS Code's exact storage schema** — `ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)` with `user_version = 1` (`src/core/db_operations.py`).
- **Docs** — Added a three-generation compatibility table, the Bug #13 catalog entry and report, `repair` flags, and Reset semantics, and updated test counts. The safety statements now state the single localhost-only connection used by `repair --summaries` (`README.md`, `SECURITY.md`, `BUGS_RESEARCH.md`, `CONTRIBUTING.md`, `BUGREPORT_Google_Antigravity_SummariesCache_Bug13.md`).

### Fork audit
All 12 public forks were compared with this repository. Two carry unique work:
- **felimz `feature/workspace-resolution-repair`** (Antigravity 2.0 URI scripts, a prune CLI, workspace heuristics). Its process-name and console-encoding findings and its `.db`-metadata workspace idea were adopted, as noted above. The rest was not adopted, because:
  - automatic forced pruning deletes conversations without a backup;
  - its workspace matching is tied to one user's folders;
  - its protobuf rewriters write files the language server owns and roll back to stale backups.
- **SawLay043's Go rewrite** contained no new format knowledge. Comparing it against this codebase exposed the POSIX URI, step-blob, SQLite-URI, timestamp and storage bugs fixed above.

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
