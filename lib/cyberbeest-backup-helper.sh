#!/bin/bash
# Full-disk backup, run as root via pkexec from cyberbeest_backup_gui.py.
# Usage: cyberbeest-backup-helper.sh <parent-folder>
# stdin: line 1 = the computer's master (disk) password, which also locks the backup; the pipe then stays open for "cancel"
# (see cyberbeest-backup-common.sh for the protocol on stdout).
#
# Writes <parent>/Cyberbeest-backup-<host>-<date>/ holding
#   cyberbeest-backup.luks   LUKS2 container (argon2id, AES-256 XTS, the same
#                            as the disk) with everything inside it: the EFI
#                            and /boot partitions, the LUKS header, the LVM
#                            metadata, layout.env and root.pcl.zst, a zstd
#                            compressed partclone image of the root LV taken
#                            from an LVM snapshot. Decrypted root data never
#                            touches the backup drive unencrypted, and the
#                            LUKS header (which a thief could use to attack
#                            the disk password offline) isn't lying around in
#                            the clear either.
#   backup-info.txt          plain text: when, which machine, how big
#   README.txt               plain text: how to restore by hand
#
# Deployed root-owned to /usr/local/lib/cyberbeest/ by 73-cyberbeest-backup.sh.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/cyberbeest-backup-common.sh"

TOTAL=6
SNAP_MAX_G=10
CRYPT_NAME=cyberbeest-backup-container
SNAP_NAME=cyberbeest-backup-snap
CONTAINER_MAPPED=""
MNT=""
SNAP_DEV=""
DEST=""
FINISHED=0

cleanup() {
    stop_cancel_watch
    trap - EXIT INT TERM
    if [ -n "$MNT" ] && mountpoint -q "$MNT"; then umount "$MNT" 2>/dev/null; fi
    [ -n "$MNT" ] && rmdir "$MNT" 2>/dev/null
    [ -e "/dev/mapper/$CRYPT_NAME" ] && cryptsetup close "$CRYPT_NAME" 2>/dev/null
    if [ -n "$SNAP_DEV" ] && lvs "$SNAP_DEV" >/dev/null 2>&1; then lvremove -f "$SNAP_DEV" >/dev/null 2>&1; fi
    unmark_busy
    if [ "$FINISHED" != 1 ] && [ -n "$DEST" ] && [ -d "$DEST" ]; then
        # Keep the evidence small: the half-written container is useless.
        rm -f "$DEST/cyberbeest-backup.luks"
        mv "$DEST" "$DEST.INCOMPLETE" 2>/dev/null
        echo "backup did not finish; leftovers are in $DEST.INCOMPLETE"
    fi
    [ -d "${DEST:-}.INCOMPLETE" ] && chown -R "$CB_USER_UID" "$DEST.INCOMPLETE" 2>/dev/null
    exit "${1:-0}"
}
trap 'cleanup $?' EXIT
trap 'cleanup 143' INT TERM

[ "$EUID" -eq 0 ] || { echo "@@ERROR@@ not_root"; exit 1; }
init_user_and_log backup
PARENT="${1:-}"
read_secrets 1
PASS="${CB_PASS[0]}"
mark_busy

# ---------------------------------------------------------------- 1: checks
stage 1 $TOTAL check
for c in partclone.ext4 zstd cryptsetup lvs vgcfgbackup blkid lsblk findmnt mkfs.ext4; do
    command -v "$c" >/dev/null || die missing_tool "$c"
done
[ -d "$PARENT" ] && [ -w "$PARENT" ] || die bad_destination "$PARENT is not a writable folder"

detect_layout

# The container is locked with the master password, so a typo here would make
# a backup nobody can open: check it against the disk's own keyslot first.
printf '%s' "$PASS" | cryptsetup open --test-passphrase --key-file=- "$CB_LUKS_DEV" 2>/dev/null \
    || die bad_master_passphrase "does not unlock $CB_LUKS_DEV"

PARENT_DEV="$(source_dev_of "$PARENT")"
[ -n "$PARENT_DEV" ] && [ "$(disk_of "$PARENT_DEV")" = "$CB_DISK" ] && die same_disk "$PARENT is on $CB_DISK"
case "$(stat -f -c %T "$PARENT")" in msdos | vfat) die fat_filesystem "$PARENT" ;; esac

