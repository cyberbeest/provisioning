#!/bin/bash
# Adds the Signal and Element vendor apt repos to unattended-upgrades'
# allowlist so their updates install automatically like Debian's own,
# instead of sitting as manual-only entries in GNOME Software -- see
# lib/add-vendor-origins-unattended-upgrades.sh for the exact Origin/Codename
# values (Signal's Release file really does say "Origin: . xenial").
# Depends on 05-unattended-upgrades-security.sh (installs unattended-upgrades
# itself) and 03-secure-messengers.sh (registers Signal/Element's vendor apt
# repos via lib/cyberbeest-pkg-helper.sh setup-repo).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/06-vendor-origins-unattended-upgrades.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : provisioning vendor-origins unattended-upgrades allowlist ==="
bash "$DIR/lib/add-vendor-origins-unattended-upgrades.sh"
echo "=== done ==="
