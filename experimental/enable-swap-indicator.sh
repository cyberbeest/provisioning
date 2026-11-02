#!/bin/bash
# EXPERIMENTAL: swap indicator panel icon (genmon plugin-231). A red square
# (darker towards the corners) that lights up whenever anything is swapped in
# or out and slowly shrinks and fades until it disappears again. Driven by the
# pswpin/pswpout counters in /proc/vmstat; no daemon, the genmon script
# (lib/swap-indicator-genmon.sh, 1 s) keeps its own state file under
# $XDG_RUNTIME_DIR. Frames are pre-rendered by lib/swap-indicator-icons/generate.py.
#
# Usage: sudo bash enable-swap-indicator.sh
# Undo:  sudo bash disable-swap-indicator.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-swap-indicator.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing swap indicator ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
BIN="$TARGET_HOME/.local/bin"
SHARE="$TARGET_HOME/.local/share/cyberbeest-swap-indicator"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$BIN" "$SHARE"
for f in swap-indicator-genmon.sh swap-indicator-panel-icon.sh; do
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/$f" "$BIN/$f"
done
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/lib/swap-indicator-icons/swap-*.png "$SHARE/"

echo "--- Adding the panel icon ---"
sudo -u "$TARGET_USER" env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="$TARGET_HOME/.Xauthority" \
	DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$TARGET_USER")/bus" \
	"$BIN/swap-indicator-panel-icon.sh" add || echo "panel icon not added now (no session?) -- re-run in a graphical session"

echo "=== $(date) : done ==="
