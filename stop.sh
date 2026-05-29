#!/usr/bin/env bash
PID=$(pgrep -f "syswatch-desklet/main.py")
if [ -n "$PID" ]; then
    kill "$PID"
    echo "SysWatch gestoppt (PID $PID)"
else
    echo "SysWatch läuft nicht"
fi
