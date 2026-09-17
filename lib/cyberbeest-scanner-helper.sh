#!/bin/bash
# Runs the Cyberbeest Malware Scanner's checks (debsums, clamscan, rkhunter,
# chkrootkit) as root, called via pkexec from cyberbeest_scanner_gui.py.
# Deployed read-only to /usr/local/lib/cyberbeest/ by
# 59-cyberbeest-scanner.sh, with __TARGET_HOME__/__TARGET_USER__ filled in
# at provisioning time (see that script for why it must live root-owned
# under /usr/local/lib rather than under /home).
#
# clamd is started here, right before the scan, and stopped right after --
# NOT left running as a resident daemon -- since an always-on clamd (DB
# resident in RAM) would work against the notification-mode/34h-battery
# pitch. See 51-fail2ban.sh for the same "install but don't run unless
# actually needed" pattern applied to a different daemon.
#
# Protocol on stdout: lines starting with "@@STAGE@@ " are progress markers
# for the GUI (index total name); a "=== <human label> ===" line announces
# each stage for the log pane; everything else is raw tool output, also
# appended to the timestamped report file with "===<name>===" separators
# (a separate, machine-parseable marker) so interpret_results.py can split
# it back into sections. During the clamscan stage, "@@CLAMTOTAL@@ <n>" (once)
# and "@@CLAMPROGRESS@@ <n>" (periodically) give per-file progress within
# that stage. A final "@@DONE@@ <report path>" line marks completion, or
# "@@INTERRUPTED@@" if the GUI was closed / pkexec's process was killed
# mid-scan (pkexec forwards SIGTERM/INT/HUP to what it launches).
#
# Getting killed mid-scan must not leave clamd running (defeats the whole
# "not resident, to save battery" point) or lose all incremental-cache
# progress -- see the cleanup() trap below.
set -uo pipefail

TARGET_USER="__TARGET_USER__"
TARGET_HOME="__TARGET_HOME__"
SCANDIR="$TARGET_HOME/.local/share/cyberbeest/scanner"
MANIFEST="$SCANDIR/.clamscan-manifest.tsv"
MANIFEST_EXCLUDE_RE='(^/(proc|sys|dev|run)(/|$))|(/\.cache/)|(^/var/cache/)|(\.(qcow2|vdi|vmdk|iso|img)$)'
LIBDIR="$TARGET_HOME/.local/lib/cyberbeest-scanner"
STAMP="$(date +%Y%m%d-%H%M%S)"
REPORT="$SCANDIR/reports/scan-$STAMP.log"
mkdir -p "$SCANDIR/reports"

CLAM_STAGE_ACTIVE=0
CLAMD_STARTED=0
FINISHED=0
NEW_MANIFEST=""
CHANGED_FOR_CLEANUP=""
CONFIRMED=""

