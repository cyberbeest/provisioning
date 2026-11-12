#!/bin/bash
# Installs the lock-screen curtain: an opaque gray window with a padlock that
# is painted BEFORE the screen locks, so the last desktop frame can never
# flash in front of a bystander while the lock dialog comes up or while the
# screen wakes for unlocking. Every lock path goes through
# ~/bin/cyberbeest-lock (curtain first, then xfce4-screensaver --lock):
# xflock4 reaches it through xfce4-session's LockCommand, the idle lock is
# triggered by lock-warning-watcher.sh. Toggle is CURTAIN_ENABLED in
# ~/.config/cyberbeest/power-settings.conf (default true), surfaced as a
# checkbox in the Cyberbeest Settings power tab.
# See lib/lock-screen-curtain.py and lib/cyberbeest-lock.
# Idempotent: safe to re-run.
#
# Rewritten 2026-11-12: the earlier xterm-based curtain (a hidden window
# created once and mapped on the lock signal) kept resurfacing on its own and
# only ever covered the screen after the lock had started.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/54-lock-screen-curtain.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing lock-screen-curtain ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (GTK bindings, gdbus) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 libglib2.0-bin

echo "--- Installing curtain daemon and lock command to $TARGET_HOME/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/lock-screen-curtain.py" "$TARGET_HOME/bin/lock-screen-curtain.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-lock" "$TARGET_HOME/bin/cyberbeest-lock"
# Superseded xterm-based implementation.
rm -f "$TARGET_HOME/bin/lock-screen-curtain.sh"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/lock-screen-curtain.service" \
	"$TARGET_HOME/.config/systemd/user/lock-screen-curtain.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../lock-screen-curtain.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-screen-curtain.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lock-screen-curtain.service"

# xflock4 (keybinding, menus, logout dialog, lid close) runs the command in
# xfce4-session's /general/LockCommand before any screensaver of its own.
LOCK_COMMAND="$TARGET_HOME/bin/cyberbeest-lock"
echo "--- Pointing xfce4-session's LockCommand at $LOCK_COMMAND ---"
SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1 || true)"
if [ -n "$SESSION_PID" ]; then
	# Live session: go through the running xfconfd (writing the channel file
	# under it would be clobbered by its in-memory state).
	DBUS_ADDR="$(tr '\0' '\n' < "/proc/$SESSION_PID/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' || true)"
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfconf-query -c xfce4-session -p /general/LockCommand -n -t string -s '$LOCK_COMMAND'" || true
else
	# No session, so no xfconfd running: edit the channel file directly.
	XML_DIR="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$XML_DIR"
	python3 - "$XML_DIR/xfce4-session.xml" "$LOCK_COMMAND" <<'PYEOF'
import os
import sys
import xml.etree.ElementTree as ET

path, command = sys.argv[1], sys.argv[2]
if os.path.exists(path):
    tree = ET.parse(path)
    root = tree.getroot()
else:
    root = ET.Element("channel", name="xfce4-session", version="1.0")
    tree = ET.ElementTree(root)
general = next((p for p in root.findall("property") if p.get("name") == "general"), None)
if general is None:
    general = ET.SubElement(root, "property", name="general", type="empty")
lock = next((p for p in general.findall("property") if p.get("name") == "LockCommand"), None)
if lock is None:
    lock = ET.SubElement(general, "property", name="LockCommand")
lock.set("type", "string")
lock.set("value", command)
ET.indent(tree)
tree.write(path, encoding="UTF-8", xml_declaration=True)
PYEOF
	chown "$TARGET_USER:$TARGET_USER" "$XML_DIR/xfce4-session.xml"
fi

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart lock-screen-curtain.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
