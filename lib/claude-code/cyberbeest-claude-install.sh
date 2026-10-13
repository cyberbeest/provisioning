#!/bin/bash
# "Install Claude Code" menu entry (installed by 68-claude-code-launchers.sh).
#
# Opt-in only: no numbered provisioning step runs this. Shows a big privacy
# warning first (Claude Code sends everything it works on to Anthropic's
# servers), and does nothing unless the user clicks "I understand".
#
# Runs as the normal user, NOT root: the official installer refuses sudo and
# everything lands under $HOME, so cyberbeest-claude-remove.sh can take it all
# out again. Installs:
#   - Claude Code itself (official installer from claude.ai/install.sh)
#   - ~/claude: working folder with a CLAUDE.md for the sudo-helper convention
#     (RUNME markers), the sudo helper daemon (autostarted), Claude Sessions
#     window, spawn-claude-session.sh, claude-stop.sh, wait-for-runme.sh
#   - spoken replies: speak-replies mod + Piper TTS (runs locally), /voice toggles
#   - a "Claude Code" menu entry that opens a terminal in ~/claude
# Idempotent: safe to re-run. Adds only what is missing (icons, launchers, voices,
# venv, CLAUDE.md, settings entries); the scripts we ship are refreshed.
set -uo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
. "$DIR/../i18n.sh"

if [ "$(id -u)" -eq 0 ]; then
	echo "Run this as your normal user, not with sudo." >&2
	exit 1
fi

STATE="$HOME/.local/share/cyberbeest"
LOG="$STATE/claude-code-install.log"
mkdir -p "$STATE"
WORK="$HOME/claude"
TTS="$HOME/.local/share/claude-tts"
APPS="$HOME/.local/share/applications"
HF=https://huggingface.co/rhasspy/piper-voices/resolve/main

if ! zenity --question --default-cancel --width=560 \
	--title="$(t claude.warn_title)" \
	--text="$(t claude.warn_message)" \
	--ok-label="$(t claude.warn_install)" \
	--cancel-label="$(t claude.warn_cancel)"; then
	exit 0
fi

