#!/bin/bash
# Builds and installs the custom xfce4-panel plugins (cpuload-color,
# kitt-scanner, wattage-panel, mem-liquid) from source -- see
# lib/xfce-panel-plugins/. Built on the target rather than shipped as
# prebuilt .so files, since the panel plugin ABI is tied to the exact
# xfce4-panel/gtk3 versions installed, which a binary can't guarantee.
# Idempotent: safe to re-run (make install just overwrites).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/11-xfce-panel-plugins.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : building custom xfce4-panel plugins ==="

echo "--- Installing build dependencies ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y build-essential pkg-config gettext \
	libxfce4panel-2.0-dev libxfce4util-dev libxfce4ui-2-dev \
	libgtk-3-dev libx11-dev libxext-dev

echo "--- Building and installing plugins ---"
make -C "$DIR/lib/xfce-panel-plugins" clean install

echo "--- Reloading xfce4-panel for the logged-in user, if one is running ---"
TARGET_USER="${SUDO_USER:-cyberbeest}"
if command -v xfce4-panel >/dev/null 2>&1; then
	PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
	if [ -n "$PANEL_PID" ]; then
		DBUS_ADDR=""
		# cat (not `< file`) so a PID that vanishes between pgrep and here
		# just yields empty output instead of a fatal shell redirection error.
		DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	fi
fi

echo "=== $(date) : done ==="
