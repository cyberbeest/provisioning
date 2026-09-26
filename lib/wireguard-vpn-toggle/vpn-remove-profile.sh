#!/bin/bash
# Removes an imported VPN profile (stops it first if active), and removes
# the panel icon entirely if that was the last profile.
#
# Usage: vpn-remove-profile.sh <profile-name>
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

NAME="${1:-}"
[ -z "$NAME" ] && exit 1

STATE_DIR="$HOME/.config/cyberbeest"
PROFILES_FILE="$STATE_DIR/vpn_profiles"
STATE_FILE="$STATE_DIR/vpn_active"

sudo -n /usr/local/lib/cyberbeest/vpn-remove-helper.sh "$NAME"

[ "$(cat "$STATE_FILE" 2>/dev/null)" = "$NAME" ] && rm -f "$STATE_FILE"

if [ -f "$PROFILES_FILE" ]; then
    grep -vxF "$NAME" "$PROFILES_FILE" >"$PROFILES_FILE.tmp" 2>/dev/null || true
    mv "$PROFILES_FILE.tmp" "$PROFILES_FILE"
fi

if [ ! -s "$PROFILES_FILE" ]; then
    "$HOME/.local/bin/vpn-panel-icon.sh" remove
fi

remove_msg="$(t vpn.remove_notify)"
notify-send --urgency=low --app-name="Cyberbeest VPN" "${remove_msg//NAME/$NAME}" 2>/dev/null || true
