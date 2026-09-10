#!/bin/bash
# Builds the KVM/GNOME-Boxes variant of the sandbox-VM donor image from the
# clean "Cyberbeest Donor Image" VirtualBox VM (already stripped of SSH/
# history by prepare-vm-donor.sh -- see that script for how it got that
# way). Host-only helper -- not part of provisioning, never runs on real
# hardware, and not something an end user's machine ever runs.
#
# Unlike the VirtualBox donor (a straight .vdi export), the KVM guest needs
# extra packages baked in that VirtualBox's own Guest Additions made
# unnecessary there:
#   - qemu-guest-agent: lets the host issue a real `shutdown` inside the
#     guest via its virtio-serial channel, bypassing XFCE's power-manager
#     confirmation dialog that a plain ACPI `virsh shutdown` triggers.
#   - spice-vdagent: clipboard sync + the display-resize negotiation that
#     GNOME Boxes' resize protocol depends on (paired with QXL video on the
#     host side, not virtio-vga -- see lib/spice-resize-apply.sh's own
#     comment for why the negotiation alone isn't enough on XFCE/X11).
#   - lib/spice-resize-apply.sh + its autostart entry: works around
#     spice-vdagent 0.22.1's XFCE/X11 resize gap (see that script).
#
# All of this is applied *offline* via virt-customize (libguestfs) --
# no VM boot involved, so the process is fully unattended and reproducible.
#
# Usage: bash build-kvm-donor-image.sh (no sudo needed)
# Idempotent: re-running overwrites the previous output qcow2 from a fresh
# copy of the VBox donor each time (rather than compounding customizations
# on top of a previous run's output).
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"

VBOX_VDI="$HOME/VirtualBox VMs/Cyberbeest Donor Image/Cyberbeest Donor Image.vdi"
BUILD_DIR="$HOME/vms/donor-build"
OUT_QCOW2="$BUILD_DIR/cyberbeest-donor.qcow2"
OUT_GZ="$BUILD_DIR/cyberbeest-donor.qcow2.gz"

if [ ! -f "$VBOX_VDI" ]; then
	echo "Donor VDI not found at: $VBOX_VDI" >&2
	exit 1
fi

mkdir -p "$BUILD_DIR"

echo "=== $(date) : converting VDI -> qcow2 ==="
rm -f "$OUT_QCOW2"
qemu-img convert -p -O qcow2 "$VBOX_VDI" "$OUT_QCOW2"

echo "=== $(date) : installing qemu-guest-agent + spice-vdagent, and the resize workaround (offline, via virt-customize) ==="
# The /home/cyberbeest/... paths below are inside the GUEST disk image, not
# this (host) machine -- the shipped product image always has a fixed
# "cyberbeest" account (same as the base ISO itself), unrelated to
# whatever username is running this build script.
virt-customize -a "$OUT_QCOW2" \
	--network \
	--install qemu-guest-agent,spice-vdagent \
	--upload "$DIR/lib/spice-resize-apply.sh:/home/cyberbeest/.local/bin/spice-resize-apply.sh" \
	--upload "$DIR/lib/spice-resize-apply.desktop:/home/cyberbeest/.config/autostart/spice-resize-apply.desktop" \
	--run-command "chmod +x /home/cyberbeest/.local/bin/spice-resize-apply.sh" \
	--run-command "chown -R cyberbeest:cyberbeest /home/cyberbeest/.local /home/cyberbeest/.config"

echo "=== $(date) : compacting ==="
qemu-img convert -p -O qcow2 -c "$OUT_QCOW2" "$OUT_QCOW2.compact"
mv "$OUT_QCOW2.compact" "$OUT_QCOW2"

echo "=== $(date) : compressing ==="
rm -f "$OUT_GZ"
pv "$OUT_QCOW2" | gzip > "$OUT_GZ"

echo "=== $(date) : done: $OUT_GZ ==="
qemu-img info "$OUT_QCOW2"
ls -lh "$OUT_GZ"
