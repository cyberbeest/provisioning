#!/bin/bash
# Marks this machine as the disposable Fresh VM dev/test rig, so
# 90-vm-mode-overrides.sh auto-applies its dev-rig overrides (solid
# background, no lock/screensaver, VM-specific boot logo, etc.) on every
# future provisioning re-run without needing PROVISIONING_DEV_TEST_VM
# re-exported each session.
#
# Run this ONCE, by hand, as root, right after setting up the disposable
# test rig from a donor image -- NOT as part of the normal numbered
# provisioning chain, and NEVER on a real customer machine or on whatever
# produces the actual shippable cyberbeest-vm.qcow2 product:
#
#   sudo bash lib/mark-dev-test-vm.sh
#
# The marker lives on disk (/etc/cyberbeest/dev-test-vm-marker), so it
# survives every future provisioning re-run on this same rig -- but that
# also means it survives a naive disk clone. If this rig's donor image is
# ever reused as the starting point for the real shippable VM product,
# whatever build step does that MUST remove this file explicitly
# (`rm -f /etc/cyberbeest/dev-test-vm-marker`), or the shipped product
# will silently get dev-rig overrides (autologin, no lock screen) baked
# in -- see 90-vm-mode-overrides.sh's header for the 2026-09-19 incident
# this whole gating exists to prevent.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "must run as root (sudo bash lib/mark-dev-test-vm.sh)" >&2
	exit 1
fi

VIRT="$(systemd-detect-virt || true)"
if [ "$VIRT" = "none" ]; then
	echo "refusing: systemd-detect-virt reports bare metal, this is not a VM" >&2
	exit 1
fi

install -d -m 755 /etc/cyberbeest
printf '%s\n' "created $(date) by mark-dev-test-vm.sh" > /etc/cyberbeest/dev-test-vm-marker
chmod 644 /etc/cyberbeest/dev-test-vm-marker

echo "--- marked as disposable dev/test VM (detected virtualization: $VIRT) ---"
echo "--- re-run 90-vm-mode-overrides.sh (or the full provisioning chain) to apply overrides now ---"
