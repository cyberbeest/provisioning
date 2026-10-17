#!/bin/bash
# Installs "word passphrase" entry at the LUKS unlock prompt:
#  * lib/cyberbeest-askpass-words (crypttab keyscript) normalizes what is
#    typed: lower case, umlauts -> ae/oe/ue/ss, every run of separators ->
#    one "-", leading/trailing "-" dropped;
#  * the Plymouth theme (word_mode=1) shows one pill per completed word and
#    bullets only for the word being typed.
#
# REQUIREMENT: the LUKS passphrase in key slot 0 must already be in
# canonical form (lower-case words joined by "-"), otherwise the disk will
# no longer unlock. disk_password_gui.py generates and stores that form.
# Check before rebooting:  echo -n 'the-words-here' | sudo cryptsetup open --test-passphrase <device>
#
# crypttab has room for ONE keyscript. With Boot Fresh installed, its wrapper
# (cyberbeest-askpass-boot-fresh) stays the keyscript and applies the shared
# filter (lib/cyberbeest-passphrase-filter) itself; this script then only
# installs the filter + its initramfs hook. enable-boot-fresh.sh does the
# reverse switch when run on a machine that already has this feature. Any other
# keyscript makes this script refuse to run.
#
# Verified 2026-10-09 in a Debian 13 UEFI LUKS test VM (tower, pwtest):
# "TIGER  Lamp..OCEAN " unlocked a disk whose passphrase is
# tiger-lamp-ocean. Not yet tried on real hardware.
#
# Usage: sudo bash enable-passphrase-words.sh
# Idempotent. Undo: restore /etc/crypttab.bak-words-*, rerun this script's
# theme step with WORD_MODE=0, update-initramfs -u -k all.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-passphrase-words.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing word passphrase entry ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

KEYSCRIPT=/lib/cryptsetup/cyberbeest-askpass-words
BOOT_FRESH_KEYSCRIPT=/lib/cryptsetup/cyberbeest-askpass-boot-fresh

if grep -q keyscript= /etc/crypttab \
   && ! grep -q "keyscript=$KEYSCRIPT" /etc/crypttab \
   && ! grep -q "keyscript=$BOOT_FRESH_KEYSCRIPT" /etc/crypttab; then
	echo "ABORT: /etc/crypttab already uses a different keyscript:" >&2
	grep keyscript= /etc/crypttab >&2
	exit 1
fi

echo "--- optional pre-flight: is the current passphrase already canonical? ---"
if [ -t 0 ] && [ -z "${PWWORDS_SKIP_CHECK:-}" ]; then
	LUKS_UUID="$(awk '!/^#/ && NF {print $2; exit}' /etc/crypttab | sed 's/^UUID=//')"
	read -rsp "Type the current master passphrase to check it (Enter to skip): " PW; echo
	if [ -n "$PW" ]; then
		STUB="$(mktemp)"; printf '#!/bin/sh\nprintf %%s "$PW"\n' > "$STUB"; chmod 700 "$STUB"
		NORM="$(PW="$PW" CYBERBEEST_ASKPASS="$STUB" CYBERBEEST_FILTER="$DIR/../lib/cyberbeest-passphrase-filter" sh "$DIR/../lib/cyberbeest-askpass-words" x)"; rm -f "$STUB"
		if [ "$NORM" != "$PW" ]; then
			echo "ABORT: that passphrase is not in canonical form (it would become '$NORM'); the disk would stop unlocking. Change it with disk_password_gui.py first." >&2
			exit 1
		fi
		if printf '%s' "$PW" | cryptsetup open --test-passphrase "/dev/disk/by-uuid/$LUKS_UUID" -; then
			echo "OK: passphrase is canonical and unlocks the disk."
		else
			echo "ABORT: that passphrase does not unlock the disk." >&2
			exit 1
		fi
	fi
	unset PW
fi

