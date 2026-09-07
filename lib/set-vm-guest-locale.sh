#!/bin/bash
# Matches the sandbox guest VM's locale/keyboard to the host's own, offline
# -- before the guest ever boots, so its first-run desktop already speaks
# the same language and types the same keyboard layout as the machine
# it's running on, without the user having to configure a second, separate
# copy of 00-locale-keyboard-timezone.sh's questionnaire inside the guest.
#
# Works directly on the disk image file via virt-customize (libguestfs) --
# no VM boot involved. Mirrors 00-locale-keyboard-timezone.sh's own
# locale/keyboard-application commands exactly (debconf-set-selections +
# dpkg-reconfigure, not hand-editing /etc/default/locale or
# /etc/default/keyboard directly) so the guest ends up in the identical
# state a real install of that script would produce -- console-setup,
# /etc/locale.gen, and /etc/default/keyboard all regenerated consistently
# from the same source of truth Debian's own packages use.
#
# Reads the *host's* current settings (this script runs on a machine that
# has already been through 00-locale-keyboard-timezone.sh itself) rather
# than asking again.
#
# Deliberately skips two steps 00-locale-keyboard-timezone.sh does: setupcon
# (applies the keymap to the *current* console -- meaningless offline, with
# no console attached) and update-initramfs (there to fix the keymap on the
# host's own LUKS unlock prompt, which this guest doesn't have). Both are
# no-ops for an image that hasn't booted yet.
#
# Usage: set-vm-guest-locale.sh <path-to-disk-image>
set -euo pipefail

DISK="${1:?Usage: set-vm-guest-locale.sh <path-to-disk-image>}"

HOST_LANG="$(sed -n 's/^LANG="\?\([^"]*\)"\?/\1/p' /etc/default/locale | head -1)"
HOST_XKBLAYOUT="$(sed -n 's/^XKBLAYOUT="\?\([^"]*\)"\?/\1/p' /etc/default/keyboard | head -1)"
HOST_XKBVARIANT="$(sed -n 's/^XKBVARIANT="\?\([^"]*\)"\?/\1/p' /etc/default/keyboard | head -1)"

if [ -z "$HOST_LANG" ] || [ -z "$HOST_XKBLAYOUT" ]; then
	echo "set-vm-guest-locale: couldn't read LANG/XKBLAYOUT from the host -- aborting" >&2
	exit 1
fi
echo "--- Host locale: $HOST_LANG, keyboard: $HOST_XKBLAYOUT${HOST_XKBVARIANT:+/$HOST_XKBVARIANT} ---"

GUEST_SCRIPT="$(mktemp)"
trap 'rm -f "$GUEST_SCRIPT"' EXIT
cat > "$GUEST_SCRIPT" <<EOF
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

gen_locales="$HOST_LANG UTF-8"
[ "$HOST_LANG" != "en_US.UTF-8" ] && gen_locales="\$gen_locales, en_US.UTF-8 UTF-8"
debconf-set-selections <<-INNER_EOF
	locales locales/default_environment_locale select $HOST_LANG
	locales locales/locales_to_be_generated multiselect \$gen_locales
INNER_EOF
{
	echo "$HOST_LANG UTF-8"
	[ "$HOST_LANG" != "en_US.UTF-8" ] && echo "en_US.UTF-8 UTF-8"
} > /etc/locale.gen
locale-gen
update-locale --no-checks LANG
update-locale "LANG=$HOST_LANG"
dpkg-reconfigure -f noninteractive locales

debconf-set-selections <<-INNER_EOF
	keyboard-configuration keyboard-configuration/modelcode string pc105
	keyboard-configuration keyboard-configuration/model select Generic 105-key PC
	keyboard-configuration keyboard-configuration/layoutcode string $HOST_XKBLAYOUT
	keyboard-configuration keyboard-configuration/variantcode string $HOST_XKBVARIANT
	keyboard-configuration keyboard-configuration/xkb-keymap select $HOST_XKBLAYOUT
INNER_EOF
dpkg-reconfigure -f noninteractive keyboard-configuration
EOF

echo "--- Applying inside the guest image via virt-customize ---"
virt-customize -a "$DISK" \
	--upload "$GUEST_SCRIPT:/tmp/set-vm-guest-locale-inner.sh" \
	--run-command "bash /tmp/set-vm-guest-locale-inner.sh && rm -f /tmp/set-vm-guest-locale-inner.sh"
