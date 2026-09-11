#!/bin/bash
# Downloads the Cyberbeest VM (same OS as the host, for running
# untrusted apps in extra isolation) and registers it under QEMU/KVM +
# GNOME Boxes -- see lib/download-and-create-sandbox-vm-kvm.sh for the
# actual mechanism, and 53a-qemu-kvm-boxes.sh for installing the hypervisor
# itself. This is the only VM image provisioning auto-builds -- the
# VirtualBox equivalent (experimental/55-cyberbeest-sandbox-vm.sh) moved
# out of the default chain 2026-09-11, run manually if wanted.
#
# Gated on the provisioning profile's "download the VM image" choice (see
# lib/vm-profile-gate.sh) -- everything else about VM support
# (53-virtualbox.sh, 53a-qemu-kvm-boxes.sh, 57-hypervisor-switcher.sh)
# installs unconditionally regardless of this choice.
#
# Skipped entirely inside a VM: a VM guest has no business getting its own
# nested VM (see 90-vm-mode-overrides.sh, which is the mirror-image
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
# name ("Cyberbeest VM") has a space, which virt-install rejects
# outright ("Guest name '...' can not contain ' ' character") -- the
# libvirt-facing name is now sanitized separately from the display name.
#
# Bumped 2026-09-11: lib/download-and-create-sandbox-vm-kvm.sh's download
# now resumes an interrupted transfer (via curl -C -) instead of starting
# over -- caught after a host reboot mid-download left a 243MB .part file
# behind. Guards against resuming into a stale file if the donor image is
# updated on the server mid-download, by comparing the remote ETag against
# one recorded next to the .part.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/56-cyberbeest-sandbox-vm-kvm.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest VM (KVM) ==="

# shellcheck disable=SC1091
. "$DIR/lib/vm-profile-gate.sh"

VIRT="$(systemd-detect-virt || true)"
if [ "$VIRT" != "none" ]; then
	echo "running inside a VM (systemd-detect-virt: $VIRT) -- skipping, no nested VM"
	echo "=== $(date) : done (skipped) ==="
	exit 0
fi

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- Installing libguestfs-tools (offline locale-sync) and pv (download progress) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y libguestfs-tools pv

echo "--- Downloading and creating the VM as $TARGET_USER ---"
sudo -u "$TARGET_USER" bash "$DIR/lib/download-and-create-sandbox-vm-kvm.sh"

echo "=== $(date) : done ==="
