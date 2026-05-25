#!/usr/bin/env bash
# Compile and install .po → .mo translation files
UUID="syswatch"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCALE_DIR="$HOME/.local/share/locale"

for po in "$SCRIPT_DIR/po"/*.po; do
    lang=$(basename "$po" .po)
    mo_dir="$LOCALE_DIR/$lang/LC_MESSAGES"
    mkdir -p "$mo_dir"
    if msgfmt -o "$mo_dir/$UUID.mo" "$po"; then
        echo "  ✓ $lang"
    else
        echo "  ✗ $lang (error)"
    fi
done
echo "Done — $(ls "$SCRIPT_DIR/po"/*.po | wc -l) languages installed."
