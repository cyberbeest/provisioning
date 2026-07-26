#!/bin/bash
# Installs the Cyberbeest desktop wallpaper + the autostart entry that sets
# it reliably regardless of what XRandR calls the actual monitor -- see
# lib/set-desktop-background.sh for why a static xfce4-desktop.xml copy
# doesn't work across different hardware.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/18-desktop-background.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing desktop background ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing xrandr (used to find the real monitor name) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y x11-xserver-utils

echo "--- Installing wallpaper images ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg.png" "$TARGET_HOME/Pictures/Cyberbeest.png"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-desktop-bg-simplified.png" "$TARGET_HOME/Pictures/Cyberbeest-simplified.png"

echo "--- Also dropping it into /usr/share/backgrounds/xfce/ ---"
# So it's directly pickable from Desktop Settings' "xfce" folder (the one
# xfdesktop4-data ships) without needing xfconf automation to have run at
# all -- a human can just click it in the grid.
install -m 644 "$DIR/lib/assets/cyberbeest-desktop-bg.png" \
	/usr/share/backgrounds/xfce/cyberbeest.png

echo "--- Installing set-desktop-background.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/set-desktop-background.sh" "$TARGET_HOME/.local/bin/set-desktop-background.sh"

echo "--- Installing autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-set-wallpaper.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-set-wallpaper.desktop"

echo "--- Running it now, if the target user has an active session ---"
TARGET_UID="$(id -u "$TARGET_USER")"
if [ -d "/run/user/$TARGET_UID" ]; then
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $TARGET_HOME/.local/bin/set-desktop-background.sh" || true
else
	echo "no active session for $TARGET_USER -- it'll run at next login"
fi

echo "=== $(date) : done ==="
