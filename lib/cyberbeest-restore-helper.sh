#!/bin/bash
# Full-disk restore of a backup made by cyberbeest-backup-helper.sh. Run as
# root via pkexec from cyberbeest_backup_gui.py -- normally from the Cyberbeest
# live stick, because the volume group inside the backup has the same name as
# the one on an installed Cyberbeest system and two can't be active at once.
# Usage: cyberbeest-restore-helper.sh <backup-folder> <target-disk>
# stdin: line 1 = the master password the computer had when the backup was made
# (it locks the backup container and the restored disk alike); then the pipe stays open for
# "cancel" (see cyberbeest-backup-common.sh for the protocol on stdout).
#
# ERASES <target-disk> completely. Everything is verified before the first
# byte is written: both passwords, layout, sizes, that the disk isn't in use.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/cyberbeest-backup-common.sh"

TOTAL=6
BK_NAME=cyberbeest-restore-backup
CRYPT_NAME=cyberbeest-restore-crypt
BK_MNT=""
ESP_MNT=""
VG=""
WIPED=0
FINISHED=0

cleanup() {
    stop_cancel_watch
    trap - EXIT INT TERM
    [ -n "$ESP_MNT" ] && mountpoint -q "$ESP_MNT" && umount "$ESP_MNT" 2>/dev/null
    [ -n "$ESP_MNT" ] && rmdir "$ESP_MNT" 2>/dev/null
    [ -n "$VG" ] && [ -e "/dev/mapper/$CRYPT_NAME" ] && vgchange -an "$VG" >/dev/null 2>&1
    [ -e "/dev/mapper/$CRYPT_NAME" ] && cryptsetup close "$CRYPT_NAME" 2>/dev/null
    [ -n "$BK_MNT" ] && mountpoint -q "$BK_MNT" && umount "$BK_MNT" 2>/dev/null
    [ -n "$BK_MNT" ] && rmdir "$BK_MNT" 2>/dev/null
    [ -e "/dev/mapper/$BK_NAME" ] && cryptsetup close "$BK_NAME" 2>/dev/null
    unmark_busy
    if [ "$FINISHED" != 1 ] && [ "$WIPED" = 1 ]; then
        echo "@@WARN@@ disk_incomplete the target disk was already changed and is not a working system"
    fi
    exit "${1:-0}"
}
trap 'cleanup $?' EXIT
trap 'cleanup 143' INT TERM

[ "$EUID" -eq 0 ] || { echo "@@ERROR@@ not_root"; exit 1; }
init_user_and_log restore
BACKUP="${1:-}"
TARGET="${2:-}"
read_secrets 1
BK_PASS="${CB_PASS[0]}"
DISK_PASS="$BK_PASS"
mark_busy

getv() { sed -n "s/^$1=//p" "$BK_MNT/layout.env" | head -1; }

# ---------------------------------------------------------------- 1: checks
stage 1 $TOTAL check
for c in partclone.ext4 zstd cryptsetup lvm pvcreate vgcfgrestore sfdisk wipefs mkswap e2fsck resize2fs blkid lsblk; do
    command -v "$c" >/dev/null || die missing_tool "$c"
done

[ -f "$BACKUP/cyberbeest-backup.luks" ] || die bad_backup "no cyberbeest-backup.luks in $BACKUP"
[ -b "$TARGET" ] || die bad_target "$TARGET is not a block device"
case "$(lsblk -dno TYPE "$TARGET")" in disk | loop) ;; *) die bad_target "$TARGET is not a whole disk" ;; esac

# Never touch a disk that is in use, holds the running system, or holds the
# backup being restored.
if lsblk -nro MOUNTPOINTS "$TARGET" | grep -q . || [ "$(lsblk -nro TYPE "$TARGET" | grep -cv -e '^disk$' -e '^loop$' -e '^part$')" != 0 ]; then
    die target_busy "$TARGET or one of its partitions is mounted or open"
fi
BK_DEV="$(source_dev_of "$BACKUP")"
[ -n "$BK_DEV" ] && [ "$(disk_of "$BK_DEV")" = "$TARGET" ] && die backup_on_target "the backup is on $TARGET"
RUN_DEV="$(source_dev_of /)"
[ -n "$RUN_DEV" ] && [ "$(disk_of "$RUN_DEV")" = "$TARGET" ] && die target_busy "$TARGET holds the running system"

