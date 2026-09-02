#!/bin/bash
# Shuts the machine down if the screen stays locked continuously for SHUTDOWN_AFTER seconds.
# Any unlock resets the timer. Just stays awake and polls until the deadline -- an earlier
# version could cycle suspend/wake on battery to save power while still delivering queued
# notification sounds, but battery measurements showed screen-off draw is already low enough
# that it wasn't worth the complexity; see provisioning/experimental/cyberbeest-power-settings.sh
# for that removed code.

DEFAULT_SHUTDOWN_MIN=60  # default minutes locked before shutdown
DEFAULT_MINIMIZE_MIN=10  # default minutes locked before minimizing windows (power saving: minimized windows stop repainting)
DEFAULT_THROTTLE_PERCENT=10  # default CPU cap (% of one core, per process) applied to the browser while locked; 0 disables
POLL_INTERVAL=15         # how often to check lock state
MINIMIZED_STATE_FILE="$HOME/.cache/cyberbeest/lock-minimized-windows.list"
THROTTLE_STATE_FILE="$HOME/.cache/cyberbeest/lock-throttle-cpulimit.pids"
# Process names to throttle while locked. firejail's sandboxed launch (see
# browser-sandbox.sh) doesn't hide these from the host process table, so
# plain pgrep/cpulimit on the host works regardless of the sandbox.
BROWSER_PROCESS_NAMES="firefox-esr firefox chromium chromium-browser google-chrome"
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

# Minimizes every normal top-level window that isn't already minimized, and
# records their IDs so restore_windows can bring back only those ones later
# (windows the user had already minimized before locking are left alone).
minimize_windows() {
    mkdir -p "$(dirname "$MINIMIZED_STATE_FILE")"
    : > "$MINIMIZED_STATE_FILE"
    local id type state
    while read -r id _; do
        [ -z "$id" ] && continue
        type=$(xprop -id "$id" _NET_WM_WINDOW_TYPE 2>/dev/null)
        case "$type" in
            *_NET_WM_WINDOW_TYPE_DESKTOP*|*_NET_WM_WINDOW_TYPE_DOCK*) continue ;;
        esac
        state=$(xprop -id "$id" _NET_WM_STATE 2>/dev/null)
        case "$state" in
            *_NET_WM_STATE_HIDDEN*) continue ;; # already minimized, leave as-is
        esac
        wmctrl -ir "$id" -b add,hidden
        echo "$id" >> "$MINIMIZED_STATE_FILE"
    done < <(wmctrl -l 2>/dev/null)
    logger -t lock-shutdown-watcher "Minimized $(wc -l < "$MINIMIZED_STATE_FILE") window(s) after prolonged lock"
}

is_hidden() {
    xprop -id "$1" _NET_WM_STATE 2>/dev/null | grep -q "_NET_WM_STATE_HIDDEN"
}

restore_windows() {
    [ -s "$MINIMIZED_STATE_FILE" ] || { rm -f "$MINIMIZED_STATE_FILE"; return; }
    local id restored=0 failed=0
    while read -r id; do
        [ -z "$id" ] && continue
        # Right after unlock, xfwm4/the screensaver's own teardown can briefly
        # re-assert a window's prior (hidden) state a moment after our own
        # unhide lands -- a race a single immediate check won't catch. Keep
        # reasserting for a few seconds so it settles into the visible state.
        local attempt
        for attempt in 1 2 3 4 5; do
            if is_hidden "$id"; then
                wmctrl -ir "$id" -b remove,hidden
                xdotool windowmap "$id" windowactivate "$id" 2>/dev/null
            fi
            sleep 1
            is_hidden "$id" || break
        done
        if is_hidden "$id"; then
            failed=$(( failed + 1 ))
        else
            restored=$(( restored + 1 ))
        fi
    done < "$MINIMIZED_STATE_FILE"
    local msg="Restored ${restored} window(s) after unlock"
    [ "$failed" -gt 0 ] && msg="${msg}, ${failed} failed to restore"
    logger -t lock-shutdown-watcher "$msg"
    rm -f "$MINIMIZED_STATE_FILE"
}

# Caps each matched browser process (and its children, e.g. tab/GPU
# processes -- cpulimit -m tracks those as they fork) to PERCENT% of one CPU
# core via periodic SIGSTOP/SIGCONT. Deliberately not a hard freeze: this
# keeps enough cycles flowing that in-progress downloads still make progress
# and queued web-notification audio still plays, just slower, rather than
# using something like a full SIGSTOP that would silence audio outright.
throttle_browser() {
    local percent="$1"
    mkdir -p "$(dirname "$THROTTLE_STATE_FILE")"
    : > "$THROTTLE_STATE_FILE"
    local name pid
    for name in $BROWSER_PROCESS_NAMES; do
        for pid in $(pgrep -x "$name" 2>/dev/null); do
            cpulimit -z -q -l "$percent" -p "$pid" -m &
            echo $! >> "$THROTTLE_STATE_FILE"
        done
    done
    logger -t lock-shutdown-watcher "Throttled browser CPU to ${percent}% after prolonged lock"
}

unthrottle_browser() {
    [ -s "$THROTTLE_STATE_FILE" ] || { rm -f "$THROTTLE_STATE_FILE"; return; }
    local pid
    while read -r pid; do
        [ -z "$pid" ] && continue
        # cpulimit's own exit handler SIGCONTs whatever it last stopped, so
        # just killing the watcher is enough to release the throttle.
        kill "$pid" 2>/dev/null
    done < "$THROTTLE_STATE_FILE"
    rm -f "$THROTTLE_STATE_FILE"
}

windows_minimized=0

while true; do
    if is_locked; then
        now=$(date +%s)
        if [ "$locked_since" -eq 0 ]; then
            locked_since=$now
        fi
        elapsed=$(( now - locked_since ))

        if [ "$windows_minimized" -eq 0 ]; then
            minimize_min=$(read_setting MINIMIZE_MINUTES "$DEFAULT_MINIMIZE_MIN")
            if [ "$minimize_min" -gt 0 ] && [ "$elapsed" -ge $(( minimize_min * 60 )) ]; then
                minimize_windows
                throttle_percent=$(read_setting BROWSER_THROTTLE_PERCENT "$DEFAULT_THROTTLE_PERCENT")
                [ "$throttle_percent" -gt 0 ] && throttle_browser "$throttle_percent"
                windows_minimized=1
            fi
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

            if [ "$elapsed" -ge "$SHUTDOWN_AFTER" ]; then
                logger -t lock-shutdown-watcher "Locked for >= ${SHUTDOWN_AFTER}s, shutting down"
                systemctl poweroff
                exit 0
            fi

            sleep "$POLL_INTERVAL"
        fi
    else
        if [ "$windows_minimized" -eq 1 ]; then
            restore_windows
            unthrottle_browser
            windows_minimized=0
        fi
        locked_since=0
        sleep "$POLL_INTERVAL"
    fi
done
