#!/bin/bash
# Installs unattended-upgrades and configures it for Debian security updates
# only, on a daily timer -- see lib/setup_unattended_upgrades.sh for the
# actual config. Prerequisite for 06-vendor-origins-unattended-upgrades.sh,
# which extends the same allowlist to cover the Signal/Element vendor repos.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/05-unattended-upgrades-security.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning unattended-upgrades (security-only) ==="
bash "$DIR/lib/setup_unattended_upgrades.sh"
