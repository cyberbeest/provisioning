#!/bin/bash
# acpid action for the power button. acpid gets the raw ACPI event
# regardless of what xfce4-power-manager does with it (it holds a logind
# inhibitor and shows its own "Ask" dialog on the first press) -- this
# script just tracks press timestamps in a tmpfs state file: a first press
# is a no-op here (the dialog still appears as normal), a second press
# within WINDOW_MS forces an immediate real shutdown, bypassing the
# dialog. See ../55-powerbtn-double-press.sh.
set -uo pipefail

# One physical press reaches acpid as two events (the input layer's
# "button/power PBTN" and the netlink "button/power LNXPWRBN"), usually
# ~150ms apart, so anything closer together than DEBOUNCE_MS is the same
# press -- without this, a single press counted as a double one and shut
# down immediately. 1000ms wasn't enough margin in practice: it happened
# twice (2026-09-20, 2026-09-28) with systemd-logind logging only one real
# "Power key pressed short" both times, so the gap between the two acpid
# events can run well past 1s on this hardware. Bumped to 3000ms, still
# leaving 3s of the WINDOW_MS below for a real second press.
STATE_FILE=/run/cyberbeest-powerbtn-last-press
WINDOW_MS=6000
DEBOUNCE_MS=3000

now=$(date +%s%3N)
last=0
[ -f "$STATE_FILE" ] && last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
case "$last" in '' | *[!0-9]*) last=0 ;; esac
elapsed=$((now - last))

if [ "$elapsed" -lt "$DEBOUNCE_MS" ]; then
	exit 0
elif [ "$elapsed" -le "$WINDOW_MS" ]; then
	logger -t cyberbeest-powerbtn "second power-button press within $((WINDOW_MS / 1000))s -- shutting down now"
	rm -f "$STATE_FILE"
	systemctl poweroff
else
	echo "$now" > "$STATE_FILE"
fi
