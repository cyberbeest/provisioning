#!/bin/bash
# Installs QEMU/KVM + libvirt + GNOME Boxes on the host for the same-OS VM
# feature -- the guest VM itself is a separate, later step
# (56-cyberbeest-sandbox-vm-kvm.sh).
#
# KVM is the only hypervisor provisioning installs: in-tree,
# hardware-accelerated, and -- via this setup -- unprivileged per-user
# `qemu:///session`, with QEMU sandboxed via seccomp. VirtualBox was
# dropped entirely 2026-09-19 (its kernel modules are unsigned and
# out-of-tree, and it has a materially worse VM-escape CVE track record)
# rather than kept side by side -- no reason to ship a slower, less secure
# tool for a job KVM already covers. See memory:
# cyberbeest_vbox_to_kvm_boxes_migration, cyberbeest_drop_virtualbox_discussion.
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

echo "--- Disabling GNOME Boxes' first-run welcome tutorial/carousel ---"
# Boxes shows a first-run onboarding carousel (view stack in
# src/welcome-tutorial.vala upstream, gated by the org.gnome.boxes
# "first-run" gsettings key, default true) the first time it's opened.
# End users should never see dev/onboarding chrome, so ship the schema
# default as already-seen. Same technique as 02-gnome-software-store.sh's
# gschema.override for org.gnome.software's Explore carousel.
cat >/usr/share/glib-2.0/schemas/95-cyberbeest-gnome-boxes.gschema.override <<'EOF'
[org.gnome.boxes]
first-run=false
EOF
glib-compile-schemas /usr/share/glib-2.0/schemas/
echo "Disabled GNOME Boxes' first-run tutorial (first-run=false)."

echo "--- Enabling libvirtd ---"
systemctl enable --now libvirtd

echo "--- Removing VirtualBox, if a previous provisioning run installed it ---"
# Cleanup for machines provisioned before 2026-09-19, when 53-virtualbox.sh
# (and the hypervisor switcher, 57-hypervisor-switcher.sh) still installed
# it side by side with KVM. Both scripts are gone now, so nothing else in
# provisioning removes this on an update -- has to happen here.
if dpkg -l virtualbox-7.2 2>/dev/null | grep -q '^ii'; then
	apt-get -o DPkg::Lock::Timeout=60 purge -y virtualbox-7.2
fi
rm -f /etc/apt/sources.list.d/virtualbox.list /usr/share/keyrings/oracle-virtualbox-2016.gpg
gpasswd -d "$TARGET_USER" vboxusers 2>/dev/null || true
rm -f "$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-vbox.desktop" \
	"$TARGET_HOME/.local/share/applications/cyberbeest-switch-to-kvm.desktop" \
	"$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch-ui.sh" \
	"$TARGET_HOME/.local/bin/cyberbeest-hypervisor-switch.sh"

echo "=== $(date) : done ==="
