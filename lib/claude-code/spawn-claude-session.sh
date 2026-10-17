#!/bin/bash
# Starts a new, separate Claude Code session with an initial prompt.
#
#   spawn-claude-session.sh [-n NAME] [-d DIR] [-m MODEL] [--bg] [-f PROMPTFILE | PROMPT...] [-- EXTRA CLAUDE ARGS]
#
# Default (visible): opens an xfce4-terminal window running an interactive
# `claude` with the prompt already submitted. You can watch it, answer its
# permission prompts and talk to it; other sessions can reach it by name via
# SendMessage/ListAgents. The window stays open (as a shell) after claude exits.
#
# --bg (headless): runs `claude -p` detached, output in
# ~/claude/.sessions/NAME-TIMESTAMP.log. Nothing can answer permission prompts
# in this mode, so the session only gets the tools you pre-allow, e.g.
#   spawn-claude-session.sh --bg -n probe "..." -- --allowedTools "Bash(ls:*)" "Read"
# It never uses --dangerously-skip-permissions; pass that yourself after `--`
# if you really want it.
#
# The prompt goes through a file, so quoting never matters. Sessions start in
# DIR (default: the current directory) with that directory's CLAUDE.md, memory
# and permissions, exactly like a session you started by hand.
set -euo pipefail

NAME="" DIR="$PWD" MODEL="" BG=0 PROMPT_FILE="" EXTRA=()
while [ $# -gt 0 ]; do
	case "$1" in
	-n | --name) NAME="$2"; shift 2 ;;
	-d | --dir) DIR="$2"; shift 2 ;;
	-m | --model) MODEL="$2"; shift 2 ;;
	-f | --file) PROMPT_FILE="$2"; shift 2 ;;
	--bg) BG=1; shift ;;
	--) shift; EXTRA=("$@"); break ;;
	-h | --help) sed -n '2,22p' "$0"; exit 0 ;;
	-*) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
	*) break ;;
	esac
done

STATE_DIR="$HOME/claude/.sessions"
mkdir -p "$STATE_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
[ -n "$NAME" ] || NAME="session-$STAMP"
SAFE_NAME="$(printf '%s' "$NAME" | tr -c 'A-Za-z0-9._-' '_')"

if [ -z "$PROMPT_FILE" ]; then
	[ $# -gt 0 ] || { echo "no prompt given (pass text or -f FILE)" >&2; exit 2; }
	PROMPT_FILE="$STATE_DIR/$SAFE_NAME-$STAMP.prompt"
	printf '%s\n' "$*" >"$PROMPT_FILE"
fi
[ -r "$PROMPT_FILE" ] || { echo "cannot read prompt file: $PROMPT_FILE" >&2; exit 2; }
# The session starts inside DIR, so a relative path would no longer resolve there.
PROMPT_FILE="$(realpath "$PROMPT_FILE")"
[ -d "$DIR" ] || { echo "no such directory: $DIR" >&2; exit 2; }
CLAUDE_BIN="$(command -v claude)" || { echo "claude not found in PATH" >&2; exit 1; }

ARGS=(--name "$NAME")
[ -z "$MODEL" ] || ARGS+=(--model "$MODEL")
ARGS+=("${EXTRA[@]}")

if [ "$BG" -eq 1 ]; then
	LOG="$STATE_DIR/$SAFE_NAME-$STAMP.log"
	(cd "$DIR" && nohup setsid "$CLAUDE_BIN" -p "${ARGS[@]}" "$(cat "$PROMPT_FILE")" >"$LOG" 2>&1 </dev/null &)
	echo "started headless session '$NAME' in $DIR"
	echo "log: $LOG"
else
	: "${DISPLAY:=:0}"
	export DISPLAY
	command -v xfce4-terminal >/dev/null || { echo "xfce4-terminal not found (use --bg)" >&2; exit 1; }
	# $0/$1... inside bash -c are passed as separate arguments: no quoting issues.
	setsid nohup xfce4-terminal --icon=claude-code --title "claude: $NAME" --working-directory "$DIR" \
		-x bash -c 'bin="$1"; pf="$2"; shift 2; "$bin" "$@" "$(cat "$pf")"; echo; echo "[session ended - shell stays open]"; exec bash' \
		_ "$CLAUDE_BIN" "$PROMPT_FILE" "${ARGS[@]}" >/dev/null 2>&1 &
	echo "opened a terminal window for session '$NAME' in $DIR"
fi
