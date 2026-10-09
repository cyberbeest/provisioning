#!/bin/bash
# EXPERIMENTAL: shows a mouse pointer on the boot screen, including the LUKS
# password prompt. Works with mice, touchpads, tablets and touch screens.
#
# Plymouth has no pointer of its own, so this installs a patched build of it
# (source patch: lib/plymouth-pointer/plymouth-pointer.patch, GPL-2+). Four files
# are replaced and have to go together:
#   libply-splash-core.so.5.0.0, plymouth/renderers/drm.so,
#   plymouth/renderers/frame-buffer.so, plymouth/script.so
# They are built for exactly Plymouth 24.004.60-5 (Debian 13); the script
# refuses to run on any other version.
#
# What it changes:
#  1. The four files in /usr/lib/x86_64-linux-gnu (originals saved once in
#     /var/backups/cyberbeest/plymouth-pointer/stock together with the current
#     initrd).
#  2. /etc/initramfs-tools/modules: adds "evdev". Debian leaves that module out
#     of the initramfs, so while the password prompt is on screen the kernel has
#     no /dev/input/eventN and no pointer could ever appear. The line is only
#     added if missing, and only removed again if this script added it.
#  3. Regenerates the initrd of the RUNNING kernel only. Every other kernel's
#     initrd stays stock Plymouth, so GRUB's Advanced options always has a way
#     back. (A later kernel update regenerates its initrd from the system files,
#     so it carries the pointer too.)
#
# Typing the password is unaffected: keyboards still reach Plymouth through the
# console, the pointer only reads mouse-like devices.
#
# Also in this build: Ctrl+F at the password prompt no longer lands in the
# password field (the key still reaches the theme script, for Boot Fresh).
#
# If something looks wrong at boot: at the GRUB menu press 'e' and add
#   plymouth.disable-pointer
# to the line starting with 'linux' (turns the pointer off for that boot), or
# pick an older kernel under Advanced options.
#
# An 'apt upgrade' of plymouth or libplymouth5 puts the stock files back; run
# this script again afterwards (it is idempotent).
#
# Usage: sudo bash enable-plymouth-pointer.sh
# Undo:  sudo bash disable-plymouth-pointer.sh
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-plymouth-pointer.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Plymouth mouse pointer (experimental) ==="

abort() {
	echo "ABORT: $*" >&2
	exit 1
}

[ "$(id -u)" -eq 0 ] || abort "must run as root (sudo bash $0)"

SRC="$DIR/lib/plymouth-pointer"
LIB=/usr/lib/x86_64-linux-gnu
FILES=(
	libply-splash-core.so.5.0.0
	plymouth/renderers/drm.so
	plymouth/renderers/frame-buffer.so
	plymouth/script.so
)
EXPECTED_VERSION="24.004.60-5"
BACKUP_DIR=/var/backups/cyberbeest/plymouth-pointer
STOCK="$BACKUP_DIR/stock"
EVDEV_MARK="$BACKUP_DIR/added-evdev"
MODFILE=/etc/initramfs-tools/modules
KVER="$(uname -r)"

is_fork() { grep -aq ply_pointer_new "$1" 2>/dev/null; }

restore_and_exit() {
	echo "$1 Restoring stock Plymouth."
	bash "$DIR/disable-plymouth-pointer.sh"
	exit 1
}

# 1. Only the exact Plymouth these files were built against
ver="$(dpkg-query -W -f='${Version}' plymouth 2>/dev/null)"
[ "$ver" = "$EXPECTED_VERSION" ] || abort "plymouth is '$ver', these files are for $EXPECTED_VERSION"
[ "$(uname -m)" = x86_64 ] || abort "built for x86_64"
[ -d "$SRC/files" ] || abort "missing $SRC/files"
(cd "$SRC/files" && sha256sum -c --quiet ../SHA256SUMS) || abort "checksum mismatch, the package is damaged"
[ -f "/boot/initrd.img-$KVER" ] || abort "no /boot/initrd.img-$KVER for the running kernel"

# 2. Room for the backup and for a new initrd
need_kb=$(($(stat -c %s "/boot/initrd.img-$KVER") / 1024 * 2 + 20480))
mkdir -p "$BACKUP_DIR" || abort "cannot create $BACKUP_DIR"
for d in /boot "$BACKUP_DIR"; do
	avail_kb=$(df -Pk "$d" | awk 'NR==2{print $4}')
	[ "$avail_kb" -gt "$need_kb" ] || abort "not enough space in $d ($avail_kb KB free, need $need_kb KB)"
done

# 3. Keep the stock files and initrd as the reference to go back to. Taken only while
#    stock Plymouth is installed; a backup made earlier is never overwritten.
if ! is_fork "$LIB/libply-splash-core.so.5.0.0"; then
	rm -rf "$STOCK"
	mkdir -p "$STOCK/files" || abort "cannot create $STOCK"
	for f in "${FILES[@]}"; do
		mkdir -p "$STOCK/files/$(dirname "$f")"
		cp -a "$LIB/$f" "$STOCK/files/$f" || abort "cannot back up $f"
	done
	cp -a "/boot/initrd.img-$KVER" "$STOCK/initrd.img-$KVER" || abort "cannot back up the initrd"
	echo "$KVER" >"$STOCK/kernel"
	echo "$ver" >"$STOCK/version"
	echo "Stock Plymouth saved in $STOCK"
