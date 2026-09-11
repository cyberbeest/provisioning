#!/bin/bash
# Flips which hypervisor holds VT-x/AMD-V: VirtualBox and KVM cannot both
# hold hardware virtualization at once (confirmed live: VirtualBox 7.2
# fails to start a VM with VERR_VMX_IN_VMX_ROOT_MODE the instant kvm_intel
# is loaded, even completely idle -- a real hardware exclusion, not a
# stale blacklist file). Both hypervisors are always installed side by
# side; this is what actually lets the user switch which one is *active*
# without a reboot.
#
# Root-only (unloading/loading kernel modules) -- invoked via pkexec from
# lib/cyberbeest-hypervisor-switch-ui.sh, not directly by the user.
#
# Usage: cyberbeest-hypervisor-switch.sh <vbox|kvm>
set -euo pipefail

TARGET="${1:?usage: cyberbeest-hypervisor-switch.sh <vbox|kvm>}"
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"

case "$TARGET" in
	vbox)
		if ! command -v VBoxManage >/dev/null 2>&1; then
			echo "VirtualBox is not installed." >&2
			exit 1
		fi
		if su - "$TARGET_USER" -c "virsh --connect qemu:///session list --state-running --name" 2>/dev/null | grep -q .; then
			echo "A KVM virtual machine is currently running -- shut it down first." >&2
			exit 1
		fi

		echo "--- Unloading KVM ---"
		for mod in kvm_intel kvm_amd kvm; do
			modprobe -r "$mod" 2>/dev/null || true
		done

		echo "--- Blacklisting KVM so it doesn't reload on next boot ---"
		cat > /etc/modprobe.d/blacklist-kvm.conf <<'EOF'
# Disabled: conflicts with VirtualBox's use of VT-x/AMD-V (VirtualBox can't
# run VMX/SVM root mode while KVM holds it). Written by
# cyberbeest-hypervisor-switch.sh -- remove by switching back to KVM
# through the same tool, not by hand.
blacklist kvm_intel
blacklist kvm_amd
blacklist kvm
EOF
		update-initramfs -u
		echo "--- Active hypervisor: VirtualBox ---"
		;;

	kvm)
		if ! command -v virsh >/dev/null 2>&1; then
			echo "QEMU/KVM is not installed." >&2
			exit 1
		fi
		if VBoxManage list runningvms 2>/dev/null | grep -q .; then
			echo "A VirtualBox virtual machine is currently running -- shut it down first." >&2
			exit 1
		fi

		echo "--- Removing the KVM blacklist, if present ---"
		if [ -f /etc/modprobe.d/blacklist-kvm.conf ]; then
			rm -f /etc/modprobe.d/blacklist-kvm.conf
			update-initramfs -u
		fi

		echo "--- Unloading VirtualBox's kernel modules ---"
		for mod in vboxnetadp vboxnetflt vboxdrv; do
			modprobe -r "$mod" 2>/dev/null || true
		done

		echo "--- Loading KVM ---"
		if grep -q vmx /proc/cpuinfo; then
			modprobe kvm_intel
		elif grep -q svm /proc/cpuinfo; then
			modprobe kvm_amd
		else
			echo "WARNING: no VT-x/AMD-V flag found in /proc/cpuinfo" >&2
		fi
		echo "--- Active hypervisor: QEMU/KVM ---"
		;;

	*)
		echo "usage: cyberbeest-hypervisor-switch.sh <vbox|kvm>" >&2
		exit 1
		;;
esac
