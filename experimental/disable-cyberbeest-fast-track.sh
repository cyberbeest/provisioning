#!/bin/bash
# Undo for enable-cyberbeest-fast-track.sh.
set -euo pipefail
TARGET_USER="${SUDO_USER:?run via sudo}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
sudo -u "$TARGET_USER" env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="$TARGET_HOME/.Xauthority" \
	"$TARGET_HOME/.local/bin/fasttrack-panel-icon.sh" remove || true
pkill -u "$TARGET_USER" -f '[c]yberbeest-fasttrack\.sh' || true
rm -f "$TARGET_HOME/.config/autostart/cyberbeest-fasttrack.desktop" "$TARGET_HOME/.local/share/applications/cyberbeest-fast-track.desktop" \
	"$TARGET_HOME"/.local/bin/{cyberbeest-fasttrack.sh,fasttrack-genmon.sh,fasttrack-menu.py,fasttrack-panel-icon.sh}
rm -rf "$TARGET_HOME/.local/state/cyberbeest-fasttrack"
echo "Fast Track removed."
