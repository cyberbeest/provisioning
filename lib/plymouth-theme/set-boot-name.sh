#!/bin/bash
# Rewrites the machine-name line shown above the LUKS unlock prompt, then
# rebuilds the initramfs so the change actually takes effect at next boot
# (plymouth runs from the initramfs, before the encrypted root is even
# mounted, so it never re-reads /usr/share/plymouth/themes/... live).
#
# Installed to /usr/local/sbin/cyberbeest-set-boot-name by
# setup-grub-plymouth-theme.sh and invoked via pkexec from
# disk_password_gui.py's "Boot Screen" tab, e.g.:
#   pkexec /usr/local/sbin/cyberbeest-set-boot-name "My Cyberbeest"
# Pass an empty string to clear the name back to no name line.
set -euo pipefail

SCRIPT_FILE="/usr/share/plymouth/themes/cyberbeest/cyberbeest.script"
NAME_FILE="/etc/cyberbeest/machine-name"
MAX_NAME_LENGTH=40

name="${1:-}"
# Defense in depth: disk_password_gui.py already enforces this, but this
# script runs as root via pkexec so it can't trust argv blindly.
name="${name//$'\n'/}"
name="${name//$'\r'/}"
if [ "${#name}" -gt "$MAX_NAME_LENGTH" ]; then
	echo "Machine name too long (max $MAX_NAME_LENGTH characters)." >&2
	exit 1
fi

if [ ! -f "$SCRIPT_FILE" ]; then
	echo "Plymouth theme script not found: $SCRIPT_FILE" >&2
	exit 1
fi

# Escapes backslash and double-quote so the value can sit inside a
# plymouth-script double-quoted string literal without breaking out of it.
escape_for_script_string() {
	local s="$1"
	s="${s//\\/\\\\}"
	s="${s//\"/\\\"}"
	printf '%s' "$s"
}

name_escaped="$(escape_for_script_string "$name")"
new_line="password_dialog.machine_name = \"${name_escaped}\";"

line_no="$(grep -n '^password_dialog.machine_name = ' "$SCRIPT_FILE" | head -1 | cut -d: -f1)"
if [ -z "$line_no" ]; then
	echo "Could not find the machine_name line in $SCRIPT_FILE" >&2
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
printf '%s' "$name" > "$NAME_FILE"
chmod 644 "$NAME_FILE"

echo "--- Rebuilding initramfs with updated boot screen name ---"
plymouth-set-default-theme -R cyberbeest
