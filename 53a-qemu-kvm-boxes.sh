#!/bin/bash
# Installs QEMU/KVM + libvirt + GNOME Boxes on the host, as an alternative
# hypervisor to VirtualBox (53-virtualbox.sh) for the same-OS VM feature --
# the guest VM itself is a separate, later step
# (56-cyberbeest-sandbox-vm-kvm.sh).
#
# Why an alternative to VirtualBox at all: VirtualBox's kernel modules are
# unsigned and out-of-tree, and it has a materially worse VM-escape CVE
# track record than KVM (in-tree, hardware-accelerated, and -- via this
# setup -- unprivileged per-user `qemu:///session`, with QEMU sandboxed via
# seccomp). See memory: cyberbeest_vbox_to_kvm_boxes_migration.
#
# Decided 2026-09-11: both stay installed unconditionally (no "pick a
# hypervisor" profile question) -- KVM is the promoted default (it's the
# only one provisioning auto-builds a VM disk image for, see
# 56-cyberbeest-sandbox-vm-kvm.sh), VirtualBox stays available but
# unpromoted for users who want it. They're mutually exclusive at runtime
# on the same machine (VirtualBox can't hold VT-x/AMD-V while KVM does,
# and vice versa), so:
#   - 53-virtualbox.sh blacklists the kvm/kvm_intel/kvm_amd modules.
#   - This script undoes that blacklist if present, and loads kvm_intel or
#     kvm_amd itself.
# This script's the letter-suffixed one (53a runs right after 53, see
# lib's letter-suffix scheme), so it always wins the module-blacklist
# tug-of-war -- KVM ends up active after a fresh provisioning run, with the
# Whisker switcher (57-hypervisor-switcher.sh) there if the user wants
# VirtualBox active instead.
#
# Idempotent: safe to re-run.
#
# Bumped 2026-09-11: added the qemu.conf max_core=0 setting (see its own
# comment below) -- without it, virt-install run via `sudo -u
# $TARGET_USER` (as 56-cyberbeest-sandbox-vm-kvm.sh does) fails outright
# with a core-file-size rlimit error.
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

echo "--- Configuring qemu:///session to not try raising RLIMIT_CORE ---"
# libvirt's QEMU session driver always tries to raise the guest process's
# RLIMIT_CORE to unlimited before exec (max_core defaults to "unlimited"
# on Linux -- see qemu.conf.in upstream). When the VM is created via
# `sudo -u $TARGET_USER` (56-cyberbeest-sandbox-vm-kvm.sh runs the actual
# virt-install that way, since provisioning itself runs as root), sudo's
# PAM session caps the hard limit at 0 for that invocation (confirmed live
# 2026-09-11: a plain SSH login shows "unlimited" for the same user, but
# `sudo -n -u <user>` shows 0 -- a PAM/sudo interaction, root cause not
# fully pinned down), and virt-install then fails with "cannot limit core
# file size of process ... to 18446744073709551615: Operation not
# permitted". Setting max_core to 0 tells libvirt not to touch the limit
# at all, sidestepping the problem -- we don't need core dumps from
# sandbox VM guests anyway.
#
# Must be a bare integer, NOT a quoted string: libvirt's config parser
# only accepts the quoted form for the literal string "unlimited";
# max_core = "0" throws "unsupported configuration: Unknown core size
# '0'" and breaks the QEMU driver's init entirely (confirmed live
# 2026-09-11 -- caught and fixed the same session).
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/libvirt"
if ! grep -q "^max_core" "$TARGET_HOME/.config/libvirt/qemu.conf" 2>/dev/null; then
	echo "max_core = 0" >> "$TARGET_HOME/.config/libvirt/qemu.conf"
	chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/libvirt/qemu.conf"
fi

echo "--- Enabling libvirtd ---"
systemctl enable --now libvirtd

echo "=== $(date) : done ==="
