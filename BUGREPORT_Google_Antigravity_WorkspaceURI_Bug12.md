# Google Antigravity IDE — Bug Report: Windows Drive-Letter URI Encoding Mismatch (Bug #12)

> **Component:** `workbench.desktop.main.js` / Frontend URI Comparison & `trajectorySummaries`  
> **Platform:** Windows 10 / Windows 11  
> **Severity:** Medium-High (Usability Friction & Past Conversation Association Failure)  
> **Reported By:** Abhishek Khanra  
> **Affected Versions:** Antigravity IDE v2.0.0 through v2.1.1+  

---

## Executive Summary

On Windows, whenever a user clicks a past conversation in the Antigravity IDE, a popup dialog appears:
> *"Select where to open the conversation — Open in current window / Open in workspace"*

Even when the user is already in the correct workspace where the conversation was created, this dialog appears every time. Furthermore, past conversations often fail to display in the workspace sidebar.

---

## Technical Root Cause Analysis

The root cause is a drive-letter encoding mismatch between the IDE's backend service and its frontend React/Electron components:

1. **Backend Service (`jetskiAgent`)**: Writes workspace URIs using **raw unencoded drive-letter colons**:
   ```
   file:///c:/Users/Username/Projects/MyProject
   ```

2. **Frontend Workbench / State**: Expects percent-encoded drive-letter colons:
   ```
   file:///c%3A/Users/Username/Projects/MyProject
   ```

In `workbench.desktop.main.js`, the frontend performs strict JavaScript string equality (`===`) and array checks (`.includes()`) directly on these raw URI strings without normalizing drive-letter colons (`c:` vs `c%3A`):

### Comparison Location 1: The Disambiguation Dialog Check
```javascript
// Located in conversation handler inside workbench.desktop.main.js
if (F.length === 1 && F[0] === d.workspaceUris[0]) {
    o(_.selectedCascadeId), setTimeout(() => { r() }, 50);
    return;
}
```
* **Failure**: `F[0]` is `file:///c:/...` and `d.workspaceUris[0]` is `file:///c%3A/...`.  
* `F[0] === d.workspaceUris[0]` evaluates to `false`, causing the IDE to show the "Select where to open" popup dialog every time.

### Comparison Location 2: Sidebar Workspace Filtering
```javascript
// Filter past conversations for active workspace
n.workspaces.map(r => r.workspaceFolderAbsoluteUri).some(r => e.includes(r))
```
* **Failure**: `r` contains raw `c:` while array `e` contains percent-encoded `c%3A`.  
* `e.includes(r)` evaluates to `false`, causing past conversations to disappear or fail to match the active workspace.

### Comparison Location 3: State Sync Comparison
```javascript
l.workspaceFolderAbsoluteUri === n.toString()
```
* **Failure**: Mismatch between raw colon and percent-encoded string representations.

---

## Recommended Official Fix (For Google Antigravity Engineering Team)

In the frontend workbench codebase:

1. **Use VS Code `extUri` Comparison**: Replace raw string `===` comparisons with VS Code's built-in URI comparison helper:
   ```typescript
   this.uriIdentityService.extUri.isEqual(uriA, uriB)
   ```
2. **Normalize Backend URIs**: Ensure `jetskiAgent` normalizes all Windows drive-letter colons to `%3A` before writing to `trajectorySummaries` or returning over RPC.

---

## Community Workaround Script (`fix_workspace_uri.py`)

A standalone Python script was authored by Abhishek Khanra to fix this issue on affected Windows installations:

1. **Database Normalization**: Normalizes all workspace URIs stored in `state.vscdb` (`trajectorySummaries` Protobuf blob) from `file:///c:/` to `file:///c%3A/`.
2. **Surgical JS Patching**: Wraps string comparison expressions in `workbench.desktop.main.js` with a lightweight normalizer helper (`_aUF`) that standardizes `c:` to `c%3A` prior to evaluation.
3. **Checksum Recalculation**: Recalculates and updates the SHA-256 base64 checksum in `product.json` to prevent installation corruption warnings.

---
