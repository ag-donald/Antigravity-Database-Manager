"""
Constants shared across all recovery modules.
"""

from __future__ import annotations

import os

# ==============================================================================
# ==============================================================================
# VERSION & IDENTITY
# ==============================================================================
VERSION = "1.3.0"
TOOL_NAME = "Agmercium Antigravity Recovery Tool"

# ==============================================================================
# TUNING PARAMETERS
# ==============================================================================
MIN_TITLE_LENGTH = 5           # Minimum chars for a line to qualify as a title
MAX_TITLE_LENGTH = 80          # Truncation limit for extracted titles
BACKUP_PREFIX = "agmercium_recovery"
UUID_PATTERN = rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# ==============================================================================
# DATABASE KEYS
# ==============================================================================
PB_KEY = "antigravityUnifiedStateSync.trajectorySummaries"
JSON_KEY = "chat.ChatSessionStore.index"

# ==============================================================================
# ARTIFACT PATHS
# ==============================================================================
TITLE_ARTIFACT_FILES = ["task.md", "implementation_plan.md", "walkthrough.md"]
OVERVIEW_SUBPATH = os.path.join(".system_generated", "logs", "overview.txt")
