#!/bin/bash
# Installs a risk-acceptance warning shown every time GNOME Software launches
# (app grid, menu, or D-Bus activation), since its Explore/search covers the
# whole Debian archive, not just Cyberbeest-approved apps -- see
# ../cyberbeest-launch-software.sh for the dialog and
# ../install-software-warning.sh for the .desktop/D-Bus override mechanics.
# Depends on 02-gnome-software-store.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/04-software-launch-warning.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning software-launch warning ==="
bash "$DIR/../install-software-warning.sh"
echo "=== done ==="
