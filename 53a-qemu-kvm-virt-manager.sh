#!/bin/bash
# Installs QEMU/KVM + libvirt + Virtual Machine Manager on the host for the
# same-OS VM feature -- the guest VM itself is a separate, later step
# (56-cyberbeest-sandbox-vm-kvm.sh).
#
# The VM itself opens from its own menu entry in a plain virt-viewer window
# (see lib/cyberbeest-vm-start.sh). Virtual Machine Manager is the full view
# of all VMs -- including the backup a VM update leaves behind -- set to
# show the user's own VMs (qemu:///session) rather than the system ones.
# GNOME Boxes was used until 2026-09-24 and is removed here: it hid what
# state a VM was actually in (running, paused, saved), which is false
# simplicity for something that holds on to RAM and data.
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
LOG="$DIR/53a-qemu-kvm-virt-manager.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing QEMU/KVM + Virtual Machine Manager ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

echo "--- apt-get update ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq

echo "--- Installing qemu-kvm, libvirt, Virtual Machine Manager, and supporting packages ---"
apt-get -o DPkg::Lock::Timeout=60 install -y \
	virt-manager \
	virt-viewer \
	libvirt-daemon-system \
	libvirt-clients \
	virtinst \
	qemu-kvm \
	qemu-utils \
	ovmf \
	virtiofsd \
	passt \
	lzop

echo "--- Removing VirtualBox's KVM blacklist, if present ---"
# Written by the old 53-virtualbox.sh (VirtualBox and KVM can't both hold
# VT-x). This removal was lost when VirtualBox was dropped on 2026-09-19, so
# machines that ever had VirtualBox kept KVM blocked from loading at boot,
# and libvirt silently fell back to software emulation (TCG): a VM that
# took 7+ minutes to boot and then timed out into emergency mode.
rm -f /etc/modprobe.d/blacklist-kvm.conf

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
# Closing the sandbox VM's window saves (hibernates) it -- see
# lib/cyberbeest-vm-start.sh. lzop-compressed (hence the package above).
# Measured 2026-09-25 on the dev machine (N3350), same 1.3 GB of guest RAM:
# lzop's file is 0.51 GB (raw 1.3-1.5, zstd 0.34), and it decompresses as
# fast as zstd (~5 s, CPU-bound), so restores are equally quick -- but it
# saves in ~11 s instead of zstd's ~22 s, which keeps the "saving"
# notice and its shutdown lock short. "sparse" was no better than raw.
# On host shutdown, the user's libvirt daemon saves running VMs (its
# per-user default, made explicit) -- but by default it would also restore
# them as soon as it starts again after the reboot, bringing the VM back
# running with no window. With restore off, a saved VM waits for its menu
# entry, which restores it into a window.
QEMU_CONF="$TARGET_HOME/.config/libvirt/qemu.conf"
qemu_conf_changed=false
touch "$QEMU_CONF"
for setting in 'save_image_format = "lzop"' 'auto_shutdown_try_save = "persistent"' 'auto_shutdown_restore = 0'; do
	key="${setting%% *}"
	if grep -qxF "$setting" "$QEMU_CONF"; then
		continue
	elif grep -q "^$key " "$QEMU_CONF"; then
		# Set to something else before (save_image_format was "zstd" for a day).
		sed -i "s|^$key .*|$setting|" "$QEMU_CONF"
	else
		echo "$setting" >>"$QEMU_CONF"
	fi
	qemu_conf_changed=true
done
chown "$TARGET_USER:$TARGET_USER" "$QEMU_CONF"
# The user's session libvirtd reads qemu.conf only at startup; it exits on
# its own when idle, but a running one would keep the old settings until
# then. Only restarted while no VM runs: a VM survives the restart, but the
# new daemon no longer knows its shared folder's virtiofsd can be saved,
# so saving that VM fails ("migration with this virtiofs device is not
# supported") until it's shut down once -- seen 2026-09-25.
if [ "$qemu_conf_changed" = true ] && ! pgrep -u "$TARGET_USER" -f '^/usr/bin/qemu-system' >/dev/null; then
	pkill -u "$TARGET_USER" -x libvirtd || true
fi

echo "--- Letting a shutdown wait for the sandbox VM to be saved ---"
# If the laptop shuts down with the VM running, the user's libvirt daemon
# saves it (auto_shutdown_try_save, below) under a shutdown "delay" lock.
# logind only waits InhibitDelayMaxSec for such locks -- 5 s by default,
# while a save takes 20-35 s. Only matters while a delay lock is actually
# held. Read by logind at its next start (reboot).
install -d /etc/systemd/logind.conf.d
cat >/etc/systemd/logind.conf.d/cyberbeest-vm.conf <<'EOF'
# Cyberbeest: time for the sandbox VM to be saved before shutdown -- see
# 53a-qemu-kvm-virt-manager.sh.
[Login]
InhibitDelayMaxSec=90
EOF

echo "--- Pointing Virtual Machine Manager at the user's own VMs ---"
# Its default is the system-wide qemu:///system, where none of our VMs are
# (they run unprivileged under qemu:///session). Shipped as the schema
# default, so a user who adds other connections keeps them.
cat >/usr/share/glib-2.0/schemas/95-cyberbeest-virt-manager.gschema.override <<'EOF'
[org.virt-manager.virt-manager.connections]
uris=['qemu:///session']
autoconnect=['qemu:///session']
EOF

echo "--- Removing GNOME Boxes, if a previous provisioning run installed it ---"
if dpkg -l gnome-boxes 2>/dev/null | grep -q '^ii'; then
	apt-get -o DPkg::Lock::Timeout=60 remove -y gnome-boxes
fi
rm -f /usr/share/glib-2.0/schemas/95-cyberbeest-gnome-boxes.gschema.override
glib-compile-schemas /usr/share/glib-2.0/schemas/

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
