#!/bin/bash
# Panel item: shows the currently configured auto-shutdown-while-locked
# time(s) for xfce4-genmon-plugin. Reads the same config file as
# lock-shutdown-watcher.sh. Click opens a quick menu to change it (see
# shutdown-timer-menu.py).

POWER_SETTINGS="$HOME/.config/cyberbeest/power-settings.conf"
DEFAULT_MIN=60

read_setting() {
    # read_setting KEY DEFAULT
    [ -f "$POWER_SETTINGS" ] || { echo "$2"; return; }
    local value
    value=$(grep "^$1=" "$POWER_SETTINGS" | tail -n1 | cut -d= -f2-)
    echo "${value:-$2}"
}

shutdown_minutes_for() {
    local value
    value=$(read_setting "${1}_SHUTDOWN_MINUTES" "")
    [ -n "$value" ] || value=$(read_setting SHUTDOWN_MINUTES "$DEFAULT_MIN")
    echo "$value"
}

fmt() {
    local mins=$1
    if [ "$mins" -eq 0 ]; then
        echo "Never"
    elif [ "$mins" -ge 60 ] && [ $(( mins % 60 )) -eq 0 ]; then
        echo "$(( mins / 60 ))h"
    elif [ "$mins" -ge 60 ]; then
        echo "$(( mins / 60 ))h$(( mins % 60 ))m"
    else
        echo "${mins}m"
    fi
}

ac_min=$(shutdown_minutes_for AC)
bat_min=$(shutdown_minutes_for BATTERY)
linked=$(read_setting LINK_AC_BATTERY "true")

# xfce4-screensaver owns idle-lock timing through its own xfconf channel --
# the delay property has a 1-minute floor and no "Never" value of its own,
# so "Never" is idle-activation/enabled=false instead.
if [ "$(xfconf-query -c xfce4-screensaver -p /saver/idle-activation/enabled 2>/dev/null)" = "false" ]; then
    idle_delay_min=0
else
    idle_delay_min=$(xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay 2>/dev/null)
    idle_delay_min=${idle_delay_min:-5}
fi
if [ "$idle_delay_min" -eq 0 ]; then
    lock_line="No auto-lock"
else
    lock_line="Locks after $(fmt "$idle_delay_min") idle"
fi

# A configured auto-shutdown time is a no-op if the screen never auto-locks --
# flag that on the icon itself, not just in the tooltip, since it silently
# defeats a safety feature the device otherwise relies on.
warn_txt=""
warn_line=""
if [ "$idle_delay_min" -eq 0 ] && { [ "$ac_min" -gt 0 ] || [ "$bat_min" -gt 0 ]; }; then
    warn_txt=" ⚠"
    warn_line="IMPORTANT: Auto-lock is off, so auto-shutdown is disabled&#10;"
fi

if [ "$linked" = "true" ] || [ "$ac_min" = "$bat_min" ]; then
    echo "<txt>⏻ $(fmt "$ac_min")${warn_txt}</txt>"
    if [ "$ac_min" -eq 0 ]; then
        echo "<tool>${warn_line}${lock_line}&#10;Auto-shutdown while locked is disabled (AC and battery)&#10;Click to change</tool>"
    else
        echo "<tool>${warn_line}${lock_line}&#10;Auto-shutdown after $(fmt "$ac_min") locked (AC and battery)&#10;Click to change</tool>"
    fi
else
    echo "<txt>⏻ $(fmt "$ac_min")/$(fmt "$bat_min")${warn_txt}</txt>"
    printf '<tool>%sAuto-shutdown after being locked:&#10;  AC: %s&#10;  Battery: %s&#10;Click to change</tool>\n' \
        "${warn_line}${lock_line}&#10;" "$(fmt "$ac_min")" "$(fmt "$bat_min")"
fi
echo "<txtclick>$HOME/.local/bin/shutdown-timer-menu.py</txtclick>"
