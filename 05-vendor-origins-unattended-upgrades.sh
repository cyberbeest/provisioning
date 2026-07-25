#!/bin/bash
# Adds the Signal and Element vendor apt repos to unattended-upgrades'
# allowlist so their updates install automatically like Debian's own,
# instead of sitting as manual-only entries in GNOME Software -- see
# ../add-vendor-origins-unattended-upgrades.sh for the exact Origin/Codename
# values (Signal's Release file really does say "Origin: . xenial").
# Depends on unattended-upgrades already being set up (see
# ../setup_unattended_upgrades.sh) and on Signal/Element's own apt repos
# already being registered (via ../cyberbeest-pkg-helper.sh setup-repo).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/05-vendor-origins-unattended-upgrades.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning vendor-origins unattended-upgrades allowlist ==="
bash "$DIR/../add-vendor-origins-unattended-upgrades.sh"
echo "=== done ==="
