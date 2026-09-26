#!/bin/bash
# Unprivileged half of VPN profile import: lets the user pick a WireGuard
# .conf file (from their provider -- Mullvad, IVPN, ProtonVPN's manual
# configs, a self-hosted server, etc.) and a short name for it, then hands
# off to the root-side helper to actually install it. Launched from the
# Whisker menu entry "Import VPN Profile" or from the panel icon's menu.

set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

SRC="$(zenity --file-selection --title="$(t vpn.import_file_title)" \
    --file-filter="$(t vpn.import_file_filter) | *.conf" 2>/dev/null)"
[ -z "$SRC" ] && exit 0

DEFAULT_NAME="$(basename "$SRC" .conf | tr -c 'a-zA-Z0-9_-' '-')"
NAME="$(zenity --entry --title="$(t vpn.import_name_title)" \
    --text="$(t vpn.import_name_text)" \
    --entry-text="$DEFAULT_NAME" 2>/dev/null)"
[ -z "$NAME" ] && exit 0

if ! [[ "$NAME" =~ ^[a-zA-Z0-9_-]{1,32}$ ]]; then
    zenity --error --text="$(t vpn.import_invalid_name)" 2>/dev/null
    exit 1
fi

STATE_DIR="$HOME/.config/cyberbeest"
mkdir -p "$STATE_DIR"
PROFILES_FILE="$STATE_DIR/vpn_profiles"
touch "$PROFILES_FILE"
if grep -qxF "$NAME" "$PROFILES_FILE"; then
    exists_msg="$(t vpn.import_name_exists)"
    zenity --error --text="${exists_msg//NAME/$NAME}" 2>/dev/null
    exit 1
fi

if ! sudo -n /usr/local/lib/cyberbeest/vpn-import-helper.sh "$SRC" "$NAME" >/dev/null; then
    zenity --error --text="$(t vpn.import_failed)" 2>/dev/null
    exit 1
fi

echo "$NAME" >>"$PROFILES_FILE"
"$HOME/.local/bin/vpn-panel-icon.sh" add

notify_title="$(t vpn.import_notify_title)"
notify-send --urgency=low --app-name="Cyberbeest VPN" \
    "${notify_title//NAME/$NAME}" "$(t vpn.import_notify_body)" 2>/dev/null || true
