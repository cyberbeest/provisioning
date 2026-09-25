#!/bin/bash
# Restarts this user's xfce4-panel if it ever crashes on its own (the known
# liblauncher.so segfault -- see lib/xfce-panel-reload.sh's xfce_panel_launch
# -- or anything else). That helper's own one-shot retry only covers a crash
# in the few seconds right after a *provisioning-triggered* reload; a panel
# that dies hours later, with nothing else running, previously just stayed
# dead until the next login. This is a long-lived systemd --user service
# (see xfce-panel-watchdog.service) that just polls.
#
# Coordination with everything else that kills+relaunches the panel
# (lib/xfce-panel-reload.sh for provisioning scripts, and the standalone
# i2pd/vpn/dot panel-icon.sh toggles): all of them, including this script,
# flock the same /run/user/<uid>/cyberbeest-panel-reload.lock for the whole
# kill-through-launch window. That lets this watchdog tell "the panel is
# down because someone else's *intentional* reload is in flight" (lock
# held -- back off, they'll bring it back up) apart from "the panel is down
# because it genuinely crashed on its own" (lock free) -- see
# xfce-panel-reload.sh's own comment on xfce_panel_reload_lock for the full
# race this avoids. Without it, this watchdog could fire mid-reload and
# either fight the in-progress kill+relaunch or spawn a second panel
# alongside the one the other script is about to launch.

set -uo pipefail

POLL_INTERVAL=5
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"
PANEL_RELOAD_LOCK_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/cyberbeest-panel-reload.lock"

# Crash-loop breaker: if the panel keeps dying right after we relaunch it
# (a persistently broken config or plugin, not the sporadic liblauncher
# segfault this was built for), stop hammering it -- keep watching and
# logging, but skip the actual relaunch until enough time has passed for
# old attempts to age back out of the window. Resumes on its own; nothing
# to reset by hand.
MAX_RESTARTS_PER_WINDOW=5
RESTART_WINDOW_SECONDS=600
restart_times=()

panel_alive() {
    pgrep -x xfce4-panel >/dev/null 2>&1
}

session_alive() {
    # If the whole XFCE session is gone too (logout/shutdown in progress),
    # there's nothing to restart into -- don't fight a legitimate teardown.
    pgrep -x xfce4-session >/dev/null 2>&1
}

record_restart_and_check_throttle() {
    local now cutoff kept=() t
    now=$(date +%s)
    cutoff=$((now - RESTART_WINDOW_SECONDS))
    for t in "${restart_times[@]:-}"; do
        [ -n "$t" ] && [ "$t" -ge "$cutoff" ] && kept+=("$t")
    done
    kept+=("$now")
    restart_times=("${kept[@]}")
    [ "${#restart_times[@]}" -le "$MAX_RESTARTS_PER_WINDOW" ]
}

panel_dbus_addr() {
    # We ARE the session user (systemd --user), so the standard per-user
    # bus path is always right -- no need to scrape another process's
    # environ for it the way the root-context lib does.
    PANEL_DBUS_ADDR="unix:path=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/bus"
}

# Systemd --user services start with a minimal environment (no
# XDG_CURRENT_DESKTOP etc.), unlike a process launched from the session's
# own autostart -- but xfce4-session is still alive whenever only the panel
# crashed, so scrape its environ the same way lib/xfce-panel-reload.sh does
# for the root-context reload. Needed for Electron's keyring-backend
# detection (Signal/Element/Telegram) when they're later launched from the
# relaunched panel/whisker menu.
capture_session_env() {
    SESSION_ENV=()
    local session_pid
    session_pid="$(pgrep -x xfce4-session | head -n1)" || true
    [ -n "$session_pid" ] || return 0
    while IFS= read -r -d '' line; do
        case "$line" in
            XDG_*=*|DESKTOP_SESSION=*) SESSION_ENV+=("$line") ;;
        esac
    done < "/proc/$session_pid/environ" 2>/dev/null || true
}

