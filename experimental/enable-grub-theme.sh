#!/bin/bash
# Installs the Cyberbeest GRUB menu theme: dark background with the hornet,
# Lato labels, friendly entry names, no recovery/firmware entries, and a
# hook that blanks the screen before the kernel starts (see
# lib/45_cyberbeest_blank for why that is needed).
#
# The menu is shown at every boot for a few seconds (default 3, with a live
# countdown) and then boots the first entry by itself. A hidden menu opened by
# a key does not work on this hardware: the firmware claims Esc at power-on
# and Shift is not seen on UEFI. Pass --timeout N to change the delay.
#
# What it changes:
#  1. /boot/grub/themes/cyberbeest (lib/grub-theme/), footer text from the
#     grub.menu_hint i18n key, resolved now like the Plymouth strings (GRUB
#     reads it before any filesystem with /etc/default/locale is available).
#  2. /etc/default/grub: GRUB_THEME, GRUB_DISTRIBUTOR=Cyberbeest (entries read
#     "Cyberbeest GNU/Linux"), GRUB_DISABLE_RECOVERY=true, GRUB_TIMEOUT_STYLE=menu
#     + GRUB_TIMEOUT=3 (or --timeout N). Originals are saved once
#     in /var/backups/cyberbeest/default-grub.pre-grub-theme for the disable
#     script. GRUB_GFXMODE is left alone.
#  3. /etc/grub.d/45_cyberbeest_blank (lib/).
#  4. /etc/grub.d/30_uefi-firmware made non-executable, so the "UEFI Firmware
#     Settings" entry disappears.
#  5. Moves a stray /etc/grub.d/10_linux.pre-cyberbeest out of grub.d: GRUB
#     runs every executable file there, so it duplicated every entry.
#
# Usage: sudo bash enable-grub-theme.sh [--timeout SECONDS]
# Undo:  sudo bash disable-grub-theme.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-grub-theme.log"
exec > >(tee -a "$LOG") 2>&1

TIMEOUT=3
if [ "${1:-}" = "--timeout" ]; then
	TIMEOUT="${2:-}"
	case "$TIMEOUT" in
	'' | *[!0-9]*)
		echo "--timeout needs a whole number of seconds." >&2
		exit 1
		;;
	esac
fi

echo "=== $(date) : installing GRUB theme (menu timeout ${TIMEOUT}s) ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

. "$DIR/../lib/i18n.sh"

GRUB_FILE=/etc/default/grub
BACKUP_DIR=/var/backups/cyberbeest
GRUB_BACKUP="$BACKUP_DIR/default-grub.pre-grub-theme"
THEME_DEST=/boot/grub/themes/cyberbeest
UEFI_SCRIPT=/etc/grub.d/30_uefi-firmware

install -d -m 755 "$BACKUP_DIR"
[ -e "$GRUB_BACKUP" ] || cp -p "$GRUB_FILE" "$GRUB_BACKUP"

echo "--- moving any stray 10_linux backup out of /etc/grub.d ---"
if [ -e /etc/grub.d/10_linux.pre-cyberbeest ]; then
	[ -e "$BACKUP_DIR/10_linux.pre-cyberbeest" ] || cp -p /etc/grub.d/10_linux.pre-cyberbeest "$BACKUP_DIR/"
	rm -f /etc/grub.d/10_linux.pre-cyberbeest
	echo "moved (it duplicated every boot entry)"
fi

echo "--- installing the theme ---"
rm -rf "$THEME_DEST"
install -d -m 755 "$THEME_DEST"
install -m 644 "$DIR/lib/grub-theme/background.png" "$DIR/lib/grub-theme/"*.pf2 "$THEME_DEST/"
sed -e "s|__MENU_HINT__|$(t grub.menu_hint)|" -e "s|__COUNTDOWN__|$(t grub.countdown)|" \
	"$DIR/lib/grub-theme/theme.txt" > "$THEME_DEST/theme.txt"
chmod 644 "$THEME_DEST/theme.txt"

set_grub_var() {
	# set_grub_var KEY VALUE -- replaces an existing KEY=... line (commented
	# or not) or appends a new one.
	local key="$1" value="$2"
	if grep -qE "^${key}=" "$GRUB_FILE"; then
		sed -i "s|^${key}=.*|${key}=${value}|" "$GRUB_FILE"
	elif grep -qE "^#${key}=" "$GRUB_FILE"; then
		sed -i "s|^#${key}=.*|${key}=${value}|" "$GRUB_FILE"
	else
		echo "${key}=${value}" >> "$GRUB_FILE"
	fi
}

echo "--- configuring $GRUB_FILE ---"
set_grub_var GRUB_THEME '"/boot/grub/themes/cyberbeest/theme.txt"'
set_grub_var GRUB_DISTRIBUTOR Cyberbeest
set_grub_var GRUB_DISABLE_RECOVERY '"true"'
sed -i '/^GRUB_GFXPAYLOAD_LINUX=/d' "$GRUB_FILE"
set_grub_var GRUB_TIMEOUT_STYLE menu
set_grub_var GRUB_TIMEOUT "$TIMEOUT"

echo "--- installing the blank-screen hook ---"
install -m 755 "$DIR/lib/45_cyberbeest_blank" /etc/grub.d/45_cyberbeest_blank

echo "--- hiding the UEFI Firmware Settings entry ---"
if [ -x "$UEFI_SCRIPT" ]; then
	chmod -x "$UEFI_SCRIPT"
	touch "$BACKUP_DIR/uefi-entry-hidden"
	echo "made $UEFI_SCRIPT non-executable"
else
	echo "$UEFI_SCRIPT absent or already non-executable."
fi

echo "--- backing up grub.cfg, then regenerating it ---"
[ -e /boot/grub/grub.cfg ] && cp -p /boot/grub/grub.cfg /boot/grub/grub.cfg.bak
update-grub

echo "--- verifying ---"
if ! grep -q 'function load_video' /boot/grub/grub.cfg || ! grep -q 'gfxterm_font="Lato Regular 16"' /boot/grub/grub.cfg; then
	echo "WARNING: blank-screen hook not found in grub.cfg; the menu will show a leftover picture while the kernel loads." >&2
fi
grep -E '^(menuentry|submenu)' /boot/grub/grub.cfg | cut -c1-100
echo "=== done. Reboot to see the menu. ==="
