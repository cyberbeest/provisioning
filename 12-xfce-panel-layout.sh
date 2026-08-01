#!/bin/bash
# Lays out the xfce4 panel to match the dev machine: Whisker menu, the
# custom monitoring plugins (built by 11-xfce-panel-plugins.sh), a genmon
# security-status widget (fed by 07-security-update-timer.sh), a genmon
# shutdown-timer widget showing the current auto-shutdown-while-locked time
# (fed by shutdown-timer-genmon.sh; click opens a quick preset menu via
# shutdown-timer-menu.py -- which also has the Lock/Restart/Shut Down
# actions from 09-cyberbeest-logout-dialog.sh's cyberbeest-logout, so there's
# no separate standalone Power launcher pinned to the panel any more), the
# power manager plugin, a terminal launcher, and a pulseaudio volume
# plugin (its icon overridden with a padded version so it doesn't dominate
# the panel visually -- see the icons-adwaita-symbolic-status install
# below). The Cyberbeest Power Settings GUI isn't pinned to the panel
# either -- it shows up in Whisker's Settings category instead.
# Depends on: 07-security-update-timer.sh, 08-cyberbeest-power-settings.sh,
# 09-cyberbeest-logout-dialog.sh, 10-browser-sandbox.sh,
# 11-xfce-panel-plugins.sh.
# Idempotent: safe to re-run (overwrites its own config files; backs up any
# pre-existing xfce4-panel.xml the first time). Also removes any other panel
# (e.g. Debian's stock second panel) so only this one is left, since a live
# xfconfd won't drop a panel it already has in memory just because the file
# on disk changed underneath it.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/12-xfce-panel-layout.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : applying xfce4 panel layout ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
LAYOUT="$DIR/lib/xfce-panel-layout"

echo "--- Installing whiskermenu, genmon, power-manager and pulseaudio panel plugins ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xfce4-whiskermenu-plugin xfce4-genmon-plugin \
	xfce4-power-manager xfce4-power-manager-plugins xfce4-pulseaudio-plugin

echo "--- Installing genmon script + icons ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/update-genmon.sh" "$TARGET_HOME/.local/bin/update-genmon.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/shutdown-timer-genmon.sh" "$TARGET_HOME/.local/bin/shutdown-timer-genmon.sh"
# GENMON_WIDGET_NAME must match this template's plugin-16 (see
# xfce4-panel.xml.template) so the "refresh the panel icon now" call after
# picking a preset targets the right widget.
sed "s|__GENMON_WIDGET__|genmon-16|g" "$DIR/lib/shutdown-timer-menu.py" \
	> "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
chmod 755 "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see lib/i18n.py.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/update-genmon-icons"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/ok-check.png" "$TARGET_HOME/.local/share/update-genmon-icons/ok-check.png"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-panel-icon.png" "$TARGET_HOME/Pictures/Cyberbeest-panel-icon.png"

# The pulseaudio plugin's volume icon comes from Adwaita (not hicolor --
# Tango, the active GTK icon theme, inherits from Adwaita before falling
# back to hicolor), and at full size it's a solid, bold glyph that draws
# the eye far more than the rest of the panel. These are the same Adwaita
# SVGs padded into a larger canvas so the artwork renders smaller with a
# visible margin, at any requested icon size.
echo "--- Installing padded volume/mic icon overrides ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/icons/Adwaita/symbolic/status"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR"/lib/assets/icons-adwaita-symbolic-status/*.svg \
	"$TARGET_HOME/.local/share/icons/Adwaita/symbolic/status/"

echo "--- Writing genmon-11.rc, kitt-scanner-14.rc, mem-liquid-15.rc, genmon-16.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$LAYOUT/genmon.rc.template" > "$TARGET_HOME/.config/xfce4/panel/genmon-11.rc"
install -m 644 "$LAYOUT/kitt-scanner.rc" "$TARGET_HOME/.config/xfce4/panel/kitt-scanner-14.rc"
install -m 644 "$LAYOUT/mem-liquid.rc" "$TARGET_HOME/.config/xfce4/panel/mem-liquid-15.rc"
sed "s|__HOME__|$TARGET_HOME|g" "$LAYOUT/shutdown-timer-genmon.rc.template" > "$TARGET_HOME/.config/xfce4/panel/genmon-16.rc"

echo "--- Writing launcher-9 (terminal) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/launcher-9"
install -m 644 "$LAYOUT/terminal-emulator.desktop" \
	"$TARGET_HOME/.config/xfce4/panel/launcher-9/terminal-emulator.desktop"

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
		# cat (not `< file`) so a PID that vanishes between pgrep and here
		# just yields empty output instead of a fatal shell redirection error.
		DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
		DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"

		# Debian's stock xfce4-panel default (or a first login that happened
		# before this script ran) may have created a second panel (its own
		# top/bottom bar, id != 1). Overwriting the file above doesn't remove
		# it from a *live* xfconfd's in-memory state -- kill xfconfd so it
		# comes back reading only our file, before restarting the panel.
		pkill -u "$TARGET_USER" -x xfconfd || true
		sleep 1
		# grep/while both legitimately exit non-zero when there are no stray
		# panels to remove (the normal case) -- under pipefail+set -e that
		# would otherwise kill the whole script right here, so guard the
		# entire pipeline with || true.
		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels" \
			| tail -n +2 | sed '/^$/d' \
			| grep -v '^1$' | while read -r stray_id; do
			[ -n "$stray_id" ] || continue
			echo "removing stray panel-$stray_id"
			su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels/panel-$stray_id --reset -R" || true
		done || true
		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels -t int -s 1 --force-array" || true

		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
	fi
fi

echo "=== $(date) : done ==="
