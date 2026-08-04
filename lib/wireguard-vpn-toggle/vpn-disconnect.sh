#!/bin/bash
# Disconnects whichever VPN profile is currently active.
set -uo pipefail

STATE_DIR="$HOME/.config/cyberbeest"
STATE_FILE="$STATE_DIR/vpn_active"
ACTIVE="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ -n "$ACTIVE" ]; then
    sudo -n systemctl stop "wg-quick@${ACTIVE}"
    rm -f "$STATE_FILE"
    notify-send --urgency=low --app-name="Cyberbeest VPN" "Disconnected" 2>/dev/null || true
fi
