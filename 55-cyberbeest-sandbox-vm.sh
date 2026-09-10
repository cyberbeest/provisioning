#!/bin/bash
# Downloads the Cyberbeest sandbox VM (same OS as the host, for running
# untrusted apps in extra isolation) and registers it in VirtualBox --
# see lib/download-and-create-sandbox-vm.sh for the actual mechanism, and
# 53-virtualbox.sh for installing the hypervisor itself.
#
# Skipped entirely inside a VM: a VM guest has no business getting its own
# nested sandbox VM (see 90-vm-mode-overrides.sh, which is the mirror-image
# check -- that one only runs *inside* a VM, this one only outside).
#
# This is a large download (several GB) -- by far the longest-running step
# in the whole provisioning chain. run-gui.py's "stop after current
# script" should be able to interrupt it immediately rather than waiting
# for the download to finish on its own.
# Depends on: 53-virtualbox.sh.
# Idempotent: safe to re-run (download-and-create-sandbox-vm.sh detects an
# existing VM of the same name and skips cleanly rather than re-downloading
# several GB over it).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/55-cyberbeest-sandbox-vm.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest sandbox VM ==="

# shellcheck disable=SC1091
. "$DIR/lib/vm-profile-gate.sh" vbox

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
sudo -u "$TARGET_USER" bash "$DIR/lib/download-and-create-sandbox-vm.sh"

echo "=== $(date) : done ==="
