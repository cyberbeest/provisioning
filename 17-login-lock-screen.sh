#!/bin/bash
# Brands the LightDM login screen and the xfce4-screensaver lock screen:
# Cyberbeest background + single-user lockdown on login, and the same
# "Enter short password to unlock desktop" message via PAM on both --
# see lib/setup-login-lock-screen.sh.
# Idempotent: safe to re-run (backs up any pre-existing config the first
# time, as *.pre-cyberbeest).
# LOCALE_DEPENDENT: bakes the PAM "unlock desktop" message text for whatever
# locale is active when this runs (pam_echo.so just cats a static file, it
# can't look up the locale live at login/lock time -- see
# lib/setup-login-lock-screen.sh). 00-locale-keyboard-timezone.sh greps for
# this marker and deletes this script's own log after applying a language
# change, so it shows up as "changed" and gets re-run instead of silently
# staying on the old language.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/17-login-lock-screen.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : branding login/lock screens ==="
bash "$DIR/lib/setup-login-lock-screen.sh"
