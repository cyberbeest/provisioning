#!/bin/bash
# Toggles a bright background at the LUKS unlock prompt (a poor man's
# flashlight for typing in the dark), then rebuilds the initramfs so the
# change actually takes effect at next boot (plymouth runs from the
# initramfs, before the encrypted root is even mounted, so it never
# re-reads /usr/share/plymouth/themes/... live).
#
# Installed to /usr/local/sbin/cyberbeest-set-boot-bright-mode by
# setup-grub-plymouth-theme.sh and invoked via pkexec from
# disk_password_gui.py's "Boot Screen" tab, e.g.:
#   pkexec /usr/local/sbin/cyberbeest-set-boot-bright-mode 1
set -euo pipefail

SCRIPT_FILE="/usr/share/plymouth/themes/cyberbeest/cyberbeest.script"
STATE_FILE="/etc/cyberbeest/plymouth-bright-mode"

value="${1:-}"
if [ "$value" != "0" ] && [ "$value" != "1" ]; then
	echo "Usage: $0 0|1" >&2
	exit 1
fi

if [ ! -f "$SCRIPT_FILE" ]; then
	echo "Plymouth theme script not found: $SCRIPT_FILE" >&2
	exit 1
fi

new_line="bright_mode = \"${value}\";"

line_no="$(grep -n '^bright_mode = ' "$SCRIPT_FILE" | head -1 | cut -d: -f1)"
if [ -z "$line_no" ]; then
	echo "Could not find the bright_mode line in $SCRIPT_FILE" >&2
	exit 1
fi

tmp="$(mktemp)"
{
	head -n "$((line_no - 1))" "$SCRIPT_FILE"
	printf '%s\n' "$new_line"
	tail -n "+$((line_no + 1))" "$SCRIPT_FILE"
} > "$tmp"
mv "$tmp" "$SCRIPT_FILE"
chmod 644 "$SCRIPT_FILE"

install -d -m 755 /etc/cyberbeest
printf '%s' "$value" > "$STATE_FILE"
chmod 644 "$STATE_FILE"

echo "--- Rebuilding initramfs with updated boot screen brightness ---"
plymouth-set-default-theme -R cyberbeest
