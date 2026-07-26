#!/bin/bash
# Shuts the machine down if the screen stays locked continuously for SHUTDOWN_AFTER seconds.
# Any unlock resets the timer.
#
# By default (and always on AC), it just stays awake and polls until the deadline. If the
# experimental NOTIFICATIONS_WHEN_LOCKED setting is on, on battery it instead cycles between a
# short awake window (to let apps reconnect and fire any queued notification sounds) and a
# longer suspend window (RTC-timed via wakealarm), so most of the time is spent asleep. The
# deadline is wall-clock, so it's unaffected by how much of that time was spent suspended.

DEFAULT_SHUTDOWN_MIN=60 # default minutes locked before shutdown
POLL_INTERVAL=15        # how often to check lock state on AC
DEFAULT_AWAKE_MIN=1     # default awake window per cycle on battery (minutes)
DEFAULT_ASLEEP_MIN=9    # default suspended window per cycle on battery (minutes)
WAKEALARM=/sys/class/rtc/rtc0/wakealarm
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

notifications_when_locked_enabled() {
    # Defaults to disabled (experimental) if the config file or key is missing.
    [ "$(read_setting NOTIFICATIONS_WHEN_LOCKED false)" = "true" ]
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

suspend_for() {
    local secs=$1
    echo 0 > "$WAKEALARM" 2>/dev/null
    if ! echo "+$secs" > "$WAKEALARM" 2>/dev/null; then
        logger -t lock-shutdown-watcher "Could not arm RTC wakealarm, skipping suspend cycle"
        return 1
    fi
    logger -t lock-shutdown-watcher "Suspending for ${secs}s"
    systemctl suspend
}

idle_ms() {
    xprintidle 2>/dev/null
}

wait_awake_window() {
    # Waits at least $1 seconds, but extends the wait a second at a time
    # while xprintidle shows recent activity (someone's typing/clicking,
    # e.g. mid password entry), so we never suspend out from under a login
    # attempt. Returns early the moment the session unlocks. If xprintidle
    # is unavailable, falls back to the plain fixed wait. Uncapped on the
    # activity side -- real input means someone's actually there.
    local min_wait=$1
    local idle_safe_ms=5000
    local start
    start=$(date +%s)
    local deadline=$(( start + min_wait ))

    while true; do
        if ! is_locked; then
            return
        fi
        local now
        now=$(date +%s)
        local ms
        ms=$(idle_ms)
        if [ -n "$ms" ] && [ "$ms" -lt "$idle_safe_ms" ]; then
            sleep 1
            continue
        fi
        if [ "$now" -ge "$deadline" ]; then
            return
        fi
        sleep 1
    done
}

screen_off() {
    # Cuts the panel via DPMS right after an RTC resume, so the flash of the
    # lock screen is brief instead of lasting the whole awake window. Any real
    # input (mouse/keyboard) wakes it back up automatically -- that's DPMS's
    # normal behavior, no polling needed here.
    #
    # Retried over ~10s: right after resume, the X server/DRM is still
    # settling and xfce4-power-manager may re-assert display-on shortly
    # after the resume event, so a single one-shot call can silently lose
    # that race.
    for _ in $(seq 1 10); do
        xset dpms force off 2>/dev/null
        sleep 1
    done
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
            # 0 == "Never" for this power source: skip the shutdown deadline
            # and the notification suspend-cycle (which is defined relative
            # to that deadline) entirely, just poll.
            sleep "$POLL_INTERVAL"
        else
            SHUTDOWN_AFTER=$(( shutdown_min * 60 ))

            elapsed=$(( now - locked_since ))
            if [ "$elapsed" -ge "$SHUTDOWN_AFTER" ]; then
                logger -t lock-shutdown-watcher "Locked for >= ${SHUTDOWN_AFTER}s, shutting down"
                systemctl poweroff
                exit 0
            fi

            if on_battery && notifications_when_locked_enabled; then
                remaining=$(( SHUTDOWN_AFTER - elapsed ))
                asleep_min=$(read_setting ASLEEP_MINUTES "$DEFAULT_ASLEEP_MIN")
                awake_min=$(read_setting AWAKE_MINUTES "$DEFAULT_AWAKE_MIN")
                asleep_s=$(( asleep_min * 60 ))
                if [ "$asleep_s" -gt "$remaining" ]; then
                    asleep_s=$remaining
                fi
                if suspend_for "$asleep_s"; then
                    screen_off
                    wait_awake_window "$(( awake_min * 60 ))"
                else
                    sleep "$POLL_INTERVAL"
                fi
            else
                # Experimental cycling off (or on AC): never suspend, just stay
                # awake and poll until the lock either clears or hits the deadline.
                sleep "$POLL_INTERVAL"
            fi
        fi
    else
        locked_since=0
        sleep "$POLL_INTERVAL"
    fi
done
