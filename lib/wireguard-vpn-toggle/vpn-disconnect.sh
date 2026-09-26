#!/bin/bash
# Disconnects whichever VPN profile is currently active.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

STATE_DIR="$HOME/.config/cyberbeest"
STATE_FILE="$STATE_DIR/vpn_active"
ACTIVE="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ -n "$ACTIVE" ]; then
    sudo -n systemctl stop "wg-quick@${ACTIVE}"
    rm -f "$STATE_FILE"
    notify-send --urgency=low --app-name="Cyberbeest VPN" "$(t vpn.disconnect_notify)" 2>/dev/null || true
fi
