#!/bin/bash
# Installs gnome-calculator -- since whisker menu has no calculator app by
# default. Plain apt package, in Debian main, no repo setup needed. Chosen
# over galculator: shows up in the menu simply as "Calculator", which is
# less confusing for normal users.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/32-calculator.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing gnome-calculator ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y gnome-calculator

echo "=== done ==="
