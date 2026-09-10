#!/bin/bash
# Sets xfwm4's workspace count to 1 -- normal (non-power) users essentially
# never use multiple Unix workspaces, and XFCE's own default (4) just adds
# unexplained keyboard shortcuts and an unused workspace switcher for
# someone who never asked for either.
#
# Surgically sets just this one property rather than installing a whole
# xfwm4.xml the way 16-power-lock-config.sh does for xfce4-power-manager/
# xfce4-screensaver: those channels are comprehensively defined by that
# script (a full overwrite is the intent), but xfwm4.xml may already carry
# real customizations (window snapping, button layout, theme) that have
# nothing to do with workspaces -- a blind overwrite would silently nuke
# those. python3's xml.etree edits the property in place (or creates the
# file fresh, minimal, if none exists yet) and leaves everything else
# untouched.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/28-single-workspace.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting workspace count to 1 ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
XFWM4_XML="$XML_DIR/xfwm4.xml"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"

python3 - "$XFWM4_XML" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]

try:
	tree = ET.parse(path)
	root = tree.getroot()
except (FileNotFoundError, ET.ParseError):
	root = ET.Element("channel", name="xfwm4", version="1.0")
	tree = ET.ElementTree(root)

general = root.find("./property[@name='general']")
if general is None:
	general = ET.SubElement(root, "property", name="general", type="empty")

workspace_count = general.find("./property[@name='workspace_count']")
if workspace_count is None:
	workspace_count = ET.SubElement(general, "property", name="workspace_count")
workspace_count.set("type", "int")
workspace_count.set("value", "1")

tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
chown "$TARGET_USER:$TARGET_USER" "$XFWM4_XML"

echo "--- Pushing the value live, if the target user has an active session ---"
TARGET_UID="$(id -u "$TARGET_USER")"
if [ -d "/run/user/$TARGET_UID" ]; then
	SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfwm4 | head -1)"
	DBUS_ADDR=""
	if [ -n "$SESSION_PID" ]; then
		DBUS_ADDR="$(cat "/proc/$SESSION_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	fi
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfconf-query -c xfwm4 -p /general/workspace_count -n -t int -s 1" || true
else
	echo "no active session for $TARGET_USER -- value will apply at next login"
fi

echo "=== $(date) : done ==="
