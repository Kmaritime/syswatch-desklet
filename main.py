#!/usr/bin/env python3
"""SysWatch Desklet — Modular Linux desktop monitoring widget."""

import math
import os
import sys
import importlib
import json

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

try:
    import cairo
    _CAIRO_SOURCE = cairo.OPERATOR_SOURCE
    _CAIRO_OVER   = cairo.OPERATOR_OVER
except ImportError:
    _CAIRO_SOURCE = 1
    _CAIRO_OVER   = 2


class SysWatchDesklet(Gtk.Window):

    def __init__(self, config_path: str):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.config_path = config_path
        self.config = self._load_config()
        self._plugins: list = []   # (name, plugin_instance, plugin_cfg)

        self._setup_window()
        self._apply_styles()
        self._load_plugins()
        self._build_ui()
        self._start_timers()

    # ─────────────────────────────────────────────────────────── config

    def _load_config(self) -> dict:
        with open(self.config_path) as fh:
            return json.load(fh)

    # ─────────────────────────────────────────────────────────── window

    def _setup_window(self):
        cfg = self.config.get('window', {})
        self.set_title("SysWatch")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_below(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.move(cfg.get('x', 10), cfg.get('y', 10))
        self.set_default_size(cfg.get('width', 400), 1)
        self.connect('destroy', self._on_destroy)
        self.connect('draw', self._on_draw)

    def _on_destroy(self, _widget):
        for src in getattr(self, '_timer_sources', []):
            GLib.source_remove(src)
        self._timer_sources = []
        Gtk.main_quit()

    def _on_draw(self, _widget, cr):
        cfg    = self.config.get('window', {})
        r, g, b = cfg.get('bg_rgb', [0.04, 0.04, 0.10])
        alpha  = cfg.get('opacity', 0.88)
        radius = cfg.get('corner_radius', 10)
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        pi = math.pi

        # Clear to fully transparent
        cr.set_operator(_CAIRO_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()

        # Draw rounded-rectangle background
        cr.set_operator(_CAIRO_OVER)
        cr.new_path()
        cr.arc(radius,     radius,     radius,  pi,        1.5 * pi)
        cr.arc(w - radius, radius,     radius, -0.5 * pi,  0)
        cr.arc(w - radius, h - radius, radius,  0,          0.5 * pi)
        cr.arc(radius,     h - radius, radius,  0.5 * pi,   pi)
        cr.close_path()
        cr.set_source_rgba(r, g, b, alpha)
        cr.fill()
        return False  # let GTK render child widgets on top

    # ─────────────────────────────────────────────────────────── styles

    def _apply_styles(self):
        css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'style.css')
        provider = Gtk.CssProvider()
        if os.path.exists(css_path):
            provider.load_from_path(css_path)
        else:
            provider.load_from_data(b"* { color: #d0d0e0; }")
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    # ─────────────────────────────────────────────────────────── plugins

    def _load_plugins(self):
        plugins_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plugins')
        if plugins_dir not in sys.path:
            sys.path.insert(0, plugins_dir)

        for name, pcfg in self.config.get('plugins', {}).items():
            if not pcfg.get('enabled', True):
                continue
            try:
                mod    = importlib.import_module(name)
                plugin = mod.Plugin(pcfg)
                self._plugins.append((name, plugin, pcfg))
                print(f"[syswatch] loaded plugin: {name}")
            except Exception as exc:
                print(f"[syswatch] plugin '{name}' failed: {exc}", file=sys.stderr)

    # ─────────────────────────────────────────────────────────── UI

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        hdr = Gtk.Label(label="⚙ SysWatch")
        hdr.set_name('header')
        hdr.set_xalign(0)
        outer.pack_start(hdr, False, False, 0)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.get_style_context().add_class('header-sep')
        outer.pack_start(sep, False, False, 6)

        for name, plugin, _cfg in self._plugins:
            try:
                plugin._resize_cb = self._auto_resize   # inject resize hook
                widget = plugin.get_widget()
                if widget:
                    outer.pack_start(widget, False, True, 2)
            except Exception as exc:
                print(f"[syswatch] widget error '{name}': {exc}", file=sys.stderr)

        self.add(outer)
        self.show_all()

    # ─────────────────────────────────────────────────────────── resize

    def _auto_resize(self):
        """Shrink height to 1 so GTK recalculates natural height from content."""
        w = self.config.get('window', {}).get('width', 400)
        self.resize(w, 1)

    # ─────────────────────────────────────────────────────────── timers

    def _start_timers(self):
        self._timer_sources: list = []
        default_interval = self.config.get('refresh_interval', 5)
        for name, plugin, pcfg in self._plugins:
            interval = max(1, pcfg.get('refresh', default_interval))
            GLib.idle_add(self._do_once, name, plugin)
            src = GLib.timeout_add_seconds(interval, self._do_refresh, name, plugin)
            self._timer_sources.append(src)

    @staticmethod
    def _do_once(name: str, plugin) -> bool:
        """Initial one-shot refresh at startup."""
        try:
            plugin.refresh()
        except Exception as exc:
            print(f"[syswatch] initial refresh '{name}': {exc}", file=sys.stderr)
        return False  # GLib.SOURCE_REMOVE — do not repeat

    @staticmethod
    def _do_refresh(name: str, plugin) -> bool:
        """Periodic refresh — called by timeout, must return True to keep timer alive."""
        try:
            plugin.refresh()
        except Exception as exc:
            print(f"[syswatch] refresh error '{name}': {exc}", file=sys.stderr)
        return True  # GLib.SOURCE_CONTINUE


# ─────────────────────────────────────────────────────────────────────────────

def main():
    base_dir    = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, 'config.json')
    if not os.path.exists(config_path):
        sys.exit(f"Config not found: {config_path}")

    SysWatchDesklet(config_path)
    Gtk.main()


if __name__ == '__main__':
    main()
