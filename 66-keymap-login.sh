#!/bin/bash
# Installs the login step that loads /etc/default/keyboard's layout into X's
# main keyboard (see lib/cyberbeest-keymap-login.sh for the why: y/z swapped
# in text typed by Dictate on a German layout). Idempotent.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/66-keymap-login.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date) : installing keyboard layout login step ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin" "$TARGET_HOME/.config/autostart"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest-keymap-login.sh" "$TARGET_HOME/.local/bin/cyberbeest-keymap-login.sh"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-keymap-login.desktop" \
    > "$TARGET_HOME/.config/autostart/cyberbeest-keymap-login.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-keymap-login.desktop"
echo "=== $(date) : done (takes effect at next login) ==="
