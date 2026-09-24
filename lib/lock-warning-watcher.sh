#!/bin/bash
# Pops a desktop notification a few seconds before xfce4-screensaver's own
# idle timer locks the screen, so a user who's still there (just not
# touching the mouse/keyboard) gets a chance to wiggle the mouse and reset
# the idle clock instead of being locked out. Normally just a warning -- it
# doesn't touch the lock timer itself, which xfce4-screensaver owns via its
# own xfconf channel (see 16-power-lock-config.sh) -- except when "no mercy"
# mode (NO_MERCY_LOCK_ENABLED) is on, in which case this script also forces
# the lock through via `xfce4-screensaver-command --lock` once the idle
# delay is reached and xfce4-screensaver is being inhibited, since an
# inhibit (video playback, a presentation, or a stuck/orphaned one) would
# otherwise silently defeat xfce4-screensaver's own idle timer.
#
# Reads the same config file as lock-shutdown-watcher.sh and
# shutdown-timer-menu.py (WARN_BEFORE_LOCK_ENABLED / WARN_SECONDS_BEFORE_LOCK /
# NO_MERCY_LOCK_ENABLED, set from lock-power-saving-dialog.py's "Extended
# Power Options" window). Polls xprintidle every second -- cheap enough for
# second-level precision, unlike the 15s poll lock-shutdown-watcher.sh uses
# for its much coarser post-lock deadlines.

DEFAULT_WARN_ENABLED=true
DEFAULT_WARN_SECONDS=10
DEFAULT_NO_MERCY_ENABLED=false
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

is_inhibited() {
    xfce4-screensaver-command -q 2>/dev/null | grep -q "is being inhibited"
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

warned_remaining=0

while true; do
    if is_locked; then
        warned_remaining=0
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

    # No-mercy: force the lock through even though an app is inhibiting
    # xfce4-screensaver's own idle timer (video playback, a presentation,
    # or a stuck/orphaned inhibit -- see the 2026-09-14 postmortem where an
    # orphaned inhibit silently defeated auto-lock for hours). Opt-in via
    # lock-power-saving-dialog.py's "Extended Power Options" window;
    # deliberately no extra warning beyond the notification below.
    no_mercy=$(read_setting NO_MERCY_LOCK_ENABLED "$DEFAULT_NO_MERCY_ENABLED")
    if [ "$no_mercy" = "true" ] && [ "$remaining" -le 0 ] && is_inhibited; then
        xfce4-screensaver-command --lock >/dev/null 2>&1
    fi

    warn_enabled=$(read_setting WARN_BEFORE_LOCK_ENABLED "$DEFAULT_WARN_ENABLED")
    warn_seconds=$(read_setting WARN_SECONDS_BEFORE_LOCK "$DEFAULT_WARN_SECONDS")
    if [ "$warn_enabled" = "true" ] && [ "$warn_seconds" -gt 0 ]; then
        if [ "$remaining" -gt 0 ] && [ "$remaining" -le "$warn_seconds" ]; then
            # Re-sent every second (replacing the previous one in place
            # via -r) so the title counts down the remaining seconds.
            if [ "$remaining" -ne "$warned_remaining" ]; then
                if [ "$remaining" -eq 1 ]; then
                    title=$(t lockwarning.title_one)
                else
                    title=$(t lockwarning.title)
                    title=${title//SECONDS/$remaining}
                fi
                last_notif_id=$(notify-send -p -r "$last_notif_id" \
                    -t $(( (remaining + 1) * 1000 )) \
                    "$title" \
                    "$(t lockwarning.body)")
                warned_remaining=$remaining
            fi
        elif [ "$remaining" -gt "$warn_seconds" ]; then
            warned_remaining=0
            close_notification
        fi
    fi

    sleep "$POLL_INTERVAL"
done
