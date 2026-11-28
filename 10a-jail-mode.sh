#!/bin/bash
# App-protection (jail) mode: all apps / only chosen apps / none.
#
# Installs the shared jail-lib.sh that every *-sandbox.sh wrapper sources
# (so each app can run with or without firejail), the settings dialog, the
# panel icon (genmon-222: lock = all, lock + n/m = some, open lock = none),
# and the generator for the two Firefox menu entries ("Firefox (protected)" /
# "Firefox (unprotected)") plus the hidden entry that opens html files
# double-clicked in Files in the UNPROTECTED browser (a jailed Firefox cannot
# see files outside Downloads/Pictures).
#
# Default is "all" (unchanged behavior). Config: ~/.config/cyberbeest/jail.conf
# Runs right after 10-browser-sandbox.sh and before 11*/12 (the panel layout
# wires plugin-222, whose script and rc must already exist) and before the
# 38/39/40* app wrappers, which source ~/bin/jail-lib.sh.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/10a-jail-mode.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing jail-mode support ==="
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
GENMON_WIDGET="genmon-222"

U() { install -o "$TARGET_USER" -g "$TARGET_USER" "$@"; }

echo "--- Installing jail-lib / jail-apply to $TARGET_HOME/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin" "$TARGET_HOME/.local/bin"
U -m 644 "$DIR/lib/jail-lib.sh" "$TARGET_HOME/bin/jail-lib.sh"
U -m 755 "$DIR/lib/jail-apply.sh" "$TARGET_HOME/bin/jail-apply.sh"
# The wrappers installed by 10-browser-sandbox.sh predate this script on a
# fresh run; reinstall the ones that now need jail-lib (idempotent).
U -m 755 "$DIR/lib/browser-sandbox.sh" "$TARGET_HOME/bin/browser-sandbox.sh"
U -m 755 "$DIR/lib/browser-unsandboxed.sh" "$TARGET_HOME/bin/browser-unsandboxed.sh"

echo "--- Installing settings dialog and panel icon script ---"
U -m 755 "$DIR/lib/jail-settings.py" "$TARGET_HOME/.local/bin/jail-settings.py"
U -m 755 "$DIR/lib/jail-status-genmon.sh" "$TARGET_HOME/.local/bin/jail-status-genmon.sh"
U -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
U -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
U -m 644 "$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" \
	"$DIR/lib/i18n/strings_en.py" "$DIR/lib/i18n/strings_de.py" "$TARGET_HOME/.local/bin/i18n/"

echo "--- Writing $GENMON_WIDGET.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$DIR/lib/xfce-panel-layout/jail-status-genmon.rc.template" \
	> "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"

echo "--- Generating the Firefox menu entries for the current mode ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
su - "$TARGET_USER" -c "'$TARGET_HOME/bin/jail-apply.sh'" || echo "warning: jail-apply.sh failed" >&2

echo "=== $(date) : done ==="
