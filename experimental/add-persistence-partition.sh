#!/bin/bash
# Adds a persistence partition to a USB stick that already has a Cyberbeest
# live ISO (from remaster-live-stick.sh) dd'd onto it. live-boot on that ISO
# is always built with the "persistence" boot param + persistence-label=
# persistence, so it auto-detects and uses this partition on any future
# boot -- no ISO rebuild, no boot-menu edit needed.
#
# Run this AFTER dd'ing the ISO, not before -- dd overwrites the whole
# device's partition table, which would wipe a persistence partition
# created first.
#
# Usage: sudo bash add-persistence-partition.sh /dev/sdX [size_MB]
#   /dev/sdX   the stick's block device (whole disk, not a partition)
#   size_MB    optional; defaults to all remaining free space on the stick
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/add-persistence-partition.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : starting add-persistence-partition ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0 /dev/sdX [size_MB])." >&2
	exit 1
fi

DEV="${1:-}"
SIZE="${2:-}"

if [ -z "$DEV" ] || [ ! -b "$DEV" ]; then
	echo "Usage: sudo bash $0 /dev/sdX [size_MB]" >&2
	echo "Run this AFTER dd'ing the Cyberbeest live ISO onto the stick." >&2
	exit 1
fi

# Refuse anything that's obviously this machine's own boot/root disk rather
# than a removable stick -- a wrong device here is a wrong-disk partition
# edit, not a recoverable mistake.
ROOT_DEV="$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)"
if [ -n "$ROOT_DEV" ] && [ "$DEV" = "/dev/$ROOT_DEV" ]; then
	echo "Refusing to touch $DEV -- it's this machine's own root disk." >&2
	exit 1
fi
REMOVABLE="$(cat "/sys/block/$(basename "$DEV")/removable" 2>/dev/null || echo 0)"
if [ "$REMOVABLE" != "1" ]; then
	echo "$DEV is not marked removable -- refusing to touch it." >&2
	echo "(this script is meant for USB sticks, not internal disks)" >&2
	exit 1
fi

echo "--- Current partition table on $DEV ---"
parted -s "$DEV" unit MB print

if parted -sm "$DEV" unit MB print | tail -n +3 | grep -qi persistence 2>/dev/null; then
	echo "Note: continuing anyway, but check the table above --" >&2
	echo "a partition may already exist here." >&2
fi

LAST_END_MB="$(parted -sm "$DEV" unit MB print | tail -n +3 | awk -F: '{gsub("MB","",$3); print $3+0}' | sort -n | tail -1)"
if [ -z "$LAST_END_MB" ]; then
	echo "Could not determine end of last partition on $DEV -- aborting." >&2
	exit 1
fi
START=$(( ${LAST_END_MB%.*} + 1 ))

if [ -n "$SIZE" ]; then
	END="$((START + SIZE))MB"
else
	END="100%"
fi

echo "--- Creating persistence partition on $DEV: ${START}MB to $END ---"
parted -s "$DEV" -- mkpart primary ext4 "${START}MB" "$END"
partprobe "$DEV"
sleep 2

PART="$(lsblk -lnpo NAME "$DEV" | tail -1)"
if [ "$PART" = "$DEV" ]; then
	echo "New partition device not found after partprobe -- aborting." >&2
	exit 1
fi

echo "--- Formatting $PART as ext4, label 'persistence' ---"
mkfs.ext4 -F -L persistence "$PART"

MNT="$(mktemp -d)"
mount "$PART" "$MNT"
echo "/ union" >"$MNT/persistence.conf"
umount "$MNT"
rmdir "$MNT"

echo
echo "=== $(date) : done ==="
echo "Persistence partition created on $PART (label 'persistence')."
echo "Any Cyberbeest live stick built with remaster-live-stick.sh will pick"
echo "this up automatically on next boot -- changes made in the live"
echo "session will persist across reboots from here on."
