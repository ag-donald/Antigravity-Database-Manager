#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
                           AGMERCIUM RECOVERY SUITE
                     Antigravity IDE History Recovery Tool
================================================================================

  Author:       Donald R. Johnson
  Organization: Agmercium (https://agmercium.com)
  License:      The Unlicense (Public Domain)
  Version:      1.1.0
  Python:       3.7+
  Dependencies: None (standard library only)

  A production-ready, enterprise-grade utility to securely rebuild the internal
  SQLite UI indices of the Google Antigravity IDE from local Protobuf (.pb)
  cache files.

  This resolves the critical data-loss bug where the IDE fails to correctly
  flush its JSON/Protobuf conversation indices during shutdown, resulting in
  complete loss of UI history upon restart or update.

  Usage:
    1. Close the Antigravity IDE completely.
    2. Run: python antigravity_recover.py
    3. Follow the interactive prompts.
    4. Restart the Antigravity IDE.

  For help:  python antigravity_recover.py --help

  GitHub:  https://github.com/agmercium/antigravity-recovery
  Issues:  https://github.com/agmercium/antigravity-recovery/issues

================================================================================
"""

from __future__ import annotations

from src.recovery import main
from src.logger import Logger

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        Logger.error("Interrupted by user.", fatal=True)
