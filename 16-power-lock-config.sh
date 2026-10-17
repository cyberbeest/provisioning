#!/bin/bash
# Installs this machine's power-manager and screen-lock settings: display
# sleeps after 5 minutes idle and turns off after 6 (DPMS), the screen
# locks after 5 minutes idle (on a first run only -- re-runs keep the
# user's own lock delay and matching DPMS timings), brightness reduction on inactivity is
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

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"

echo "--- Installing xfce4-power-manager and xfce4-screensaver ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y xfce4-power-manager xfce4-screensaver

# Session lookup up front: the user's current lock-delay choice is read
# from the live xfconfd (newest state) before the channel files get
# overwritten below, and the same values are pushed back live afterwards.
TARGET_UID="$(id -u "$TARGET_USER")"
HAVE_SESSION=false
if [ -d "/run/user/$TARGET_UID" ]; then
	HAVE_SESSION=true
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	as_user() { su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $*" || true; }
fi

# xml_prop FILE /nested/prop/path [VALUE]: reads a property's value from an
# xfconf channel file, or with VALUE, rewrites it in place (keeping the
# file's existing type attribute). Prints nothing if the property is missing.
xml_prop() {
	python3 - "$@" <<'EOF'
import sys, xml.etree.ElementTree as ET
path, prop = sys.argv[1], sys.argv[2]
try:
    tree = ET.parse(path)
except FileNotFoundError:
    sys.exit(0)
except Exception as e:
    print(f"WARNING: can't parse {path}: {e}", file=sys.stderr)
    sys.exit(0)
node = tree.getroot()
for name in prop.strip("/").split("/"):
    node = next((c for c in node.findall("property") if c.get("name") == name), None)
    if node is None:
        sys.exit(0)
if len(sys.argv) > 3:
    node.set("value", sys.argv[3])
    tree.write(path, encoding="UTF-8", xml_declaration=True)
else:
    print(node.get("value", ""))
EOF
}

# The lock delay (and the DPMS timings the "Lock screen after" picker keeps
# in step with it -- see shutdown-timer-menu.py's set_idle_delay_minutes())
# are the user's choice, not ours: on a re-run (Cyberbeest Update re-runs
# this script whenever it changes), keep whatever they picked instead of
# resetting to the 5-minute defaults. Only a first run applies the
# defaults. "Ran before" = the one-time .pre-cyberbeest backup or the
# marker below exists. Everything else in these channels (dimming off,
# DPMS on, no auto-suspend) is still enforced on every run.
MARKER="$TARGET_HOME/.config/cyberbeest/power-lock-config.installed"
PREVIOUSLY_RUN=false
if [ -e "$MARKER" ] || [ -e "$XML_DIR/xfce4-screensaver.xml.pre-cyberbeest" ]; then
	PREVIOUSLY_RUN=true
fi

# user_pref CHANNEL /prop DEFAULT REGEX: the user's current value if this
# isn't a first run and it's well-formed, else DEFAULT.
user_pref() {
	local channel="$1" prop="$2" default="$3" regex="$4" value=""
	if [ "$PREVIOUSLY_RUN" = true ]; then
		if [ "$HAVE_SESSION" = true ]; then
			value="$(as_user "xfconf-query -c $channel -p $prop" 2>/dev/null | tail -n1)"
		fi
		[ -n "$value" ] || value="$(xml_prop "$XML_DIR/$channel.xml" "$prop")"
	fi
	if [[ "$value" =~ $regex ]]; then echo "$value"; else echo "$default"; fi
}

PM=/xfce4-power-manager
IDLE_ENABLED="$(user_pref xfce4-screensaver /saver/idle-activation/enabled true '^(true|false)$')"
IDLE_DELAY="$(user_pref xfce4-screensaver /saver/idle-activation/delay 5 '^[0-9]+$')"
declare -A DPMS
for source in ac battery; do
	DPMS[$source-sleep]="$(user_pref xfce4-power-manager "$PM/dpms-on-$source-sleep" 5 '^[0-9]+$')"
	DPMS[$source-off]="$(user_pref xfce4-power-manager "$PM/dpms-on-$source-off" 6 '^[0-9]+$')"
done
echo "lock: enabled=$IDLE_ENABLED delay=${IDLE_DELAY}min; dpms ac=${DPMS[ac-sleep]}/${DPMS[ac-off]} battery=${DPMS[battery-sleep]}/${DPMS[battery-off]} (previously run: $PREVIOUSLY_RUN)"

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
xml_prop "$XML_DIR/xfce4-screensaver.xml" /saver/idle-activation/enabled "$IDLE_ENABLED"
xml_prop "$XML_DIR/xfce4-screensaver.xml" /saver/idle-activation/delay "$IDLE_DELAY"
for source in ac battery; do
	xml_prop "$XML_DIR/xfce4-power-manager.xml" "$PM/dpms-on-$source-sleep" "${DPMS[$source-sleep]}"
	xml_prop "$XML_DIR/xfce4-power-manager.xml" "$PM/dpms-on-$source-off" "${DPMS[$source-off]}"
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
if [ "$HAVE_SESSION" = true ]; then
	as_user "xfconf-query -c xfce4-screensaver -p /saver/idle-activation/enabled -n -t bool -s $IDLE_ENABLED"
	as_user "xfconf-query -c xfce4-screensaver -p /saver/idle-activation/delay -n -t int -s $IDLE_DELAY"
	# /lock/enabled and /lock/user-switching/enabled are also in the xml file
	# installed above, but a raw XML overwrite alone only takes effect at
	# xfce4-screensaver's next startup -- a live session's already-running
	# xfconfd never loaded these properties (they were never set via
	# xfconf-query before now) and will flush its stale in-memory model back
	# over the file, silently dropping the whole /lock section we just wrote.
	# Push them live too, same as idle-activation above.
	as_user "xfconf-query -c xfce4-screensaver -p /lock/enabled -n -t bool -s true"
	as_user "xfconf-query -c xfce4-screensaver -p /lock/user-switching/enabled -n -t bool -s false"
	for source in ac battery; do
		as_user "xfconf-query -c xfce4-power-manager -p $PM/dpms-on-$source-sleep -n -t int -s ${DPMS[$source-sleep]}"
		as_user "xfconf-query -c xfce4-power-manager -p $PM/dpms-on-$source-off -n -t int -s ${DPMS[$source-off]}"
	done
	# Brightness reduction on inactivity: 9 is xfpm's "Never" (not 0), and
	# the keys are brightness-on-*, not the brightness-inactivity-on-* ones
	# earlier revisions wrote (ignored by xfpm, so battery kept its
	# compiled-in 300s dim) -- drop those leftovers too.
	for source in ac battery; do
		as_user "xfconf-query -c xfce4-power-manager -p $PM/brightness-on-$source -n -t int -s 9"
		as_user "xfconf-query -c xfce4-power-manager -p $PM/brightness-inactivity-on-$source -r"
	done
	as_user "xfconf-query -c xfce4-power-manager -p $PM/dpms-enabled -n -t bool -s true"
else
	echo "no active session for $TARGET_USER -- values will apply at next login"
fi

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/cyberbeest"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 /dev/null "$MARKER"

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
