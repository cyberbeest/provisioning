#!/bin/bash
# Installs Kleopatra -- a GUI certificate/key manager and front-end for GnuPG.
# Gives users a simple way to generate PGP keys and encrypt/decrypt files or
# text without touching the command line.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/36-kleopatra.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing kleopatra ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y kleopatra

echo "=== updating desktop menu cache ==="
update-desktop-database /usr/share/applications || true

echo "=== done ==="
