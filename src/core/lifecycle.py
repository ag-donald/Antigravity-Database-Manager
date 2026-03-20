"""
Production-grade application lifecycle manager.

Provides the ``ApplicationContext`` context manager that wraps all execution,
handling:
  - Python version validation
  - Database path resolution and permission checks
  - Signal registration (SIGINT / SIGTERM)
  - Guaranteed terminal and temporary-file cleanup via atexit
"""

from __future__ import annotations

import atexit
import glob
import os
import signal
import sys
from typing import Optional, Callable

from .constants import VERSION, APP_NAME, MIN_PYTHON_VERSION, DB_FILENAME
from .environment import EnvironmentResolver


class ApplicationContext:
    """
    Context manager wrapping the entire application lifecycle.

    Usage::

        with ApplicationContext() as ctx:
            ctx.perform_preflight_checks()
            # ... launch TUI or Headless controller ...
    """

    def __init__(self) -> None:
        self.app_name: str = APP_NAME
        self.version: str = VERSION
        self.db_path: str = ""
        self.gem_base: str = ""
        self.convs_dir: str = ""
        self.brain_dir: str = ""
        self.ide_running: bool = False
        self.shutdown_requested: bool = False
        self._tui_cleanup_fn: Optional[Callable[[], None]] = None
        self._original_sigint: Optional[signal.Handlers] = None
        self._original_sigterm: Optional[signal.Handlers] = None

    # ------------------------------------------------------------------
    # Context Manager Protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "ApplicationContext":
        self._register_signals()
        self._register_atexit()
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None,
                 exc_tb: object) -> bool:
        self._teardown()
        return False  # Do not suppress exceptions

    # ------------------------------------------------------------------
    # Preflight Checks
    # ------------------------------------------------------------------

    def perform_preflight_checks(self) -> list[str]:
        """
        Runs all startup validations. Returns a list of warning messages
        (empty if everything is clean). Raises SystemExit on fatal errors.
        """
        warnings: list[str] = []

        # 1. Python version
        if sys.version_info < MIN_PYTHON_VERSION:
            major, minor = MIN_PYTHON_VERSION
            print(f"[FATAL] Python {major}.{minor}+ is required. "
                  f"Current: {sys.version_info.major}.{sys.version_info.minor}")
            sys.exit(2)

        # 2. Resolve paths
        self.db_path = EnvironmentResolver.get_antigravity_db_path()
        self.gem_base = EnvironmentResolver.get_gemini_base_path()
        self.convs_dir = os.path.join(self.gem_base, "conversations")
        self.brain_dir = os.path.join(self.gem_base, "brain")

        # 3. Validate database exists
        if not os.path.isfile(self.db_path):
            warnings.append(f"Database not found at: {self.db_path}")

        # 4. Validate permissions
        if os.path.isfile(self.db_path) and not os.access(self.db_path, os.R_OK | os.W_OK):
            warnings.append(f"Insufficient read/write permissions on: {self.db_path}")

        # 5. Detect IDE lock
        self.ide_running = EnvironmentResolver.is_antigravity_running()
        if self.ide_running:
            warnings.append("Antigravity IDE appears to be running! "
                            "The IDE may OVERWRITE changes when it shuts down.")

        return warnings

    # ------------------------------------------------------------------
    # TUI Cleanup Registration
    # ------------------------------------------------------------------

    def register_tui_cleanup(self, fn: Callable[[], None]) -> None:
        """Register a function to restore the terminal state on exit."""
        self._tui_cleanup_fn = fn

    # ------------------------------------------------------------------
    # Signal Handling
    # ------------------------------------------------------------------

    def _register_signals(self) -> None:
        """Trap SIGINT and SIGTERM for graceful shutdown."""
        self._original_sigint = signal.getsignal(signal.SIGINT)

        def _handle_signal(signum: int, frame: object) -> None:
            self.shutdown_requested = True
            # Force exit — atexit handlers will fire
            sys.exit(130 if signum == signal.SIGINT else 143)

        signal.signal(signal.SIGINT, _handle_signal)
        if sys.platform != "win32":
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, _handle_signal)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _register_atexit(self) -> None:
        """Register atexit so cleanup happens even on unhandled exceptions."""
        atexit.register(self._teardown)

    def _teardown(self) -> None:
        """Guaranteed cleanup: restore terminal, delete orphan .tmp files."""
        # 1. Restore terminal state (TUI only)
        if self._tui_cleanup_fn:
            try:
                self._tui_cleanup_fn()
            except Exception:
                pass  # Best-effort; never crash during teardown
            self._tui_cleanup_fn = None  # Prevent double-fire

        # 2. Restore original signal handlers
        if self._original_sigint is not None:
            try:
                signal.signal(signal.SIGINT, self._original_sigint)
            except Exception:
                pass
            self._original_sigint = None

        if self._original_sigterm is not None:
            try:
                signal.signal(signal.SIGTERM, self._original_sigterm)
            except Exception:
                pass
            self._original_sigterm = None

        # 3. Clean up orphaned .tmp files
        if self.db_path:
            self._cleanup_tmp_files()

    def _cleanup_tmp_files(self) -> None:
        """Delete any .tmp files left by interrupted atomic writes."""
        db_dir = os.path.dirname(self.db_path)
        if not db_dir or not os.path.isdir(db_dir):
            return
        pattern = os.path.join(db_dir, f"{DB_FILENAME}.tmp*")
        for tmp_file in glob.glob(pattern):
            try:
                os.remove(tmp_file)
            except OSError:
                pass
