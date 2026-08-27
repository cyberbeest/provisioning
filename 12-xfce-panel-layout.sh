#!/bin/bash
# Lays out the xfce4 panel to match the dev machine, plugins grouped left
# to right: Whisker menu, tasklist -- Programs (file manager launcher; no
# terminal launcher -- the typical user isn't expected to use one, and it's
# still reachable from the Whisker menu for anyone who does) --
# Hardware (systray, pulseaudio volume plugin, its icon overridden with a
# padded version so it doesn't dominate the panel visually -- see the
# icons-adwaita-symbolic-status install below) -- Status (the custom
# monitoring plugins built by 11-xfce-panel-plugins.sh: kitt-scanner,
# mem-liquid, wattage-panel; plus a genmon security-status widget fed by
# 07-security-update-timer.sh) -- Power (the power manager plugin, and a
# genmon shutdown-timer widget showing the current auto-shutdown-while-locked
# time, fed by shutdown-timer-genmon.sh; click opens a quick preset menu via
# shutdown-timer-menu.py -- which also has the Lock/Restart/Shut Down
# actions from 09-cyberbeest-logout-dialog.sh's cyberbeest-logout, so there's
# no separate standalone Power launcher pinned to the panel any more) --
# clock, last so any dynamically-added icons (e.g. the optional i2pd toggle
# from 22-i2p-package-manager.sh) can always insert themselves right before
# it.
# Also installs Cyberbeest Extended Power Options (lib/lock-power-saving-dialog.py):
# a small Whisker-menu app (Cyberbeest category) for the window-minimize-delay
# and browser-CPU-throttle settings lock-shutdown-watcher.sh applies while
# locked. shutdown-timer-menu.py's "Power saving while locked..." item opens
# the same script as a shortcut.
# Depends on: 07-security-update-timer.sh, 09-cyberbeest-logout-dialog.sh,
# 10-browser-sandbox.sh, 11-xfce-panel-plugins.sh.
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
# The genmon icon's click action opens the last run's log via a small GTK
# dialog. Needs i18n.py (installed below) next to it, same as
# shutdown-timer-menu.py.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/update-genmon-view-log.py" "$TARGET_HOME/.local/bin/update-genmon-view-log.py"
# update-genmon.sh sources i18n.sh relative to its own location, so that (and
# its strings.*.sh catalogs) need to live next to it too -- see lib/i18n.sh.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings.*.sh "$TARGET_HOME/.local/bin/i18n/"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/shutdown-timer-genmon.sh" "$TARGET_HOME/.local/bin/shutdown-timer-genmon.sh"
# GENMON_WIDGET_NAME must match this template's plugin-16 (see
# xfce4-panel.xml.template) so the "refresh the panel icon now" call after
# picking a preset targets the right widget.
sed "s|__GENMON_WIDGET__|genmon-16|g" "$DIR/lib/shutdown-timer-menu.py" \
	> "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
chmod 755 "$TARGET_HOME/.local/bin/shutdown-timer-menu.py"
# The menu's "Power saving while locked..." item launches this as a
# separate process (see shutdown-timer-menu.py's open_power_saving_dialog).
sed "s|__GENMON_WIDGET__|genmon-16|g" "$DIR/lib/lock-power-saving-dialog.py" \
	> "$TARGET_HOME/.local/bin/lock-power-saving-dialog.py"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/lock-power-saving-dialog.py"
chmod 755 "$TARGET_HOME/.local/bin/lock-power-saving-dialog.py"
# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see lib/i18n.py.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/update-genmon-icons"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/ok-check.png" "$TARGET_HOME/.local/share/update-genmon-icons/ok-check.png"
# Not Pictures/Bilder: that's user-visible and locale-renamed (English
# "Pictures" vs. German "Bilder"), so a hardcoded/stale reference to it can
# silently break this app-UI icon (the whisker menu button itself did,
# exactly this way, before this comment existed). .local/share/cyberbeest/
# icons is a fixed, non-user-facing location no XDG-dirs translation or user
# reorganization touches.
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-panel-icon.png" "$ICONS_DIR/Cyberbeest-panel-icon.png"
# Also installed by 21-/48- -- duplicated here (idempotent, same file) since
# this script doesn't depend on those running first.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" "$ICONS_DIR/Cyberbeest-black.png"

echo "--- Installing app menu entry for Cyberbeest Extended Power Options (Whisker menu, Cyberbeest category) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-extended-power-options.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Extended Power Options
Name[de]=Cyberbeest Erweiterte Energieoptionen
Comment=Window minimizing and browser CPU throttling while the screen is locked
Comment[de]=Fenster minimieren und Browser-CPU begrenzen bei gesperrtem Bildschirm
Exec=$TARGET_HOME/.local/bin/lock-power-saving-dialog.py
Icon=$ICONS_DIR/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-extended-power-options.desktop"

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

# Cleanup for machines provisioned before the terminal launcher was dropped
# from the panel -- overwriting xfce4-panel.xml below removes plugin-9 from
# the layout, but doesn't touch this now-orphaned launcher config dir.
rm -rf "$TARGET_HOME/.config/xfce4/panel/launcher-9"

echo "--- Writing launcher-18 (file manager) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/launcher-18"
install -m 644 "$LAYOUT/file-manager.desktop" \
	"$TARGET_HOME/.config/xfce4/panel/launcher-18/file-manager.desktop"

echo "--- Writing xfce4-panel.xml ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
PANEL_XML="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
if [ -e "$PANEL_XML" ] && [ ! -e "$PANEL_XML.pre-cyberbeest" ]; then
	cp "$PANEL_XML" "$PANEL_XML.pre-cyberbeest"
fi
sed -e "s|__HOME__|$TARGET_HOME|g" -e "s|__ICONS_DIR__|$ICONS_DIR|g" \
	"$LAYOUT/xfce4-panel.xml.template" > "$PANEL_XML"

echo "--- Fixing ownership ---"
chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4"

echo "--- Reloading xfce4-panel for the logged-in user, if one is running ---"
. "$DIR/lib/xfce-panel-reload.sh"
if xfce_panel_dbus_addr; then
	# Debian's stock xfce4-panel default (or a first login that happened
	# before this script ran) may have created a second panel (its own
	# top/bottom bar, id != 1). Overwriting the file above doesn't remove
	# it from a *live* xfconfd's in-memory state -- kill xfconfd so it
	# comes back reading only our file, before restarting the panel.
	xfce_panel_kill

	# grep/while both legitimately exit non-zero when there are no stray
	# panels to remove (the normal case) -- under pipefail+set -e that
	# would otherwise kill the whole script right here, so guard the
	# entire pipeline with || true.
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels" \
		| tail -n +2 | sed '/^$/d' \
		| grep -v '^1$' | while read -r stray_id; do
		[ -n "$stray_id" ] || continue
		echo "removing stray panel-$stray_id"
		su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels/panel-$stray_id --reset -R" || true
	done || true
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$XFCE_PANEL_DBUS_ADDR' xfconf-query -c xfce4-panel -p /panels -t int -s 1 --force-array" || true

	xfce_panel_launch
fi

echo "=== $(date) : done ==="
