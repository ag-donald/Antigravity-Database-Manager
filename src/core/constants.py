"""
Constants shared across all recovery modules.
"""

from __future__ import annotations

# ==============================================================================
# VERSION & IDENTITY
# ==============================================================================
VERSION = "8.6.1"
APP_NAME = "Agmercium Antigravity IDE DB Manager"
TOOL_NAME = "Agmercium Antigravity IDE Recovery Tool"
AGMERCIUM_URL = "https://www.agmercium.com"

# ==============================================================================
# DATABASE SETTINGS
# ==============================================================================
DB_FILENAME = "state.vscdb"
STORAGE_FILENAME = "storage.json"
MIN_PYTHON_VERSION = (3, 10)

# ==============================================================================
# TUNING PARAMETERS
# ==============================================================================
BACKUP_PREFIX = "agmercium_recovery"
UUID_PATTERN = rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# ==============================================================================
# DATABASE KEYS
# ==============================================================================
PB_KEY = "antigravityUnifiedStateSync.trajectorySummaries"
JSON_KEY = "chat.ChatSessionStore.index"
