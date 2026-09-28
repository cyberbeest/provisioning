#!/bin/bash
# acpid action for the power button, invoked as
#   cyberbeest-powerbtn-double-press.sh "<raw event text>"
# via the "%e" placeholder in ../lib/cyberbeest-powerbtn-double.acpi. acpid
# gets the raw ACPI event regardless of what xfce4-power-manager does with
# it (it holds a logind inhibitor and shows its own "Ask" dialog on every
# press) -- this script tracks a press count in a tmpfs state file:
# REQUIRED_PRESSES quick presses in a row (each gap <= WINDOW_MS) forces
# an immediate real shutdown, bypassing the dialog. Any single press still
# lets the dialog appear as normal; a gap over WINDOW_MS resets the count
# back to 1. See ../55-powerbtn-double-press.sh. Touching
# /run/cyberbeest-powerbtn-test-mode swaps the real `systemctl poweroff`
# for a desktop notification instead, for testing the full press-counting
# flow on real hardware without any shutdown risk. Not created by the
# installer -- live behavior (the default) needs it absent.
#
# Deliberately press-based, not hold-based: a hold-to-shutdown design was
# tried and abandoned 2026-09-28 after holding the real button (even with
# the software side just logging, never calling poweroff) left the
# machine in a broken state -- keyboard dead and the power LED off while
# still fully running, needing a hard power-cycle to recover. That's a
# firmware/EC-level fault below anything Linux can see or control, so the
# fix is to never require a sustained hold at all.
set -uo pipefail

# One physical press reaches acpid as two events for the SAME press --
# confirmed live 2026-09-28: "button/power PBTN 00000080 00000000" (input
# layer) and "button/power PNP0C0C:00 00000080 00000001" (netlink).
# Earlier versions tried to dedupe these by elapsed time (DEBOUNCE_MS),
# but that conflicts with wanting fast repeated real taps to each
# register -- a large-enough debounce to reliably swallow the phantom
# (it ran past 1s on this hardware, see git history) also silently drops
# a genuine second tap made within that same window. Filtering by event
# identifier instead removes the duplicate at the source, so only a small
# DEBOUNCE_MS is kept, as a cheap safety net rather than the main defense.
read -r _ ident _ _ <<<"${1:-}"
[ "$ident" = "PBTN" ] || exit 0

STATE_TIME_FILE=/run/cyberbeest-powerbtn-last-press
STATE_COUNT_FILE=/run/cyberbeest-powerbtn-press-count
WINDOW_MS=6000
DEBOUNCE_MS=250
REQUIRED_PRESSES=4

now=$(date +%s%3N)
last=0
[ -f "$STATE_TIME_FILE" ] && last=$(cat "$STATE_TIME_FILE" 2>/dev/null || echo 0)
case "$last" in '' | *[!0-9]*) last=0 ;; esac
count=0
[ -f "$STATE_COUNT_FILE" ] && count=$(cat "$STATE_COUNT_FILE" 2>/dev/null || echo 0)
case "$count" in '' | *[!0-9]*) count=0 ;; esac
elapsed=$((now - last))

if [ "$elapsed" -lt "$DEBOUNCE_MS" ]; then
	exit 0
elif [ "$elapsed" -le "$WINDOW_MS" ] && [ "$count" -gt 0 ]; then
	count=$((count + 1))
else
	count=1
fi

if [ "$count" -ge "$REQUIRED_PRESSES" ]; then
	rm -f "$STATE_TIME_FILE" "$STATE_COUNT_FILE"
	if [ -f /run/cyberbeest-powerbtn-test-mode ]; then
		logger -t cyberbeest-powerbtn "$REQUIRED_PRESSES power-button presses within ${WINDOW_MS}ms of each other -- TEST MODE, not shutting down"
		# Same root-to-user-session pattern as xfce-panel-reload.sh: pull
		# DISPLAY/DBUS_SESSION_BUS_ADDRESS off a running session process
		# rather than assuming a fixed value, since this runs as root
		# with no session environment of its own.
		target_user=cyberbeest
		panel_pid="$(pgrep -u "$target_user" -x xfce4-panel | head -1)" || true
		if [ -n "${panel_pid:-}" ]; then
			env_blob="$(tr '\0' '\n' < "/proc/$panel_pid/environ")"
			env_display="$(printf '%s\n' "$env_blob" | sed -n 's/^DISPLAY=//p')"
			env_dbus="$(printf '%s\n' "$env_blob" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
			su - "$target_user" -c "DISPLAY='${env_display:-:0}' DBUS_SESSION_BUS_ADDRESS='$env_dbus' notify-send --urgency=critical 'Power button (test mode)' '$REQUIRED_PRESSES presses detected -- would shut down now'" || true
		fi
	else
		logger -t cyberbeest-powerbtn "$REQUIRED_PRESSES power-button presses within ${WINDOW_MS}ms of each other -- shutting down now"
		systemctl poweroff
	fi
else
	echo "$now" > "$STATE_TIME_FILE"
	echo "$count" > "$STATE_COUNT_FILE"
fi