ROOT_USED_KB="$(df --output=used -k "${CB_ROOT_MNT:-/}" | tail -1 | tr -d ' ')"
CONTAINER_G=$(( ROOT_USED_KB / 1048576 + 6 ))
NEED_KB=$(( (CONTAINER_G + 1) * 1048576 ))
FREE_KB="$(df --output=avail -k "$PARENT" | tail -1 | tr -d ' ')"
if (( FREE_KB < NEED_KB )); then
    die no_space "need $(( NEED_KB / 1048576 ))G, have $(( FREE_KB / 1048576 ))G"
fi

# Snapshot room: as much of the VG's free space as allowed. Writes during a
# long imaging run land in the snapshot and a full one is invalid.
VG_FREE_M="$(vgs --noheadings --units m --nosuffix -o vg_free "$CB_VG" | tr -d ' ')"
SNAP_MB=${VG_FREE_M%.*}
(( SNAP_MB > SNAP_MAX_G * 1024 )) && SNAP_MB=$(( SNAP_MAX_G * 1024 ))
(( SNAP_MB >= 512 )) || die no_snapshot_space "volume group has ${SNAP_MB}M free"

[ -n "$CB_EXTRA_PARTS" ] && warn extra_partitions "$CB_EXTRA_PARTS"

DEST="$PARENT/Cyberbeest-backup-$(hostname)-$(date +%Y%m%d-%H%M%S)"
[ -e "$DEST" ] && die bad_destination "$DEST exists"
mkdir "$DEST" || die bad_destination "cannot create $DEST"

# ------------------------------------------------------------ 2: container
stage 2 $TOTAL container
CONTAINER="$DEST/cyberbeest-backup.luks"
truncate -s "${CONTAINER_G}G" "$CONTAINER" || die bad_destination "cannot size container"
printf '%s' "$PASS" | cryptsetup luksFormat --type luks2 --pbkdf argon2id --batch-mode --key-file=- "$CONTAINER" \
    || die container_failed "luksFormat"
printf '%s' "$PASS" | cryptsetup open --key-file=- "$CONTAINER" "$CRYPT_NAME" || die container_failed "open"
unset PASS CB_PASS
mkfs.ext4 -q -m 0 -L cb-backup "/dev/mapper/$CRYPT_NAME" || die container_failed "mkfs"
MNT="$(mktemp -d /run/cyberbeest-backup.XXXXXX)"
mount "/dev/mapper/$CRYPT_NAME" "$MNT" || die container_failed "mount"

# ------------------------------------------------- 3: small partitions etc.
stage 3 $TOTAL boot
sync
zstd -1 -q -c < "$CB_EFI_DEV" > "$MNT/efi.img.zst" || die backup_failed "efi"
zstd -1 -q -c < "$CB_BOOT_DEV" > "$MNT/boot.img.zst" || die backup_failed "boot"
cryptsetup luksHeaderBackup "$CB_LUKS_DEV" --header-backup-file "$MNT/luks_header.img" || die backup_failed "luks header"
vgcfgbackup -f "$MNT/vg_metadata.txt" "$CB_VG" >/dev/null || die backup_failed "lvm metadata"
cat > "$MNT/layout.env" <<EOF
FORMAT=1
CREATED=$(date -Is)
HOST=$(hostname)
SECTOR=$CB_SECTOR
DISK_BYTES=$(blockdev --getsize64 "$CB_DISK")
VG=$CB_VG
ROOT_LV=$CB_ROOT_LV
ROOT_BYTES=$CB_ROOT_BYTES
ROOT_USED_BYTES=$(( ROOT_USED_KB * 1024 ))
SWAPS=$CB_SWAPS
EFI_GEOM=$(part_geometry "$CB_EFI_DEV")
BOOT_GEOM=$(part_geometry "$CB_BOOT_DEV")
LUKS_GEOM=$(part_geometry "$CB_LUKS_DEV")
EXTRA_PARTS=$CB_EXTRA_PARTS
EOF

