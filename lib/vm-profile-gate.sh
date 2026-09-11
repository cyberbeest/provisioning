# Sourced (not executed) by 56-cyberbeest-sandbox-vm-kvm.sh: reads the "VM
# image" choice from the provisioning profile dialog (see run-gui.py's
# ProvisioningProfileDialog) and `exit 0`s the *caller* -- since this is
# sourced into the same shell, not run as a subprocess -- if the user
# opted out of the multi-GB KVM disk-image download.
#
# 53-virtualbox.sh, 53a-qemu-kvm-boxes.sh, and 57-hypervisor-switcher.sh no
# longer source this: both hypervisors install unconditionally now (no
# "pick a hypervisor" profile question), only the VM disk-image download
# is optional. See memory: cyberbeest_kvm_provisioning_track for the
# 2026-09-11 decision to drop VirtualBox's own disk-image build entirely
# (experimental/55-cyberbeest-sandbox-vm.sh) rather than gate it.
#
# Missing profile file, or the var unset within it (a standalone/manual
# run outside run-gui.py, or a run-gui.py session where the profile dialog
# was never shown): defaults to "download it", i.e. the behavior this
# script had before the profile section existed.
#
# Usage: . "$DIR/lib/vm-profile-gate.sh"

_gate_env_file="$DIR/.provisioning-profile.env"

PROVISIONING_VM_IMAGE="yes"
if [ -f "$_gate_env_file" ]; then
	# shellcheck disable=SC1090
	. "$_gate_env_file"
fi

if [ "$PROVISIONING_VM_IMAGE" = "no" ]; then
	echo "VM disk-image download disabled in the provisioning profile -- skipping."
	exit 0
fi

unset _gate_env_file
