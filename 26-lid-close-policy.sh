#!/bin/bash
# Lid close policy: lock instantly (systemd-logind HandleLidSwitch=lock,
# no suspend) and force the display off instantly with it, instead of
# suspending or waiting on the general idle-DPMS timers from
# 16-power-lock-config.sh. See lib/lid-screen-off.sh for the part that
# forces the screen off/on in step with the lock.
#
# Lid *open* is intentionally left alone: it has no logind hook at all, so
# waking the display for it needs a separate acpid-triggered hook (see
# lib/lid-open-wake.sh, kept but NOT installed by this script) -- tried and
# postponed 2026-08-03. It reliably forced DPMS back on, but
# xfce4-screensaver re-blanks the display to Standby again within a few
# seconds via its own internal timer, racing our forced "on" and mostly
# winning, so the unlock prompt didn't reliably stay visible. Needs a fix on
# the xfce4-screensaver side (or an equivalent way to suppress its own
# blank-after-lock behavior) before this is worth re-enabling. Until then,
# the display simply wakes on the next real keypress/mouse-move, as before.
# Must be run as root (edits /etc/systemd/logind.conf.d).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/26-lid-close-policy.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing lid-close policy ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (dbus-send/dbus-monitor, xset) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y dbus-bin x11-xserver-utils

echo "--- Setting HandleLidSwitch=lock in logind.conf.d ---"
install -d -m 755 /etc/systemd/logind.conf.d
cat > /etc/systemd/logind.conf.d/50-cyberbeest-lid.conf <<'EOF'
# Lid close locks the session instantly; it does not suspend. Screen-off
# is handled separately (in step with the lock) by lid-screen-off.sh.
[Login]
HandleLidSwitch=lock
EOF

echo "--- Restarting systemd-logind to pick up the new policy ---"
systemctl restart systemd-logind

echo "--- Installing lid-screen-off.sh to $TARGET_HOME/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/lid-screen-off.sh" "$TARGET_HOME/bin/lid-screen-off.sh"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/lid-screen-off.service" \
	"$TARGET_HOME/.config/systemd/user/lid-screen-off.service"

echo "--- Enabling the unit (WantedBy=default.target) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../lid-screen-off.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lid-screen-off.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/lid-screen-off.service"

echo "--- Starting it now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart lid-screen-off.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "--- Removing lid-open-wake hook, if a previous run installed it (postponed, see header) ---"
rm -f "$TARGET_HOME/bin/lid-open-wake.sh"
if [ -e /etc/acpi/events/cyberbeest-lid-open ]; then
	rm -f /etc/acpi/events/cyberbeest-lid-open
	systemctl restart acpid 2>/dev/null || true
fi

echo "=== $(date) : done ==="
