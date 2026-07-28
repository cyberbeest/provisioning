#!/bin/bash
# Installs the Cyberbeest boot splash (Plymouth theme, logo persists through
# the LUKS password prompt and shutdown) and matching GRUB styling
# (background, fast hidden timeout, no stray console text) -- see
# lib/setup-grub-plymouth-theme.sh.
# Idempotent: safe to re-run (backs up /etc/default/grub and
# /etc/grub.d/10_linux the first time, as *.pre-cyberbeest).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/15-grub-plymouth-theme.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : provisioning GRUB/Plymouth boot styling ==="
bash "$DIR/lib/setup-grub-plymouth-theme.sh"
