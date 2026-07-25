#!/bin/bash
# Installs the custom Lock/Restart/Shut Down logout dialog used as the
# Whisker menu's logout command -- see lib/cyberbeest-logout.py.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/09-cyberbeest-logout-dialog.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing cyberbeest-logout dialog ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the dialog needs) ---"
apt-get update -qq
apt-get install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing dialog script to $TARGET_HOME/.local/bin/cyberbeest-logout ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-logout.py" \
	"$TARGET_HOME/.local/bin/cyberbeest-logout"

echo "--- Installing logo ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-green.png" \
	"$TARGET_HOME/Pictures/Cyberbeest-green.png"

echo "=== $(date) : done ==="
