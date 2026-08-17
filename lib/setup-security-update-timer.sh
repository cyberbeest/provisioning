#!/bin/bash
# Replaces the default apt-daily/apt-daily-upgrade timers with a dedicated
# systemd timer that checks for and installs Debian security updates every
# 120 minutes, and records status (timestamp, duration, phase, failure
# reason) to /var/lib/security-update-status for the panel's genmon widget
# (see lib/update-genmon.sh).
set -euo pipefail

echo "--- Writing wrapper script /usr/local/sbin/security-update-check.sh ---"
cat > /usr/local/sbin/security-update-check.sh <<'EOF'
#!/bin/bash
# Runs Debian security updates (always, even on a metered connection -- see
# 51unattended-upgrades-local) and vendor messenger-app updates (Signal,
# Element -- skipped on metered unless the last successful pass was over 30
# days ago, so mobile-only users still don't go stale indefinitely) as two
# separate unattended-upgrades passes, scoped by temporarily toggling which
# apt.conf.d Origins-Pattern fragment is active. Records status for the
# panel's genmon widget (~/.local/bin/update-genmon.sh) to
# /var/lib/security-update-status (security pass) and
# /var/lib/security-update-apps-status (messenger-apps pass).
# Invoked by security-update-check.timer.
set -uo pipefail

STATUS_FILE=/var/lib/security-update-status
APPS_STATUS_FILE=/var/lib/security-update-apps-status
PHASE_FILE=/run/security-update-check.phase
CHECK_INTERVAL_SECONDS=$(( 120 * 60 ))
APPS_FORCE_INTERVAL_SECONDS=$(( 30 * 24 * 60 * 60 ))

CONF_DIR=/etc/apt/apt.conf.d
SECURITY_CONF=51unattended-upgrades-local
VENDOR_CONF=52unattended-upgrades-vendor-messengers
FORCE_CONF=53unattended-upgrades-force-apps

set_phase() {
    echo "$1" > "$PHASE_FILE"
    chmod 644 "$PHASE_FILE"
}

disable_conf() { [ -f "$CONF_DIR/$1" ] && mv "$CONF_DIR/$1" "$CONF_DIR/$1.disabled"; }
enable_conf()  { [ -f "$CONF_DIR/$1.disabled" ] && mv "$CONF_DIR/$1.disabled" "$CONF_DIR/$1"; }
cleanup() {
    enable_conf "$SECURITY_CONF"
    enable_conf "$VENDOR_CONF"
    rm -f "$CONF_DIR/$FORCE_CONF"
    rm -f "$PHASE_FILE"
}
trap cleanup EXIT

# Runs one unattended-upgrades pass (whichever Origins-Pattern fragment is
# currently enabled) and classifies the result into PASS_RESULT/PASS_REASON/
# PASS_OUTPUT globals.
run_uu_pass() {
    local pass_start="$1" out status journal combined
    out="$(unattended-upgrades 2>&1)"
    status=$?
    if [ "$status" -eq 0 ]; then
        PASS_RESULT=ok
        PASS_REASON=""
        PASS_OUTPUT="$out"
        return
    fi
    # unattended-upgrades logs via syslog rather than to its own
    # stdout/stderr, so out is typically empty here -- pull its actual log
    # lines from the journal instead. Filtered by syslog identifier (not
    # -u security-update-check.service) so this also works when the script
    # is run manually/outside the systemd unit.
    journal="$(journalctl -t unattended-upgrade --since "@$pass_start" --no-pager -o cat 2>/dev/null)"
    combined="$out"
    [ -n "$journal" ] && combined="${combined}
${journal}"
    PASS_OUTPUT="$combined"
    if echo "$combined" | grep -qi "metered connection"; then
        # Not a real failure -- unattended-upgrades deliberately skips when
        # NetworkManager reports the active connection as metered (e.g. a
        # phone tethered over mobile data), so don't alarm the user with an
        # "error" icon for working-as-intended behavior.
        PASS_RESULT=skipped-metered
        PASS_REASON="Skipped: on a metered connection."
    else
        PASS_RESULT=upgrade-error
        PASS_REASON="$(echo "$combined" | sed '/^$/d' | tail -1)"
    fi
}

start_epoch="$(date +%s)"

