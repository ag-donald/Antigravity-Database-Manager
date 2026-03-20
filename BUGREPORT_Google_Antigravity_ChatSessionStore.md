# Google Antigravity IDE — Bug Report & Workaround

> **Component:** `ChatSessionStore` / `antigravityUnifiedStateSync`
> **Severity:** Critical — Complete Data Loss (UI-level)
> **Affected Versions:** v1.18.x through v1.20.5+ (all platforms)
> **Reported By:** Donald R. Johnson (Agmercium) — <contact@agmercium.com>
> **Date:** March 20, 2026

---

## Summary

The Antigravity IDE silently resets its two internal conversation indices — `chat.ChatSessionStore.index` (JSON) and `antigravityUnifiedStateSync.trajectorySummaries` (Protobuf) — during application shutdown, IDE updates, power outages, or certain workspace transitions. This causes all conversation history to disappear from the UI sidebar, even though the underlying `.pb` conversation data files remain fully intact on disk at `~/.gemini/antigravity/conversations/`.

This is **not data loss** — the raw conversation data is never affected. It is an **index corruption** bug where the IDE's UI layer loses its mapping between conversation UUIDs and sidebar entries.

---

## Reproduction Steps

1. Open Antigravity IDE with an active project workspace containing multiple conversation histories.
2. Trigger any of the following:
   - Update the IDE to a new version.
   - Force-quit or experience an unclean shutdown (power outage, process kill).
   - Restart the application after certain workspace rebinding events.
3. Reopen the IDE.
4. **Expected:** All previous conversations appear in the sidebar.
5. **Actual:** The sidebar shows zero history. All previous conversations are gone.

### Verification That Data Is Intact

```bash
# Count the .pb files — these are the raw conversation data
ls ~/.gemini/antigravity/conversations/ | wc -l
# Example output: 100 (all files present)

# Inspect the database — the index is zeroed out
sqlite3 "$APPDATA/antigravity/User/globalStorage/state.vscdb" \
  "SELECT value FROM ItemTable WHERE key = 'chat.ChatSessionStore.index';"
# Output: {"version":1,"entries":{}}    ← EMPTY
```

---

## Root Cause Analysis

The IDE maintains two parallel indices inside its SQLite database (`state.vscdb` in `User/globalStorage/`):

| Index | Key | Format | Purpose |
|-------|-----|--------|---------|
| **Session Store** | `chat.ChatSessionStore.index` | JSON | Maps conversation UUIDs to UI sidebar metadata |
| **Trajectory Summaries** | `antigravityUnifiedStateSync.trajectorySummaries` | Base64-encoded Protobuf | Stores workspace bindings, timestamps, titles, and step counts per conversation |

### Failure Mode

During shutdown, the IDE performs a non-atomic flush of these two indices. If the process is interrupted (update, crash, power loss), the indices are written in an inconsistent state:

1. **JSON index** resets to `{"version":1,"entries":{}}` — all conversation mappings are deleted.
2. **Protobuf blob** either resets to empty or retains a partial state that no longer matches the JSON index.
3. The **raw `.pb` files** at `~/.gemini/antigravity/conversations/` are **never modified** by this process — they remain fully intact.

### Why The UI Shows Nothing

The IDE's sidebar renderer reads exclusively from the JSON and Protobuf indices. When both are empty, the UI renders zero conversations. It does not perform a fallback scan of the `.pb` files on disk.

---

## Technical Details

### Database Schema

The `state.vscdb` file is a standard SQLite database containing an `ItemTable` with `key TEXT PRIMARY KEY, value TEXT` columns. The relevant keys are:

```
chat.ChatSessionStore.index                         → JSON
antigravityUnifiedStateSync.trajectorySummaries      → Base64(Protobuf)
```

### Protobuf Schema (Reverse-Engineered)

The `trajectorySummaries` blob decodes to a concatenated sequence of `Field 1` (Wire Type 2) entries. Each entry contains:

