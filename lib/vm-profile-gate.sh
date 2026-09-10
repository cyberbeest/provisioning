# Sourced (not executed) by 53-virtualbox.sh, 53a-qemu-kvm-boxes.sh,
# 55-cyberbeest-sandbox-vm.sh, 56-cyberbeest-sandbox-vm-kvm.sh, and
# 57-hypervisor-switcher.sh: reads the "VM host" choice from the
# provisioning profile dialog (see run-gui.py's ProvisioningProfileDialog)
# and `exit 0`s the *caller* -- since this is sourced into the same shell,
# not run as a subprocess -- if that script's hypervisor wasn't selected.
#
# Missing profile file, or vars unset within it (a standalone/manual run
# outside run-gui.py, or a run-gui.py session where the profile dialog was
# never shown): defaults to "install everything", i.e. the behavior these
# scripts had before this profile section existed.
#
# Usage: . "$DIR/lib/vm-profile-gate.sh" <vbox|kvm|switcher>

_gate_target="${1:?vm-profile-gate.sh: usage: . vm-profile-gate.sh <vbox|kvm|switcher>}"
_gate_env_file="$DIR/.provisioning-profile.env"

PROVISIONING_VM_HOST="yes"
PROVISIONING_VM_HYPERVISOR="both"
if [ -f "$_gate_env_file" ]; then
	# shellcheck disable=SC1090
	. "$_gate_env_file"
fi

if [ "$PROVISIONING_VM_HOST" = "no" ]; then
	echo "VM host feature disabled in the provisioning profile -- skipping."
	exit 0
fi

case "$_gate_target" in
	vbox)
		if [ "$PROVISIONING_VM_HYPERVISOR" != "vbox" ] && [ "$PROVISIONING_VM_HYPERVISOR" != "both" ]; then
			echo "VirtualBox not selected in the provisioning profile (chose: $PROVISIONING_VM_HYPERVISOR) -- skipping."
			exit 0
		fi
		;;
	kvm)
		if [ "$PROVISIONING_VM_HYPERVISOR" != "kvm" ] && [ "$PROVISIONING_VM_HYPERVISOR" != "both" ]; then
			echo "QEMU/KVM not selected in the provisioning profile (chose: $PROVISIONING_VM_HYPERVISOR) -- skipping."
			exit 0
		fi
		;;
	switcher)
		if [ "$PROVISIONING_VM_HYPERVISOR" != "both" ]; then
			echo "Only one hypervisor selected in the provisioning profile (chose: $PROVISIONING_VM_HYPERVISOR) -- nothing to switch between, skipping."
			exit 0
		fi
		;;
	*)
		echo "vm-profile-gate.sh: invalid target '$_gate_target'" >&2
		exit 1
		;;
esac

unset _gate_target _gate_env_file
