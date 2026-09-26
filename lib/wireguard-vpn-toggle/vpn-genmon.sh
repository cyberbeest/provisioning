#!/bin/bash
# Panel item: shows current VPN connection status, click opens the profile
# menu (vpn-menu.py). Present whenever >=1 profile is imported; removed by
# vpn-remove-profile.sh when the last one is deleted.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

ICON_CONNECTED=/usr/share/icons/gnome/24x24/categories/applications-internet.png
ICON_DISCONNECTED=/usr/share/icons/gnome/24x24/status/network-wired-disconnected.png
ICON_WARNING=/usr/share/icons/gnome/24x24/status/dialog-warning.png

STATE_FILE="$HOME/.config/cyberbeest/vpn_active"
ACTIVE="$(cat "$STATE_FILE" 2>/dev/null || true)"
CLICK_FOR_OPTIONS="$(t vpn.genmon_click_for_options)"

if [ -n "$ACTIVE" ]; then
    if sudo -n systemctl is-active --quiet "wg-quick@${ACTIVE}" 2>/dev/null; then
        echo "<img>${ICON_CONNECTED}</img>"
        connected_msg="$(t vpn.genmon_connected)"
        echo "<tool>${connected_msg//NAME/$ACTIVE}&#10;${CLICK_FOR_OPTIONS}</tool>"
    else
        # State file says active but the tunnel isn't -- it dropped outside
        # our control (crash, provider-side disconnect). Clear the stale
        # state so the icon/menu reflect reality rather than a phantom
        # connection.
        rm -f "$STATE_FILE"
        echo "<img>${ICON_WARNING}</img>"
        dropped_msg="$(t vpn.genmon_dropped)"
        echo "<tool>${dropped_msg//NAME/$ACTIVE}&#10;${CLICK_FOR_OPTIONS}</tool>"
    fi
else
    echo "<img>${ICON_DISCONNECTED}</img>"
    echo "<tool>$(t vpn.genmon_none)&#10;${CLICK_FOR_OPTIONS}</tool>"
fi
echo "<click>$HOME/.local/bin/vpn-menu.py</click>"
