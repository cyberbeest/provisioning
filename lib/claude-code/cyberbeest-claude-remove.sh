#!/bin/bash
# "Remove Claude Code" menu entry (installed by 68-claude-code-launchers.sh).
# Undoes cyberbeest-claude-install.sh completely, plus what Claude Code
# created itself: program, versions, ~/.claude (settings, login, history),
# ~/.claude.json, caches, URL handler, daemon, TTS venv + voices, mod, menu and
# autostart entries, the sudo helper. In ~/claude only the files the installer
# recorded are removed; if anything else is left there it asks before deleting
# the folder. One choice: keep settings + projects (default) or remove everything.
# Runs as the normal user.
set -uo pipefail
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
. "$DIR/../i18n.sh"

[ "$(id -u)" -eq 0 ] && { echo "Run this as your normal user, not with sudo." >&2; exit 1; }
[ -n "${HOME:-}" ] && [ -d "$HOME" ] || exit 1

STATE="$HOME/.local/share/cyberbeest"
LOG="$STATE/claude-code-remove.log"
WORK="$HOME/claude"
APPS="$HOME/.local/share/applications"
mkdir -p "$STATE"

installed=0
for p in "$HOME/.local/bin/claude" "$HOME/.local/share/claude" "$HOME/.claude" "$HOME/.claude.json" \
	"$HOME/.local/share/claude-tts" "$STATE/claude-code-files.txt"; do
	[ -e "$p" ] && installed=1
done
if [ "$installed" -eq 0 ]; then
	zenity --info --width=380 --title="$(t claude.remove_title)" --text="$(t claude.remove_none_message)"
	exit 0
fi

# One dialog, one choice. zenity prints the extra button's label and exits 1
# for it; OK exits 0 (keep my data, the default), Cancel exits 1 with no output.
out="$(zenity --question --width=520 \
	--title="$(t claude.remove_title)" --text="$(t claude.remove_message)" \
	--ok-label="$(t claude.remove_keep_button)" \
	--extra-button="$(t claude.remove_all_button)" \
	--cancel-label="$(t claude.remove_cancel)")"
rc=$?
keep_data=1
if [ "$rc" -ne 0 ]; then
	[ "$out" = "$(t claude.remove_all_button)" ] || exit 0
	keep_data=0
fi

# Last chance, naming exactly what is about to go.
if [ "$keep_data" -eq 1 ]; then
	confirm_text="$(t claude.remove_confirm_keep)"
else
	confirm_text="$(t claude.remove_confirm_all)"
fi
zenity --question --default-cancel --width=460 \
	--title="$(t claude.remove_confirm_title)" --text="$confirm_text" \
	--ok-label="$(t claude.remove_confirm_yes)" --cancel-label="$(t claude.remove_cancel)" || exit 0

remove_all() {
	echo "=== $(date) : removing Claude Code ==="

	echo "--- stopping Claude Code and the sudo helper ---"
	if command -v claude >/dev/null 2>&1; then
		claude daemon stop --any || true
		sleep 2
	fi
	pkill -f '[c]laude-sudo-helper-gui.sh' || true
	pkill -f '[c]laude-sessions-gui.py' || true
	pkill -f '[c]laude-tts/(speak|synth).py' || true
	# Bracket trick: the pattern must not match this script's own command line.
	rem="$(pgrep -f '\.local/bin/clau[d]e|\.local/share/clau[d]e/versions/' || true)"
	[ -n "$rem" ] && { kill $rem 2>/dev/null; sleep 1; kill -9 $rem 2>/dev/null; } || true

	echo "--- panel launchers ---"
	bash "$DIR/panel-launchers.sh" remove || true

	echo "--- files in $WORK ---"
	if [ -f "$STATE/claude-code-files.txt" ]; then
		while IFS= read -r f; do
			[ -n "$f" ] && rm -f -- "$WORK/$f"
		done < "$STATE/claude-code-files.txt"
	fi
	rm -f -- "$WORK"/claude-sudo-helper-gui.*
	if [ "$keep_data" -eq 1 ]; then
		# CLAUDE.md, .sessions and the user's own files stay
		rmdir "$WORK" 2>/dev/null || echo "kept $WORK (your projects)"
	else
		rm -rf --one-file-system -- "$WORK"
	fi

	echo "--- Claude Code itself ---"
	rm -rf --one-file-system -- "$HOME/.local/share/claude" \
		"$HOME/.cache/claude" "$HOME/.cache/claude-cli-nodejs" "$HOME/.local/state/claude"
	if [ "$keep_data" -eq 1 ]; then
		# Keep settings, instructions, conversation history; drop login, plugins and the rest.
		find "$HOME/.claude" -mindepth 1 -maxdepth 1 \
			! -name projects ! -name history.jsonl ! -name settings.json ! -name CLAUDE.md \
			! -name plans ! -name skills ! -name agents ! -name commands \
			-exec rm -rf --one-file-system -- {} +
		python3 - "$HOME/.claude/settings.json" <<'PY' || true
import json, sys
p = sys.argv[1]
try:
    s = json.load(open(p))
except (OSError, ValueError):
    sys.exit(0)
s.get("enabledPlugins", {}).pop("speak-replies@local-mods", None)
s.get("extraKnownMarketplaces", {}).pop("local-mods", None)
for k in ("enabledPlugins", "extraKnownMarketplaces"):
    if k in s and not s[k]:
        del s[k]
json.dump(s, open(p, "w"), indent=2)
PY
		echo "kept settings and conversation history in $HOME/.claude"
	else
		rm -rf --one-file-system -- "$HOME/.claude"
	fi
	rm -f -- "$HOME/.local/bin/claude" "$HOME/.claude.json" "$HOME"/.claude.json.*
	rm -f -- "$APPS/claude-code-url-handler.desktop"

	echo "--- Cyberbeest additions ---"
	rm -rf --one-file-system -- "$HOME/.local/share/claude-tts"
	rm -f -- "$HOME/.config/autostart/claude-sudo-helper-gui.desktop" \
		"$APPS/cyberbeest-claude-code.desktop" "$APPS/cyberbeest-claude-sessions.desktop" \
		"$HOME/.local/share/icons/hicolor/256x256/apps/claude-code.png" \
		"$HOME/.local/share/icons/hicolor/256x256/apps/claude-sessions.png" \
		"$STATE/claude-code-files.txt"
	# x-scheme-handler/claude-cli association Claude Code registered
	for m in "$HOME/.config/mimeapps.list" "$APPS/mimeapps.list"; do
		[ -f "$m" ] && sed -i '/^x-scheme-handler\/claude-cli=/d' "$m"
	done
	command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
	echo "=== $(date) : done ==="
}

remove_all >>"$LOG" 2>&1
zenity --info --width=380 --title="$(t claude.remove_done_title)" --text="$(t claude.remove_done_message)"
