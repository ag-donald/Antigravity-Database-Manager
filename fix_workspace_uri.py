#!/usr/bin/env python3
"""
Convenience wrapper for the Bug #12 workspace-URI encoding fix.

Equivalent to::

    python antigravity_database_manager.py fix-uris [options]

The filename is kept because community bug-report threads link to it; all
logic lives in ``src/core/uri_fix.py``. See ``fix-uris --help`` for options
(``--db``, ``--no-js``, ``--ide-path``, ``--dry-run``, ``--force``).
"""

from __future__ import annotations

import argparse
import sys

from src.core.lifecycle import ApplicationContext
from src.ui_headless import cli_parser


def main() -> None:
    """Parses the wrapper's arguments and delegates to the fix-uris command."""
    # --db-path is a global option of the main entry point (it precedes the
    # subcommand there); accept it here too so the wrapper is self-contained.
    # allow_abbrev=False keeps this from swallowing --db as an abbreviation.
    pre = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--db-path", default="")
    pre_args, rest = pre.parse_known_args()

    with ApplicationContext() as ctx:
        args = cli_parser.parse_args(["fix-uris", *rest])
        if pre_args.db_path:
            ctx.db_path = pre_args.db_path
        ctx.perform_preflight_checks()
        sys.exit(cli_parser.execute(args, ctx))


if __name__ == "__main__":
    main()