BK_PASS_LEN=${#BK_PASS}
[ "$BK_PASS_LEN" -gt 0 ] || die bad_master_passphrase "empty"
printf '%s' "$BK_PASS" | cryptsetup open --key-file=- "$BACKUP/cyberbeest-backup.luks" "$BK_NAME" 2>/dev/null \
    || die bad_master_passphrase "cannot unlock the backup container"
BK_MNT="$(mktemp -d /run/cyberbeest-restore.XXXXXX)"
mount -o ro "/dev/mapper/$BK_NAME" "$BK_MNT" || die bad_backup "cannot mount the backup container"
[ "$(getv FORMAT)" = 1 ] || die bad_backup "unknown backup format '$(getv FORMAT)'"
for f in efi.img.zst boot.img.zst luks_header.img vg_metadata.txt root.pcl.zst layout.env; do
    [ -s "$BK_MNT/$f" ] || die bad_backup "$f missing in the backup"
done

# The same password must open the restored LUKS partition; it was just
# accepted by the container, but the header copy is checked before the wipe too.
printf '%s' "$DISK_PASS" | cryptsetup open --test-passphrase --key-file=- "$BK_MNT/luks_header.img" 2>/dev/null \
    || die bad_master_passphrase "does not open the backed-up LUKS header"

SECTOR=$(getv SECTOR)
[ "$(blockdev --getss "$TARGET")" = "$SECTOR" ] || die wrong_sector "target has $(blockdev --getss "$TARGET")-byte sectors, backup $SECTOR"
VG="$(getv VG)"
ROOT_LV="$(getv ROOT_LV)"
if vgs "$VG" >/dev/null 2>&1; then
    die vg_name_conflict "a volume group named $VG is already active on this system"
fi

# Space: the restored LUKS partition must hold the physical volume the backed-up
# LVM metadata describes (extent area), plus LUKS's own data offset.
PV_EXT_SECT=$(awk '/extent_size =/{es=$3} /pe_start =/{ps=$3} /pe_count =/{pc=$3} END{print ps + pc*es}' "$BK_MNT/vg_metadata.txt")
LUKS_OFFSET=$(cryptsetup luksDump "$BK_MNT/luks_header.img" | awk '/^Data segments:/{f=1} f&&/offset:/{print $2; exit}')
[ -n "$PV_EXT_SECT" ] && [ -n "$LUKS_OFFSET" ] || die bad_backup "cannot read sizes from the backup"
read -r EFI_START EFI_SIZE EFI_TYPE <<< "$(getv EFI_GEOM)"
read -r BOOT_START BOOT_SIZE BOOT_TYPE <<< "$(getv BOOT_GEOM)"
read -r LUKS_START LUKS_SIZE LUKS_TYPE <<< "$(getv LUKS_GEOM)"
NEED_BYTES=$(( LUKS_START * SECTOR + LUKS_OFFSET + PV_EXT_SECT * 512 + 4 * 1048576 ))
DISK_BYTES=$(blockdev --getsize64 "$TARGET")
(( DISK_BYTES >= NEED_BYTES )) || die target_small "need $(( NEED_BYTES / 1000000000 )) GB, disk has $(( DISK_BYTES / 1000000000 )) GB"

# ----------------------------------------------------------- 2: partitions
stage 2 $TOTAL partition
WIPED=1
wipefs -a -f "$TARGET" >/dev/null 2>&1
while read -r p; do wipefs -a -f "$p" >/dev/null 2>&1; done < <(lsblk -nlpo PATH "$TARGET" | tail -n +2)
SFDISK_SCRIPT="label: gpt
start=$EFI_START, size=$EFI_SIZE, type=$EFI_TYPE
start=$BOOT_START, size=$BOOT_SIZE, type=$BOOT_TYPE
start=$LUKS_START, type=$LUKS_TYPE"
echo "partition script:"; echo "$SFDISK_SCRIPT"
sfdisk --quiet "$TARGET" <<< "$SFDISK_SCRIPT" || die restore_failed "sfdisk"
udevadm settle
partprobe "$TARGET" 2>/dev/null
udevadm settle
case "$TARGET" in *[0-9]) PSEP=p ;; *) PSEP= ;; esac
P1="${TARGET}${PSEP}1"; P2="${TARGET}${PSEP}2"; P3="${TARGET}${PSEP}3"
for i in 1 2 3 4 5 6 7 8 9 10; do
    [ -b "$P1" ] && [ -b "$P2" ] && [ -b "$P3" ] && break
    sleep 1
done
[ -b "$P3" ] || die restore_failed "partitions did not appear"

# --------------------------------------------------- 3: EFI and /boot images
stage 3 $TOTAL boot
zstd -dc "$BK_MNT/efi.img.zst" | dd of="$P1" bs=4M conv=fsync status=none || die restore_failed "efi image"
zstd -dc "$BK_MNT/boot.img.zst" | dd of="$P2" bs=4M conv=fsync status=none || die restore_failed "boot image"

