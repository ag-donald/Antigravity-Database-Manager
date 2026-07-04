# Antigravity Database Manager - IDE Compatibility Fix

This document explains the root causes of the chat restoration bugs encountered when using the Database Manager with newer versions of the Antigravity IDE, and details the exact fixes implemented by `lionel-tlb`.

## The Issues Faced

While attempting to use the `Antigravity-Database-Manager` to recover lost conversation histories, the tool failed to locate and process recent chats. Specifically:
1. **Missing Data Directory:** The tool could not find the active workspace directory because the newest IDE update changed the core AppData folder name from `antigravity` to `antigravity-ide`.
2. **Ignored Conversation Files:** Older IDE versions stored raw conversation data as Protobuf (`.pb`) files. The newest IDE migrated to storing conversations dynamically as SQLite (`.db`) files. Because the recovery pipeline was explicitly filtering for `.pb` files, all modern conversations were completely skipped.
3. **Missing Titles (Untitled Bug):** Even after forcefully identifying the new `.db` chats, the TUI displayed `(Untitled)` for them. This happened because the new IDE stopped saving the dynamically generated chat titles into the Protobuf layer, instead shifting them to a higher-level JSON index (`chat.ChatSessionStore.index`). The manager's UI scanner was unaware of this and failed to read the JSON titles.

## How I Fixed It

To make the Database Manager fully compatible with the latest IDE ecosystem, the following three core fixes were applied:

### 1. Dynamic Path Resolution
**File:** `src/core/environment.py`
**Fix:** Updated the `get_gemini_base_path()` method. The method now checks for the existence of the `~/.gemini/antigravity-ide/` directory first, prioritizing it as the modern data source, while retaining the old `antigravity` folder as a legacy fallback.

### 2. Multi-Format Database Discovery
**File:** `src/core/db_operations.py`
**Fix:** Modified the file discovery logic within `run_recovery_pipeline()` to extract Unique IDs from both `.pb` AND `.db` files. Additionally, safety filters were added to ignore live SQLite memory-mapped files (`-shm` and `-wal`). The `resolve_title` fallback logic was also updated to extract file modification timestamps from the `.db` files when `.pb` files are absent.

### 3. Asynchronous Title Synchronization
**File:** `src/core/db_scanner.py`
**Fix:** Updated the `list_conversations()` loop to prioritize reading the real chat titles from the JSON index entry (`j_entry["title"]`). This guarantees that the UI perfectly matches the true conversation names shown inside the IDE, resolving the `(Untitled)` placeholder bug.
