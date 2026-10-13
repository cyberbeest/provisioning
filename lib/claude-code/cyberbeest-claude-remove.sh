#!/bin/bash
# "Remove Claude Code" menu entry (installed by 68-claude-code-launchers.sh).
# Undoes cyberbeest-claude-install.sh completely, plus what Claude Code
# created itself: program, versions, ~/.claude (settings, login, history),
# ~/.claude.json, caches, URL handler, daemon, TTS venv + voices, mod, menu and
# autostart entries, the sudo helper. In ~/claude only the files the installer
# recorded are removed; if anything else is left there it asks before deleting
# the folder (default: keep), and whether to keep the conversation history in
# ~/.claude/projects (default: keep). Runs as the normal user.
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

zenity --question --default-cancel --width=480 \
	--title="$(t claude.remove_title)" --text="$(t claude.remove_message)" \
	--ok-label="$(t claude.remove_button)" --cancel-label="$(t claude.remove_cancel)" || exit 0

# Ask about the work folder up front (before anything is deleted), but only
# if there will be something else left in it.
delete_workdir=0
if [ -d "$WORK" ]; then
	leftover="$(cd "$WORK" && find . -mindepth 1 -maxdepth 1 \
		! -name CLAUDE.md ! -name 'claude-sudo-helper-gui.*' ! -name '.sessions' \
		-print 2>/dev/null | sed 's#^\./##' | sort)"
	if [ -f "$STATE/claude-code-files.txt" ]; then
		leftover="$(grep -vxFf "$STATE/claude-code-files.txt" <<<"$leftover" || true)"
	fi
	if [ -n "$leftover" ]; then
		zenity --question --default-cancel --width=460 \
			--title="$(t claude.remove_workdir_title)" --text="$(t claude.remove_workdir_message)" \
			--ok-label="$(t claude.remove_workdir_delete)" --cancel-label="$(t claude.remove_workdir_keep)" \
			&& delete_workdir=1
	fi
fi

# Conversation history (session transcripts, auto-memory, prompt history) can
# stay behind: a later reinstall picks the sessions up again. Default: keep.
keep_history=0
if [ -d "$HOME/.claude/projects" ] || [ -f "$HOME/.claude/history.jsonl" ]; then
	zenity --question --default-cancel --width=460 \
		--title="$(t claude.remove_history_title)" --text="$(t claude.remove_history_message)" \
		--ok-label="$(t claude.remove_history_delete)" --cancel-label="$(t claude.remove_history_keep)" \
		|| keep_history=1
fi

remove_all() {
	echo "=== $(date) : removing Claude Code ==="

	echo "--- stopping Claude Code and the sudo helper ---"
	if command -v claude >/dev/null 2>&1; then
		claude daemon stop --any || true
		sleep 2
	fi
	pkill -f '[c]laude-sudo-helper-gui.sh' || true
	pkill -f '[c]laude-sessions-gui.py' || true
	pkill -f '[c]laude-tts/speak.py' || true
	# Bracket trick: the pattern must not match this script's own command line.
	rem="$(pgrep -f '\.local/bin/clau[d]e|\.local/share/clau[d]e/versions/' || true)"
	[ -n "$rem" ] && { kill $rem 2>/dev/null; sleep 1; kill -9 $rem 2>/dev/null; } || true

	echo "--- files in $WORK ---"
	if [ -f "$STATE/claude-code-files.txt" ]; then
		while IFS= read -r f; do
			[ -n "$f" ] && rm -f -- "$WORK/$f"
		done < "$STATE/claude-code-files.txt"
	fi
	rm -f -- "$WORK"/claude-sudo-helper-gui.* "$WORK/CLAUDE.md"
	rm -rf --one-file-system -- "$WORK/.sessions"
	if [ "$delete_workdir" -eq 1 ]; then
		rm -rf --one-file-system -- "$WORK"
	else
		rmdir "$WORK" 2>/dev/null || echo "kept $WORK (not empty)"
	fi

	echo "--- Claude Code itself ---"
	rm -rf --one-file-system -- "$HOME/.local/share/claude" \
		"$HOME/.cache/claude" "$HOME/.cache/claude-cli-nodejs" "$HOME/.local/state/claude"
	if [ "$keep_history" -eq 1 ]; then
		# everything in ~/.claude except the transcripts/memory and prompt history
		find "$HOME/.claude" -mindepth 1 -maxdepth 1 ! -name projects ! -name history.jsonl \
			-exec rm -rf --one-file-system -- {} +
		echo "kept conversation history in $HOME/.claude"
	else
		rm -rf --one-file-system -- "$HOME/.claude"
	fi
	rm -f -- "$HOME/.local/bin/claude" "$HOME/.claude.json" "$HOME"/.claude.json.*
	rm -f -- "$APPS/claude-code-url-handler.desktop"

	echo "--- Cyberbeest additions ---"
	rm -rf --one-file-system -- "$HOME/.local/share/claude-tts"
	rm -f -- "$HOME/.config/autostart/claude-sudo-helper-gui.desktop" \
		"$APPS/cyberbeest-claude-code.desktop" "$APPS/cyberbeest-claude-sessions.desktop" \
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
