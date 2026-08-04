#!/bin/bash
# Adds a "Shut Down" button to the xfce4-screensaver unlock dialog
# (alongside Switch User / Log Out / Cancel / Unlock) -- upstream never
# shipped one, and it was lost when this machine moved from light-locker
# (whose lock screen was really the LightDM greeter, with its own power
# indicator) to xfce4-screensaver. Rebuilds the package from Debian
# source with shutdown-button.patch applied. See
# lib/build-xfce4-screensaver-shutdown-button.sh.
# Also fixes a related shutdown delay: gvfsd-trash can wedge probing
# /boot/efi's trash dir (root-only permissions) and needs SIGKILLing at
# stop, adding up to 90s to every shutdown.
# Idempotent: safe to re-run (rebuilds and reinstalls each time).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/30-lockscreen-shutdown-button.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : adding shutdown button to lock screen ==="
bash "$DIR/lib/build-xfce4-screensaver-shutdown-button.sh"
