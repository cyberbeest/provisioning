#!/bin/bash
# Reverses enable-hibernation.sh: re-masks hibernate.target + sleep.target,
# removes the swapfile and all resume/GRUB config it added, and restores
# RESUME= to point at whatever swap device/LV existed before (so re-running
# enable-hibernation.sh on a freshly re-provisioned or reused test machine
# starts from a clean, debt-free state -- no leftover swapfile disk cost).
#
# Usage: sudo bash disable-hibernation.sh
# Idempotent: safe to re-run (each step checks before acting).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/disable-hibernation.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : disabling hibernation ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

SWAPFILE=/swapfile

echo "--- re-masking hibernate.target + sleep.target ---"
systemctl mask hibernate.target sleep.target
systemctl list-unit-files --state=masked | grep -iE "sleep|suspend|hibernate" || true

if swapon --show=NAME --noheadings 2>/dev/null | grep -qx "$SWAPFILE"; then
	echo "--- turning off $SWAPFILE ---"
	swapoff "$SWAPFILE"
fi
if [[ -e "$SWAPFILE" ]]; then
	echo "--- removing $SWAPFILE ---"
	rm -f "$SWAPFILE"
fi
if grep -q "^$SWAPFILE " /etc/fstab; then
	echo "--- removing fstab entry ---"
	sed -i "\#^$SWAPFILE #d" /etc/fstab
fi

echo "--- restoring RESUME= to the original swap device ---"
ORIG_SWAP=$(awk 'NR>1 && $1!="'"$SWAPFILE"'"{print $1; exit}' /proc/swaps)
if [[ -n "$ORIG_SWAP" ]]; then
	echo "RESUME=$ORIG_SWAP" > /etc/initramfs-tools/conf.d/resume
	echo "restored: RESUME=$ORIG_SWAP"
else
	echo "No other active swap device found -- leaving /etc/initramfs-tools/conf.d/resume as-is." >&2
fi

echo "--- stripping resume=/resume_offset= from /etc/default/grub ---"
# [^" ]+, not \S+: see enable-hibernation.sh for why \S+ corrupts the line
# when resume_offset= is the last token before the closing quote.
sed -i -E 's/ ?resume=[^" ]+//; s/ ?resume_offset=[^" ]+//' /etc/default/grub
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub

echo "--- removing persisted hibernate-mode tmpfiles rule ---"
rm -f /etc/tmpfiles.d/cyberbeest-hibernate-mode.conf
echo platform > /sys/power/disk 2>/dev/null || true

echo "--- cleaning up backup files left by enable-hibernation.sh ---"
rm -f "$DIR"/resume.conf.bak-* /etc/default/grub.bak-*

echo "--- update-initramfs ---"
update-initramfs -u -k all

echo "--- update-grub ---"
update-grub

echo "=== $(date) : done. Reboot to fully clear the resume config from a running kernel. ==="
