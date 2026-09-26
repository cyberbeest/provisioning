#!/bin/bash
# Adds/removes the VPN genmon panel icon (plugin-228) from the live panel.
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

PLUGIN_ID=228
ACTION="${1:-}"

# Never use `xfce4-panel -r`: it asks the still-running process to restart
# itself from whatever config it already has cached client-side, then
# persists that stale state back to xfconfd -- silently clobbering the
# xfconf write this script just made. A graceful kill has the same problem
# (exiting also re-persists in-memory config). See provisioning-bleeding's
# lib/xfce-panel-reload.sh, which this is ported from: SIGKILL xfce4-panel
# outright, then launch a completely fresh panel process so it has no
# cached state to fall back on.
#
# Deliberately does NOT kill xfconfd. xfconfd already holds the correct,
# just-written value -- it has no stale cache to drop -- so SIGKILLing it
# only risked losing its own async disk flush and reviving the stale
# on-disk config on respawn. Caught 2026-09-16 on tower: an i2pd icon
# removal kept coming back because xfconfd was killed before it had
# flushed the plugin-ids write to xfce4-panel.xml.
panel_dbus_addr() {
    local panel_pid
    panel_pid="$(pgrep -x xfce4-panel | head -n1)"
    [ -z "$panel_pid" ] && return 1
    PANEL_DBUS_ADDR="$(tr '\0' '\n' <"/proc/$panel_pid/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
    PANEL_DBUS_ADDR="${PANEL_DBUS_ADDR:-unix:path=/run/user/$(id -u)/bus}"
}

# Flocks the same file lib/xfce-panel-reload.sh and the panel watchdog use
# so a kill+relaunch here can never interleave with one of theirs -- two
# racing kill+relaunch cycles could otherwise land a SIGKILL on the
# *other's* freshly-launched process, or spawn two panels back to back. See
# xfce-panel-reload.sh's own comment on xfce_panel_reload_lock for the full
# story. /run/user, not $HOME, so a stale lock can never survive a reboot.
PANEL_RELOAD_LOCK_FILE="/run/user/$(id -u)/cyberbeest-panel-reload.lock"

reload_panel() {
    # Self-heal a lock file a root-context reload left behind before
    # xfce-panel-reload.sh's own chmod-0666 fix existed (root:root, mode
    # 644 -- unwritable by us). We can't chmod/chown our way out of that
    # (neither the file's owner nor root), only delete it -- unlink is
    # governed by the directory's permissions, not the file's, and
    # /run/user/<uid> is ours. Confirmed live 2026-09-25 on .76: this
    # exact situation silently blocked the panel watchdog's every
    # relaunch attempt after a provisioning reload ran, with nothing short
    # of manually removing the file able to clear it.
    if [ -e "$PANEL_RELOAD_LOCK_FILE" ] && ! : 2>/dev/null >>"$PANEL_RELOAD_LOCK_FILE"; then
        echo "warning: panel-reload lock file isn't writable by us -- removing a likely stale root-owned copy" >&2
        rm -f "$PANEL_RELOAD_LOCK_FILE" 2>/dev/null || true
    fi
    (
        flock -x 200
        reload_panel_impl
    ) 200>"$PANEL_RELOAD_LOCK_FILE"
}

reload_panel_impl() {
    # No panel running (no graphical session) -- nothing to reload.
    local old_pid
    old_pid="$(pgrep -x xfce4-panel | head -n1)"
    panel_dbus_addr || return 0

    pkill -9 -x xfce4-panel 2>/dev/null || true

    # Wait for the old process to actually be gone instead of trusting a
    # flat sleep -- a lingering old process (SIGKILL raced, or something
    # respawned it instantly) would otherwise go unnoticed, and the
    # pid-exists check below can't tell that apart from a genuinely fresh
    # launch.
    local waited=0
    while pgrep -x xfce4-panel >/dev/null 2>&1; do
        sleep 0.5
        waited=$((waited + 1))
        if [ "$waited" -ge 10 ]; then
            echo "warning: xfce4-panel still running 5s after SIGKILL" >&2
            break
        fi
    done

    DISPLAY="${DISPLAY:-:0}" DBUS_SESSION_BUS_ADDRESS="$PANEL_DBUS_ADDR" \
        setsid xfce4-panel >/dev/null 2>&1 </dev/null &
    disown

    # Poll for a new, different pid -- "a process exists" alone can't tell
    # a genuinely fresh launch apart from the old one never having died.
    # Caught 2026-09-14 on the sibling i2pd toggle icon: the xfconf write
    # succeeded but the live panel silently never picked up the new icon.
    local new_pid=""
    waited=0
    while [ "$waited" -lt 10 ]; do
        new_pid="$(pgrep -x xfce4-panel | head -n1)"
        if [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ]; then
            break
        fi
        sleep 0.5
        waited=$((waited + 1))
    done
    if [ -z "$new_pid" ]; then
        echo "warning: xfce4-panel did not come back up" >&2
        return 1
    fi
    if [ "$new_pid" = "$old_pid" ]; then
        echo "warning: xfce4-panel pid unchanged after launch (old process never died?)" >&2
        return 1
    fi

    # xfce4-session sometimes respawns a just-killed panel from its own
    # cached state a moment later, replacing the fresh one we just
    # launched -- re-check after a short settle so that's caught too.
    sleep 1.5
    local settled_pid
    settled_pid="$(pgrep -x xfce4-panel | head -n1)"
    if [ "$settled_pid" != "$new_pid" ]; then
        echo "warning: xfce4-panel pid changed again during settle (pid $new_pid -> ${settled_pid:-gone})" >&2
        return 1
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
    # reload_panel itself now detects a reload that didn't genuinely take
    # live effect (old process never died, or something respawned over our
    # fresh launch) -- retry the whole apply+reload cycle on that, not just
    # on the xfconf state check, since a bad reload can also mean stale
    # cached state got re-persisted over our write.
    reload_ok=0
    for _ in 1 2 3; do
        if reload_panel; then
            reload_ok=1
            break
        fi
        sleep 1
        apply_"$ACTION"
    done
    [ "$reload_ok" -eq 1 ] || echo "warning: panel reload didn't take live effect after retries" >&2
    is_applied || echo "warning: plugin-${PLUGIN_ID} state didn't stick after retries" >&2
    ;;
*)
    echo "Usage: $0 add|remove" >&2
    exit 1
    ;;
esac
