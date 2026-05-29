"""BasePlugin — every plugin inherits from this."""

import threading
from gi.repository import GLib


class BasePlugin:
    """
    Subclasses must implement:
      _build_widget()  — create GTK widgets, store root in self._widget
      get_data()       — fetch data (may block; runs in worker thread)
      _apply_data(data) — update widgets (runs in GTK main thread), return False
    """

    def __init__(self, config: dict):
        self.config      = config
        self._widget     = None
        self._resize_cb  = None   # injected by main window after plugin load
        self._build_widget()

    # ── must override ─────────────────────────────────────────────────────────

    def _build_widget(self):
        raise NotImplementedError

    def get_data(self) -> dict:
        raise NotImplementedError

    def _apply_data(self, data: dict) -> bool:
        raise NotImplementedError

    # ── public API ────────────────────────────────────────────────────────────

    def get_widget(self):
        return self._widget

    def refresh(self):
        """Non-blocking: spawn background thread, then schedule UI update."""
        t = threading.Thread(target=self._bg_refresh, daemon=True)
        t.start()

    # ── internal ──────────────────────────────────────────────────────────────

    def _bg_refresh(self):
        try:
            data = self.get_data()
            GLib.idle_add(self._update, data)
        except Exception as exc:
            print(f"[{self.__class__.__name__}] bg error: {exc}")

    def _update(self, data: dict) -> bool:
        self._apply_data(data)
        if self._resize_cb:
            self._resize_cb()
        return False
