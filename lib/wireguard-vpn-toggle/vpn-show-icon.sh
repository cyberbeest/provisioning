#!/bin/bash
# Undoes vpn-hide-icon.sh: clears the hidden marker and re-shows the panel
# icon. Does not reconnect anything -- pick a profile from the icon's own
# menu once it's back.
set -uo pipefail

STATE_DIR="$HOME/.config/cyberbeest"
PROFILES_FILE="$STATE_DIR/vpn_profiles"

rm -f "$STATE_DIR/vpn_icon_hidden"
[ -s "$PROFILES_FILE" ] && "$HOME/.local/bin/vpn-panel-icon.sh" add
exit 0
