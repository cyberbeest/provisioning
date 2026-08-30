#!/bin/bash
# Follow-up to fix-remaster-initramfs.sh: that script cleared the
# binary_linux-image stage marker (to re-copy the regenerated initrd into
# the build tree) but left the binary_iso marker alone, so `lb build`
# skipped rebuilding the actual .iso file -- "W: Skipping binary_iso,
# already done" -- even though the underlying binary/ tree had changed.
# The previous .iso had already been moved out by hand (see
# remaster-live-stick.sh's own final mv, or a manual copy), so nothing was
# left in the build dir for the "no .iso found" check to pick up either.
#
# This just clears that one marker and reruns `lb build` -- squashfs and
# the linux-image copy are both already done, so this should be quick (just
# re-runs xorriso to assemble the ISO from the already-updated tree).
#
# Usage: sudo bash fix-remaster-iso-assembly.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/fix-remaster-iso-assembly.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : re-assembling the ISO ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

WORK="/root/live-stick-remaster"

if [ ! -d "$WORK" ]; then
	echo "$WORK not found -- run remaster-live-stick.sh first." >&2
	exit 1
fi

rm -f "$WORK/.build/binary_iso"

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
