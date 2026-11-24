#!/bin/bash
# Switches word passphrase entry at the LUKS unlock prompt on or off:
#  * on: crypttab gets the normalizing keyscript (lower case, umlauts
#    transliterated, any run of separators -> one "-") and the Plymouth theme
#    shows one tag per finished word instead of one bullet per key;
#  * off: the keyscript is taken out of crypttab again and the theme goes
#    back to plain bullets.
# Then rebuilds the initramfs (plymouth and the keyscript run from it, before
# the encrypted root is mounted).
#
# Installed to /usr/local/sbin/cyberbeest-set-word-mode by
# setup-grub-plymouth-theme.sh and invoked via pkexec from
# disk_password_gui.py's "Boot Screen" tab, e.g.:
#   printf '%s\n' "$master_passphrase" | pkexec /usr/local/sbin/cyberbeest-set-word-mode 1
#
# Switching ON reads the current master passphrase from stdin first: with the
# keyscript wired in, whatever is typed at boot is normalized before it
# reaches LUKS, so a passphrase that is not already in canonical form would
# no longer unlock the disk. It must be canonical AND unlock the disk, or
# nothing is changed.
#
# Exit codes: 0 ok; 2 usage; 3 crypttab uses a different keyscript (Boot
# Fresh); 4 passphrase not in canonical form; 5 passphrase does not unlock
# the disk; 1 anything else.
#
# CYBERBEEST_ROOT (default empty) prefixes every path, so the logic can be
# tried against a scratch tree without touching the real system.
set -euo pipefail

R="${CYBERBEEST_ROOT:-}"
CRYPTTAB="$R/etc/crypttab"
THEME_SCRIPT="$R/usr/share/plymouth/themes/cyberbeest/cyberbeest.script"
STATE_FILE="$R/etc/cyberbeest/word-passphrase-mode"
SRC_DIR="$R/usr/local/lib/cyberbeest/word-passphrase"
KEYSCRIPT="/lib/cryptsetup/cyberbeest-askpass-words"
BOOT_FRESH_KEYSCRIPT="/lib/cryptsetup/cyberbeest-askpass-boot-fresh"
KEYSCRIPT_DEST="$R$KEYSCRIPT"
FILTER_DEST="$R/lib/cryptsetup/cyberbeest-passphrase-filter"
HOOK_DEST="$R/etc/initramfs-tools/hooks/cyberbeest-passphrase-filter"

value="${1:-}"
if [ "$value" != "0" ] && [ "$value" != "1" ]; then
	echo "Usage: $0 0|1   (1 reads the current master passphrase from stdin)" >&2
	exit 2
fi
[ -f "$THEME_SCRIPT" ] || { echo "Plymouth theme script not found: $THEME_SCRIPT" >&2; exit 1; }
[ -f "$CRYPTTAB" ] || { echo "No $CRYPTTAB" >&2; exit 1; }

if grep -q "keyscript=$BOOT_FRESH_KEYSCRIPT" "$CRYPTTAB" \
   || { grep -q 'keyscript=' "$CRYPTTAB" && ! grep -q "keyscript=$KEYSCRIPT" "$CRYPTTAB"; }; then
	echo "/etc/crypttab already uses a different keyscript (Boot Fresh?); not changing it." >&2
	exit 3
fi

set_theme_word_mode() {
	local line_no tmp
	line_no="$(grep -n '^word_mode = ' "$THEME_SCRIPT" | head -1 | cut -d: -f1)"
	[ -n "$line_no" ] || { echo "Could not find the word_mode line in $THEME_SCRIPT" >&2; exit 1; }
	tmp="$(mktemp)"
	{
		head -n "$((line_no - 1))" "$THEME_SCRIPT"
		printf 'word_mode = "%s";\n' "$1"
		tail -n "+$((line_no + 1))" "$THEME_SCRIPT"
	} > "$tmp"
	cat "$tmp" > "$THEME_SCRIPT"
	rm -f "$tmp"
	chmod 644 "$THEME_SCRIPT"
}

write_state() {
	install -d -m 755 "$(dirname "$STATE_FILE")"
	printf '%s' "$1" > "$STATE_FILE"
	chmod 644 "$STATE_FILE"
}

if [ "$value" = "1" ]; then
	IFS= read -r PW || true
	[ -n "$PW" ] || { echo "No passphrase given on stdin." >&2; exit 5; }

	for f in cyberbeest-passphrase-filter cyberbeest-askpass-words cyberbeest-passphrase-filter.hook; do
		[ -f "$SRC_DIR/$f" ] || { echo "Missing $SRC_DIR/$f (rerun 15-grub-plymouth-theme.sh)" >&2; exit 1; }
	done

	# Same filter the boot prompt will apply: the passphrase must come out unchanged.
	# shellcheck disable=SC1091
	. "$SRC_DIR/cyberbeest-passphrase-filter"
	NORM="$(printf '%s' "$PW" | cyberbeest_normalize_passphrase)"
	if [ "$NORM" != "$PW" ]; then
		echo "The master password is not in word form (lower-case words joined by \"-\")." >&2
		exit 4
	fi

	LUKS_UUID="$(awk '!/^#/ && NF {print $2; exit}' "$CRYPTTAB" | sed 's/^UUID=//')"
	if ! printf '%s' "$PW" | cryptsetup open --test-passphrase "/dev/disk/by-uuid/$LUKS_UUID" -; then
		echo "That master password does not unlock the disk." >&2
		exit 5
	fi
	unset PW NORM

	echo "--- keeping the running kernel's initrd as /boot/cyberbeest-words-backup ---"
	if [ -z "$R" ] && [ -f "/boot/initrd.img-$(uname -r)" ]; then
		install -d /boot/cyberbeest-words-backup
		cp -n "/boot/initrd.img-$(uname -r)" /boot/cyberbeest-words-backup/
	fi

	echo "--- installing filter, keyscript and initramfs hook ---"
	install -d "$(dirname "$KEYSCRIPT_DEST")" "$(dirname "$HOOK_DEST")"
	install -m 644 "$SRC_DIR/cyberbeest-passphrase-filter" "$FILTER_DEST"
	install -m 755 "$SRC_DIR/cyberbeest-askpass-words" "$KEYSCRIPT_DEST"
	install -m 755 "$SRC_DIR/cyberbeest-passphrase-filter.hook" "$HOOK_DEST"

	if ! grep -q "keyscript=$KEYSCRIPT" "$CRYPTTAB"; then
		cp "$CRYPTTAB" "$CRYPTTAB.bak-words-$(date +%s)"
		sed -i -E "/keyscript=/! s#^(\S+[[:space:]]+\S+[[:space:]]+\S+[[:space:]]+)(\S+)\$#\1\2,keyscript=$KEYSCRIPT#" "$CRYPTTAB"
		grep -q "keyscript=$KEYSCRIPT" "$CRYPTTAB" || { echo "Could not wire the keyscript into $CRYPTTAB" >&2; exit 1; }
	fi

	set_theme_word_mode 1
	write_state 1
else
	if grep -q "keyscript=$KEYSCRIPT" "$CRYPTTAB"; then
		cp "$CRYPTTAB" "$CRYPTTAB.bak-words-$(date +%s)"
		sed -i -E "s#,keyscript=$KEYSCRIPT##" "$CRYPTTAB"
	fi
	set_theme_word_mode 0
	write_state 0
fi

if [ -z "$R" ]; then
	echo "--- Rebuilding initramfs ---"
	plymouth-set-default-theme -R cyberbeest
fi
echo "done"
