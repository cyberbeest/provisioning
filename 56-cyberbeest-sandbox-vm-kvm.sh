#!/bin/bash
# Downloads the Cyberbeest sandbox VM (same OS as the host, for running
# untrusted apps in extra isolation) and registers it under QEMU/KVM +
# GNOME Boxes -- see lib/download-and-create-sandbox-vm-kvm.sh for the
# actual mechanism, and 53a-qemu-kvm-boxes.sh for installing the hypervisor
# itself. The VirtualBox equivalent is 55-cyberbeest-sandbox-vm.sh.
#
# Skipped entirely inside a VM: a VM guest has no business getting its own
# nested sandbox VM (see 90-vm-mode-overrides.sh, which is the mirror-image
# check -- that one only runs *inside* a VM, this one only outside).
#
# This is a large download (several GB) -- by far the longest-running step
# in the whole provisioning chain. run-gui.py's "stop after current
# script" should be able to interrupt it immediately rather than waiting
# for the download to finish on its own.
# Depends on: 53a-qemu-kvm-boxes.sh.
# Idempotent: safe to re-run (download-and-create-sandbox-vm-kvm.sh detects
# an existing VM of the same name and skips cleanly rather than
# re-downloading several GB over it).
#
# Bumped 2026-09-10: lib/download-and-create-sandbox-vm-kvm.sh's default VM
# name ("Cyberbeest Sandbox") has a space, which virt-install rejects
# outright ("Guest name '...' can not contain ' ' character") -- the
# libvirt-facing name is now sanitized separately from the display name.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/56-cyberbeest-sandbox-vm-kvm.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest sandbox VM (KVM) ==="

# shellcheck disable=SC1091
. "$DIR/lib/vm-profile-gate.sh" kvm

VIRT="$(systemd-detect-virt || true)"
if [ "$VIRT" != "none" ]; then
	echo "running inside a VM (systemd-detect-virt: $VIRT) -- skipping, no nested sandbox VM"
	echo "=== $(date) : done (skipped) ==="
	exit 0
fi

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- Installing libguestfs-tools (offline locale-sync) and pv (download progress) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y libguestfs-tools pv

echo "--- Downloading and creating the sandbox VM as $TARGET_USER ---"
sudo -u "$TARGET_USER" bash "$DIR/lib/download-and-create-sandbox-vm-kvm.sh"

echo "=== $(date) : done ==="
