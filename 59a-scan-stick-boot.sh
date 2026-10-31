#!/bin/bash
# "Scan from the boot stick": when the Cyberbeest stick is plugged in, a
# popup offers to restart and scan this computer from the stick (the stick
# opens the internal disk read-only and scans it from outside; see
# lib/cyberbeest-stick-scan.sh and cyberbeest-tools/combine-live-and-installer.sh).
#
# Installs:
#  - the user service lib/cyberbeest-scan-stick-watch.sh (the popup);
#  - the root helper + polkit policy (verifies the stick, arms the one-time
#    boot, reboots);
#  - a GRUB entry (/etc/grub.d/42_cyberbeest_scan_stick) that loads the scan
#    menu off the stick. GRUB_DEFAULT becomes "saved" because grub-reboot only
#    works with it; with no saved entry that still boots entry 0, exactly as
#    before.
#  - /etc/cyberbeest/scan-allowed-signers (the public key stick manifests are
#    signed with), if lib/cyberbeest-scan-allowed-signers exists in this
#    checkout. Without it the helper warns and boots unauthenticated sticks.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/59a-scan-stick-boot.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the boot-stick scan offer ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

echo "--- Installing dependencies (zenity, openssh-client, pkexec) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y zenity openssh-client polkitd pkexec

echo "--- Installing root helper + polkit policy ---"
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/lib/cyberbeest-scan-stick-helper.sh" /usr/local/lib/cyberbeest/cyberbeest-scan-stick-helper.sh
install -m 644 "$DIR/lib/com.cyberbeest.scan-stick.policy" /usr/share/polkit-1/actions/com.cyberbeest.scan-stick.policy

if [ -f "$DIR/lib/cyberbeest-scan-allowed-signers" ]; then
	echo "--- Installing the trusted stick-signing key ---"
	install -d /etc/cyberbeest
	install -m 644 "$DIR/lib/cyberbeest-scan-allowed-signers" /etc/cyberbeest/scan-allowed-signers
else
	echo "NOTE: lib/cyberbeest-scan-allowed-signers not present -- sticks will NOT be authenticated yet."
fi

echo "--- GRUB: one-time boot entry for the stick ---"
install -m 755 "$DIR/lib/cyberbeest-scan-stick-grub" /etc/grub.d/42_cyberbeest_scan_stick
if grep -q '^GRUB_DEFAULT=' /etc/default/grub; then
	sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' /etc/default/grub
else
	echo 'GRUB_DEFAULT=saved' >> /etc/default/grub
fi
update-grub
grep -q cyberbeest-scan-stick /boot/grub/grub.cfg || { echo "GRUB entry missing after update-grub" >&2; exit 1; }

echo "--- Installing the popup watcher for $TARGET_USER ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin" "$TARGET_HOME/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-scan-stick-watch.sh" "$TARGET_HOME/bin/cyberbeest-scan-stick-watch.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/bin/i18n.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" "$TARGET_HOME/bin/i18n/"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/cyberbeest-scan-stick-watch.service" \
	"$TARGET_HOME/.config/systemd/user/cyberbeest-scan-stick-watch.service"
ln -sf ../cyberbeest-scan-stick-watch.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/cyberbeest-scan-stick-watch.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/cyberbeest-scan-stick-watch.service"

if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart cyberbeest-scan-stick-watch.service || true
else
	echo "no active session for $TARGET_USER -- the watcher starts at next login"
fi

echo "=== $(date) : done ==="
