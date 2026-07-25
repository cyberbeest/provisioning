#!/bin/bash
# Runs every provisioning script in this directory in numeric order.
# Each NN-*.sh script is expected to be idempotent and self-logging.
set -euo pipefail
cd "$(dirname "$0")"

for script in [0-9][0-9]-*.sh; do
	echo "=== running $script ==="
	if bash "$script"; then
		echo "=== $script done (log: ${script%.sh}.log) ==="
	else
		echo "=== $script FAILED (log: ${script%.sh}.log) ===" >&2
		echo "Stopping here since later scripts may depend on this one." >&2
		exit 1
	fi
done

# Best-effort: run-all.sh may be invoked headlessly (no X session), so a
# missing/failing panel reload here is not an error. It may also be invoked
# via `sudo ./run-all.sh` (see README), in which case this whole script runs
# as root and can't reach the logged-in user's D-Bus session bus directly --
# drop back to that user for the reload, reading the bus address off their
# actual running panel process (most reliable) rather than assuming the
# standard /run/user/<uid>/bus path.
if command -v xfce4-panel >/dev/null 2>&1; then
	echo "Reloading xfce4-panel to pick up new/changed desktop entries..."
	if [ "$(id -u)" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
		TARGET_UID="$(id -u "$SUDO_USER")"
		PANEL_PID="$(pgrep -u "$SUDO_USER" -x xfce4-panel | head -1)"
		DBUS_ADDR=""
		if [ -n "$PANEL_PID" ] && [ -r "/proc/$PANEL_PID/environ" ]; then
			DBUS_ADDR="$(tr '\0' '\n' < "/proc/$PANEL_PID/environ" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
		fi
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
		su - "$SUDO_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	else
		xfce4-panel -r || true
	fi
fi
