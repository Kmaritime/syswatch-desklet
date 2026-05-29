# SysWatch — Linux System Monitor Widget

A dark-themed, always-on-desktop system monitoring widget for Linux.  
Built with **Python 3 + GTK 3** — runs on any desktop environment (GNOME, KDE, XFCE, Cinnamon, …).

---

## Features

| Section | Details |
|---|---|
| **CPU / RAM** | Usage bars with colour thresholds (green → amber → red), optional per-core mini-bars |
| **GPU** | Auto-detects NVIDIA (`nvidia-smi`), AMD (`amdgpu`/`radeon` sysfs), Intel iGPU (i915/Xe). Hidden if no GPU found. |
| **CPU Governor** | Scaling governor per core group + current frequency range |
| **Containers** | Docker **and** Podman — lists all containers sorted by state (running first). Falls back to last-known data if daemon is unreachable. |
| **Network** | Parallel ICMP ping with latency for any number of user-defined hosts |

---

## Requirements

| Dependency | Purpose |
|---|---|
| Python 3.10+ | Runtime |
| `python3-gi` | GTK 3 bindings (PyGObject) |
| `python3-cairo` | Transparent rounded background |
| `python3-psutil` | CPU / RAM metrics |
| `docker` or `podman` (optional) | Container section |
| `nvidia-smi` (optional) | NVIDIA GPU support |

Install on Debian/Ubuntu/Mint:

```bash
sudo apt install python3-gi python3-cairo python3-psutil gir1.2-gtk-3.0
```

---

## Installation & Start

```bash
git clone https://github.com/Kmaritime/syswatch-desklet.git
cd syswatch-desklet
./start.sh          # launches widget in background
./stop.sh           # stops it
```

Or run directly:

```bash
python3 main.py
```

---

## Configuration

Edit **`config.json`** to customise position, plugins and refresh intervals:

```json
{
  "window": {
    "x": 50,
    "y": 50,
    "width": 420,
    "opacity": 0.88,
    "bg_rgb": [0.04, 0.04, 0.10],
    "corner_radius": 10
  },
  "refresh_interval": 5,
  "plugins": {
    "system_stats": { "enabled": true, "refresh": 2, "show_per_core": false },
    "gpu_stats":    { "enabled": true, "refresh": 3 },
    "cpu_governor": { "enabled": true, "refresh": 10 },
    "docker_status":{ "enabled": true, "refresh": 10, "max_containers": 20 },
    "ip_monitor":   {
      "enabled": true, "refresh": 30,
      "hosts": [
        {"name": "Router", "host": "192.168.1.1"},
        {"name": "NAS",    "host": "192.168.1.10"}
      ]
    }
  }
}
```

Disable any section by setting `"enabled": false`. Plugin order in `config.json` controls display order.

---

## Architecture

```
main.py               — GTK window, plugin loader, timer management
plugins/
  base.py             — BasePlugin: background-thread refresh + GTK idle_add
  system_stats.py     — CPU & RAM
  gpu_stats.py        — GPU (NVIDIA / AMD / Intel)
  cpu_governor.py     — scaling governor + frequency
  docker_status.py    — Docker / Podman containers
  ip_monitor.py       — ICMP ping monitor
style.css             — dark HUD theme
config.json           — user configuration
```

Each plugin runs its data collection in a **background thread** (never blocks the UI), then schedules the widget update back on the GTK main thread via `GLib.idle_add`.

---

## GPU Support

| Vendor | Detection | Metrics |
|---|---|---|
| NVIDIA | `nvidia-smi` present | Usage %, VRAM used/total, temperature |
| AMD | `amdgpu`/`radeon` driver in `/sys/class/drm/` | Usage %, VRAM, hwmon temperature |
| Intel | `i915`/`xe` driver in `/sys/class/drm/` | Current / max GT frequency |

GPU type is detected **once** at startup and cached — no repeated sysfs scans.

---

## Writing a Plugin

Create `plugins/myplugin.py`:

```python
from base import BasePlugin
from gi.repository import Gtk

class Plugin(BasePlugin):
    def _build_widget(self):
        self._label = Gtk.Label(label="–")
        self._widget = self._label          # must set self._widget

    def get_data(self) -> dict:             # runs in background thread
        return {"value": 42}

    def _apply_data(self, data: dict) -> bool:   # runs in GTK main thread
        self._label.set_text(str(data["value"]))
        return False
```

Then add an entry to `config.json`:

```json
"myplugin": { "enabled": true, "refresh": 5 }
```

---

## License

MIT — see [LICENSE](LICENSE).
