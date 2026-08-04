#!/bin/bash
# Connects a named VPN profile. If another profile is currently active,
# disconnects it first (wg-quick doesn't support two overlapping default-
# route tunnels cleanly, and "one active VPN at a time" is the expected
# mental model anyway).
#
# Usage: vpn-connect.sh <profile-name>
set -uo pipefail

NAME="${1:-}"
[ -z "$NAME" ] && exit 1

STATE_DIR="$HOME/.config/cyberbeest"
STATE_FILE="$STATE_DIR/vpn_active"
mkdir -p "$STATE_DIR"

ACTIVE="$(cat "$STATE_FILE" 2>/dev/null || true)"
if [ -n "$ACTIVE" ] && [ "$ACTIVE" != "$NAME" ]; then
    sudo -n systemctl stop "wg-quick@${ACTIVE}"
fi

if sudo -n systemctl start "wg-quick@${NAME}"; then
    echo "$NAME" >"$STATE_FILE"
    notify-send --urgency=low --app-name="Cyberbeest VPN" \
        "Connected" "VPN profile \"$NAME\" is now active." 2>/dev/null || true
else
    notify-send --urgency=critical --app-name="Cyberbeest VPN" \
        "Connection failed" "Could not start VPN profile \"$NAME\". Check the config file." 2>/dev/null || true
    rm -f "$STATE_FILE"
fi
