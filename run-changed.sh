#!/bin/bash
# Like run-all.sh, but skips any NN-*.sh script whose log file is newer than
# the script itself -- i.e. it already ran successfully since it was last
# edited. Useful for re-running just the scripts you've touched instead of
# the whole set (each script is idempotent anyway, so this is a speed
# optimization, not a correctness requirement).
#
# Caveat: this compares file mtimes, so a fresh `git clone`/checkout (which
# resets mtimes on all files) will make everything look "changed" again.
set -euo pipefail

# Each NN-*.sh script expects to run as root -- re-exec under sudo up front
# (prompting for the password once here) rather than letting the first
# script fail confusingly partway through its own apt-get/etc calls.
if [ "$(id -u)" -ne 0 ]; then
	exec sudo bash "$0" "$@"
fi

cd "$(dirname "$0")"
source lib/sticky-header.sh

scripts=( [0-9][0-9]-*.sh )
sticky_header_start
trap sticky_header_stop EXIT

for i in "${!scripts[@]}"; do
	script="${scripts[$i]}"
	remaining=$(( ${#scripts[@]} - i - 1 ))
	sticky_header_set "$script" "$remaining"
	log="${script%.sh}.log"
	if [ -e "$log" ] && [ "$log" -nt "$script" ]; then
		echo "=== skipping $script (unchanged since $log) ==="
		continue
	fi
	echo "=== running $script ==="
	if bash "$script"; then
		echo "=== $script done (log: $log) ==="
	else
		echo "=== $script FAILED (log: $log) ===" >&2
		echo "Stopping here since later scripts may depend on this one." >&2
		exit 1
	fi
	ran_something=1
done

# Best-effort: may be invoked headlessly (no X session), so a missing/failing
# panel reload here is not an error. It may also be invoked via
# `sudo ./run-changed.sh` (see README), in which case this whole script runs
# as root and can't reach the logged-in user's D-Bus session bus directly --
# drop back to that user for the reload, reading the bus address off their
# actual running panel process (most reliable) rather than assuming the
# standard /run/user/<uid>/bus path.
if [ -n "${ran_something:-}" ] && command -v xfce4-panel >/dev/null 2>&1; then
	echo "Reloading xfce4-panel to pick up new/changed desktop entries..."
	if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
		TARGET_UID="$(id -u "$SUDO_USER")"
		PANEL_PID="$(pgrep -u "$SUDO_USER" -x xfce4-panel | head -1)"
		DBUS_ADDR=""
		if [ -n "$PANEL_PID" ]; then
			# cat (not `< file`) so a PID that vanishes between pgrep and here
			# just yields empty output instead of a fatal shell redirection error.
			DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
		fi
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
		su - "$SUDO_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	else
		xfce4-panel -r || true
	fi
fi
