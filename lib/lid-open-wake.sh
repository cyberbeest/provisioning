#!/bin/bash
# Called by acpid on every button/lid ACPI event (both open and close --
# acpid's event codes for lid state aren't reliably documented across
# kernel versions, so instead of parsing them we just re-read the actual
# current state and act only on open). Lid close is already handled by
# logind (HandleLidSwitch=lock) + lid-screen-off.sh; this only handles the
# direction logind has no hook for: waking the display the instant the lid
# opens, instead of waiting for the first stray keypress.
TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
# Plain-text mirror of the logger calls below -- shared with
# lid-screen-off.sh's own DEBUG_LOG, see that script for why (journal access
# needs adm/systemd-journal group or sudo to see this script's root-owned
# entries, a plain file sidesteps that).
DEBUG_LOG="$TARGET_HOME/.cache/cyberbeest-lid-debug.log"
log() {
    logger -t lid-open-wake "$1"
    mkdir -p "$(dirname "$DEBUG_LOG")"
    echo "$(date '+%H:%M:%S') lid-open-wake: $1" >> "$DEBUG_LOG"
    chown "$TARGET_USER:$TARGET_USER" "$DEBUG_LOG" 2>/dev/null
}

STATE_FILE=$(ls /proc/acpi/button/lid/*/state 2>/dev/null | head -1)
if [ -z "$STATE_FILE" ]; then
    log "No /proc/acpi/button/lid state file found, exiting"
    exit 0
fi
if ! grep -q open "$STATE_FILE"; then
    log "acpid event fired but lid reads closed, ignoring (this was the close event)"
    exit 0
fi
log "Lid open detected, waking display"

run_as_user() { sudo -u "$TARGET_USER" DISPLAY=:0 XAUTHORITY="$TARGET_HOME/.Xauthority" "$@"; }

# Cancel lid-screen-off.sh's pending DPMS-off retry loop (see that script --
# it keeps forcing DPMS off for up to 10s after a lock, so without this an
# open inside that window gets its "on" immediately stomped by the loop's
# next tick).
PIDFILE="$TARGET_HOME/.cache/cyberbeest-lid-dpms-off.pid"
if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log "Cancelling pending DPMS-off loop (pid $pid)"
        kill "$pid" 2>/dev/null
    fi
    rm -f "$PIDFILE"
fi

run_as_user xset dpms force on
# DPMS-on alone leaves xfce4-screensaver's blank layer covering the already-
# locked unlock dialog -- it only reveals the password prompt on real input
# activity, so nudge the pointer (net zero movement) to count as that.
run_as_user xdotool mousemove_relative -- 1 0
run_as_user xdotool mousemove_relative -- -1 0
log "Done"
