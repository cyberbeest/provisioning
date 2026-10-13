#!/bin/bash
# Puts two menu entries on the machine: "Install Claude Code (cloud AI)" and
# "Remove Claude Code". Does NOT install Claude Code: it is a cloud service that
# sends everything it works on to Anthropic, which contradicts Cyberbeest's
# privacy defaults, so it is opt-in. The install entry shows a big privacy
# warning first (lib/claude-code/cyberbeest-claude-install.sh); the remove entry
# deletes everything again (lib/claude-code/cyberbeest-claude-remove.sh).
# The entries point at this checkout's lib/claude-code/, so Cyberbeest Update
# keeps the scripts current.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/68-claude-code-launchers.log"
exec > >(tee -a "$LOG") 2>&1
. "$DIR/lib/i18n.sh"

echo "=== $(date) : Claude Code install/remove menu entries ==="
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
APPS="$TARGET_HOME/.local/share/applications"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APPS"
chmod 755 "$DIR/lib/claude-code/"cyberbeest-claude-*.sh

write_entry() { # file name comment script
	cat > "$APPS/$1" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$DIR/lib/claude-code/$4
Icon=$5
Terminal=false
Categories=Utility;
EOF
	chown "$TARGET_USER:$TARGET_USER" "$APPS/$1"
}

if [ "$(_i18n_locale)" = "de" ]; then
	write_entry cyberbeest-claude-install.desktop "Claude Code installieren (Cloud-KI)" \
		"Cloud-KI-Assistent; schickt deine Arbeit an Anthropic. Zeigt zuerst eine Datenschutz-Warnung." \
		cyberbeest-claude-install.sh dialog-warning
	write_entry cyberbeest-claude-remove.desktop "Claude Code entfernen" \
		"Löscht Claude Code und alles Zugehörige vollständig" cyberbeest-claude-remove.sh edit-delete
else
	write_entry cyberbeest-claude-install.desktop "Install Claude Code (cloud AI)" \
		"Cloud AI assistant; sends your work to Anthropic. Shows a privacy warning first." \
		cyberbeest-claude-install.sh dialog-warning
	write_entry cyberbeest-claude-remove.desktop "Remove Claude Code" \
		"Deletes Claude Code and everything that came with it" cyberbeest-claude-remove.sh edit-delete
fi
echo "=== done ==="
