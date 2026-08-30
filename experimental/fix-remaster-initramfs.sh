#!/bin/bash
# One-shot follow-up for remaster-live-stick.sh: regenerates the initramfs
# in an already-populated chroot and redoes just the final assembly stages.
#
# Why this is needed: live-build's binary_linux-image stage only cp's
# whatever chroot/boot/initrd.img-* already exists (see
# /usr/lib/live/build/binary_linux-image) -- it never rebuilds it. Left
# alone, that's still the donor machine's real initramfs, built back when
# /etc/crypttab pointed at its actual LUKS UUID -- the cryptsetup hook bakes
# that UUID into the image at generation time, so remaster-live-stick.sh
# clearing the crypttab *text file* did nothing to an initramfs that was
# already compiled before that edit. Symptom (found 2026-08-30, booting the
# first remastered image in VirtualBox): the live system hangs at an
# early-boot LUKS unlock prompt for a device that doesn't exist.
#
# Run this ON the same machine remaster-live-stick.sh already ran on --
# it reuses that run's chroot in place rather than rebuilding from scratch,
# so it skips the slow parts (rsync copy, squashfs compression).
#
# Usage: sudo bash fix-remaster-initramfs.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/fix-remaster-initramfs.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : regenerating initramfs and re-finishing the live-stick build ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

WORK="/root/live-stick-remaster"
CHROOT="$WORK/chroot"

if [ ! -d "$CHROOT" ]; then
	echo "$CHROOT not found -- run remaster-live-stick.sh first." >&2
	exit 1
fi

echo "--- Regenerating initramfs (crypttab already cleared, live-boot already installed) ---"
mount --bind /dev "$CHROOT/dev"
mount --bind /proc "$CHROOT/proc"
mount --bind /sys "$CHROOT/sys"
chroot "$CHROOT" update-initramfs -u -k all
umount "$CHROOT/dev" "$CHROOT/proc" "$CHROOT/sys"

echo "--- Clearing the stale binary_linux-image stage marker ---"
# Forces lb build to re-copy the (now fixed) initrd; binary_rootfs (the slow
# squashfs step) stays marked done since nothing there changed.
rm -f "$WORK/.build/binary_linux-image"

echo "--- Resuming lb build ---"
cd "$WORK"
lb build

OUT_ISO="$DIR/cyberbeest-live-remastered-amd64.iso"
ISO_FILE="$(find "$WORK" -maxdepth 1 -name '*.iso' | head -1)"
if [ -z "$ISO_FILE" ]; then
	echo "Build finished but no .iso found -- check the log above." >&2
	exit 1
fi
mv "$ISO_FILE" "$OUT_ISO"
chown "${SUDO_USER:-cyberbeest}:${SUDO_USER:-cyberbeest}" "$OUT_ISO"

echo
echo "=== $(date) : done ==="
echo "Image: $OUT_ISO"
ls -lh "$OUT_ISO"