# ------------------------------------------------------ 4: LUKS and LVM
stage 4 $TOTAL encryption
cryptsetup luksHeaderRestore "$P3" --header-backup-file "$BK_MNT/luks_header.img" --batch-mode \
    || die restore_failed "luksHeaderRestore"
printf '%s' "$DISK_PASS" | cryptsetup open --key-file=- "$P3" "$CRYPT_NAME" || die restore_failed "open restored LUKS"
unset DISK_PASS BK_PASS CB_PASS
PV_ID=$(awk '/physical_volumes \{/{f=1} f&&/pv0 \{/{g=1} g&&/id = /{gsub(/"/,"",$3); print $3; exit}' "$BK_MNT/vg_metadata.txt")
[ -n "$PV_ID" ] || die bad_backup "no physical volume id in the LVM metadata"
pvcreate -ff -y --uuid "$PV_ID" --restorefile "$BK_MNT/vg_metadata.txt" "/dev/mapper/$CRYPT_NAME" >/dev/null || die restore_failed "pvcreate"
vgcfgrestore -f "$BK_MNT/vg_metadata.txt" "$VG" >/dev/null || die restore_failed "vgcfgrestore"
vgchange -ay "$VG" >/dev/null || die restore_failed "vgchange"
for s in $(getv SWAPS); do
    IFS=: read -r sname _ suuid <<< "$s"
    mkswap -q -U "$suuid" "/dev/$VG/$sname" >/dev/null || die restore_failed "mkswap $sname"
done

# Bigger target disk: give the extra room to root (after the image is back).
pvresize "/dev/mapper/$CRYPT_NAME" >/dev/null 2>&1
GROW=0
FREE_M=$(vgs --noheadings --units m --nosuffix -o vg_free "$VG" | tr -d ' ')
if (( ${FREE_M%.*} >= 256 )); then
    lvextend -l +100%FREE "/dev/$VG/$ROOT_LV" >/dev/null && GROW=1
fi

# ------------------------------------------------------------ 5: root image
stage 5 $TOTAL system
PCERR=/run/cyberbeest-partclone.err
RCF=/run/cyberbeest-restore.rc
: > "$PCERR"
( zstd -dc "$BK_MNT/root.pcl.zst" \
    | partclone.ext4 -r -s - -o "/dev/$VG/$ROOT_LV" -L /run/cyberbeest-partclone.log 2> "$PCERR"
  echo "${PIPESTATUS[*]}" > "$RCF" ) &
JOB=$!
watch_progress "$JOB" "$PCERR"
wait "$JOB"
read -r RC0 RC1 < "$RCF"
if [ "$RC0" != 0 ] || [ "$RC1" != 0 ]; then
    tr '\r' '\n' < "$PCERR" | tail -n 5
    die restore_failed "root image exited $RC0/$RC1"
fi

# ------------------------------------------------------------- 6: finishing
stage 6 $TOTAL finish
e2fsck -f -p "/dev/$VG/$ROOT_LV" >/dev/null
FSCK_RC=$?
(( FSCK_RC <= 1 )) || die restore_failed "filesystem check of the restored system returned $FSCK_RC"
if [ "$GROW" = 1 ]; then
    resize2fs "/dev/$VG/$ROOT_LV" >/dev/null 2>&1 || warn grow_failed "root keeps its old size"
fi

# Boot entry for firmware that lost it (new disk, empty NVRAM). Best effort:
# the removable-media fallback path on the ESP works without it.
if [ -d /sys/firmware/efi/efivars ] && command -v efibootmgr >/dev/null; then
    ESP_MNT="$(mktemp -d /run/cyberbeest-esp.XXXXXX)"
    if mount -o ro "$P1" "$ESP_MNT" 2>/dev/null; then
        LOADER=""
        for cand in EFI/debian/shimx64.efi EFI/debian/grubx64.efi; do
            [ -f "$ESP_MNT/$cand" ] && { LOADER="\\${cand//\//\\}"; break; }
        done
        if [ -n "$LOADER" ]; then
            efibootmgr --create --disk "$TARGET" --part 1 --label "Cyberbeest" --loader "$LOADER" >/dev/null 2>&1 \
                || warn no_boot_entry "could not register a firmware boot entry"
        else
            warn no_boot_entry "no bootloader found on the EFI partition"
        fi
    fi
fi
sync
FINISHED=1
echo "@@DONE@@ $TARGET"
