#!/bin/bash
# acpid action for the power button. acpid gets the raw ACPI event
# regardless of what xfce4-power-manager does with it (it holds a logind
# inhibitor and shows its own "Ask" dialog on the first press) -- this
# script just tracks press timestamps in a tmpfs state file: a first press
# is a no-op here (the dialog still appears as normal), a second press
# within WINDOW seconds forces an immediate real shutdown, bypassing the
# dialog. See ../55-powerbtn-double-press.sh.
set -uo pipefail

STATE_FILE=/run/cyberbeest-powerbtn-last-press
WINDOW=6

now=$(date +%s)
last=0
[ -f "$STATE_FILE" ] && last=$(cat "$STATE_FILE" 2>/dev/null || echo 0)

if [ $((now - last)) -le "$WINDOW" ]; then
	logger -t cyberbeest-powerbtn "second power-button press within ${WINDOW}s -- shutting down now"
	rm -f "$STATE_FILE"
	systemctl poweroff
else
	echo "$now" > "$STATE_FILE"
fi
