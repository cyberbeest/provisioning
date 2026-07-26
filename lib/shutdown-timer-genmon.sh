#!/bin/bash
# Panel item: shows the currently configured auto-shutdown-while-locked
# time(s) for xfce4-genmon-plugin. Reads the same config file as
# lock-shutdown-watcher.sh and cyberbeest_power_settings_gui.py. Click opens
# a quick menu to change it (see shutdown-timer-menu.py).

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

idle_delay_s=$(gsettings get org.gnome.desktop.session idle-delay 2>/dev/null | awk '{print $2}')
idle_delay_s=${idle_delay_s:-300}
lock_line="Locks after $(fmt $(( idle_delay_s / 60 ))) idle"

if [ "$linked" = "true" ] || [ "$ac_min" = "$bat_min" ]; then
    echo "<txt>⏻ $(fmt "$ac_min")</txt>"
    if [ "$ac_min" -eq 0 ]; then
        echo "<tool>${lock_line}&#10;Auto-shutdown while locked is disabled (AC and battery)&#10;Click to change</tool>"
    else
        echo "<tool>${lock_line}&#10;Auto-shutdown after $(fmt "$ac_min") locked (AC and battery)&#10;Click to change</tool>"
    fi
else
    echo "<txt>⏻ $(fmt "$ac_min")/$(fmt "$bat_min")</txt>"
    printf '<tool>%s&#10;Auto-shutdown after being locked:&#10;  AC: %s&#10;  Battery: %s&#10;Click to change</tool>\n' \
        "$lock_line" "$(fmt "$ac_min")" "$(fmt "$bat_min")"
fi
echo "<txtclick>$HOME/.local/bin/shutdown-timer-menu.py</txtclick>"
