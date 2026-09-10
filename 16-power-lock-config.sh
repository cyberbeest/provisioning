#!/bin/bash
# Installs this machine's power-manager and screen-lock settings: display
# sleeps after 5 minutes idle and turns off after 6 (DPMS), the screen
# locks after 5 minutes idle, brightness reduction on inactivity is
# disabled outright (found enabled by default on a fresh install,
# dimming the screen ahead of the actual lock), and there's no separate
# system auto-suspend (that's handled by lock-shutdown-watcher.sh instead)
# -- see lib/xfce-perchannel-xml/xfce4-power-manager.xml and
# xfce4-screensaver.xml.
# Also disables light-locker's autostart: it's pulled in as an xfce4-session
# recommend, and having it running alongside xfce4-screensaver makes both
# fight over the lock/unlock X grab -- intermittently leaving the unlock
# dialog's password field unable to take keyboard focus.
# Idempotent: safe to re-run (backs up any pre-existing config the first
# time, as *.pre-cyberbeest). Also pushes the values live via xfconf-query
# for an already-active session, since the xml install alone only affects
# what these daemons read at their next startup.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/16-power-lock-config.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing power/screen-lock config ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"

echo "--- Installing xfce4-power-manager and xfce4-screensaver ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xfce4-power-manager xfce4-screensaver

echo "--- Installing xfconf channel files ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"
for channel in xfce4-power-manager xfce4-screensaver; do
	dest="$XML_DIR/$channel.xml"
	if [ -e "$dest" ] && [ ! -e "$dest.pre-cyberbeest" ]; then
		cp "$dest" "$dest.pre-cyberbeest"
	fi
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
		"$DIR/lib/xfce-perchannel-xml/$channel.xml" "$dest"
done

echo "--- Pushing the values live, if the target user has an active session ---"
# The xml install above only affects what xfce4-power-manager and
# xfce4-screensaver read at their *next* startup -- a live session's
# already-running daemons keep whatever DPMS/lock-delay values they loaded
# with (often xfce4-power-manager's own compiled-in 10min-sleep/15min-off
# defaults, if it first started before this xml existed) until logout or
# reboot. xfconf-query writes go out over D-Bus and both daemons apply
# property-changed signals live, so push the same values that way too --
# same mechanism the "Lock screen after" panel picker uses, confirmed on a
# real machine (beestified tower) to actually take effect immediately where
# a raw xml overwrite did not.
TARGET_UID="$(id -u "$TARGET_USER")"
if [ -d "/run/user/$TARGET_UID" ]; then
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	as_user() { su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $*" || true; }

	as_user "xfconf-query -c xfce4-screensaver -p /saver/idle-activation/enabled -n -t bool -s true"
	as_user "xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay -n -t int -s 5"
	for source in ac battery; do
		as_user "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-on-$source-sleep -n -t int -s 5"
		as_user "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-on-$source-off -n -t int -s 6"
	done
	as_user "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/brightness-inactivity-on-ac -n -t int -s 0"
	as_user "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/brightness-inactivity-on-battery -n -t int -s 0"
	as_user "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-enabled -n -t bool -s true"
else
	echo "no active session for $TARGET_USER -- values will apply at next login"
fi

echo "--- Disabling light-locker autostart (xfce4-screensaver is the locker) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
cat > "$TARGET_HOME/.config/autostart/light-locker.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Screen Locker
Exec=light-locker
NoDisplay=true
Hidden=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/light-locker.desktop"
pkill -u "$TARGET_USER" -x light-locker || true

echo "=== $(date) : done ==="
