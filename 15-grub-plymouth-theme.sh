#!/bin/bash
# Installs the Cyberbeest boot splash (Plymouth theme, logo persists through
# the LUKS password prompt and shutdown) and matching GRUB styling
# (background, fast hidden timeout, no stray console text) -- see
# lib/setup-grub-plymouth-theme.sh.
# Idempotent: safe to re-run (backs up /etc/default/grub and
# /etc/grub.d/10_linux the first time, as *.pre-cyberbeest).
# LOCALE_DEPENDENT: bakes the LUKS-prompt text and GRUB background image for
# whatever locale is active when this runs (Plymouth/GRUB run before any
# filesystem holding /etc/default/locale is mounted, so they can't look it up
# live like the desktop-side i18n tools do -- see lib/setup-grub-plymouth-theme.sh).
# 00-locale-keyboard-timezone.sh greps for this marker and deletes this
# script's own log after applying a language change, so it shows up as
# "changed" and gets re-run instead of silently staying on the old language.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/15-grub-plymouth-theme.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : provisioning GRUB/Plymouth boot styling ==="
bash "$DIR/lib/setup-grub-plymouth-theme.sh"
