# Sourced (not executed) by 56-cyberbeest-sandbox-vm-kvm.sh: reads the "VM
# image" choice from the provisioning profile dialog (see run-gui.py's
# ProvisioningProfileDialog) and `exit 0`s the *caller* -- since this is
# sourced into the same shell, not run as a subprocess -- if the user
# opted out of the multi-GB KVM disk-image download.
#
# 53a-qemu-kvm-boxes.sh doesn't source this: KVM installs unconditionally
# (no "pick a hypervisor" profile question -- it's the only hypervisor
# provisioning ships, VirtualBox was dropped entirely 2026-09-19), only the
# VM disk-image download is optional. See memory:
# cyberbeest_kvm_provisioning_track, cyberbeest_drop_virtualbox_discussion.
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
