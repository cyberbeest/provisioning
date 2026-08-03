#!/bin/bash
# Watches for systemd-logind's Lock/Unlock signal on our session (fired by
# HandleLidSwitch=lock in /etc/systemd/logind.conf.d/50-cyberbeest-lid.conf
# when the lid closes) and forces the display off/on immediately -- lid
# close already locks near-instantly via logind itself, this just makes the
# panel go dark with it instead of waiting on the general idle-DPMS timers
# from 16-power-lock-config.sh.
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

# Plain-text mirror of the logger calls below -- readable without journal
# access (journalctl needs adm/systemd-journal group membership or sudo to
# see the acpid/root-owned entries lid-open-wake.sh writes, so a shared
# plain file is the easiest way to watch both sides of this at once).
DEBUG_LOG="$HOME/.cache/cyberbeest-lid-debug.log"
log() {
    logger -t lid-screen-off "$1"
    mkdir -p "$(dirname "$DEBUG_LOG")"
    echo "$(date '+%H:%M:%S') lid-screen-off: $1" >> "$DEBUG_LOG"
}

# Shared with lid-open-wake.sh (a separate process, invoked by acpid on lid
# *open* -- which never sends the Unlock signal this script listens for,
# since opening the lid doesn't unlock the session). That script kills the
# PID recorded here before forcing DPMS on, otherwise a lid reopened inside
# the 10s retry window below gets its "on" stomped by this loop's next tick.
PIDFILE="$HOME/.cache/cyberbeest-lid-dpms-off.pid"

screen_off() {
    mkdir -p "$(dirname "$PIDFILE")"
    # logind's "lock" action sends this Lock signal once per session the
    # user has (several, in practice -- not just the graphical one), so a
    # single lid-close event shows up here as several near-simultaneous
    # calls. Only keep one retry loop alive: without this guard, each extra
    # call spawned its own untracked ~10s off-loop that PIDFILE couldn't
    # cancel, so a lid reopened inside that window could get re-blanked out
    # from under an in-progress unlock by a loop nothing knew to kill.
    if [ -f "$PIDFILE" ]; then
        pid="$(cat "$PIDFILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log "Lock signal: off-loop already running (pid $pid), ignoring duplicate"
            return
        fi
    fi
    log "Lock signal: forcing DPMS off"
    # Retried over ~10s, same as lock-shutdown-watcher.sh's screen_off():
    # xfce4-power-manager can re-assert display-on shortly after the lock
    # signal, so a single one-shot call can silently lose that race.
    (
        for _ in $(seq 1 10); do
            xset dpms force off 2>/dev/null
            sleep 1
        done
        rm -f "$PIDFILE"
    ) &
    echo "$!" > "$PIDFILE"
}

screen_on() {
    if [ -f "$PIDFILE" ]; then
        pid="$(cat "$PIDFILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            log "Unlock signal: cancelling pending DPMS-off loop (pid $pid)"
            kill "$pid" 2>/dev/null
        fi
        rm -f "$PIDFILE"
    fi
    log "Unlock signal: forcing DPMS on"
    xset dpms force on 2>/dev/null
}

dbus-monitor --system "type='signal',interface='org.freedesktop.login1.Session',member='Lock'" \
             "type='signal',interface='org.freedesktop.login1.Session',member='Unlock'" 2>/dev/null |
while read -r line; do
    case "$line" in
        *member=Lock*) screen_off ;;
        *member=Unlock*) screen_on ;;
    esac
done
