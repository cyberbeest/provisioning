# shellcheck shell=bash
# Shared by cyberbeest-backup-helper.sh and cyberbeest-restore-helper.sh (both
# run as root via pkexec, from cyberbeest_backup_gui.py). Sourced, not run.
# Installed root-owned next to the helpers in /usr/local/lib/cyberbeest/ by
# 73-cyberbeest-backup.sh.
#
# Protocol on stdout, one marker per line (everything else is log text):
#   @@STAGE@@ <idx> <total> <key>   a new stage began
#   @@PROGRESS@@ <percent>          progress inside the current stage
#   @@WARN@@ <code> <detail>        something the user should know, not fatal
#   @@ERROR@@ <code> <detail>       fatal; the helper exits 1 right after
#   @@DONE@@ <path>                 success (backup folder / restored disk)
# The GUI maps <code> to a translated message (see backup.err.* in lib/i18n).
#
# stdin: the passphrase lines the helper documents, then it stays open. A line
# "cancel" -- or the GUI dying, which closes the pipe -- stops the helper. A
# root process can't be signalled from the unprivileged GUI, hence this.

CB_LIBDIR=/usr/local/lib/cyberbeest
# fd 3 (the cancel pipe) is open in children; LVM would warn about it
export LVM_SUPPRESS_FD_WARNINGS=1

stage() { echo "@@STAGE@@ $1 $2 $3"; }
progress() { echo "@@PROGRESS@@ $1"; }
warn() { echo "@@WARN@@ $1 ${2:-}"; }
die() { echo "@@ERROR@@ $1 ${2:-}"; exit 1; }

# Sets CB_USER_HOME/CB_USER_UID and opens the log under the user's data dir.
init_user_and_log() {
    local kind="$1" uid
    uid="${PKEXEC_UID:-${SUDO_UID:-0}}"
    CB_USER_UID="$uid"
    CB_USER_HOME="$(getent passwd "$uid" | cut -d: -f6)"
    [ -n "$CB_USER_HOME" ] || CB_USER_HOME=/root
    local logdir="$CB_USER_HOME/.local/share/cyberbeest/backup"
    mkdir -p "$logdir"
    CB_LOG="$logdir/$kind-$(date +%Y%m%d-%H%M%S).log"
    : > "$CB_LOG"
    chown -R "$uid:$(id -g "$uid" 2>/dev/null || echo "$uid")" "$CB_USER_HOME/.local/share/cyberbeest" 2>/dev/null || true
    exec > >(tee -a "$CB_LOG") 2>&1
}

# Reads the passphrase lines off stdin (callers pass how many), then detaches
# every child from stdin and starts the cancel watcher on a saved copy of it.
CB_PASS=()
read_secrets() {
    local n="$1" i line
    for ((i = 0; i < n; i++)); do
        IFS= read -r line || die no_passphrase "stdin closed"
        CB_PASS+=("$line")
    done
    exec 3<&0 0</dev/null
    start_cancel_watch
}

descendants() {
    local c
    for c in $(pgrep -P "$1"); do
        echo "$c"
        descendants "$c"
    done
}

start_cancel_watch() {
    local parent=$$
    (
        while IFS= read -r l <&3; do
            [ "$l" = cancel ] && break
        done
        # Stop the long-running descendants first: bash only runs its TERM trap
        # after the foreground job ends, which for an imaging run is minutes
        # away. tee stays (the log), and so does this subshell.
        for p in $(descendants "$parent"); do
            [ "$p" = "$BASHPID" ] && continue
            [ "$(cat "/proc/$p/comm" 2>/dev/null)" = tee ] && continue
            kill -TERM "$p" 2>/dev/null
        done
        kill -TERM "$parent" 2>/dev/null
    ) &
    CB_WATCH_PID=$!
}

stop_cancel_watch() {
    [ -n "${CB_WATCH_PID:-}" ] && kill "$CB_WATCH_PID" 2>/dev/null
    CB_WATCH_PID=
}

# Marks the machine busy so lib/lock-shutdown-watcher.sh doesn't power off
# during a long run just because the screen stayed locked.
CB_BUSY_FILE=/run/cyberbeest-backup-running
mark_busy() { echo $$ > "$CB_BUSY_FILE"; }
unmark_busy() { rm -f "$CB_BUSY_FILE"; }

# disk_of /dev/x -> /dev/<whole disk> (a loop device counts as a disk, which
# is what the test harness uses)
disk_of() {
    local d
    d="$(lsblk -snro NAME,TYPE "$1" 2>/dev/null | awk '$2=="disk"||$2=="loop"{n=$1} END{print n}')"
    [ -n "$d" ] && echo "/dev/$d"
}

# source_dev_of PATH -> block device holding PATH (btrfs "[/@]" suffix stripped)
source_dev_of() {
    local s
    s="$(findmnt -T "$1" -no SOURCE 2>/dev/null | head -1)"
    echo "${s%%\[*}"
}