# Runs on any exit -- normal completion, or a signal (see the INT/TERM trap
# below, which calls this then re-exits). Idempotent: safe even if it runs
# twice (once from the signal handler, once from the EXIT trap it then
# triggers), since each step guards on the state it would have already
# cleared.
cleanup() {
  # Stop anything still running (clamdscan/rkhunter/chkrootkit/debsums are
  # all direct children of this script, including across a pipeline, since
  # bash forks each pipeline stage from the invoking shell).
  pkill -TERM -P $$ 2>/dev/null || true
  sleep 1
  pkill -KILL -P $$ 2>/dev/null || true

  if [ "$CLAM_STAGE_ACTIVE" = 1 ] && [ -n "$NEW_MANIFEST" ] && [ -f "$NEW_MANIFEST" ]; then
    echo "interrupted mid-scan: saving progress on confirmed-clean files..." | tee -a "$REPORT"
    MERGED="$(mktemp)"
    python3 "$LIBDIR/manifest_diff.py" merge \
      "$MANIFEST" "$NEW_MANIFEST" "${CHANGED_FOR_CLEANUP:-/dev/null}" "${CONFIRMED:-/dev/null}" "$MERGED" \
      2>&1 | tee -a "$REPORT"
    mv "$MERGED" "$MANIFEST"
    chown "$TARGET_USER:$TARGET_USER" "$MANIFEST" 2>/dev/null || true
    CLAM_STAGE_ACTIVE=0
  fi

  if [ "$CLAMD_STARTED" = 1 ]; then
    systemctl stop clamav-daemon 2>/dev/null || true
    CLAMD_STARTED=0
  fi

  chown "$TARGET_USER:$TARGET_USER" "$REPORT" 2>/dev/null || true

  if [ "$FINISHED" != 1 ]; then
    echo "@@INTERRUPTED@@"
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 143' INT TERM

section() {
  echo "===$1===" >> "$REPORT"
  echo "=== $2 ===" | tee -a "$REPORT"
}

# clamdscan -v only emits ONE verbose line per argument -- for a bare
# directory path that's a single "<dir>: OK" line for the whole tree, not
# one per file inside it. Per-file granularity only happens via
# --file-list, which is why the full-scan branch below builds one from the
# manifest instead of ever passing clamdscan a bare "/". Turns that
# per-file stream into "@@CLAMPROGRESS@@ n" markers every 25 files instead
# of forwarding all the "<path>: OK" lines into the log/report as noise
# (note: no -i here, since it suppresses the OK lines this depends on --
# the awk filter below does that job instead), and appends each confirmed
# path to $CONFIRMED so an interrupt can tell what's actually safe to carry
# forward. FOUND lines (an actual hit) and clamdscan's own summary block
# still pass through untouched. stdbuf forces line buffering so progress
# arrives live instead of waiting on a pipe's default block buffering.
run_clamdscan_with_progress() {
  local total="$1" confirmed_file="$2"; shift 2
  echo "@@CLAMTOTAL@@ $total"
  stdbuf -oL clamdscan -v "$@" 2>&1 | stdbuf -oL awk -v total="$total" -v confirmed="$confirmed_file" '
    /: OK$/     { n++; path=$0; sub(/: OK$/, "", path); print path >> confirmed; fflush(confirmed)
                  if (n % 25 == 0 || n == total) { print "@@CLAMPROGRESS@@ " n; fflush() } next }
    /FOUND$/    { n++; path=$0; sub(/: .*/, "", path); print path >> confirmed; fflush(confirmed)
                  print; print "@@CLAMPROGRESS@@ " n; fflush(); next }
    { print; fflush() }
  '
}

echo "@@STAGE@@ 1 4 debsums"
section debsums "Checking base-system files (debsums)"
debsums -c 2>&1 | tee -a "$REPORT"

echo "@@STAGE@@ 2 4 clamscan"
section clamscan "Scanning for known malware (ClamAV)"
CLAM_STAGE_ACTIVE=1
echo "starting clamd (not left running otherwise, to save battery)..." | tee -a "$REPORT"
systemctl start clamav-daemon
CLAMD_STARTED=1
for _ in $(seq 1 30); do
  [ -S /var/run/clamav/clamd.ctl ] && break
  sleep 1
done

NEW_MANIFEST="$(mktemp)"
CONFIRMED="$(mktemp)"
echo "building file manifest (size/mtime/header-hash) to find what changed..." | tee -a "$REPORT"
python3 "$LIBDIR/manifest_diff.py" build / "$MANIFEST_EXCLUDE_RE" "$NEW_MANIFEST"
if [ -s "$MANIFEST" ]; then
  echo "incremental scan: comparing against the last manifest..." | tee -a "$REPORT"
  CHANGED="$(mktemp)"
  CHANGED_FOR_CLEANUP="$CHANGED"
  python3 "$LIBDIR/manifest_diff.py" diff "$MANIFEST" "$NEW_MANIFEST" "$CHANGED" 2>&1 | tee -a "$REPORT"
  if [ -s "$CHANGED" ]; then
    run_clamdscan_with_progress "$(wc -l < "$CHANGED")" "$CONFIRMED" --fdpass --multiscan --file-list="$CHANGED" | tee -a "$REPORT"
  else
    echo "no changed files, nothing to scan" | tee -a "$REPORT"
  fi
else
  echo "no prior manifest found, running a full scan" | tee -a "$REPORT"
  FULL_LIST="$(mktemp)"
  CHANGED_FOR_CLEANUP="$FULL_LIST"
  cut -f1 "$NEW_MANIFEST" > "$FULL_LIST"
  run_clamdscan_with_progress "$(wc -l < "$FULL_LIST")" "$CONFIRMED" --fdpass --multiscan --file-list="$FULL_LIST" | tee -a "$REPORT"
fi
mv "$NEW_MANIFEST" "$MANIFEST"
chown "$TARGET_USER:$TARGET_USER" "$MANIFEST"
rm -f "$CHANGED_FOR_CLEANUP" "$CONFIRMED"
CLAM_STAGE_ACTIVE=0

systemctl stop clamav-daemon
CLAMD_STARTED=0

echo "@@STAGE@@ 3 4 rkhunter"
section rkhunter "Checking for rootkits (rkhunter)"
rkhunter --check --sk --nocolors 2>&1 | tee -a "$REPORT"

echo "@@STAGE@@ 4 4 chkrootkit"
section chkrootkit "Checking for rootkits (chkrootkit)"
chkrootkit 2>&1 | tee -a "$REPORT"

chown "$TARGET_USER:$TARGET_USER" "$REPORT"
FINISHED=1
echo "@@DONE@@ $REPORT"
