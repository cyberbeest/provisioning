#!/bin/bash
# Installs GNOME Software as the friendly package-browsing/search app that
# replaced Synaptic (deemed too complicated for end users) without pulling
# in flatpak/snap infrastructure -- see ../install-gnome-software.sh for the
# reasoning and package-selection details.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/02-gnome-software-store.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning GNOME Software store ==="
bash "$DIR/../install-gnome-software.sh"
echo "=== done ==="
