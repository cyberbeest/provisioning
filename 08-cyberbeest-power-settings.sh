#!/bin/bash
# Installs the Cyberbeest Power Settings GUI (lock/shutdown timing config)
# and its Whisker-menu launcher -- see lib/cyberbeest-power-settings.py.
#
# Note: this GUI only edits ~/.config/cyberbeest/power-settings.conf: the
# lock-shutdown-watcher user service that actually reads that file and
# enforces the lock/shutdown/suspend-cycle behavior is a separate piece of
# this machine's setup not yet migrated into this repo. Until that lands,
# installing this GUI gives users a settings screen with no effect yet.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/08-cyberbeest-power-settings.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing cyberbeest-power-settings ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get update -qq
apt-get install -y python3-gi gir1.2-gtk-3.0

echo "--- Installing GUI script to $TARGET_HOME/.local/bin/cyberbeest-power-settings ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-power-settings.py" \
	"$TARGET_HOME/.local/bin/cyberbeest-power-settings"

echo "--- Installing icon ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" \
	"$TARGET_HOME/Pictures/Cyberbeest-black.png"

echo "--- Installing launcher desktop entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-power.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Power Settings
Comment=Configure Cyberbeest lock/suspend/notification behavior
Exec=$TARGET_HOME/.local/bin/cyberbeest-power-settings
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-power.desktop"

echo "=== $(date) : done ==="
