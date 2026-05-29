#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }

# Single-instance guard
if pgrep -f "syswatch-desklet/main.py" > /dev/null 2>&1; then
    echo "SysWatch läuft bereits (PID $(pgrep -f syswatch-desklet/main.py))"
    exit 0
fi

# Dependency checks
python3 -c "import gi" 2>/dev/null || die "PyGObject fehlt: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
python3 -c "import psutil" 2>/dev/null || die "psutil fehlt: sudo apt install python3-psutil"

DISPLAY="${DISPLAY:-:0}" nohup python3 "$SCRIPT_DIR/main.py" > /tmp/syswatch.log 2>&1 &
echo "SysWatch gestartet (PID $!)"
