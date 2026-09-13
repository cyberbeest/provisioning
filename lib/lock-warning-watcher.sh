#!/bin/bash
# Pops a desktop notification a few seconds before xfce4-screensaver's own
# idle timer locks the screen, so a user who's still there (just not
# touching the mouse/keyboard) gets a chance to wiggle the mouse and reset
# the idle clock instead of being locked out. Purely a warning -- it never
# touches the lock timer itself, which xfce4-screensaver owns via its own
# xfconf channel (see 16-power-lock-config.sh).
#
# Reads the same config file as lock-shutdown-watcher.sh and
# shutdown-timer-menu.py (WARN_BEFORE_LOCK_ENABLED / WARN_SECONDS_BEFORE_LOCK,
# set from lock-power-saving-dialog.py's "Extended Power Options" window).
# Polls xprintidle every second -- cheap enough for second-level precision,
# unlike the 15s poll lock-shutdown-watcher.sh uses for its much coarser
# post-lock deadlines.

DEFAULT_WARN_ENABLED=true
DEFAULT_WARN_SECONDS=10
POLL_INTERVAL=1
POWER_SETTINGS="$HOME/.config/cyberbeest/power-settings.conf"
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

# i18n.sh (and its i18n/ catalog dir) is installed next to this script --
# see lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
. "$SELF_DIR/i18n.sh"

read_setting() {
    # read_setting KEY DEFAULT
    [ -f "$POWER_SETTINGS" ] || { echo "$2"; return; }
    local value
    value=$(grep "^$1=" "$POWER_SETTINGS" | tail -n1 | cut -d= -f2-)
    echo "${value:-$2}"
}

is_locked() {
    dbus-send --session --dest=org.xfce.ScreenSaver --type=method_call \
        --print-reply /org/xfce/ScreenSaver org.xfce.ScreenSaver.GetActive \
        2>/dev/null | grep -q "boolean true"
}

# Closes the still-open warning notification, if any. Needed for two
# reasons: normal-urgency notifications auto-expire on their own via -t,
# but a fast lock/unlock cycle (e.g. a short idle delay) can still leave
# one visible right after unlock since its timeout hadn't elapsed yet --
# proactively closing it the moment the screen actually locks avoids that.
# Also don't use -u critical here even though it'd render more
# prominently: per the desktop notification spec, critical-urgency
# notifications are exempt from their own expire-timeout and stay up
# until explicitly dismissed -- confirmed live 2026-09-13, two of them
# stacked up and sat on screen indefinitely.
last_notif_id=0
close_notification() {
    [ "$last_notif_id" -gt 0 ] || return
    gdbus call --session --dest=org.freedesktop.Notifications \
        --object-path /org/freedesktop/Notifications \
        --method org.freedesktop.Notifications.CloseNotification \
        "$last_notif_id" >/dev/null 2>&1
    last_notif_id=0
}

# Echoes 0 if idle-activation is disabled (screen never auto-locks) or the
# xfconf channel isn't readable yet (e.g. right after login).
idle_delay_seconds() {
    if [ "$(xfconf-query -c xfce4-screensaver -p /saver/idle-activation/enabled 2>/dev/null)" = "false" ]; then
        echo 0
        return
    fi
    local mins
    mins=$(xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay 2>/dev/null)
    echo $(( ${mins:-5} * 60 ))
}

warned=0

while true; do
    warn_enabled=$(read_setting WARN_BEFORE_LOCK_ENABLED "$DEFAULT_WARN_ENABLED")
    warn_seconds=$(read_setting WARN_SECONDS_BEFORE_LOCK "$DEFAULT_WARN_SECONDS")

    if [ "$warn_enabled" != "true" ] || [ "$warn_seconds" -le 0 ] || is_locked; then
        warned=0
        close_notification
        sleep 2
        continue
    fi

    delay_seconds=$(idle_delay_seconds)
    if [ "$delay_seconds" -le 0 ]; then
        sleep 5
        continue
    fi

    idle_ms=$(xprintidle 2>/dev/null)
    if [ -z "$idle_ms" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi
    remaining=$(( delay_seconds - idle_ms / 1000 ))

    if [ "$remaining" -gt 0 ] && [ "$remaining" -le "$warn_seconds" ]; then
        if [ "$warned" -eq 0 ]; then
            last_notif_id=$(notify-send -p \
                -t $(( (remaining + 1) * 1000 )) \
                "$(t lockwarning.title)" \
                "$(t lockwarning.body)")
            warned=1
        fi
    elif [ "$remaining" -gt "$warn_seconds" ]; then
        warned=0
        close_notification
    fi

    sleep "$POLL_INTERVAL"
done
