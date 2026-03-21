"""
Event System for the TUI.

Provides a typed event bus, key binding management, and focus tracking.

UX Best Practices enforced:
  - Consistent keyboard shortcuts across all views
  - Context-sensitive key bindings (actions change based on active view)
  - Predictable focus order (tab cycles forward, shift+tab cycles back)
  - Event-driven architecture decouples input from logic
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any


# ==============================================================================
# EVENT TYPES
# ==============================================================================

class EventType(enum.Enum):
    """Enumeration of all event categories."""
    KEY          = "key"
    FOCUS        = "focus"
    BLUR         = "blur"
    RESIZE       = "resize"
    TIMER        = "timer"
    ACTION       = "action"
    NOTIFICATION = "notification"


@dataclass
class Event:
    """
    Base event object.

    UX Best Practice: All events carry enough context for any handler to
    act without coupling to the event source.
    """
    type: EventType
    handled: bool = False
    propagate: bool = True

    def stop_propagation(self) -> None:
        """Prevent this event from reaching further handlers."""
        self.propagate = False

    def mark_handled(self) -> None:
        """Mark this event as fully handled."""
        self.handled = True
        self.propagate = False


@dataclass
class ResizeEvent(Event):
    """Fired when the terminal is resized."""
    cols: int = 80
    rows: int = 24

    def __init__(self, cols: int, rows: int) -> None:
        super().__init__(type=EventType.RESIZE)
        self.cols = cols
        self.rows = rows


@dataclass
class ActionEvent(Event):
    """Application-level action triggered by a key binding or UI interaction."""
    action: str = ""
    payload: Any = None

    def __init__(self, action: str, payload: Any = None) -> None:
        super().__init__(type=EventType.ACTION)
        self.action = action
        self.payload = payload


@dataclass
class NotificationEvent(Event):
    """System notification (toast, status bar update, etc.)."""
    message: str = ""
    severity: str = "info"   # "info", "success", "warning", "error"
    duration: float = 5.0    # Auto-dismiss time in seconds

    def __init__(self, message: str, severity: str = "info",
                 duration: float = 5.0) -> None:
        super().__init__(type=EventType.NOTIFICATION)
        self.message = message
        self.severity = severity
        self.duration = duration


# ==============================================================================
# EVENT BUS — Central Pub/Sub Dispatcher
# ==============================================================================

# Type alias for event handler callbacks
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Central publish-subscribe event dispatcher.

    UX Best Practice: Decoupled event handling ensures UI updates are
    predictable and testable. Components don't need to know who else is
    listening.

    Usage::

        bus = EventBus()
        bus.on(EventType.ACTION, my_handler)
        bus.emit(ActionEvent("save"))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}

    def on(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def off(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    def emit(self, event: Event) -> None:
        """
        Dispatch an event to all registered handlers.

        Handlers are called in registration order. Any handler may call
        ``event.stop_propagation()`` to prevent further handlers from firing.
        """
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            if not event.propagate:
                break
            try:
                handler(event)
            except Exception:
                pass  # Handlers must not crash the event loop

    def clear(self) -> None:
        """Remove all handlers (used during teardown)."""
        self._handlers.clear()


# ==============================================================================
# KEY BINDING MANAGER
# ==============================================================================

@dataclass
class KeyBinding:
    """
    Maps a key combination to a named action.

    UX Best Practice: Named actions decouple key assignments from behavior,
    allowing consistent behavior even if keymaps change.
    """
    key: str             # Key name (e.g., "q", "enter", "escape", "ctrl+s")
    action: str          # Action identifier (e.g., "quit", "confirm", "save")
    description: str     # Human-readable description for help display
    context: str = ""    # Context scope (empty = global)


class KeyBindingManager:
    """
    Context-sensitive key binding dispatcher.

    UX Best Practice: Global bindings (e.g., Quit, Help) are always available.
    Context-specific bindings override globals when a view is active.
    This ensures users can always rely on core shortcuts working everywhere.

    Usage::

        kb = KeyBindingManager()
        kb.register("q", "quit", "Quit application")
        kb.register("enter", "confirm", "Confirm", context="modal")
        action = kb.resolve("q")            # → "quit"
        action = kb.resolve("q", "modal")   # → "quit" (global fallback)
    """

    def __init__(self) -> None:
        self._bindings: list[KeyBinding] = []

    def register(self, key: str, action: str, description: str = "",
                 context: str = "") -> None:
        """Register a key binding. Context-specific bindings take priority."""
        self._bindings.append(KeyBinding(
            key=key, action=action, description=description, context=context,
        ))

    def unregister(self, key: str, context: str = "") -> None:
        """Remove a previously registered binding."""
        self._bindings = [
            b for b in self._bindings
            if not (b.key == key and b.context == context)
        ]

    def resolve(self, key: str, context: str = "") -> Optional[str]:
        """
        Resolve a key press to an action name.

        Priority: context-specific binding > global binding.
        """
        # First try context-specific
        if context:
            for b in self._bindings:
                if b.key == key and b.context == context:
                    return b.action

        # Fallback to global
        for b in self._bindings:
            if b.key == key and b.context == "":
                return b.action

        return None

    def get_hints(self, context: str = "") -> list[tuple[str, str]]:
        """
        Get all bindings for display in the help footer/overlay.

        Returns list of (key_display, description) tuples sorted by relevance.

        UX Best Practice: Discoverable shortcuts reduce learning curve.
        Show the most relevant bindings for the current context.
        """
        seen: set[str] = set()
        hints: list[tuple[str, str]] = []

        # Context-specific first
        if context:
            for b in self._bindings:
                if b.context == context and b.action not in seen:
                    hints.append((b.key, b.description or b.action))
                    seen.add(b.action)

        # Then globals
        for b in self._bindings:
            if b.context == "" and b.action not in seen:
                hints.append((b.key, b.description or b.action))
                seen.add(b.action)

        return hints


# ==============================================================================
# FOCUS MANAGER
# ==============================================================================

class FocusManager:
    """
    Manages focus cycling across focusable components.

    UX Best Practices enforced:
      - Predictable tab order (left-to-right, top-to-bottom)
      - Only one element has focus at a time
      - Focus wraps at boundaries (last → first, first → last)
      - Focus state is always visible to the user via component styling
    """

    def __init__(self) -> None:
        self._focusables: list[str] = []  # Ordered component IDs
        self._current: int = -1

    @property
    def current_id(self) -> Optional[str]:
        """ID of the currently focused component, or None."""
        if 0 <= self._current < len(self._focusables):
            return self._focusables[self._current]
        return None

    def register(self, component_id: str) -> None:
        """Add a focusable component to the focus chain."""
        if component_id not in self._focusables:
            self._focusables.append(component_id)
            if self._current == -1:
                self._current = 0

    def unregister(self, component_id: str) -> None:
        """Remove a component from the focus chain."""
        if component_id in self._focusables:
            idx = self._focusables.index(component_id)
            self._focusables.remove(component_id)
            if self._current >= len(self._focusables):
                self._current = max(0, len(self._focusables) - 1)
            elif idx < self._current:
                self._current -= 1

    def focus_next(self) -> Optional[str]:
        """
        Move focus to the next component in the chain (wraps).

        UX Best Practice: Tab key cycles focus forward.
        """
        if not self._focusables:
            return None
        self._current = (self._current + 1) % len(self._focusables)
        return self._focusables[self._current]

    def focus_prev(self) -> Optional[str]:
        """
        Move focus to the previous component in the chain (wraps).

        UX Best Practice: Shift+Tab cycles focus backward.
        """
        if not self._focusables:
            return None
        self._current = (self._current - 1) % len(self._focusables)
        return self._focusables[self._current]

    def focus_id(self, component_id: str) -> bool:
        """Directly focus a specific component by ID."""
        if component_id in self._focusables:
            self._current = self._focusables.index(component_id)
            return True
        return False

    def has_focus(self, component_id: str) -> bool:
        """Check if a specific component currently has focus."""
        return self.current_id == component_id

    def reset(self) -> None:
        """Clear all focusable registrations."""
        self._focusables.clear()
        self._current = -1