```protobuf
// Outer entry (repeated Field 1)
message TrajectorySummaryEntry {
    string conversation_uuid = 1;      // e.g., "a63edb81-6b65-40d0-8960-a657bbcd8650"
    Base64Wrapper payload = 2;         // Contains the inner payload as Base64
}

// Base64Wrapper
message Base64Wrapper {
    string base64_encoded_payload = 1; // Base64-encoded inner blob
}

// Inner payload (decoded from Base64)
message TrajectoryPayload {
    string title = 1;                  // Conversation title
    int32 step_count = 2;              // Number of agent steps
    Timestamp created_at = 3;          // Creation timestamp
    string conversation_uuid = 4;      // Must match outer UUID
    int32 status = 5;                  // 1 = ACTIVE
    Timestamp modified_at = 7;         // Last modified timestamp
    WorkspaceMetadata workspace = 9;   // Workspace binding
    Timestamp last_accessed = 10;      // Last accessed timestamp
    WorkspaceParams workspace_params = 17; // Extended workspace URI parameters
}
```

### JSON Schema

```json
{
  "version": 1,
  "entries": {
    "<conversation-uuid>": {
      "title": "Conversation Title",
      "isStale": false,
      "lastModified": 1710886400
    }
  }
}
```

---

## Impact

- Affects **all platforms** (Windows, macOS, Linux).
- Reported by **dozens of users** across the Google AI Developers Forum, Reddit, and in-app feedback channels.
- Users lose access to their **entire conversation history** in the UI, creating significant productivity disruption.
- Particularly severe for users with deep, multi-day agentic sessions containing critical implementation context.

### Community Reports

| Platform | Thread Count | Key Threads |
|----------|-------------|-------------|
| Google AI Dev Forum | 10+ | [BUG] Chat history lost after update, [BUG] Conversation history lost after power outage, [CRITICAL] Conversations Corrupted & Unrecoverable |
| Reddit (r/GoogleAntigravityIDE) | 5+ | "Chat history randomly disappears", "Losing prompt history after restart" |

---

## Workaround

We have developed and released an open-source recovery tool that rebuilds both indices from the intact `.pb` files:

**Repository:** [github.com/agmercium/antigravity-recovery](https://github.com/agmercium/antigravity-recovery)

### How It Works

1. Discovers all `.pb` conversation files in `~/.gemini/antigravity/conversations/`.
2. Extracts titles from brain artifacts (`task.md`, `implementation_plan.md`, `walkthrough.md`).
3. Synthesizes Protobuf entries with byte-accurate Wire Type 2 nested schemas.
4. Merges new entries into the existing indices (non-destructive — preserves cloud-only conversations).
5. Creates automatic timestamped backups before any writes.

### Usage

```bash
# Close the IDE first (mandatory!)
python antigravity_recover.py
# Follow prompts → reopen IDE → history restored
```

---

## Recommended Fix

### Short-Term

1. **Atomic index writes**: Use SQLite transactions with `BEGIN IMMEDIATE` to ensure both the JSON and Protobuf indices are written atomically. If either write fails, roll back both.
2. **Shutdown hook**: Register a reliable shutdown handler that flushes indices before process termination, even on SIGTERM/SIGKILL.

### Long-Term

1. **Fallback disk scan**: If the JSON index loads with zero entries but `.pb` files exist on disk, the IDE should initiate an automatic recovery scan.
2. **Index integrity check**: On startup, verify that the number of `.pb` files on disk matches the number of entries in both indices. If they diverge, trigger a rebuild.
3. **WAL mode for SQLite**: Enable Write-Ahead Logging (`PRAGMA journal_mode=WAL`) to prevent corruption during concurrent reads/writes.

---

## Attachments

- **Recovery Tool Source:** [github.com/agmercium/antigravity-recovery](https://github.com/agmercium/antigravity-recovery)
- **Reverse-Engineered Protobuf Schema:** `docs/schema.proto` in the repository
- **Changelog:** `CHANGELOG.md` in the repository

---

## Contact

**Donald R. Johnson**
Agmercium — [agmercium.com](https://agmercium.com)
Email: contact@agmercium.com

---

*This report was prepared using the Agmercium Antigravity IDE Database Management Hub v8.5.0.*
