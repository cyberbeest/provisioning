#!/bin/bash
# Panel item: shows the currently configured auto-shutdown-while-locked
# time(s) for xfce4-genmon-plugin. Reads the same config file as
# lock-shutdown-watcher.sh. Click opens a quick menu to change it (see
# shutdown-timer-menu.py).

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# i18n.sh (and its i18n/ catalog dir) is installed next to this script -- see
# lib/i18n.sh's own comment about resolving relative to BASH_SOURCE.
. "$SELF_DIR/i18n.sh"

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
        t shutdown_genmon.never
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
    lock_line="$(t shutdown_genmon.no_auto_lock)"
else
    lock_line="$(t shutdown_genmon.locks_after)"
    lock_line="${lock_line//DURATION/$(fmt "$idle_delay_min")}"
fi

# A configured auto-shutdown time is a no-op if the screen never auto-locks --
# flag that on the icon itself, not just in the tooltip, since it silently
# defeats a safety feature the device otherwise relies on.
warn_txt=""
warn_line=""
if [ "$idle_delay_min" -eq 0 ] && { [ "$ac_min" -gt 0 ] || [ "$bat_min" -gt 0 ]; }; then
    warn_txt=" ⚠"
    warn_line="$(t shutdown_genmon.auto_lock_off_warning)&#10;"
fi

click_line="$(t shutdown_genmon.click_to_change)"

if [ "$linked" = "true" ] || [ "$ac_min" = "$bat_min" ]; then
    echo "<txt>⏻ $(fmt "$ac_min")${warn_txt}</txt>"
    if [ "$ac_min" -eq 0 ]; then
        echo "<tool>${warn_line}${lock_line}&#10;$(t shutdown_genmon.disabled_both)&#10;${click_line}</tool>"
    else
        after_both="$(t shutdown_genmon.after_both)"
        after_both="${after_both//DURATION/$(fmt "$ac_min")}"
        echo "<tool>${warn_line}${lock_line}&#10;${after_both}&#10;${click_line}</tool>"
    fi
else
    echo "<txt>⏻ $(fmt "$ac_min")/$(fmt "$bat_min")${warn_txt}</txt>"
    ac_line="$(t shutdown_genmon.ac_label)"
    ac_line="${ac_line//DURATION/$(fmt "$ac_min")}"
    bat_line="$(t shutdown_genmon.battery_label)"
    bat_line="${bat_line//DURATION/$(fmt "$bat_min")}"
    printf '<tool>%s%s&#10;  %s&#10;  %s&#10;%s</tool>\n' \
        "${warn_line}${lock_line}&#10;" "$(t shutdown_genmon.after_locked_header)" "$ac_line" "$bat_line" "$click_line"
fi
echo "<txtclick>$HOME/.local/bin/shutdown-timer-menu.py</txtclick>"
