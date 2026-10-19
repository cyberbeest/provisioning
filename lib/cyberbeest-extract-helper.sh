#!/bin/bash
# Opens a Cyberbeest backup read-only so single files and folders can be copied
# out. Run as root via pkexec from cyberbeest_backup_gui.py ("Find files" tab).
# Usage: cyberbeest-extract-helper.sh <backup-folder> <scratch-folder>
# stdin: line 1 = the master password the computer had when the backup was made;
# the pipe then stays open: "cancel" aborts the unpacking, and once
# "@@READY@@ <mountpoint>" has been printed a "close" line (or the GUI dying)
# unmounts everything and deletes the scratch file.
#
# The backup's root image is a partclone stream, which can't be read in place.
# So it is unpacked into a sparse scratch file (about the size of the used data
# on disk) and loop-mounted read-only. Cost: restore-like time and scratch space.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/cyberbeest-backup-common.sh"

TOTAL=3
BK_NAME=cyberbeest-extract-backup
VIEW=/mnt/cyberbeest-backup-view
BK_MNT=""
SCRATCH=""
FINISHED=0

cleanup() {
    stop_cancel_watch
    trap - EXIT INT TERM
    mountpoint -q "$VIEW" && umount "$VIEW" 2>/dev/null
    rmdir "$VIEW" 2>/dev/null
    [ -n "$SCRATCH" ] && rm -f "$SCRATCH"
    [ -n "$BK_MNT" ] && mountpoint -q "$BK_MNT" && umount "$BK_MNT" 2>/dev/null
    [ -n "$BK_MNT" ] && rmdir "$BK_MNT" 2>/dev/null
    [ -e "/dev/mapper/$BK_NAME" ] && cryptsetup close "$BK_NAME" 2>/dev/null
    unmark_busy
    exit "${1:-0}"
}
trap 'cleanup $?' EXIT
trap 'cleanup 143' INT TERM

[ "$EUID" -eq 0 ] || { echo "@@ERROR@@ not_root"; exit 1; }
init_user_and_log extract
BACKUP="${1:-}"
SCRATCH_DIR="${2:-}"
read_secrets 1
PASS="${CB_PASS[0]}"
mark_busy

getv() { sed -n "s/^$1=//p" "$BK_MNT/layout.env" | head -1; }

stage 1 $TOTAL check
for c in partclone.ext4 zstd cryptsetup e2fsck mount; do
    command -v "$c" >/dev/null || die missing_tool "$c"
done
[ -f "$BACKUP/cyberbeest-backup.luks" ] || die bad_backup "no cyberbeest-backup.luks in $BACKUP"
[ -d "$SCRATCH_DIR" ] && [ -w "$SCRATCH_DIR" ] || die bad_destination "$SCRATCH_DIR is not a writable folder"
case "$(stat -f -c %T "$SCRATCH_DIR")" in msdos | vfat) die fat_filesystem "$SCRATCH_DIR" ;; esac
mountpoint -q "$VIEW" && die view_busy "$VIEW is already in use"

printf '%s' "$PASS" | cryptsetup open --key-file=- "$BACKUP/cyberbeest-backup.luks" "$BK_NAME" 2>/dev/null \
    || die bad_master_passphrase "cannot unlock the backup container"
unset PASS CB_PASS
BK_MNT="$(mktemp -d /run/cyberbeest-extract.XXXXXX)"
mount -o ro "/dev/mapper/$BK_NAME" "$BK_MNT" || die bad_backup "cannot mount the backup container"
[ "$(getv FORMAT)" = 1 ] && [ -s "$BK_MNT/root.pcl.zst" ] || die bad_backup "unknown or incomplete backup"

ROOT_BYTES="$(getv ROOT_BYTES)"
USED="$(getv ROOT_USED_BYTES)"
[ -n "$USED" ] || USED=$(( $(stat -c %s "$BK_MNT/root.pcl.zst") * 3 ))
NEED=$(( USED + 2 * 1073741824 ))
FREE=$(( $(df --output=avail -k "$SCRATCH_DIR" | tail -1 | tr -d ' ') * 1024 ))
(( FREE >= NEED )) || die no_space "need $(( NEED / 1000000000 )) GB, have $(( FREE / 1000000000 )) GB"
[ -n "$ROOT_BYTES" ] || die bad_backup "no root size in the backup"

stage 2 $TOTAL unpack
SCRATCH="$SCRATCH_DIR/cyberbeest-backup-scratch.img"
rm -f "$SCRATCH"
truncate -s "$ROOT_BYTES" "$SCRATCH" || die bad_destination "cannot create the scratch file"
PCERR=/run/cyberbeest-partclone.err
RCF=/run/cyberbeest-extract.rc
: > "$PCERR"
( zstd -dc "$BK_MNT/root.pcl.zst" \
    | partclone.ext4 -r -s - -O "$SCRATCH" -L /run/cyberbeest-partclone.log 2> "$PCERR"
  echo "${PIPESTATUS[*]}" > "$RCF" ) &
JOB=$!
watch_progress "$JOB" "$PCERR"
wait "$JOB"
read -r RC0 RC1 < "$RCF"
if [ "$RC0" != 0 ] || [ "$RC1" != 0 ]; then
    tr '\r' '\n' < "$PCERR" | tail -n 5
    die extract_failed "unpacking exited $RC0/$RC1"
fi
unmark_busy

stage 3 $TOTAL mount
# The image was taken from a live snapshot, so its journal needs replaying.
# That is fine here: it is a private scratch copy.
e2fsck -f -p "$SCRATCH" >/dev/null 2>&1
(( $? <= 1 )) || die extract_failed "the unpacked filesystem is damaged"
umount "$BK_MNT" && rmdir "$BK_MNT" && BK_MNT=""
cryptsetup close "$BK_NAME"
mkdir -p "$VIEW"
mount -o ro,loop,nosuid,nodev,noexec "$SCRATCH" "$VIEW" || die extract_failed "cannot mount the unpacked image"

echo "@@READY@@ $VIEW"
stop_cancel_watch
while IFS= read -r l <&3; do
    [ "$l" = close ] && break
done
FINISHED=1