install_all() {
	set -euo pipefail
	echo "=== $(date) : installing Claude Code ==="

	echo "--- Claude Code (official installer) ---"
	if [ ! -x "$HOME/.local/bin/claude" ]; then
		curl -fsSL https://claude.ai/install.sh | bash
	else
		echo "already installed"
	fi
	[ -x "$HOME/.local/bin/claude" ]

	echo "--- Working folder $WORK ---"
	install -d "$WORK"
	for f in claude-sessions-gui.py spawn-claude-session.sh claude-stop.sh \
		claude-sudo-helper-gui.sh claude-sudo-helper-confirm-toggle.sh wait-for-runme.sh; do
		install -m 755 "$DIR/$f" "$WORK/$f"
	done
	if [ ! -e "$WORK/CLAUDE.md" ]; then
		install -m 644 "$DIR/CLAUDE.md.template" "$WORK/CLAUDE.md"
	fi
	# Record what we put in ~/claude, so removal never guesses.
	printf '%s\n' claude-sessions-gui.py spawn-claude-session.sh claude-stop.sh \
		claude-sudo-helper-gui.sh claude-sudo-helper-confirm-toggle.sh wait-for-runme.sh \
		> "$STATE/claude-code-files.txt"

	echo "--- Icons, autostart + menu entries (each only if missing) ---"
	ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"
	install -d "$HOME/.config/autostart" "$APPS" "$ICONS"
	for i in claude-code claude-sessions; do
		[ -e "$ICONS/$i.png" ] || install -m 644 "$DIR/icons/$i.png" "$ICONS/$i.png"
	done
	# put_if_missing FILE < content: adds a missing launcher, keeps an existing one.
	# Exception: an entry still carrying a generic icon from an earlier version of
	# this installer is replaced, so it picks up the blue icon.
	put_if_missing() {
		if [ ! -e "$1" ]; then
			cat > "$1"; echo "added $(basename "$1")"
		elif grep -qE '^Icon=(utilities-terminal|utilities-system-monitor)$' "$1"; then
			cat > "$1"; echo "updated $(basename "$1") (new icon)"
		else
			cat >/dev/null; echo "have $(basename "$1")"
		fi
	}
	put_if_missing "$HOME/.config/autostart/claude-sudo-helper-gui.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude sudo helper (GUI)
Comment=Watches ~/claude for RUNME-* scripts from Claude and asks before running them as root.
Exec=$WORK/claude-sudo-helper-gui.sh
X-GNOME-Autostart-Phase=Application
NoDisplay=true
EOF
	put_if_missing "$APPS/cyberbeest-claude-code.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Code
Comment=Cloud AI assistant (sends your work to Anthropic)
Exec=xfce4-terminal --working-directory=$WORK --title="Claude Code" -e "bash -ic claude"
Icon=claude-code
Terminal=false
Categories=Utility;
EOF
	put_if_missing "$APPS/cyberbeest-claude-sessions.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Sessions
Comment=Live list of all Claude Code sessions with their last message
Exec=$WORK/claude-sessions-gui.py
Icon=claude-sessions
Terminal=false
Categories=Utility;
EOF

	echo "--- Spoken replies (Piper, local) ---"
	install -d "$TTS"
	install -m 755 "$DIR/speak.py" "$DIR/synth.py" "$DIR/gen_sounds.py" "$TTS/"
	python3 "$TTS/gen_sounds.py"  # message-type beeps, synthesized (no audio files in the repo)
	if [ ! -x "$TTS/venv/bin/python" ]; then
		python3 -m venv "$TTS/venv"
	fi
	"$TTS/venv/bin/python" -c 'import piper' 2>/dev/null || "$TTS/venv/bin/pip" install --quiet 'piper-tts==1.8.0'
	for v in en/en_GB/alan/medium/en_GB-alan-medium de/de_DE/thorsten/medium/de_DE-thorsten-medium; do
		n="$(basename "$v")"
		for ext in onnx onnx.json; do
			if [ ! -s "$TTS/$n.$ext" ]; then
				curl -fsSL -o "$TTS/$n.$ext.part" "$HF/$v.$ext"
				mv "$TTS/$n.$ext.part" "$TTS/$n.$ext"
			fi
		done
	done

	echo "--- speak-replies mod + settings ---"
	MODS="$HOME/.claude/local-mods"
	install -d "$MODS/.claude-plugin" "$MODS/mods"
	cp -r "$DIR/mod/speak-replies" "$MODS/mods/"
	sed -i "s#@HOME@#$HOME#g" "$MODS/mods/speak-replies/hooks/register.ts"
	cp "$DIR/mod/marketplace.json" "$MODS/.claude-plugin/marketplace.json"
	python3 - "$HOME" <<'PY'
import json, os, sys
home = sys.argv[1]
p = os.path.join(home, ".claude", "settings.json")
try:
    s = json.load(open(p))
except (OSError, ValueError):
    s = {}
s.setdefault("enabledPlugins", {})["speak-replies@local-mods"] = True
s.setdefault("extraKnownMarketplaces", {})["local-mods"] = {
    "source": {"source": "directory", "path": os.path.join(home, ".claude", "local-mods")}}
s.setdefault("theme", "dark")
tmp = p + ".tmp"
json.dump(s, open(tmp, "w"), indent=2)
os.replace(tmp, p)
PY

	echo "--- Starting the sudo helper ---"
	pgrep -f '[c]laude-sudo-helper-gui.sh' >/dev/null || \
		(setsid "$WORK/claude-sudo-helper-gui.sh" >/dev/null 2>&1 &)
	command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
	echo "=== $(date) : done ==="
}

# --pulsate progress; install_all's output goes to the log only.
(
	install_all >>"$LOG" 2>&1
	echo $? > "$STATE/.claude-install-rc"
) | zenity --progress --pulsate --auto-close --no-cancel --width=420 \
	--title="$(t claude.warn_title)" --text="$(t claude.installing)" >/dev/null 2>&1

rc="$(cat "$STATE/.claude-install-rc" 2>/dev/null || echo 1)"
rm -f "$STATE/.claude-install-rc"
if [ "$rc" -eq 0 ]; then
	zenity --info --width=420 --title="$(t claude.install_done_title)" \
		--text="$(t claude.install_done_message)"
else
	zenity --error --width=420 --title="$(t claude.install_failed_title)" \
		--text="$(t claude.install_failed_message | sed "s#LOG#$LOG#")"
	exit 1
fi
