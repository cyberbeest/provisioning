#!/bin/bash
# Installs VirtualBox Guest Additions inside a VM running the Cyberbeest
# live/installed system, for smoother dev testing (resolution auto-resize,
# shared clipboard, shared folders). Host-only helper -- not part of
# provisioning, never runs on real hardware.
#
# Expects the Guest Additions CD to already be attached from the host side
# (VirtualBox menu: Devices > Insert Guest Additions CD image...). This
# script finds it, mounts it if needed, and runs the installer from it.
#
# Usage: sudo bash install-vbox-guest-additions.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/install-vbox-guest-additions.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing VirtualBox Guest Additions ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

MOUNT_POINT="/mnt/vbox-guest-additions"
MOUNTED_HERE=0

find_mounted_cd() {
	# Already auto-mounted by the desktop (udisks2), e.g. /media/<user>/VBoxAdditions_x.y.z
	findmnt -rn -o TARGET -S /dev/sr0 2>/dev/null && return 0
	find /media -maxdepth 2 -iname 'VBoxAdditions*' -type d 2>/dev/null | head -1
}

CD_PATH="$(find_mounted_cd || true)"

if [ -z "$CD_PATH" ]; then
	if [ ! -b /dev/sr0 ]; then
		echo "No CD-ROM device (/dev/sr0) found -- attach the Guest Additions CD" >&2
		echo "from the host first (Devices > Insert Guest Additions CD image...)." >&2
		exit 1
	fi
	echo "Guest Additions CD not auto-mounted, mounting manually..."
	mkdir -p "$MOUNT_POINT"
	mount -o ro /dev/sr0 "$MOUNT_POINT"
	MOUNTED_HERE=1
	CD_PATH="$MOUNT_POINT"
fi

echo "Using Guest Additions CD at: $CD_PATH"

INSTALLER="$CD_PATH/VBoxLinuxAdditions.run"
if [ ! -f "$INSTALLER" ]; then
	echo "$INSTALLER not found -- is the right CD image attached?" >&2
	[ "$MOUNTED_HERE" -eq 1 ] && umount "$MOUNT_POINT"
	exit 1
fi

echo "Installing build dependencies (dkms, headers, build-essential)..."
apt-get update
apt-get install -y --no-install-recommends build-essential dkms "linux-headers-$(uname -r)"

echo "Running $INSTALLER..."
# The installer exits non-zero on things like "no updates needed" even on
# success, so don't let set -e kill the script over its exit code.
sh "$INSTALLER" --nox11 || true

if [ "$MOUNTED_HERE" -eq 1 ]; then
	umount "$MOUNT_POINT"
	rmdir "$MOUNT_POINT"
fi

REAL_USER="${SUDO_USER:-cyberbeest}"
usermod -aG vboxsf "$REAL_USER" || true

echo
echo "=== $(date) : done ==="
echo "Reboot the VM (or at least log out/in) for the new kernel modules and"
echo "the vboxsf group membership to take effect."
