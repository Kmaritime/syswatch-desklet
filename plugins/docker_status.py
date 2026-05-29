"""Container status plugin — supports Docker and Podman."""

import json
import shutil
import subprocess

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from base import BasePlugin


STATE_MAP = {
    'running':    ('●', 'docker-running'),
    'exited':     ('○', 'docker-exited'),
    'paused':     ('◐', 'docker-paused'),
    'restarting': ('↻', 'docker-restarting'),
    'created':    ('○', 'docker-created'),
    'dead':       ('✕', 'docker-exited'),
    'removing':   ('✕', 'docker-exited'),
}


def _parse_state(container: dict) -> str:
    state  = container.get('State', '').lower()
    status = container.get('Status', '').lower()
    for key in STATE_MAP:
        if key in state or key in status:
            return key
    return 'created'


def _find_runtime() -> str | None:
    for rt in ('docker', 'podman'):
        if shutil.which(rt):
            return rt
    return None


class Plugin(BasePlugin):

    def _build_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.get_style_context().add_class('plugin-section')

        self._title_lbl = Gtk.Label(label="CONTAINERS")
        self._title_lbl.set_name('section-title')
        self._title_lbl.set_xalign(0)
        box.pack_start(self._title_lbl, False, False, 0)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.pack_start(self._list_box, False, False, 0)

        self._widget = box
        self._runtime: str | None = None       # detected lazily, cached for session
        self._last_containers: list | None = None  # last successful result

    def get_data(self) -> dict:
        if self._runtime is None:
            self._runtime = _find_runtime() or ''
        rt = self._runtime
        if not rt:
            return {'error': 'docker / podman not found', 'containers': [], 'runtime': None}
        try:
            r = subprocess.run(
                [rt, 'ps', '-a', '--format', '{{json .}}'],
                capture_output=True, text=True, timeout=8
            )
            if r.returncode != 0:
                err = (r.stderr.strip() or f'{rt} error')[:80]
                return {'error': err, 'containers': self._last_containers or [], 'runtime': rt, 'stale': True}
            containers = []
            for line in r.stdout.splitlines():
                line = line.strip()
                if line:
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            self._last_containers = containers
            return {'containers': containers, 'error': None, 'runtime': rt}
        except subprocess.TimeoutExpired:
            return {'error': f'timeout ({rt})', 'containers': self._last_containers or [], 'runtime': rt, 'stale': True}
        except Exception as exc:
            return {'error': str(exc)[:80], 'containers': self._last_containers or [], 'runtime': rt, 'stale': True}

    def _apply_data(self, data: dict) -> bool:
        rt = data.get('runtime')
        if rt:
            self._title_lbl.set_text(rt.upper())

        for child in self._list_box.get_children():
            self._list_box.remove(child)

        if data.get('error'):
            prefix = "  ⚠ (stale) " if data.get('stale') else "  ⚠ "
            lbl = Gtk.Label(label=f"{prefix}{data['error']}")
            lbl.set_xalign(0)
            lbl.get_style_context().add_class('status-error' if not data.get('stale') else 'status-unknown')
            self._list_box.pack_start(lbl, False, False, 0)
            # fall through to show stale containers below if available
            if not data.get('containers'):
                self._list_box.show_all()
                return False

        containers = data.get('containers', [])
        max_show   = self.config.get('max_containers', 15)

        # Sort: running first, then alphabetically by name
        def sort_key(c):
            state = _parse_state(c)
            return (0 if state == 'running' else 1, self._container_name(c))

        containers = sorted(containers, key=sort_key)

        if not containers:
            lbl = Gtk.Label(label="  no containers found")
            lbl.set_xalign(0)
            lbl.get_style_context().add_class('status-unknown')
            self._list_box.pack_start(lbl, False, False, 0)
        else:
            for c in containers[:max_show]:
                self._list_box.pack_start(self._make_row(c), False, False, 0)
            if len(containers) > max_show:
                more = Gtk.Label(label=f"  … {len(containers) - max_show} more")
                more.set_xalign(0)
                more.get_style_context().add_class('status-unknown')
                self._list_box.pack_start(more, False, False, 0)

        self._list_box.show_all()
        return False

    @staticmethod
    def _container_name(c: dict) -> str:
        name = c.get('Names', c.get('Name', 'unknown'))
        name = name.split(',')[0].strip()
        return name.lstrip('/')

    def _make_row(self, c: dict) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        state            = _parse_state(c)
        icon_ch, css_cls = STATE_MAP.get(state, ('?', ''))

        icon = Gtk.Label(label=icon_ch)
        icon.get_style_context().add_class(css_cls)
        icon.set_width_chars(2)
        row.pack_start(icon, False, False, 0)

        name     = self._container_name(c)
        name_lbl = Gtk.Label(label=name[:26])
        name_lbl.set_xalign(0)
        name_lbl.set_width_chars(26)
        name_lbl.get_style_context().add_class('monospace')
        row.pack_start(name_lbl, False, False, 0)

        status_txt = c.get('Status', state)[:22]
        status_lbl = Gtk.Label(label=status_txt)
        status_lbl.set_xalign(0)
        status_lbl.get_style_context().add_class('status-dim')
        row.pack_start(status_lbl, False, False, 0)

        return row
