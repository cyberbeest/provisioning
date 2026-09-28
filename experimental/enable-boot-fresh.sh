#!/bin/bash
# Installs "Boot Fresh": a Ctrl+F option at the LUKS unlock prompt to skip
# resuming a pending hibernation image and continue a normal boot instead.
# Depends on: enable-hibernation.sh already run (this is only useful once
# hibernation itself works) and enable-hibernate-splash.sh's theme install
# path having been used at least once (this reuses the same substituted
# theme location).
#
# Five pieces, tied together here:
#  1. cyberbeest-boot-fresh-marker.hook (systemd-sleep): marks whether a
#     hibernation image is pending, on /boot -- the one filesystem
#     readable before LUKS unlock.
#  2. cyberbeest-askpass-boot-fresh (crypttab keyscript): tells the theme
#     about that marker before showing the prompt, and afterward detects
#     Ctrl+F (embedded as a raw 0x06 byte in the typed password -- see
#     that script's own comments for why) and records the choice.
#  3. resume-boot-fresh (local-premount override): honors that choice by
#     skipping the actual resume call.
#  4. cyberbeest.script changes: the visible button + its keyboard toggle
#     (purely cosmetic -- the functional effect is entirely pieces 2+3).
#  5. /etc/crypttab: wires piece 2 in via the standard keyscript= option.
#
# This touches the boot-critical LUKS/cryptsetup/resume path. Test via
# plymouthd --tty=/dev/ttyN --mode=boot on a spare VT (see the
# conversation this shipped from) before trusting it on a real reboot --
# not something to iterate on live the way hibernation itself was.
#
# Usage: sudo bash enable-boot-fresh.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-boot-fresh.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Boot Fresh ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

echo "--- installing systemd-sleep marker hook ---"
install -m 755 "$DIR/lib/cyberbeest-boot-fresh-marker.hook" /usr/lib/systemd/system-sleep/cyberbeest-boot-fresh-marker

echo "--- installing crypttab keyscript wrapper ---"
install -d /lib/cryptsetup
install -m 755 "$DIR/lib/cyberbeest-askpass-boot-fresh" /lib/cryptsetup/cyberbeest-askpass-boot-fresh

echo "--- installing local-premount resume override ---"
install -d /etc/initramfs-tools/scripts/local-premount
install -m 755 "$DIR/lib/resume-boot-fresh" /etc/initramfs-tools/scripts/local-premount/resume

echo "--- wiring the keyscript into /etc/crypttab ---"
KEYSCRIPT=/lib/cryptsetup/cyberbeest-askpass-boot-fresh
if grep -q "keyscript=$KEYSCRIPT" /etc/crypttab; then
	echo "already wired, skipping"
else
	cp /etc/crypttab "/etc/crypttab.bak-$(date +%s)"
	# Appends to the 4th (options) field of every crypttab line that
	# doesn't already have a keyscript= option. This product ships with
	# exactly one LUKS entry (the root+swap volume group), so in
	# practice this touches a single line -- but is written to handle
	# more without assuming it.
	sed -i -E "/keyscript=/! s#^(\S+[[:space:]]+\S+[[:space:]]+\S+[[:space:]]+)(\S+)\$#\1\2,keyscript=$KEYSCRIPT#" /etc/crypttab
	cat /etc/crypttab
fi

echo "--- rebuilding the Plymouth theme (preserving current machine name / bright mode) ---"
THEME_SRC="$DIR/../lib/plymouth-theme"
THEME_DIR=/usr/share/plymouth/themes/cyberbeest
if [ ! -f "$THEME_DIR/cyberbeest.script" ]; then
	echo "ABORT: $THEME_DIR/cyberbeest.script not found -- theme isn't installed here (run 15-grub-plymouth-theme.sh first)." >&2
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
    "$THEME_SRC/cyberbeest.script" > "$THEME_DIR/cyberbeest.script"
chmod 644 "$THEME_DIR/cyberbeest.script"
# -R (--rebuild-initrd) already calls plymouth-update-initrd internally
# (confirmed by reading /usr/sbin/plymouth-set-default-theme), which does
# a full update-initramfs -- covers the crypttab/resume-override/askpass
# changes above too, not just the theme. A separate explicit
# update-initramfs call here was regenerating the initramfs twice per
# kernel for no reason.
plymouth-set-default-theme -R cyberbeest

echo "=== $(date) : done. Reboot required. Verify on a spare VT with plymouthd --tty first -- see header. ==="
