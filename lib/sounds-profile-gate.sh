# Sourced (not executed) by 20-shutdown-sound.sh, 35-boot-chime.sh and
# 47-set-max-volume.sh: reads the "Sounds" choice from the provisioning
# profile dialog (see run-gui.py's ProvisioningProfileDialog) and `exit 0`s
# the *caller* -- since this is sourced into the same shell, not run as a
# subprocess -- if the user opted out of the Cyberbeest startup/shutdown
# sounds and the maximum-volume setting.
#
# Missing profile file, or the var unset within it (a standalone/manual run
# outside run-gui.py, or a session where the profile dialog was never
# shown): defaults to "install the sounds", i.e. the behavior these scripts
# had before the profile question existed. Same pattern as
# lib/vm-profile-gate.sh.
#
# Usage: . "$DIR/lib/sounds-profile-gate.sh"

_gate_env_file="$DIR/.provisioning-profile.env"

PROVISIONING_SOUNDS="yes"
if [ -f "$_gate_env_file" ]; then
	# shellcheck disable=SC1090
	. "$_gate_env_file"
fi

if [ "$PROVISIONING_SOUNDS" = "no" ]; then
	echo "Cyberbeest sounds disabled in the provisioning profile -- skipping."
	exit 0
fi

unset _gate_env_file
