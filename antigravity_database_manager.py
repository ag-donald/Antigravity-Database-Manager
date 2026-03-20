#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
                           AGMERCIUM RECOVERY SUITE
                     Antigravity IDE Database Management Hub
================================================================================

  Author:       Donald R. Johnson
  Organization: Agmercium (https://agmercium.com)
  License:      The Unlicense (Public Domain)
  Version:      8.5.1
  Python:       3.10+
  Dependencies: None (standard library only)

  A production-ready, enterprise-grade utility to manage the internal SQLite
  databases used by the Google Antigravity IDE. Features a world-class TUI,
  headless CLI automation, and safety-first atomic operations.

  Usage:
    Interactive TUI:              python antigravity_database_manager.py
    Headless interactive:         python antigravity_database_manager.py --headless
    Direct commands:              python antigravity_database_manager.py scan
                                  python antigravity_database_manager.py merge --source backup.vscdb
                                  python antigravity_database_manager.py backup create

  For help:  python antigravity_database_manager.py --help

  GitHub:  https://github.com/ag-donald/Antigravity-Database-Manager
  Issues:  https://github.com/ag-donald/Antigravity-Database-Manager/issues

================================================================================
"""

from __future__ import annotations

import sys

from src.core.lifecycle import ApplicationContext
from src.ui_headless import cli_parser
from src.ui_headless.controller import run_interactive


def main() -> None:
    """
    Application entry point.

    Routing logic:
      1. If a subcommand is given (e.g., ``scan``, ``merge``), execute it headlessly.
      2. If ``--headless`` is set or stdout is not a TTY, launch the interactive CLI.
      3. Otherwise, launch the full-screen TUI.
    """
    with ApplicationContext() as ctx:
        args = cli_parser.parse_args()

        if cli_parser.has_subcommand(args):
            # Direct headless command (e.g., `antigravity_database_manager.py scan`)
            ctx.perform_preflight_checks()
            exit_code = cli_parser.execute(args, ctx)
            sys.exit(exit_code)

        elif getattr(args, "headless", False) or not sys.stdout.isatty():
            # Interactive headless fallback
            exit_code = run_interactive(ctx)
            sys.exit(exit_code)

        else:
            # Full-screen TUI
            from src.ui_tui.app import App
            App(ctx).run()


if __name__ == "__main__":
    main()
