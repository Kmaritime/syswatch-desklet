"""CPU and RAM usage plugin."""

import psutil

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from base import BasePlugin


def _level_class(percent: float) -> str:
    if percent >= 90:
        return 'danger'
    if percent >= 70:
        return 'warning'
    return ''


class Plugin(BasePlugin):

    def _build_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class('plugin-section')

        title = Gtk.Label(label="CPU / RAM")
        title.set_name('section-title')
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)

        self._cpu_bar = Gtk.ProgressBar()
        self._cpu_bar.set_show_text(True)
        self._cpu_bar.set_text("CPU: –")
        box.pack_start(self._cpu_bar, False, False, 0)

        self._ram_bar = Gtk.ProgressBar()
        self._ram_bar.set_show_text(True)
        self._ram_bar.set_text("RAM: –")
        box.pack_start(self._ram_bar, False, False, 0)

        # Optional per-core mini bars
        self._core_bars: list = []
        if self.config.get('show_per_core', False):
            core_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            core_count = psutil.cpu_count(logical=True) or 1
            for _ in range(min(core_count, 16)):
                bar = Gtk.ProgressBar()
                bar.set_orientation(Gtk.Orientation.VERTICAL)
                bar.set_inverted(True)
                bar.set_size_request(8, 28)
                core_box.pack_start(bar, False, False, 0)
                self._core_bars.append(bar)
            box.pack_start(core_box, False, False, 2)

        self._widget = box

    def get_data(self) -> dict:
        cores    = psutil.cpu_percent(percpu=True, interval=0.4)
        cpu_avg  = sum(cores) / len(cores) if cores else 0.0
        vm       = psutil.virtual_memory()
        return {
            'cpu_total':   cpu_avg,
            'cpu_cores':   cores,
            'ram_percent': vm.percent,
            'ram_used_gb': vm.used   / 1_073_741_824,
            'ram_total_gb': vm.total / 1_073_741_824,
        }

    def _apply_data(self, data: dict) -> bool:
        cpu = data['cpu_total']
        self._cpu_bar.set_fraction(cpu / 100)
        self._cpu_bar.set_text(f"CPU: {cpu:.1f}%")
        self._set_level(self._cpu_bar, cpu)

        ram = data['ram_percent']
        self._ram_bar.set_fraction(ram / 100)
        self._ram_bar.set_text(
            f"RAM: {data['ram_used_gb']:.1f} / {data['ram_total_gb']:.1f} GB  ({ram:.0f}%)"
        )
        self._set_level(self._ram_bar, ram)

        for i, bar in enumerate(self._core_bars):
            val = data['cpu_cores'][i] if i < len(data['cpu_cores']) else 0.0
            bar.set_fraction(val / 100)

        return False

    @staticmethod
    def _set_level(bar: Gtk.ProgressBar, pct: float):
        sc = bar.get_style_context()
        for cls in ('warning', 'danger'):
            sc.remove_class(cls)
        cls = _level_class(pct)
        if cls:
            sc.add_class(cls)
