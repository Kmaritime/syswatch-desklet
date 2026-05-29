"""IP / hostname reachability monitor plugin."""

import re
import subprocess
import concurrent.futures

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from base import BasePlugin


class Plugin(BasePlugin):

    def _build_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.get_style_context().add_class('plugin-section')

        title = Gtk.Label(label="NETWORK")
        title.set_name('section-title')
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.pack_start(self._list_box, False, False, 0)

        # Pre-build one row per configured host
        self._row_widgets: dict[str, dict] = {}  # host -> {icon, latency_lbl}
        for h in self.config.get('hosts', []):
            host = h.get('host', '')
            if host:
                self._add_host_row(h)

        self._widget = box

    def _add_host_row(self, h: dict):
        host = h.get('host', '')
        name = h.get('name', host)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        icon = Gtk.Label(label="○")
        icon.set_width_chars(2)
        icon.get_style_context().add_class('status-unknown')
        row.pack_start(icon, False, False, 0)

        name_lbl = Gtk.Label(label=name[:18])
        name_lbl.set_xalign(0)
        name_lbl.set_width_chars(18)
        name_lbl.get_style_context().add_class('monospace')
        row.pack_start(name_lbl, False, False, 0)

        host_lbl = Gtk.Label(label=host[:18])
        host_lbl.set_xalign(0)
        host_lbl.set_width_chars(18)
        host_lbl.get_style_context().add_class('status-dim')
        row.pack_start(host_lbl, False, False, 0)

        lat_lbl = Gtk.Label(label="–")
        lat_lbl.set_xalign(1)
        lat_lbl.set_width_chars(10)
        row.pack_end(lat_lbl, False, False, 0)

        self._list_box.pack_start(row, False, False, 0)
        self._row_widgets[host] = {'icon': icon, 'latency': lat_lbl}

    def get_data(self) -> dict:
        hosts = [h.get('host', '') for h in self.config.get('hosts', []) if h.get('host')]
        if not hosts:
            return {'results': {}}

        results: dict[str, dict] = {}
        # Ping all hosts in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(hosts)) as ex:
            futures = {ex.submit(self._ping, h): h for h in hosts}
            for fut in concurrent.futures.as_completed(futures):
                h = futures[fut]
                try:
                    results[h] = fut.result()
                except Exception:
                    results[h] = {'online': False, 'latency_ms': None}

        return {'results': results}

    @staticmethod
    def _ping(host: str) -> dict:
        try:
            r = subprocess.run(
                ['ping', '-c', '1', '-W', '1', host],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0:
                m = re.search(r'time[=<]([\d.]+)\s*ms', r.stdout)
                lat = float(m.group(1)) if m else 0.0
                return {'online': True, 'latency_ms': lat}
            return {'online': False, 'latency_ms': None}
        except (subprocess.TimeoutExpired, Exception):
            return {'online': False, 'latency_ms': None}

    def _apply_data(self, data: dict) -> bool:
        for host, result in data.get('results', {}).items():
            row = self._row_widgets.get(host)
            if not row:
                continue

            icon: Gtk.Label = row['icon']
            lat_lbl: Gtk.Label = row['latency']
            sc = icon.get_style_context()
            for cls in ('status-ok', 'status-error', 'status-unknown'):
                sc.remove_class(cls)

            if result['online']:
                icon.set_text('●')
                sc.add_class('status-ok')
                ms = result['latency_ms']
                lat_lbl.set_text(f"{ms:.1f} ms" if ms and ms > 0.5 else "< 1 ms")
            else:
                icon.set_text('○')
                sc.add_class('status-error')
                lat_lbl.set_text("OFFLINE")

        self._list_box.show_all()
        return False