elif [ -f "$STOCK/files/libply-splash-core.so.5.0.0" ]; then
	echo "The pointer build is already installed; keeping the stock backup in $STOCK"
elif [ -f /var/backups/plymouth-pointer-stock/files/libply-splash-core.so.5.0.0 ] &&
	! is_fork /var/backups/plymouth-pointer-stock/files/libply-splash-core.so.5.0.0; then
	# Left by the test installer used before this script existed
	mkdir -p "$STOCK" && cp -aL /var/backups/plymouth-pointer-stock/. "$STOCK/" || abort "cannot adopt the earlier backup"
	[ -f "$STOCK/version" ] || echo "$ver" >"$STOCK/version"
	echo "Adopted the stock backup from the earlier test installer"
else
	abort "the pointer build is installed but there is no stock backup (apt-get install --reinstall plymouth libplymouth5 restores stock)"
fi

# 4. evdev in the initramfs (see the header)
if [ -f /var/backups/plymouth-pointer-added-evdev ]; then
	touch "$EVDEV_MARK" && rm -f /var/backups/plymouth-pointer-added-evdev
fi
if grep -q -E '^[[:space:]]*evdev([[:space:]]|$)' "$MODFILE" 2>/dev/null; then
	echo "evdev is already listed in $MODFILE"
else
	{
		echo "# added by the Cyberbeest Plymouth pointer install (mouse input at the password prompt)"
		echo "evdev"
	} >>"$MODFILE"
	touch "$EVDEV_MARK"
	echo "added evdev to $MODFILE"
fi

# 5. Install: copy next to the target, then rename, so nothing sees half a file
for f in "${FILES[@]}"; do
	mode="$(stat -c %a "$LIB/$f")"
	install -o root -g root -m "$mode" "$SRC/files/$f" "$LIB/$f.new" || restore_and_exit "Installing $f failed."
	mv -f "$LIB/$f.new" "$LIB/$f"
	echo "installed $f"
done
ldconfig

# 6. Regenerate the initramfs of the running kernel only
echo "Regenerating /boot/initrd.img-$KVER ..."
update-initramfs -u -k "$KVER" || restore_and_exit "update-initramfs failed."

# 7. Check that the new initrd really carries the pointer build
TMP="$(mktemp -d)"
unmkinitramfs "/boot/initrd.img-$KVER" "$TMP" 2>/dev/null
MAIN="$(find "$TMP" -path '*usr/lib/x86_64-linux-gnu/libply-splash-core.so.5.0.0' | head -1)"
ok=1
if [ -z "$MAIN" ]; then
	echo "CHECK FAILED: libply-splash-core not found in the new initrd"
	ok=0
else
	ROOT="${MAIN%usr/lib/x86_64-linux-gnu/libply-splash-core.so.5.0.0}"
	grep -aq ply_pointer_new "$MAIN" || { echo "CHECK FAILED: core library in the initrd is not the pointer build"; ok=0; }
	grep -aq "only pointer devices are taken" "$MAIN" || { echo "CHECK FAILED: core library in the initrd is an older pointer build"; ok=0; }
	grep -aq plymouth.disable-pointer "$ROOT/usr/lib/x86_64-linux-gnu/plymouth/renderers/drm.so" || { echo "CHECK FAILED: drm.so in the initrd is not the pointer build"; ok=0; }
	grep -aq SetPointerMotionFunction "$ROOT/usr/lib/x86_64-linux-gnu/plymouth/script.so" || { echo "CHECK FAILED: script.so in the initrd is not the pointer build"; ok=0; }

	# Not fatal (the boot works without it) but the pointer cannot appear at the prompt
	find "$TMP" -name 'evdev.ko*' | grep -q . || echo "WARNING: evdev.ko is not in the new initrd, no pointer at the password prompt"
	grep -q -E '^evdev' "$ROOT/conf/modules" 2>/dev/null || echo "WARNING: evdev is not in the initrd's early module list"
fi
rm -rf "$TMP"
[ "$ok" = 1 ] || restore_and_exit "The new initrd is not what was expected."

cat <<EOF

DONE. The initrd for $KVER now carries the Plymouth mouse pointer. Reboot to try it:
move the mouse or touchpad at the password screen and an arrow appears.

  - Wrong at boot? GRUB menu, 'e', add  plymouth.disable-pointer  to the 'linux' line,
    or pick an older kernel under Advanced options.
  - Undo: sudo bash $DIR/disable-plymouth-pointer.sh
  - Run this script again after an 'apt upgrade' of plymouth or libplymouth5.
Log: $LOG
EOF
