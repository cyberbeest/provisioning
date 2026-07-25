#!/bin/bash
# Lays out the xfce4 panel to match the dev machine: Whisker menu, the
# custom monitoring plugins (built by 11-xfce-panel-plugins.sh), a genmon
# security-status widget (fed by 07-security-update-timer.sh), the power
# manager plugin, and launchers for a terminal and Cyberbeest Power Settings
# (08-cyberbeest-power-settings.sh).
# Depends on: 07-security-update-timer.sh, 08-cyberbeest-power-settings.sh,
# 09-cyberbeest-logout-dialog.sh, 10-browser-sandbox.sh,
# 11-xfce-panel-plugins.sh.
# Idempotent: safe to re-run (overwrites its own config files; backs up any
# pre-existing xfce4-panel.xml the first time).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/12-xfce-panel-layout.log"
exec > "$LOG" 2>&1

echo "=== $(date) : applying xfce4 panel layout ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
LAYOUT="$DIR/lib/xfce-panel-layout"

echo "--- Installing whiskermenu, genmon and power-manager panel plugins ---"
apt-get update -qq
apt-get install -y xfce4-whiskermenu-plugin xfce4-genmon-plugin \
	xfce4-power-manager xfce4-power-manager-plugins

echo "--- Installing genmon script + icons ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/update-genmon.sh" "$TARGET_HOME/.local/bin/update-genmon.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/update-genmon-icons"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/ok-check.png" "$TARGET_HOME/.local/share/update-genmon-icons/ok-check.png"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-panel-icon.png" "$TARGET_HOME/Pictures/Cyberbeest-panel-icon.png"

echo "--- Writing genmon-11.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$LAYOUT/genmon.rc.template" > "$TARGET_HOME/.config/xfce4/panel/genmon-11.rc"

echo "--- Writing launcher-9 (terminal) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/launcher-9"
install -m 644 "$LAYOUT/terminal-emulator.desktop" \
	"$TARGET_HOME/.config/xfce4/panel/launcher-9/terminal-emulator.desktop"

echo "--- Writing launcher-10 (Cyberbeest Power Settings) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/launcher-10"
cat > "$TARGET_HOME/.config/xfce4/panel/launcher-10/cyberbeest-power.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Power Settings
Comment=Configure Cyberbeest lock/suspend/notification behavior
Exec=$TARGET_HOME/.local/bin/cyberbeest-power-settings
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF

echo "--- Writing xfce4-panel.xml ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
PANEL_XML="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
if [ -e "$PANEL_XML" ] && [ ! -e "$PANEL_XML.pre-cyberbeest" ]; then
	cp "$PANEL_XML" "$PANEL_XML.pre-cyberbeest"
fi
sed "s|__HOME__|$TARGET_HOME|g" "$LAYOUT/xfce4-panel.xml.template" > "$PANEL_XML"

echo "--- Fixing ownership ---"
chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4"

echo "--- Reloading xfce4-panel for the logged-in user, if one is running ---"
if command -v xfce4-panel >/dev/null 2>&1; then
	PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)"
	if [ -n "$PANEL_PID" ]; then
		DBUS_ADDR=""
		if [ -r "/proc/$PANEL_PID/environ" ]; then
			DBUS_ADDR="$(tr '\0' '\n' < "/proc/$PANEL_PID/environ" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
		fi
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
		# xfconfd holds the panel config in memory and can clobber the file we
		# just wrote if it's still running from before this script ran -- kill
		# it too so xfce4-panel -r starts a fresh one that reads our new file.
		pkill -u "$TARGET_USER" -x xfconfd || true
		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	fi
fi

echo "=== $(date) : done ==="
