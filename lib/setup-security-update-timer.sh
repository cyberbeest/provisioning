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
# Runs a Debian security-only update check + install, and records status
# for the panel's genmon widget (~/.local/bin/update-genmon.sh).
# Invoked by security-update-check.timer.
set -uo pipefail

STATUS_FILE=/var/lib/security-update-status
STATUS_TMP="${STATUS_FILE}.tmp.$$"
PHASE_FILE=/run/security-update-check.phase

set_phase() {
    echo "$1" > "$PHASE_FILE"
    chmod 644 "$PHASE_FILE"
}

start_epoch="$(date +%s)"

set_phase checking
update_out="$(apt-get -o DPkg::Lock::Timeout=60 update -qq 2>&1)"
update_status=$?

result=ok
reason=""

if [ "$update_status" -ne 0 ]; then
    result=network-error
    # Last non-empty line is usually the actionable bit, e.g. "Could not
    # connect" / "Temporary failure in name resolution".
    reason="$(echo "$update_out" | sed '/^$/d' | tail -1)"
else
    set_phase installing
    uu_out="$(unattended-upgrades 2>&1)"
    uu_status=$?
    if [ "$uu_status" -ne 0 ]; then
        result=upgrade-error
        reason="$(echo "$uu_out" | sed '/^$/d' | tail -1)"
    fi
fi

rm -f "$PHASE_FILE"

end_epoch="$(date +%s)"
duration=$(( end_epoch - start_epoch ))

# Keep the reason to one line, status file is sourced with `.` by the genmon
# script so it must stay shell-safe.
reason="${reason//\"/\'}"

cat > "$STATUS_TMP" <<STATUS
LAST_CHECK_EPOCH=$start_epoch
LAST_CHECK_DURATION_SECONDS=$duration
LAST_CHECK_RESULT=$result
LAST_CHECK_REASON="$reason"
STATUS
mv "$STATUS_TMP" "$STATUS_FILE"
chmod 644 "$STATUS_FILE"

[ "$result" = ok ]
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
