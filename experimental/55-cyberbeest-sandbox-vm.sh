#!/bin/bash
# Downloads the Cyberbeest VM (same OS as the host, for running untrusted
# apps in extra isolation) and registers it in VirtualBox -- see
# download-and-create-sandbox-vm.sh (same directory) for the actual
# mechanism, and 53-virtualbox.sh for installing the hypervisor itself.
#
# Moved to experimental/ 2026-09-11: no longer part of the default
# provisioning chain (run-gui.py doesn't call this). VirtualBox itself
# still installs by default via 53-virtualbox.sh -- only the automatic
# disk-image build was dropped, since 56-cyberbeest-sandbox-vm-kvm.sh
# covers that need and shipping two multi-GB VM images was wasteful. Run
# this manually if you want a VBox VM instead of/alongside the KVM one.
#
# This is a large download (several GB) -- by far the longest-running step
# in the whole provisioning chain, back when it was part of it.
# Depends on: 53-virtualbox.sh.
# Idempotent: safe to re-run (download-and-create-sandbox-vm.sh detects an
# existing VM of the same name and skips cleanly rather than re-downloading
# several GB over it).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/55-cyberbeest-sandbox-vm.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest VM (VirtualBox) ==="

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
sudo -u "$TARGET_USER" bash "$DIR/download-and-create-sandbox-vm.sh"

echo "=== $(date) : done ==="
