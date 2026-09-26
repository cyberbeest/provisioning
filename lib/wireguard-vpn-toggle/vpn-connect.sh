#!/bin/bash
# Connects a named VPN profile. If another profile is currently active,
# disconnects it first (wg-quick doesn't support two overlapping default-
# route tunnels cleanly, and "one active VPN at a time" is the expected
# mental model anyway).
#
# Usage: vpn-connect.sh <profile-name>
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

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
    connect_body="$(t vpn.connect_notify_body)"
    notify-send --urgency=low --app-name="Cyberbeest VPN" \
        "$(t vpn.connect_notify_title)" "${connect_body//NAME/$NAME}" 2>/dev/null || true
else
    failed_body="$(t vpn.connect_failed_body)"
    notify-send --urgency=critical --app-name="Cyberbeest VPN" \
        "$(t vpn.connect_failed_title)" "${failed_body//NAME/$NAME}" 2>/dev/null || true
    rm -f "$STATE_FILE"
fi