# The timer's OnBootSec=5min trigger fires on every boot regardless of when
# the last real check ran, and Persistent=true can also fire a catch-up run
# right after boot. Skip without touching the network if we already checked
# recently, so frequent reboots don't hammer Debian's mirrors more often
# than the intended 120-minute cadence. Gated on the security status file --
# both passes always run together on this cadence.
if [ -r "$STATUS_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATUS_FILE"
    if [ -n "${LAST_CHECK_EPOCH:-}" ] \
       && [ $(( start_epoch - LAST_CHECK_EPOCH )) -lt "$CHECK_INTERVAL_SECONDS" ]; then
        echo "Last check was $(( (start_epoch - LAST_CHECK_EPOCH) / 60 )) min ago, under the ${CHECK_INTERVAL_SECONDS}s interval -- skipping."
        exit 0
    fi
fi

set_phase checking
update_out="$(apt-get -o DPkg::Lock::Timeout=60 update -qq 2>&1)"
update_status=$?

security_result=ok
security_reason=""
security_output=""
apps_result=""
apps_reason=""
apps_output=""
apps_overdue=false

if [ "$update_status" -ne 0 ]; then
    security_result=network-error
    # Last non-empty line is usually the actionable bit, e.g. "Could not
    # connect" / "Temporary failure in name resolution".
    security_reason="$(echo "$update_out" | sed '/^$/d' | tail -1)"
else
    set_phase installing

    echo "--- Security pass (Debian-Security, always -- even on metered) ---"
    disable_conf "$VENDOR_CONF"
    phase1_start="$(date +%s)"
    run_uu_pass "$phase1_start"
    security_result="$PASS_RESULT"
    security_reason="$PASS_REASON"
    security_output="$PASS_OUTPUT"
    enable_conf "$VENDOR_CONF"

    echo "--- Messenger-apps pass (Signal/Element) ---"
    apps_last_success_epoch=""
    if [ -r "$APPS_STATUS_FILE" ]; then
        # shellcheck disable=SC1090
        . "$APPS_STATUS_FILE"
        apps_last_success_epoch="${LAST_SUCCESS_EPOCH:-}"
    fi
    if [ -z "$apps_last_success_epoch" ] \
       || [ $(( start_epoch - apps_last_success_epoch )) -ge "$APPS_FORCE_INTERVAL_SECONDS" ]; then
        apps_overdue=true
    fi

    disable_conf "$SECURITY_CONF"
    if [ "$apps_overdue" = true ]; then
        # It's been over 30 days since messenger apps last actually
        # updated -- force this pass through even on a metered connection,
        # so mobile-only users don't stay stale indefinitely.
        echo 'Unattended-Upgrade::Skip-Updates-On-Metered-Connections "false";' > "$CONF_DIR/$FORCE_CONF"
    fi
    phase2_start="$(date +%s)"
    run_uu_pass "$phase2_start"
    apps_result="$PASS_RESULT"
    apps_reason="$PASS_REASON"
    apps_output="$PASS_OUTPUT"
    rm -f "$CONF_DIR/$FORCE_CONF"
    enable_conf "$SECURITY_CONF"
fi

end_epoch="$(date +%s)"
duration=$(( end_epoch - start_epoch ))

# Keep reasons to one line each, status files are sourced with `.` by the
# genmon script so they must stay shell-safe.
security_reason="${security_reason//\"/\'}"
apps_reason="${apps_reason//\"/\'}"

# Full run log for the panel icon's "view log" action -- overwritten each
# run, world-readable so it can be opened without sudo.
LOG_FILE=/var/log/security-update-check-last.log
{
    echo "=== security-update-check.sh run: $(date -d "@$start_epoch") ==="
    echo "--- apt-get update ---"
    echo "$update_out"
    if [ -n "$security_output" ]; then
        echo
        echo "--- security pass (Debian-Security) ---"
        echo "$security_output"
    fi
    if [ -n "$apps_output" ]; then
        echo
        if [ "$apps_overdue" = true ]; then
            echo "--- messenger-apps pass (Signal/Element) [forced: 30+ days since last success] ---"
        else
            echo "--- messenger-apps pass (Signal/Element) ---"
        fi
        echo "$apps_output"
    fi
} > "$LOG_FILE"
chmod 644 "$LOG_FILE"

cat > "${STATUS_FILE}.tmp.$$" <<STATUS
LAST_CHECK_EPOCH=$start_epoch
LAST_CHECK_DURATION_SECONDS=$duration
LAST_CHECK_RESULT=$security_result
LAST_CHECK_REASON="$security_reason"
STATUS
mv "${STATUS_FILE}.tmp.$$" "$STATUS_FILE"
chmod 644 "$STATUS_FILE"

if [ -n "$apps_result" ]; then
    apps_success_epoch="$apps_last_success_epoch"
    [ "$apps_result" = ok ] && apps_success_epoch="$start_epoch"
    cat > "${APPS_STATUS_FILE}.tmp.$$" <<STATUS
LAST_CHECK_EPOCH=$start_epoch
LAST_CHECK_RESULT=$apps_result
LAST_CHECK_REASON="$apps_reason"
LAST_SUCCESS_EPOCH=${apps_success_epoch:-}
FORCED=$apps_overdue
STATUS
    mv "${APPS_STATUS_FILE}.tmp.$$" "$APPS_STATUS_FILE"
    chmod 644 "$APPS_STATUS_FILE"
fi

[ "$security_result" = ok ] || [ "$security_result" = skipped-metered ]
EOF
chmod 755 /usr/local/sbin/security-update-check.sh

echo "--- Writing systemd service/timer ---"
cat > /etc/systemd/system/security-update-check.service <<'EOF'
[Unit]
Description=Debian security update check (unattended-upgrades)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/security-update-check.sh
EOF

cat > /etc/systemd/system/security-update-check.timer <<'EOF'
[Unit]
Description=Run Debian security update check every 120 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=120min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "--- Disabling the default daily apt timers (replaced by security-update-check.timer) ---"
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer

echo "--- Turning off APT's own periodic scheduling (we schedule it ourselves now) ---"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF

echo "--- Enabling security-update-check.timer ---"
systemctl daemon-reload
systemctl enable --now security-update-check.timer

echo "--- Running an initial check now so the panel icon has data immediately ---"
/usr/local/sbin/security-update-check.sh || echo "(non-zero exit is fine if this first run itself hit an error -- status file is still written)"
cat /var/lib/security-update-status

echo "--- Status ---"
systemctl list-timers security-update-check.timer --no-pager
