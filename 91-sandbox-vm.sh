#!/bin/bash
# Keeps a Cyberbeest *sandbox* VM's own settings current: the VM a Cyberbeest
# laptop runs untrusted apps in (see 56-cyberbeest-sandbox-vm-kvm.sh on the
# host) runs this same provisioning inside, and this is the one script that
# knows it's in one. Recognized by /etc/cyberbeest-sandbox-vm, which the host
# writes when it sets the VM up; everywhere else -- laptops, the standalone VM
# product -- this does nothing.
#
# Installs lib/sandbox-vm-session.sh (auto-lock/blanking off, no KITT
# scanner, "VM" watermark background -- see that script) with its autostart
# entry and background tile, and runs lib/sandbox-vm-system.sh (services a
# sandbox doesn't need, lean initramfs -- see that one). The host already
# does the same for a fresh VM; this is how later fixes reach existing VMs,
# through the guest's normal update.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/91-sandbox-vm.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : sandbox VM settings ==="

# /etc/cyberbeest/sandbox-vm: where the marker lived for a day (2026-09-24)
# before moving out of the root-only /etc/cyberbeest -- see
# lib/sandbox-vm-system.sh, which moves it.
if [ ! -e /etc/cyberbeest-sandbox-vm ] && [ ! -e /etc/cyberbeest/sandbox-vm ]; then
	echo "not a sandbox VM (no /etc/cyberbeest-sandbox-vm) -- nothing to do"
	echo "=== $(date) : done (skipped) ==="
	exit 0
fi

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing the session script, autostart entry and background tile ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" \
	"$TARGET_HOME/.local/bin" "$TARGET_HOME/.config/autostart" "$TARGET_HOME/.local/share/cyberbeest"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/sandbox-vm-session.sh" "$TARGET_HOME/.local/bin/sandbox-vm-session.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/vm-background-tile.png" "$TARGET_HOME/.local/share/cyberbeest/vm-background-tile.png"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-sandbox-vm-session.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-sandbox-vm-session.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-sandbox-vm-session.desktop"

# Root-level half: skipped services, exim4's log dir, lean initramfs.
bash "$DIR/lib/sandbox-vm-system.sh" "$TARGET_USER"

echo "--- Applying it now, if the target user has an active session ---"
TARGET_UID="$(id -u "$TARGET_USER")"
SESSION_PID="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)" || true
if [ -n "$SESSION_PID" ]; then
	DBUS_ADDR="$(tr '\0' '\n' <"/proc/$SESSION_PID/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$TARGET_UID/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' $TARGET_HOME/.local/bin/sandbox-vm-session.sh" || true
else
	echo "no active session for $TARGET_USER -- it'll run at next login"
fi

echo "=== $(date) : done ==="
