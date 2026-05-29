"""GPU stats plugin — supports NVIDIA (nvidia-smi), AMD (amdgpu), Intel (i915/xe)."""

import glob
import os
import re
import shutil
import subprocess

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from base import BasePlugin


def _sysfs(path: str, default=None):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return default


def _detect_gpus() -> list[dict]:
    """Scan system for GPUs once. Returns list of descriptors."""
    gpus = []

    if shutil.which('nvidia-smi'):
        gpus.append({'type': 'nvidia'})
        return gpus  # nvidia-smi covers all NVIDIA cards

    for card_path in sorted(glob.glob('/sys/class/drm/card[0-9]*')):
        if not re.match(r'.*/card\d+$', card_path):
            continue
        dev = os.path.join(card_path, 'device')
        driver_link = os.path.join(dev, 'driver')
        try:
            driver = os.path.basename(os.readlink(driver_link))
        except OSError:
            continue

        if driver in ('amdgpu', 'radeon'):
            gpus.append({'type': 'amd', 'card': os.path.basename(card_path), 'dev': dev})
        elif driver in ('i915', 'xe'):
            gpus.append({'type': 'intel', 'card': os.path.basename(card_path), 'card_path': card_path})

    return gpus


def _nvidia_data() -> dict:
    try:
        r = subprocess.run(
            ['nvidia-smi',
             '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=4
        )
        if r.returncode != 0:
            return {'error': 'nvidia-smi failed', 'type': 'nvidia'}
        parts = [p.strip() for p in r.stdout.strip().split(',')]
        if len(parts) < 5:
            return {'error': 'unexpected nvidia-smi output', 'type': 'nvidia'}
        return {
            'type':         'nvidia',
            'name':         parts[0][:24],
            'util_pct':     float(parts[1]),
            'vram_used_mb': float(parts[2]),
            'vram_total_mb': float(parts[3]),
            'temp_c':       float(parts[4]),
        }
    except subprocess.TimeoutExpired:
        return {'error': 'nvidia-smi timeout', 'type': 'nvidia'}
    except Exception as exc:
        return {'error': str(exc)[:60], 'type': 'nvidia'}


def _amd_data(gpu: dict) -> dict:
    dev = gpu['dev']
    result: dict = {'type': 'amd', 'name': gpu['card']}

    raw = _sysfs(os.path.join(dev, 'gpu_busy_percent'))
    if raw is not None:
        try:
            result['util_pct'] = float(raw)
        except ValueError:
            pass

    vram_used  = _sysfs(os.path.join(dev, 'mem_info_vram_used'))
    vram_total = _sysfs(os.path.join(dev, 'mem_info_vram_total'))
    if vram_used and vram_total:
        try:
            result['vram_used_mb']  = int(vram_used)  / 1_048_576
            result['vram_total_mb'] = int(vram_total) / 1_048_576
        except ValueError:
            pass

    hwmon_temps = glob.glob(os.path.join(dev, 'hwmon', 'hwmon*', 'temp1_input'))
    if hwmon_temps:
        raw_t = _sysfs(hwmon_temps[0])
        if raw_t:
            try:
                result['temp_c'] = int(raw_t) / 1000
            except ValueError:
                pass

    return result


def _intel_data(gpu: dict) -> dict:
    card_path = gpu['card_path']
    result: dict = {'type': 'intel', 'name': gpu['card']}

    cur  = _sysfs(os.path.join(card_path, 'gt_cur_freq_mhz'))
    maxf = _sysfs(os.path.join(card_path, 'gt_max_freq_mhz'))
    if cur:
        try:
            result['cur_freq_mhz'] = int(cur)
        except ValueError:
            pass
    if maxf:
        try:
            result['max_freq_mhz'] = int(maxf)
        except ValueError:
            pass

    return result


class Plugin(BasePlugin):

    def _build_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class('plugin-section')

        title = Gtk.Label(label="GPU")
        title.set_name('section-title')
        title.set_xalign(0)
        box.pack_start(title, False, False, 0)

        self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.pack_start(self._rows_box, False, False, 0)

        self._widget = box
        self._gpus: list | None = None  # detected lazily on first get_data()

    def get_data(self) -> dict:
        if self._gpus is None:
            self._gpus = _detect_gpus()

        results = []
        for gpu in self._gpus:
            if gpu['type'] == 'nvidia':
                results.append(_nvidia_data())
            elif gpu['type'] == 'amd':
                results.append(_amd_data(gpu))
            elif gpu['type'] == 'intel':
                results.append(_intel_data(gpu))

        return {'gpus': results}

    def _apply_data(self, data: dict) -> bool:
        for child in self._rows_box.get_children():
            self._rows_box.remove(child)

        gpus = data.get('gpus', [])

        if not gpus:
            lbl = Gtk.Label(label="  no GPU detected")
            lbl.set_xalign(0)
            lbl.get_style_context().add_class('status-unknown')
            self._rows_box.pack_start(lbl, False, False, 0)
            self._rows_box.show_all()
            return False

        for gpu in gpus:
            self._rows_box.pack_start(self._make_row(gpu), False, False, 0)

        self._rows_box.show_all()
        return False

    def _make_row(self, gpu: dict) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)

        if 'error' in gpu:
            lbl = Gtk.Label(label=f"  ⚠ {gpu['error']}")
            lbl.set_xalign(0)
            lbl.get_style_context().add_class('status-error')
            row.pack_start(lbl, False, False, 0)
            return row

        # Utilisation bar (NVIDIA / AMD)
        if 'util_pct' in gpu:
            bar = Gtk.ProgressBar()
            bar.set_show_text(True)
            util = gpu['util_pct']
            name = gpu.get('name', gpu.get('type', '').upper())

            vram_str = ''
            if 'vram_used_mb' in gpu:
                used  = gpu['vram_used_mb']
                total = gpu['vram_total_mb']
                if total >= 1024:
                    vram_str = f"  VRAM {used/1024:.1f}/{total/1024:.1f} GB"
                else:
                    vram_str = f"  VRAM {used:.0f}/{total:.0f} MB"

            temp_str = f"  {gpu['temp_c']:.0f}°C" if 'temp_c' in gpu else ''
            bar.set_text(f"{name}  {util:.0f}%{vram_str}{temp_str}")
            bar.set_fraction(util / 100)

            sc = bar.get_style_context()
            for cls in ('warning', 'danger'):
                sc.remove_class(cls)
            if util >= 90:
                sc.add_class('danger')
            elif util >= 70:
                sc.add_class('warning')

            row.pack_start(bar, False, False, 0)

        # Intel: frequency only (no utilisation sysfs on i915)
        elif 'cur_freq_mhz' in gpu:
            cur  = gpu['cur_freq_mhz']
            maxf = gpu.get('max_freq_mhz', 0)
            text = f"  {gpu.get('name', 'Intel GPU')}  {cur}"
            if maxf:
                text += f"/{maxf} MHz"
            else:
                text += " MHz"
            lbl = Gtk.Label(label=text)
            lbl.set_xalign(0)
            lbl.get_style_context().add_class('monospace')
            row.pack_start(lbl, False, False, 0)

        return row
