#!/bin/bash
# Replaces the default daily apt-daily/apt-daily-upgrade timers with a
# dedicated systemd timer that checks for and installs Debian security
# updates every 120 minutes, recording status for the panel's genmon widget
# (12-xfce-panel-layout.sh) -- see lib/setup-security-update-timer.sh.
# Depends on: 05-unattended-upgrades-security.sh (needs unattended-upgrades
# installed and configured for security-only updates).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/07-security-update-timer.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning dedicated security-update-check timer ==="
bash "$DIR/lib/setup-security-update-timer.sh"
