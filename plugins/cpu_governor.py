"""CPU frequency governor plugin."""

import glob

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from base import BasePlugin


GOVERNOR_CSS = {
    'powersave':    'governor-powersave',
    'performance':  'governor-performance',
    'schedutil':    'governor-schedutil',
    'ondemand':     'governor-ondemand',
    'conservative': 'governor-conservative',
    'userspace':    'governor-userspace',
}


class Plugin(BasePlugin):

    def _build_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class('plugin-section')

        title = Gtk.Label(label="CPU GOVERNOR")
        title.set_name('section-title')
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)

        self._gov_label = Gtk.Label(label="–")
        self._gov_label.set_xalign(0)
        self._gov_label.get_style_context().add_class('monospace')
        box.pack_start(self._gov_label, False, False, 0)

        self._freq_label = Gtk.Label(label="")
        self._freq_label.set_xalign(0)
        self._freq_label.get_style_context().add_class('status-dim')
        box.pack_start(self._freq_label, False, False, 0)

        self._widget = box

    def get_data(self) -> dict:
        gov_paths  = sorted(glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'))
        freq_paths = sorted(glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq'))

        governors: dict[str, str] = {}
        for p in gov_paths:
            cpu = p.split('/')[5]
            try:
                governors[cpu] = open(p).read().strip()
            except OSError:
                governors[cpu] = 'unknown'

        freqs: dict[str, int] = {}
        for p in freq_paths:
            cpu = p.split('/')[5]
            try:
                freqs[cpu] = int(open(p).read().strip()) // 1000  # kHz → MHz
            except (OSError, ValueError):
                pass

        return {'governors': governors, 'freqs': freqs}

    def _apply_data(self, data: dict) -> bool:
        governors = data['governors']
        freqs     = data['freqs']

        if not governors:
            self._gov_label.set_text("cpufreq not available")
            self._freq_label.set_text("")
            return False

        # Group CPUs by governor
        groups: dict[str, list[int]] = {}
        for cpu, gov in governors.items():
            try:
                num = int(cpu[3:])
            except ValueError:
                continue
            groups.setdefault(gov, []).append(num)

        sc = self._gov_label.get_style_context()
        for css in GOVERNOR_CSS.values():
            sc.remove_class(css)

        lines = []
        dominant_gov = None
        for gov, nums in sorted(groups.items()):
            nums_s = sorted(nums)
            if len(nums_s) > 2:
                cpu_str = f"cpu{nums_s[0]}–{nums_s[-1]}"
            elif len(nums_s) == 1:
                cpu_str = f"cpu{nums_s[0]}"
            else:
                cpu_str = ', '.join(f"cpu{n}" for n in nums_s)
            lines.append(f"{cpu_str}:  {gov}")
            if dominant_gov is None or len(nums_s) > len(groups.get(dominant_gov, [])):
                dominant_gov = gov

        self._gov_label.set_text('\n'.join(lines))
        if dominant_gov:
            css = GOVERNOR_CSS.get(dominant_gov, '')
            if css:
                sc.add_class(css)

        # Frequency summary
        if freqs:
            avg = int(sum(freqs.values()) / len(freqs))
            mn  = min(freqs.values())
            mx  = max(freqs.values())
            if mx - mn < 50:
                self._freq_label.set_text(f"  ⏱ {avg} MHz")
            else:
                self._freq_label.set_text(f"  ⏱ {mn}–{mx} MHz  (avg {avg})")
        else:
            self._freq_label.set_text("")

        return False
