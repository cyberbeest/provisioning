#!/bin/bash
# Whisker menu otherwise lists three terminal emulators: Xfce Terminal
# (xfce4-terminal, the actual full-featured GTK terminal and already the
# system default), XTerm, and UXTerm (xterm forced into UTF-8 mode -- pointless
# once the system locale is already UTF-8). Hides XTerm and UXTerm from the
# menu via local .desktop overrides (NoDisplay=true) rather than uninstalling
# the xterm package, which stays installed as an xorg/xinit dependency and a
# useful fallback if the GTK stack ever breaks. Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/45-hide-redundant-terminals.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : hiding redundant terminal emulators from the app menu ==="
TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"

for f in debian-xterm debian-uxterm; do
	src="/usr/share/applications/$f.desktop"
	dest="$TARGET_HOME/.local/share/applications/$f.desktop"
	if [ -f "$src" ]; then
		cp "$src" "$dest"
		if grep -q '^NoDisplay=' "$dest"; then
			sed -i 's/^NoDisplay=.*/NoDisplay=true/' "$dest"
		else
			echo 'NoDisplay=true' >> "$dest"
		fi
		chown "$TARGET_USER:$TARGET_USER" "$dest"
		echo "hid $f.desktop"
	else
		echo "skipping $f: $src not found"
	fi
done

command -v update-desktop-database >/dev/null 2>&1 && \
	su - "$TARGET_USER" -c "update-desktop-database '$TARGET_HOME/.local/share/applications' 2>/dev/null" || true

echo "=== $(date) : done ==="
