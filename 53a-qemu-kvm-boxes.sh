#!/bin/bash
# Installs QEMU/KVM + libvirt + GNOME Boxes on the host, as an alternative
# hypervisor to VirtualBox (53-virtualbox.sh) for the same-OS sandbox-VM
# feature -- the guest VM itself is a separate, later step
# (56-cyberbeest-sandbox-vm-kvm.sh).
#
# Why an alternative to VirtualBox at all: VirtualBox's kernel modules are
# unsigned and out-of-tree, and it has a materially worse VM-escape CVE
# track record than KVM (in-tree, hardware-accelerated, and -- via this
# setup -- unprivileged per-user `qemu:///session`, with QEMU sandboxed via
# seccomp). See memory: cyberbeest_vbox_to_kvm_boxes_migration.
#
# NOT YET DECIDED whether this replaces VirtualBox outright or the two
# stay as parallel options -- both scripts currently ship. They are
# mutually exclusive at runtime on the same machine (VirtualBox can't hold
# VT-x/AMD-V while KVM does, and vice versa), so:
#   - 53-virtualbox.sh blacklists the kvm/kvm_intel/kvm_amd modules.
#   - This script undoes that blacklist if present, and loads kvm_intel or
#     kvm_amd itself.
# If both scripts end up running on the same install (nothing currently
# prevents that -- there's no "pick one hypervisor" question yet), the
# LAST one to run wins the module-blacklist tug-of-war. Needs a real
# selection mechanism before this ships for real; flagging rather than
# solving here.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/53a-qemu-kvm-boxes.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing QEMU/KVM + GNOME Boxes ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- apt-get update ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq

echo "--- Installing qemu-kvm, libvirt, GNOME Boxes, and supporting packages ---"
apt-get -o DPkg::Lock::Timeout=60 install -y \
	gnome-boxes \
	libvirt-daemon-system \
	libvirt-clients \
	virtinst \
	qemu-kvm \
	qemu-utils \
	ovmf \
	virtiofsd \
	passt

echo "--- Removing VirtualBox's kvm blacklist, if present ---"
if [ -f /etc/modprobe.d/blacklist-kvm.conf ]; then
	rm -f /etc/modprobe.d/blacklist-kvm.conf
	update-initramfs -u
	echo "removed -- was blocking kvm/kvm_intel/kvm_amd from loading"
fi

echo "--- Loading the KVM module ---"
if grep -q vmx /proc/cpuinfo; then
	modprobe kvm_intel
elif grep -q svm /proc/cpuinfo; then
	modprobe kvm_amd
else
	echo "WARNING: no VT-x/AMD-V flag found in /proc/cpuinfo -- KVM acceleration unavailable" >&2
fi

echo "--- Adding $TARGET_USER to the libvirt and kvm groups ---"
usermod -aG libvirt,kvm "$TARGET_USER"

echo "--- Enabling libvirtd ---"
systemctl enable --now libvirtd

echo "=== $(date) : done ==="
