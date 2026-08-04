#!/bin/bash
# Unprivileged half of VPN profile import: lets the user pick a WireGuard
# .conf file (from their provider -- Mullvad, IVPN, ProtonVPN's manual
# configs, a self-hosted server, etc.) and a short name for it, then hands
# off to the root-side helper to actually install it. Launched from the
# Whisker menu entry "Import VPN Profile" or from the panel icon's menu.

set -uo pipefail

SRC="$(zenity --file-selection --title="Select a WireGuard config file (.conf)" \
    --file-filter="WireGuard configs | *.conf" 2>/dev/null)"
[ -z "$SRC" ] && exit 0

DEFAULT_NAME="$(basename "$SRC" .conf | tr -c 'a-zA-Z0-9_-' '-')"
NAME="$(zenity --entry --title="Name this VPN profile" \
    --text="Short name for this profile (letters, numbers, - and _ only):" \
    --entry-text="$DEFAULT_NAME" 2>/dev/null)"
[ -z "$NAME" ] && exit 0

if ! [[ "$NAME" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
    zenity --error --text="Invalid name. Use only letters, numbers, - and _ (max 32 characters)." 2>/dev/null
    exit 1
fi

STATE_DIR="$HOME/.config/cyberbeest"
mkdir -p "$STATE_DIR"
PROFILES_FILE="$STATE_DIR/vpn_profiles"
touch "$PROFILES_FILE"
if grep -qxF "$NAME" "$PROFILES_FILE"; then
    zenity --error --text="A profile named \"$NAME\" already exists." 2>/dev/null
    exit 1
fi

if ! sudo -n /usr/local/lib/cyberbeest/vpn-import-helper.sh "$SRC" "$NAME" >/dev/null; then
    zenity --error --text="Failed to import that config. Check ~/claude or run vpn-import-helper.sh manually to see the error." 2>/dev/null
    exit 1
fi

echo "$NAME" >>"$PROFILES_FILE"
"$HOME/.local/bin/vpn-panel-icon.sh" add

notify-send --urgency=low --app-name="Cyberbeest VPN" \
    "VPN profile \"$NAME\" imported" "Click the panel icon to connect." 2>/dev/null || true