# watch_progress JOBPID ERRFILE: while the background job runs, turn partclone's
# stderr (progress is "Completed: 12.34%", rewritten with \r) into
# @@PROGRESS@@ lines. Not a process substitution on partclone's stderr: inside
# a pipeline that one inherits the pipe, and its output would land in the image.
watch_progress() {
    local job="$1" file="$2" last="" cur
    while kill -0 "$job" 2>/dev/null; do
        cur="$(tail -c 2048 "$file" 2>/dev/null | tr '\r' '\n' | grep -o 'Completed: *[0-9]*\.[0-9]*' | tail -n 1 | sed 's/Completed: *//')"
        if [ -n "$cur" ] && [ "$cur" != "$last" ]; then progress "$cur"; last="$cur"; fi
        sleep 1
    done
}

# Describes the running system's disk layout into CB_* variables, or dies with
# no_layout. Only the standard Cyberbeest layout is supported: GPT disk with
# an EFI partition, a /boot partition and one LUKS partition holding an LVM
# volume group whose root LV is ext4 and whose other LVs are swap.
# CB_ROOT_MNT lets the test harness point it at a scratch copy of that layout.
detect_layout() {
    local root_mnt="${CB_ROOT_MNT:-/}" m
    m="${root_mnt%/}"
    CB_ROOT_DEV="$(source_dev_of "$root_mnt")"
    [ -b "$CB_ROOT_DEV" ] || die no_layout "root source '$CB_ROOT_DEV' is not a block device"
    [ "$(findmnt -no FSTYPE "$root_mnt")" = ext4 ] || die no_layout "root is not ext4"

    CB_VG="$(lvs --noheadings -o vg_name "$CB_ROOT_DEV" 2>/dev/null | tr -d ' ')"
    CB_ROOT_LV="$(lvs --noheadings -o lv_name "$CB_ROOT_DEV" 2>/dev/null | tr -d ' ')"
    [ -n "$CB_VG" ] && [ -n "$CB_ROOT_LV" ] || die no_layout "root is not on LVM"

    local pvs_out
    pvs_out="$(pvs --noheadings -o pv_name -S "vg_name=$CB_VG" 2>/dev/null | tr -d ' ')"
    [ "$(echo "$pvs_out" | grep -c .)" = 1 ] || die no_layout "volume group needs exactly one physical volume"
    CB_PV="$pvs_out"
    [ "$(lsblk -no TYPE "$CB_PV" 2>/dev/null | head -1)" = crypt ] || die no_layout "physical volume is not LUKS"
    CB_LUKS_DEV="$(cryptsetup status "$CB_PV" | awk '/^ *device:/{print $2}')"
    [ -b "$CB_LUKS_DEV" ] || die no_layout "cannot find the LUKS partition"

    CB_DISK="$(disk_of "$CB_LUKS_DEV")"
    CB_BOOT_DEV="$(findmnt -no SOURCE "$m/boot" 2>/dev/null | head -1)"
    CB_EFI_DEV="$(findmnt -no SOURCE "$m/boot/efi" 2>/dev/null | head -1)"
    [ -b "$CB_BOOT_DEV" ] && [ -b "$CB_EFI_DEV" ] || die no_layout "/boot or /boot/efi is not a separate partition"
    [ "$(disk_of "$CB_BOOT_DEV")" = "$CB_DISK" ] && [ "$(disk_of "$CB_EFI_DEV")" = "$CB_DISK" ] \
        || die no_layout "EFI, /boot and LUKS partitions are not on one disk"

    # Every other LV must be swap: anything with a filesystem would silently
    # be left out of the backup.
    CB_SWAPS=""
    local name path
    while read -r name path; do
        [ "$name" = "$CB_ROOT_LV" ] && continue
        [ "$(blkid -s TYPE -o value "$path" 2>/dev/null)" = swap ] || die no_layout "volume '$name' is not swap"
        CB_SWAPS="$CB_SWAPS $name:$(blockdev --getsize64 "$path"):$(blkid -s UUID -o value "$path")"
    done < <(lvs --noheadings -o lv_name,lv_path -S "vg_name=$CB_VG" | tr -s ' ')
    CB_SWAPS="${CB_SWAPS# }"

    CB_SECTOR="$(blockdev --getss "$CB_DISK")"
    CB_ROOT_BYTES="$(blockdev --getsize64 "$CB_ROOT_DEV")"

    # Partitions the backup won't contain (user-added): tell, don't refuse.
    CB_EXTRA_PARTS=""
    local p
    while read -r p; do
        case "/dev/$p" in "$CB_BOOT_DEV" | "$CB_EFI_DEV" | "$CB_LUKS_DEV") ;; *) CB_EXTRA_PARTS="$CB_EXTRA_PARTS $p" ;; esac
    done < <(lsblk -nro NAME,TYPE "$CB_DISK" | awk '$2=="part"{print $1}')
    CB_EXTRA_PARTS="${CB_EXTRA_PARTS# }"
}

# part_geometry /dev/part -> "start size type" in logical sectors of $CB_SECTOR
part_geometry() {
    local b start size
    b="$(basename "$(readlink -f "$1")")"
    start=$(( $(cat "/sys/class/block/$b/start") * 512 / CB_SECTOR ))
    size=$(( $(cat "/sys/class/block/$b/size") * 512 / CB_SECTOR ))
    echo "$start $size $(lsblk -dno PARTTYPE "$1")"
}
