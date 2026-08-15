#!/bin/bash
# Shuts the machine down if the screen stays locked continuously for SHUTDOWN_AFTER seconds.
# Any unlock resets the timer. Just stays awake and polls until the deadline -- an earlier
# version could cycle suspend/wake on battery to save power while still delivering queued
# notification sounds, but battery measurements showed screen-off draw is already low enough
# that it wasn't worth the complexity; see provisioning/experimental/cyberbeest-power-settings.sh
# for that removed code.

DEFAULT_SHUTDOWN_MIN=60 # default minutes locked before shutdown
POLL_INTERVAL=15        # how often to check lock state
# AC adapter's sysfs device name varies by hardware (ADP1, AC, ACAD, ...) --
# find whichever one is of type Mains rather than hardcoding it.
AC_ONLINE=""
for supply in /sys/class/power_supply/*/; do
    if [ "$(cat "${supply}type" 2>/dev/null)" = "Mains" ]; then
        AC_ONLINE="${supply}online"
        break
    fi
done
POWER_SETTINGS="$HOME/.config/cyberbeest/power-settings.conf"
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

locked_since=0

read_setting() {
    # read_setting KEY DEFAULT
    [ -f "$POWER_SETTINGS" ] || { echo "$2"; return; }
    local value
    value=$(grep "^$1=" "$POWER_SETTINGS" | tail -n1 | cut -d= -f2-)
    echo "${value:-$2}"
}

shutdown_minutes_for() {
    # shutdown_minutes_for AC|BATTERY -- falls back to the pre-split
    # SHUTDOWN_MINUTES key if the config file predates the AC/battery split.
    local value
    value=$(read_setting "${1}_SHUTDOWN_MINUTES" "")
    [ -n "$value" ] || value=$(read_setting SHUTDOWN_MINUTES "$DEFAULT_SHUTDOWN_MIN")
    echo "$value"
}

is_locked() {
    dbus-send --session --dest=org.xfce.ScreenSaver --type=method_call \
        --print-reply /org/xfce/ScreenSaver org.xfce.ScreenSaver.GetActive \
        2>/dev/null | grep -q "boolean true"
}

on_battery() {
    [ "$(cat "$AC_ONLINE" 2>/dev/null)" = "0" ]
}

while true; do
    if is_locked; then
        now=$(date +%s)
        if [ "$locked_since" -eq 0 ]; then
            locked_since=$now
        fi

        if on_battery; then
            shutdown_min=$(shutdown_minutes_for BATTERY)
        else
            shutdown_min=$(shutdown_minutes_for AC)
        fi

        if [ "$shutdown_min" -eq 0 ]; then
            # 0 == "Never" for this power source: skip the shutdown deadline entirely, just poll.
            sleep "$POLL_INTERVAL"
        else
            SHUTDOWN_AFTER=$(( shutdown_min * 60 ))

            elapsed=$(( now - locked_since ))
            if [ "$elapsed" -ge "$SHUTDOWN_AFTER" ]; then
                logger -t lock-shutdown-watcher "Locked for >= ${SHUTDOWN_AFTER}s, shutting down"
                systemctl poweroff
                exit 0
            fi

            sleep "$POLL_INTERVAL"
        fi
    else
        locked_since=0
        sleep "$POLL_INTERVAL"
    fi
done
