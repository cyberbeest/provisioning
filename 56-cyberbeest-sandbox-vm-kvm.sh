#!/bin/bash
# Downloads the Cyberbeest sandbox VM (same OS as the host, for running
# untrusted apps in extra isolation) and registers it under QEMU/KVM +
# GNOME Boxes -- see lib/download-and-create-sandbox-vm-kvm.sh for the
# actual mechanism, and 53a-qemu-kvm-boxes.sh for installing the hypervisor
# itself. KVM is the only hypervisor provisioning ships -- VirtualBox was
# dropped entirely 2026-09-19, see 53a-qemu-kvm-boxes.sh.
#
# Skipped entirely inside a VM: a VM guest has no business getting its own
# nested sandbox VM (see 90-vm-mode-overrides.sh, which is the mirror-image
# check -- that one only runs *inside* a VM, this one only outside).
#
# Override: PROVISIONING_FORCE_VM_IMAGE_IN_VM=1 bypasses the
# systemd-detect-virt skip above. Added 2026-09-19 for the release-build
# pipeline (usb-stick-maker/release-build/), which necessarily runs the
# whole provisioning sequence inside a KVM guest even when the resulting
# content (a live-stick, or the standalone cyberbeest-vm.qcow2 image) is
# destined for bare-metal-style use where the download should normally
# happen. Unset/anything else -> identical behavior to before this change,
# so real end-user machines (which never set this) are unaffected.
#
# This is a large download (several GB) -- by far the longest-running step
# in the whole provisioning chain. run-gui.py's "stop after current
# script" should be able to interrupt it immediately rather than waiting
# for the download to finish on its own.
# Depends on: 53a-qemu-kvm-boxes.sh.
# The lib script installs these helpers; naming them here makes run-gui.py
# mark this script pending when one changes: lib/cyberbeest-vm-start.sh,
# lib/cyberbeest-vm-watcher.sh, lib/cyberbeest-vm-title-fix.sh.
# Idempotent: safe to re-run (download-and-create-sandbox-vm-kvm.sh skips a
# VM that's already on the pinned image).
#
# Goes pending again whenever a new image is pinned in the lib script. An
# existing VM is then only updated if the provisioning profile's "Update
# the VM" box is ticked (PROVISIONING_VM_UPDATE, read in via
# vm-profile-gate.sh; off by default), and the old VM is always kept as a
# backup -- see the lib script's header.
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
if [ "$VIRT" != "none" ] && [ "${PROVISIONING_FORCE_VM_IMAGE_IN_VM:-}" != "1" ]; then
	echo "running inside a VM (systemd-detect-virt: $VIRT) -- skipping, no nested sandbox VM"
	echo "=== $(date) : done (skipped) ==="
	exit 0
fi

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- Installing libguestfs-tools (offline locale-sync) and pv (download progress) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y libguestfs-tools pv

UPDATE_ARGS=()
[ "${PROVISIONING_VM_UPDATE:-no}" = "yes" ] && UPDATE_ARGS=(--update)

echo "--- Downloading and creating the sandbox VM as $TARGET_USER ---"
sudo -u "$TARGET_USER" bash "$DIR/lib/download-and-create-sandbox-vm-kvm.sh" "${UPDATE_ARGS[@]}"

echo "=== $(date) : done ==="
