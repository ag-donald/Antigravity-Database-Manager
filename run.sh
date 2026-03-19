#!/usr/bin/env bash
# ============================================================================
#  Agmercium Antigravity IDE History Recovery Tool — Linux / macOS Launcher
# ============================================================================

set -euo pipefail

echo ""
echo "  ============================================================"
echo "   Agmercium Antigravity IDE History Recovery Tool"
echo "   Launcher for Linux / macOS (run.sh)"
echo "  ============================================================"
echo ""

# Locate Python — try 'python3' first (preferred on Unix), then 'python'
PYTHON_CMD=""

if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    # Verify it's Python 3, not Python 2
    PY_VER=$(python --version 2>&1 | grep -oP '\d+' | head -1)
    if [ "$PY_VER" -ge 3 ] 2>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "[ERROR] 'python' points to Python 2. Please install Python 3.7+."
        echo "        On Debian/Ubuntu:  sudo apt install python3"
        echo "        On macOS:          brew install python3"
        exit 1
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "[ERROR] Python is not installed or not in your PATH."
    echo "        Please install Python 3.7+."
    echo "        On Debian/Ubuntu:  sudo apt install python3"
    echo "        On macOS:          brew install python3"
    echo "        On Fedora/RHEL:    sudo dnf install python3"
    exit 1
fi

echo "[INFO ] Using: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# Run the recovery script from the same directory as this shell script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECOVERY_SCRIPT="$SCRIPT_DIR/antigravity_recover.py"

if [ ! -f "$RECOVERY_SCRIPT" ]; then
    echo "[ERROR] antigravity_recover.py not found at: $RECOVERY_SCRIPT"
    exit 1
fi

$PYTHON_CMD "$RECOVERY_SCRIPT" "$@"
