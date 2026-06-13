"""
MVU Application Controller — the TUI main loop.

Manages the screen stack, animation-aware event loop, and terminal engine
lifecycle. This is the central coordinator between the engine, animation
manager, toast system, and all views.

UX Best Practices enforced:
  - Adaptive frame rate: 30 FPS during animations, blocking input when idle
  - Toast notifications rendered as a global overlay on every frame
  - Animated screen transitions (slide push/pop) for spatial continuity
  - Clean shutdown guaranteed even on exceptions or signals
  - Terminal title updated to show current context
"""

from __future__ import annotations

import time

from ..core.lifecycle import ApplicationContext
from ..core.constants import APP_NAME, VERSION
from .engine import TerminalEngine, Key, KeyEvent
from .animation import AnimationManager, ScreenTransition
from .capabilities import CAPS
from .components import ToastManager
from .views import (
    HomeView, ConversationBrowserView, ConversationDataView,
    RecoveryWizardView, MergeWizardView, HelpOverlay,
    WorkspaceBrowserView, StorageBrowserView,
)


class App:
    """
    The main MVU application controller.

    Entry point for the full-screen TUI experience. Provides an animation-
    aware event loop that adapts between blocking and polling modes.

    UX Best Practice: The event loop is adaptive — when animations are
    running, it polls at ~30 FPS for smooth visual updates. When the UI is
    idle, it blocks on keyboard input to use zero CPU.
    """

    def __init__(self, ctx: ApplicationContext) -> None:
        self.ctx = ctx
        self.engine = TerminalEngine()
        self.screen_stack: list[object] = []
        self.animations = AnimationManager()
        self.toasts = ToastManager()
        self._transition: ScreenTransition | None = None

    def run(self) -> None:
        """Main event loop with animation-aware rendering."""
        # Register cleanup with lifecycle manager
        self.ctx.register_tui_cleanup(self.engine.exit_fullscreen)
        self.ctx.perform_preflight_checks()
        self.engine.enter_fullscreen()
        self.engine.set_title(f"{APP_NAME} v{VERSION}")

        try:
            home = HomeView(self.ctx)
            self._push(home)

            while self.screen_stack:
                cols, rows = self.engine.get_size()

                # --- Render ---
                if self._transition and not self._transition.is_complete:
                    # Render transition animation frame
                    frame = self._transition.render(cols, rows)
                else:
                    # Clear completed transition
                    if self._transition:
                        self._transition = None

                    current = self.screen_stack[-1]
                    frame = current.view(cols, rows)

                # Overlay toasts on every frame
                if self.toasts.has_active:
                    toast_lines = self.toasts.render(cols, min(3, rows))
                    # Place toasts at the bottom, above the status bar
                    toast_start = max(0, rows - len(toast_lines) - 1)
                    for i, tl in enumerate(toast_lines):
                        if toast_start + i < len(frame):
                            frame[toast_start + i] = tl

                self.engine.paint(frame)

                # --- Tick animations ---
                self.animations.tick()

                # --- Input ---
                is_animating = (
                    self.animations.is_animating
                    or self.toasts.has_active
                    or (self._transition is not None and not self._transition.is_complete)
                )

                if is_animating:
                    # Non-blocking: poll for input with short timeout
                    key = self.engine.poll_key(timeout_ms=33)  # ~30 FPS
                    if key is None:
                        # No input — just redraw on next loop iteration
                        continue
                    # If user presses key during transition, snap to end
                    if self._transition and not self._transition.is_complete:
                        self._transition = None
                        self.engine.invalidate()
                        continue
                else:
                    # Blocking: wait for input (zero CPU when idle)
                    key = self.engine.getch()

                    # Check for resize after blocking input
                    if self.engine.size_changed():
                        self.engine.invalidate()
                        continue

                # --- Update ---
                current = self.screen_stack[-1]
                action = current.update(key)

                if action is None:
                    continue
                elif action == "back":
                    self._pop()
                elif action == "quit":
                    break
                elif action.startswith("push:"):
                    screen = self._create_screen(action)
                    if screen:
                        self._push(screen)
                elif action.startswith("toast:"):
                    # Global toast from any view: "toast:severity:message"
                    parts = action.split(":", 2)
                    if len(parts) >= 3:
                        self.toasts.push(parts[2], severity=parts[1])
                    elif len(parts) == 2:
                        self.toasts.push(parts[1])
        finally:
            self.engine.exit_fullscreen()

    def _push(self, screen: object) -> None:
        """Push a new screen onto the stack with optional slide-in transition."""
        # Capture old frame for transition
        old_frame: list[str] = []
        if self.screen_stack and not CAPS.reduce_motion:
            cols, rows = self.engine.get_size()
            old_screen = self.screen_stack[-1]
            old_frame = old_screen.view(cols, rows)

        self.screen_stack.append(screen)
        if hasattr(screen, "on_enter"):
            screen.on_enter()

        # Start slide-in transition (unless reduce motion)
        if old_frame and not CAPS.reduce_motion:
            cols, rows = self.engine.get_size()
            new_frame = screen.view(cols, rows)
            self._transition = ScreenTransition(
                old_frame, new_frame, direction="push", duration=0.15,
            )
        else:
            self.engine.invalidate()  # Force full repaint for new screen

    def _pop(self) -> None:
        """Pop the top screen off the stack with optional slide-out transition."""
        old_frame: list[str] = []
        if self.screen_stack and not CAPS.reduce_motion:
            cols, rows = self.engine.get_size()
            old_frame = self.screen_stack[-1].view(cols, rows)

        if self.screen_stack:
            self.screen_stack.pop()
        if self.screen_stack and hasattr(self.screen_stack[-1], "on_enter"):
            self.screen_stack[-1].on_enter()

        # Start slide-out transition
        if old_frame and self.screen_stack and not CAPS.reduce_motion:
            cols, rows = self.engine.get_size()
            new_frame = self.screen_stack[-1].view(cols, rows)
            self._transition = ScreenTransition(
                old_frame, new_frame, direction="pop", duration=0.15,
            )
        else:
            self.engine.invalidate()  # Force full repaint on return

    def _create_screen(self, action_string: str) -> object | None:
        """Create a screen instance from a routing action string."""
        parts = action_string.split(":")
        name = parts[1]

        if name == "browse" and len(parts) >= 3:
            db_path = ":".join(parts[2:])
            return ConversationBrowserView(db_path)
        elif name == "view" and len(parts) >= 4:
            db_path = ":".join(parts[2:-1])
            uuid = parts[-1]
            return ConversationDataView(db_path, uuid)
        elif name == "recover":
            return RecoveryWizardView(self.ctx.db_path)
        elif name == "merge":
            source_db = ":".join(parts[2:]) if len(parts) >= 3 else ""
            return MergeWizardView(self.ctx.db_path, source_db)
        elif name == "workspaces" and len(parts) >= 3:
            db_path = ":".join(parts[2:])
            return WorkspaceBrowserView(db_path)
        elif name == "storage":
            import os
            storage_dir = os.path.dirname(self.ctx.db_path)
            return StorageBrowserView(storage_dir)
        elif name == "help":
            return HelpOverlay()
        return None
