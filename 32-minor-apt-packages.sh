#!/bin/bash
# Installs a grab-bag of small, single-purpose apt packages that don't
# warrant their own script: no repo setup, no config, just `apt install`.
#   - gnome-calculator: whisker menu has no calculator app by default. Picked
#     over the lighter galculator because it shows up in the menu simply as
#     "Calculator" -- less confusing for normal users than a branded name.
#   - xclip: Claude Code's Linux clipboard-image paste shells out to
#     xclip/xsel to read image bytes off the X clipboard. Without it,
#     pasting an image into the terminal silently does nothing.
#   - kleopatra: GUI certificate/key manager and front-end for GnuPG. Gives
#     users a simple way to generate PGP keys and encrypt/decrypt files or
#     text without touching the command line.
#   - ncdu: terminal disk usage analyzer, handy for finding what's eating
#     disk space without a GUI.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/32-minor-apt-packages.log"
exec > >(tee -a "$LOG") 2>&1

PACKAGES=(gnome-calculator xclip kleopatra ncdu)

echo "=== $(date) : installing minor apt packages: ${PACKAGES[*]} ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y "${PACKAGES[@]}"

echo "=== updating desktop menu cache ==="
update-desktop-database /usr/share/applications || true

echo "=== done ==="
