#!/bin/bash
# Downloads the Cyberbeest sandbox VM (same OS as the host, for running
# untrusted apps in extra isolation) and registers it under QEMU/KVM +
# GNOME Boxes -- see lib/download-and-create-sandbox-vm-kvm.sh for the
# actual mechanism, and 53a-qemu-kvm-virt-manager.sh for installing the hypervisor
# itself. KVM is the only hypervisor provisioning ships -- VirtualBox was
# dropped entirely 2026-09-19, see 53a-qemu-kvm-virt-manager.sh.
#
# Skipped entirely inside a VM: a VM guest has no business getting its own
# nested sandbox VM (91-sandbox-vm.sh is the guest-side counterpart: it
# only acts inside a sandbox VM set up by this script).
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
# Depends on: 53a-qemu-kvm-virt-manager.sh.
# The lib script installs this launcher; naming it here makes run-gui.py
# mark this script pending when one changes: lib/cyberbeest-vm-start.sh.
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

echo "--- Giving the VM the host user's password ---"
# The hash, not the password: /etc/shadow's yescrypt hash works unchanged in
# the guest, so the host's short password also answers sudo prompts in the
# VM. A new VM would otherwise keep the image's publicly known default.
# Every run re-syncs, which also picks up a password changed with plain
# `passwd` rather than the change-password dialog (that one syncs on its
# own). Not being able to sync (VM paused or saved) isn't a provisioning
# failure -- the helper logs why and it's retried on the next run.
HOST_HASH="$(getent shadow "$TARGET_USER" | cut -d: -f2)"
printf '%s\n' "$HOST_HASH" \
	| sudo -u "$TARGET_USER" bash "$DIR/lib/cyberbeest-vm-set-password-hash.sh" || true

echo "=== $(date) : done ==="
