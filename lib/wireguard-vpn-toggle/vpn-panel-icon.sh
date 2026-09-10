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

# Never use `xfce4-panel -r`: it asks the still-running process to restart
# itself from whatever config it already has cached client-side, then
# persists that stale state back to xfconfd -- silently clobbering the
# xfconf write this script just made. A graceful kill has the same problem
# (exiting also re-persists in-memory config). See provisioning-bleeding's
# lib/xfce-panel-reload.sh, which this is ported from: SIGKILL xfconfd and
# xfce4-panel outright, then launch a completely fresh panel process so it
# has no cached state to fall back on.
panel_dbus_addr() {
    local panel_pid
    panel_pid="$(pgrep -x xfce4-panel | head -n1)"
    [ -z "$panel_pid" ] && return 1
    PANEL_DBUS_ADDR="$(tr '\0' '\n' <"/proc/$panel_pid/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
    PANEL_DBUS_ADDR="${PANEL_DBUS_ADDR:-unix:path=/run/user/$(id -u)/bus}"
}

reload_panel() {
    # No panel running (no graphical session) -- nothing to reload.
    panel_dbus_addr || return 0

    pkill -9 -x xfconfd 2>/dev/null || true
    pkill -9 -x xfce4-panel 2>/dev/null || true
    sleep 1

    DISPLAY="${DISPLAY:-:0}" DBUS_SESSION_BUS_ADDRESS="$PANEL_DBUS_ADDR" \
        setsid xfce4-panel >/dev/null 2>&1 </dev/null &
    disown
    sleep 1
    pgrep -x xfce4-panel >/dev/null || echo "warning: xfce4-panel did not come back up" >&2
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

apply_add() {
    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -n -t string -s genmon 2>/dev/null \
        || xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -s genmon

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
        [ "$id" = "$PLUGIN_ID" ] && continue # don't duplicate if already present
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
}

apply_remove() {
    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    for id in "${ids[@]}"; do
        [ "$id" = "$PLUGIN_ID" ] && continue
        new_ids+=("$id")
    done

    set_plugin_ids "${new_ids[@]}"

    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -r -R >/dev/null 2>&1
    rm -f "$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc"
}

is_applied() {
    if [ "$ACTION" = add ]; then
        get_plugin_ids | grep -qx "$PLUGIN_ID"
    else
        ! get_plugin_ids | grep -qx "$PLUGIN_ID"
    fi
}

case "$ACTION" in
add | remove)
    if [ "$ACTION" = add ] && is_applied; then
        exit 0 # already present, nothing to do
    fi

    apply_"$ACTION"
    reload_panel
    # xfce4-session sometimes auto-respawns a just-killed panel from its own
    # cached client-side state before our relaunch lands, re-persisting the
    # pre-change plugin list over the write above. Re-apply and re-check a
    # few times so the change actually sticks once things settle.
    for _ in 1 2 3; do
        is_applied && break
        sleep 1
        apply_"$ACTION"
    done
    is_applied || echo "warning: plugin-${PLUGIN_ID} state didn't stick after retries" >&2
    ;;
*)
    echo "Usage: $0 add|remove" >&2
    exit 1
    ;;
esac