echo "--- backing up the running kernel's initrd to /boot/cyberbeest-words-backup ---"
install -d /boot/cyberbeest-words-backup
cp -n "/boot/initrd.img-$(uname -r)" /boot/cyberbeest-words-backup/

echo "--- installing the shared passphrase filter + its initramfs hook ---"
install -d /lib/cryptsetup
install -m 644 "$DIR/../lib/cyberbeest-passphrase-filter" /lib/cryptsetup/cyberbeest-passphrase-filter
install -d /etc/initramfs-tools/hooks
install -m 755 "$DIR/../lib/cyberbeest-passphrase-filter.hook" /etc/initramfs-tools/hooks/cyberbeest-passphrase-filter

if grep -q "keyscript=$BOOT_FRESH_KEYSCRIPT" /etc/crypttab; then
	echo "--- Boot Fresh keyscript already in /etc/crypttab: refreshing it (it applies the filter), leaving crypttab alone ---"
	install -m 755 "$DIR/lib/cyberbeest-askpass-boot-fresh" "$BOOT_FRESH_KEYSCRIPT"
else
	echo "--- installing keyscript ---"
	install -m 755 "$DIR/../lib/cyberbeest-askpass-words" "$KEYSCRIPT"

	echo "--- wiring the keyscript into /etc/crypttab ---"
	if grep -q "keyscript=$KEYSCRIPT" /etc/crypttab; then
		echo "already wired, skipping"
	else
		cp /etc/crypttab "/etc/crypttab.bak-words-$(date +%s)"
		sed -i -E "/keyscript=/! s#^(\S+[[:space:]]+\S+[[:space:]]+\S+[[:space:]]+)(\S+)\$#\1\2,keyscript=$KEYSCRIPT#" /etc/crypttab
		cat /etc/crypttab
	fi
fi

# Read by every script that (re)generates the theme from its template, so
# word mode survives them. The initramfs only reads the finished theme.
install -d -m 755 /etc/cyberbeest
printf '%s' "${WORD_MODE:-1}" > /etc/cyberbeest/word-passphrase-mode
chmod 644 /etc/cyberbeest/word-passphrase-mode

echo "--- rebuilding the Plymouth theme (preserving machine name / bright mode) ---"
THEME_SRC="$DIR/../lib/plymouth-theme"
THEME_DIR=/usr/share/plymouth/themes/cyberbeest
if [ ! -f "$THEME_DIR/cyberbeest.script" ]; then
	echo "ABORT: $THEME_DIR/cyberbeest.script not found -- run 15-grub-plymouth-theme.sh first." >&2
	exit 1
fi
. "$DIR/../lib/i18n.sh"
MACHINE_NAME="$(cat /etc/cyberbeest/machine-name 2>/dev/null || true)"
BRIGHT_MODE="$(cat /etc/cyberbeest/plymouth-bright-mode 2>/dev/null || echo 1)"
sed_escape() {
	local s="$1"
	s="${s//\\/\\\\}"
	s="${s//|/\\|}"
	printf '%s' "$s"
}
sed -e "s|__LUKS_PROMPT__|$(sed_escape "$(t plymouth.luks_prompt)")|" \
    -e "s|__LUKS_SUCCESS__|$(sed_escape "$(t plymouth.luks_success)")|" \
    -e "s|__SHUTDOWN_TEXT__|$(sed_escape "$(t plymouth.shutdown_text)")|" \
    -e "s|__MACHINE_NAME__|$(sed_escape "$MACHINE_NAME")|" \
    -e "s|__BRIGHT_MODE__|$(sed_escape "$BRIGHT_MODE")|" \
    -e "s|__WORD_MODE__|${WORD_MODE:-1}|" \
    "$THEME_SRC/cyberbeest.script" > "$THEME_DIR/cyberbeest.script"
chmod 644 "$THEME_DIR/cyberbeest.script"
# -R rebuilds the initramfs (covers the crypttab/keyscript change too).
plymouth-set-default-theme -R cyberbeest

echo "=== $(date) : done. Reboot required. ==="
