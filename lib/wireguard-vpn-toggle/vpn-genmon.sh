#!/bin/bash
# Panel item: shows current VPN connection status, click opens the profile
# menu (vpn-menu.py). Present whenever >=1 profile is imported; removed by
# vpn-remove-profile.sh when the last one is deleted.

ICON_CONNECTED=/usr/share/icons/gnome/24x24/status/network-transmit-receive.png
ICON_DISCONNECTED=/usr/share/icons/gnome/24x24/status/network-offline.png
ICON_WARNING=/usr/share/icons/gnome/24x24/status/network-error.png

STATE_FILE="$HOME/.config/cyberbeest/vpn_active"
ACTIVE="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ -n "$ACTIVE" ]; then
    if sudo -n systemctl is-active --quiet "wg-quick@${ACTIVE}" 2>/dev/null; then
        echo "<img>${ICON_CONNECTED}</img>"
        echo "<tool>VPN connected: ${ACTIVE}&#10;Click for options.</tool>"
    else
        # State file says active but the tunnel isn't -- it dropped outside
        # our control (crash, provider-side disconnect). Clear the stale
        # state so the icon/menu reflect reality rather than a phantom
        # connection.
        rm -f "$STATE_FILE"
        echo "<img>${ICON_WARNING}</img>"
        echo "<tool>VPN disconnected unexpectedly (was: ${ACTIVE})&#10;Click for options.</tool>"
    fi
else
    echo "<img>${ICON_DISCONNECTED}</img>"
    echo "<tool>No VPN connected.&#10;Click for options.</tool>"
fi
echo "<click>$HOME/.local/bin/vpn-menu.py</click>"
