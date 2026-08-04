#!/bin/bash
# Run once per login (via autostart). wg-quick@<profile> units are never
# boot-enabled -- this restores whatever the previous session left: shows
# the panel icon if any profiles are imported, and reconnects the tunnel
# that was active when the user last logged out (if any).
set -uo pipefail

STATE_DIR="$HOME/.config/cyberbeest"
PROFILES_FILE="$STATE_DIR/vpn_profiles"
ACTIVE_FILE="$STATE_DIR/vpn_active"

if [ -s "$PROFILES_FILE" ]; then
    "$HOME/.local/bin/vpn-panel-icon.sh" add
fi

ACTIVE="$(cat "$ACTIVE_FILE" 2>/dev/null || true)"
if [ -n "$ACTIVE" ]; then
    "$HOME/.local/bin/vpn-connect.sh" "$ACTIVE"
fi