# --------------------------------------------------------------- 4: imaging
stage 4 $TOTAL image
SNAP_DEV="/dev/$CB_VG/$SNAP_NAME"
lvs "$SNAP_DEV" >/dev/null 2>&1 && lvremove -f "$SNAP_DEV" >/dev/null 2>&1
lvcreate --size "${SNAP_MB}M" --snapshot --name "$SNAP_NAME" "$CB_ROOT_DEV" >/dev/null \
    || die no_snapshot_space "lvcreate failed"
PCERR=/run/cyberbeest-partclone.err
RCF=/run/cyberbeest-backup.rc
: > "$PCERR"
( partclone.ext4 -c -s "$SNAP_DEV" -L /run/cyberbeest-partclone.log 2> "$PCERR" \
    | zstd -1 -T0 -q -o "$MNT/root.pcl.zst"; echo "${PIPESTATUS[*]}" > "$RCF" ) &
JOB=$!
watch_progress "$JOB" "$PCERR"
wait "$JOB"
read -r RC0 RC1 < "$RCF"
if [ "$RC0" != 0 ] || [ "$RC1" != 0 ]; then
    tr '\r' '\n' < "$PCERR" | tail -n 5
    die backup_failed "imaging exited $RC0/$RC1"
fi
SNAP_ATTR="$(lvs --noheadings -o lv_attr "$SNAP_DEV" | tr -d ' ')"
SNAP_PCT="$(lvs --noheadings -o snap_percent "$SNAP_DEV" | tr -d ' ')"
echo "snapshot attr=$SNAP_ATTR usage=${SNAP_PCT}%"
[ "${SNAP_ATTR:4:1}" = I ] && die snapshot_invalid "snapshot overflowed during imaging"
lvremove -f "$SNAP_DEV" >/dev/null && SNAP_DEV=""

# -------------------------------------------------------------- 5: verify
stage 5 $TOTAL verify
zstd -t -q "$MNT/root.pcl.zst" || die verify_failed "root image"
zstd -t -q "$MNT/efi.img.zst" && zstd -t -q "$MNT/boot.img.zst" || die verify_failed "boot images"
IMAGE_BYTES="$(stat -c %s "$MNT/root.pcl.zst")"
sync
umount "$MNT" && rmdir "$MNT" && MNT=""
cryptsetup close "$CRYPT_NAME" || die verify_failed "close"

# ------------------------------------------------------------- 6: finishing
stage 6 $TOTAL finish
cat > "$DEST/backup-info.txt" <<EOF
Cyberbeest full-disk backup
Created: $(date)
Machine: $(hostname)
Disk size: $(( $(blockdev --getsize64 "$CB_DISK") / 1000000000 )) GB
Compressed system image: $(( IMAGE_BYTES / 1000000 )) MB
Format: 1
EOF
cat > "$DEST/README.txt" <<'EOF'
This folder is a Cyberbeest full-disk backup. cyberbeest-backup.luks is
encrypted (LUKS2) with the computer's master password as it was when the
backup was made; without it nothing in here can be read.

To restore: start the computer from the Cyberbeest stick, open
"Cyberbeest Backup", choose the Restore tab and follow the steps.

By hand (needs cryptsetup, lvm2, partclone, zstd, parted):
  1. cryptsetup open cyberbeest-backup.luks cbbk ; mount /dev/mapper/cbbk /mnt
  2. layout.env lists the partitions (start, size, type in sectors), the
     volume group and the swap volumes. Create a GPT with the three partitions.
  3. zstd -dc /mnt/efi.img.zst  > /dev/<efi partition>
     zstd -dc /mnt/boot.img.zst > /dev/<boot partition>
  4. cryptsetup luksHeaderRestore /dev/<luks partition> --header-backup-file /mnt/luks_header.img
     cryptsetup open /dev/<luks partition> cbroot   (the same master password)
  5. pvcreate --uuid <pv id from vg_metadata.txt> --restorefile /mnt/vg_metadata.txt /dev/mapper/cbroot
     vgcfgrestore -f /mnt/vg_metadata.txt <VG name>; vgchange -ay <VG name>
     mkswap -U <uuid from layout.env> /dev/<VG name>/<swap name>
  6. zstd -dc /mnt/root.pcl.zst | partclone.ext4 -r -o /dev/<VG name>/<root LV>
EOF
chown -R "$CB_USER_UID" "$DEST" 2>/dev/null
sync
FINISHED=1
echo "@@DONE@@ $DEST"
