#!/bin/bash
# Adds/removes the VPN genmon panel icon (plugin-28) from the live panel.
# Present whenever at least one VPN profile has been imported; removed
# entirely once the last profile is deleted (vpn-remove-profile.sh calls
# "remove" for that case) -- no panel space spent on a feature nobody's
# opted into, same reasoning as the i2pd toggle icon.
#
# Usage: vpn-panel-icon.sh add|remove
#
# NOTE: xfconf-query's -a flag is --force-array, NOT "append" -- the whole
# plugin-ids array must be replaced in a single call (repeated -t int -s id
# pairs after -n -a), never built up with a loop of separate -a calls, or
# every earlier value gets clobbered down to just the last one.

set -uo pipefail

PLUGIN_ID=28
ACTION="${1:-}"

panel_dbus_env() {
    local panel_pid
    panel_pid="$(pgrep -x xfce4-panel | head -n1)"
    [ -z "$panel_pid" ] && return 1
    grep -z '^DBUS_SESSION_BUS_ADDRESS=' "/proc/$panel_pid/environ" 2>/dev/null | tr -d '\0'
}

reload_panel() {
    local env_line
    env_line="$(panel_dbus_env)"
    if [ -n "$env_line" ]; then
        env "$env_line" xfce4-panel -r >/dev/null 2>&1
    else
        xfce4-panel -r >/dev/null 2>&1
    fi
}

get_plugin_ids() {
    xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids | grep -E '^[0-9]+$'
}

find_clock_id() {
    local id
    for id in $(get_plugin_ids); do
        if [ "$(xfconf-query -c xfce4-panel -p "/plugins/plugin-${id}" 2>/dev/null)" = "clock" ]; then
            echo "$id"
            return 0
        fi
    done
    return 1
}

set_plugin_ids() {
    local args=(-c xfce4-panel -p /panels/panel-1/plugin-ids -n -a)
    for id in "$@"; do
        args+=(-t int -s "$id")
    done
    xfconf-query "${args[@]}"
}

case "$ACTION" in
add)
    if xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" >/dev/null 2>&1; then
        exit 0 # already present
    fi
    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -n -t string -s genmon

    mkdir -p "$HOME/.config/xfce4/panel"
    cat >"$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc" <<EOF
Command=$HOME/.local/bin/vpn-genmon.sh
UpdatePeriod=5000
UseLabel=0
Text=(genmon)
Font=Sans 10
EOF

    clock_id="$(find_clock_id || true)"

    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    inserted=0
    for id in "${ids[@]}"; do
        if [ -n "$clock_id" ] && [ "$id" = "$clock_id" ]; then
            new_ids+=("$PLUGIN_ID")
            inserted=1
        fi
        new_ids+=("$id")
    done
    if [ "$inserted" -eq 0 ]; then
        new_ids+=("$PLUGIN_ID")
    fi

    set_plugin_ids "${new_ids[@]}"
    reload_panel
    ;;
remove)
    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    for id in "${ids[@]}"; do
        [ "$id" = "$PLUGIN_ID" ] && continue
        new_ids+=("$id")
    done

    set_plugin_ids "${new_ids[@]}"

    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -r -R >/dev/null 2>&1
    rm -f "$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc"

    reload_panel
    ;;
*)
    echo "Usage: $0 add|remove" >&2
    exit 1
    ;;
esac
