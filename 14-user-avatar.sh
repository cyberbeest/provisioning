#!/bin/bash
# Sets the desktop account's avatar (greeter/user-switcher photo) to the
# Cyberbeest mascot, matching this dev machine's ~/.face -- see
# lib/assets/cyberbeest-face.png.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/14-user-avatar.log"
exec > "$LOG" 2>&1

echo "=== $(date) : setting user avatar ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing ~/.face (read directly by most greeters) ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/cyberbeest-face.png" "$TARGET_HOME/.face"

echo "--- Installing AccountsService icon (used by LightDM/GDM user list) ---"
install -d -m 755 /var/lib/AccountsService/icons
install -m 644 "$DIR/lib/assets/cyberbeest-face.png" "/var/lib/AccountsService/icons/$TARGET_USER"

echo "--- Pointing AccountsService's user record at it ---"
install -d -m 755 /var/lib/AccountsService/users
USER_FILE="/var/lib/AccountsService/users/$TARGET_USER"
if [ -e "$USER_FILE" ] && grep -q '^Icon=' "$USER_FILE"; then
	sed -i "s|^Icon=.*|Icon=/var/lib/AccountsService/icons/$TARGET_USER|" "$USER_FILE"
elif [ -e "$USER_FILE" ]; then
	printf 'Icon=/var/lib/AccountsService/icons/%s\n' "$TARGET_USER" >> "$USER_FILE"
else
	cat > "$USER_FILE" <<EOF
[User]
Icon=/var/lib/AccountsService/icons/$TARGET_USER
SystemAccount=false
EOF
fi
chmod 644 "$USER_FILE"

echo "=== $(date) : done ==="
