#!/bin/bash
# Brands the LightDM login screen and the xfce4-screensaver lock screen:
# Cyberbeest background + single-user lockdown on login, and the same
# "Enter short password to unlock desktop" message via PAM on both --
# see lib/setup-login-lock-screen.sh.
# Idempotent: safe to re-run (backs up any pre-existing config the first
# time, as *.pre-cyberbeest).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/17-login-lock-screen.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : branding login/lock screens ==="
bash "$DIR/lib/setup-login-lock-screen.sh"
