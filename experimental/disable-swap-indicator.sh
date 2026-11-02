#!/bin/bash
# Undo for enable-swap-indicator.sh.
set -euo pipefail
TARGET_USER="${SUDO_USER:?run via sudo}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
sudo -u "$TARGET_USER" env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="$TARGET_HOME/.Xauthority" \
	DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$TARGET_USER")/bus" \
	"$TARGET_HOME/.local/bin/swap-indicator-panel-icon.sh" remove || true
rm -f "$TARGET_HOME"/.local/bin/swap-indicator-{genmon,panel-icon}.sh
rm -rf "$TARGET_HOME/.local/share/cyberbeest-swap-indicator"
rm -f "/run/user/$(id -u "$TARGET_USER")/swap-indicator.state"
echo "Swap indicator removed."
