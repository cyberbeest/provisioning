#!/bin/bash
# Disconnects the active tunnel (if any) and removes the VPN panel icon,
# without deleting any imported profile -- for hiding the icon without
# losing the saved config. Restoring it is vpn-show-icon.sh, reachable from
# the VPN Manager landing page since the icon's own popup menu goes away
# with the icon. vpn-restore-session.sh checks the marker this writes so a
# hidden icon doesn't silently come back at the next login.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

STATE_DIR="$HOME/.config/cyberbeest"
mkdir -p "$STATE_DIR"

"$HOME/.local/bin/vpn-disconnect.sh"
"$HOME/.local/bin/vpn-panel-icon.sh" remove
touch "$STATE_DIR/vpn_icon_hidden"

notify-send --urgency=low --app-name="Cyberbeest VPN" "$(t vpn.icon_removed_notify)" 2>/dev/null || true
