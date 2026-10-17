#!/bin/bash
# Reverses enable-grub-theme.sh: removes the theme and the blank-screen hook,
# restores the /etc/default/grub values it changed (from the backup taken on
# the first run) and re-enables the UEFI Firmware Settings entry. The moved
# 10_linux backup is NOT put back into /etc/grub.d (it caused duplicate
# entries).
#
# Usage: sudo bash disable-grub-theme.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/disable-grub-theme.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : removing GRUB theme ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

GRUB_FILE=/etc/default/grub
BACKUP_DIR=/var/backups/cyberbeest
GRUB_BACKUP="$BACKUP_DIR/default-grub.pre-grub-theme"

if [ -e "$GRUB_BACKUP" ]; then
	echo "--- restoring changed values in $GRUB_FILE ---"
	for key in GRUB_THEME GRUB_DISTRIBUTOR GRUB_DISABLE_RECOVERY GRUB_TIMEOUT_STYLE GRUB_TIMEOUT GRUB_GFXPAYLOAD_LINUX; do
		sed -i "/^${key}=/d" "$GRUB_FILE"
		grep -E "^${key}=" "$GRUB_BACKUP" >> "$GRUB_FILE" || true
	done
else
	echo "No backup at $GRUB_BACKUP -- leaving $GRUB_FILE untouched." >&2
fi

echo "--- removing theme and hook ---"
rm -rf /boot/grub/themes/cyberbeest
rm -f /etc/grub.d/45_cyberbeest_blank

if [ -e "$BACKUP_DIR/uefi-entry-hidden" ]; then
	echo "--- re-enabling the UEFI Firmware Settings entry ---"
	chmod +x /etc/grub.d/30_uefi-firmware
	rm -f "$BACKUP_DIR/uefi-entry-hidden"
fi

update-grub
rm -f "$GRUB_BACKUP"
echo "=== done ==="