restart_panel_impl() {
    if ! session_alive; then
        echo "xfce-panel-watchdog: xfce4-session is also gone -- session is ending, not restarting the panel" >&2
        return 0
    fi
    if panel_alive; then
        # Whoever held the lock before us (an intentional reload) already
        # brought it back up.
        return 0
    fi

    if ! record_restart_and_check_throttle; then
        echo "xfce-panel-watchdog: xfce4-panel has crashed ${#restart_times[@]} times in the last $((RESTART_WINDOW_SECONDS / 60)) minutes -- not auto-restarting again for now (check journalctl -k for a segfault); will resume once that rate drops" >&2
        return 0
    fi

    echo "xfce-panel-watchdog: xfce4-panel is not running -- relaunching" >&2
    panel_dbus_addr
    capture_session_env

    # Launched via systemd-run into its own transient unit, NOT with a
    # plain `&` in this script -- a plain background job would fork
    # xfce4-panel (and every plugin wrapper process under it) as a member
    # of THIS service's own cgroup, since cgroup membership is inherited
    # at fork time and isn't a "current directory"-style thing a later
    # `disown` can undo. Confirmed live 2026-09-25: after one relaunch,
    # `systemctl --user status xfce-panel-watchdog.service` showed the
    # whole live panel and all its plugins nested under it -- meaning a
    # future `systemctl --user restart xfce-panel-watchdog.service` (e.g.
    # from a re-run of 60-xfce-panel-watchdog.sh) would have SIGKILLed the
    # live panel and every plugin right along with the watchdog itself.
    # `--collect` garbage-collects the transient unit once xfce4-panel
    # exits, so repeated crashes/relaunches don't pile up dead unit
    # definitions in `systemctl --user list-units`.
    local setenv_args=(--setenv="DISPLAY=${DISPLAY}" --setenv="DBUS_SESSION_BUS_ADDRESS=${PANEL_DBUS_ADDR}")
    local kv
    for kv in "${SESSION_ENV[@]:-}"; do
        [ -n "$kv" ] || continue
        setenv_args+=(--setenv="$kv")
    done
    # No `setsid` here: systemd already owns this process's lifecycle once
    # started this way, so there's no controlling-terminal/HUP concern left
    # for it to solve. It's actively harmful, in fact -- systemd-run's user
    # manager already runs the target as its own session/process-group
    # leader, so `setsid` (util-linux) has to fork a child to succeed;
    # the fork(ed) child keeps running xfce4-panel, but the *original*
    # process systemd is tracking as the unit's main PID exits right after
    # that fork, which reads as "the service already exited" -- and with
    # this unit's default KillMode=control-group, systemd then SIGTERMs the
    # rest of the cgroup (the actual xfce4-panel it just forked) as part of
    # considering the unit stopped. Confirmed live 2026-09-25: every
    # relaunch attempt with `setsid xfce4-panel` here silently produced no
    # running process and no journal output at all -- dropping `setsid`
    # fixed it immediately.
    systemd-run --user --collect --quiet \
        --unit="xfce-panel-relaunch-$(date +%s%N)" \
        --description="xfce4-panel (relaunched by xfce-panel-watchdog)" \
        "${setenv_args[@]}" \
        -- xfce4-panel

    local waited=0
    while [ "$waited" -lt 10 ]; do
        panel_alive && break
        sleep 0.5
        waited=$((waited + 1))
    done
    if panel_alive; then
        echo "xfce-panel-watchdog: xfce4-panel back up" >&2
    else
        echo "xfce-panel-watchdog: xfce4-panel did not come up after relaunch -- will retry next poll" >&2
    fi
}

# Held only around the check-and-relaunch itself, not the whole poll loop,
# and bounded so a stuck lock-holder elsewhere can't wedge this watchdog
# forever -- 90s comfortably covers the canonical lib's own worst case
# (30s kill wait + 10s launch wait + 1.5s settle + 10s crash-retry watch,
# doubled for its one retry).
restart_panel() {
    (
        if ! flock -x -w 90 200; then
            echo "xfce-panel-watchdog: could not get the panel-reload lock within 90s -- skipping this check" >&2
            exit 0
        fi
        restart_panel_impl
    ) 200>"$PANEL_RELOAD_LOCK_FILE"
}

echo "xfce-panel-watchdog: watching xfce4-panel (poll every ${POLL_INTERVAL}s)" >&2
while true; do
    panel_alive || restart_panel
    sleep "$POLL_INTERVAL"
done
