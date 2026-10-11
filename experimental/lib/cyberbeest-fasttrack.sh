#!/bin/bash
# Cyberbeest Fast Track watcher (installed to ~/.local/bin by
# experimental/enable-cyberbeest-fast-track.sh, started at login via XDG
# autostart). Long-running: about once a minute it reads the newest commit of
# the provisioning "main" branch from the Cyberbeest v-server
# (https://downloads.cyberbeest.com/fasttrack/main, a 41-byte file the server
# refreshes from GitHub every 2 minutes) and compares it with this machine's
# checkout. When there is something new it runs `cyberbeest-update.sh
# --fast-track`: the usual update dialog, and after "yes" the changed scripts
# run without a further click.
#
# The server file is only a doorbell. It must look like a 40-hex commit id and
# is used for nothing but deciding whether to show the dialog; what gets
# applied always comes from GitHub, via the update script's own git fetch.
#
# A commit that was shown once (confirmed or declined) isn't offered again;
# the next push rings again. Only for a checkout on "main" (beta track).
# Paused via the panel icon's menu (~/.local/state/cyberbeest-fasttrack/paused)
# or system-wide with /etc/cyberbeest/fasttrack-disabled.
set -uo pipefail

URL="${CYBERBEEST_FASTTRACK_URL:-https://downloads.cyberbeest.com/fasttrack/main}"
INTERVAL="${CYBERBEEST_FASTTRACK_INTERVAL:-60}"
STATE_DIR="$HOME/.local/state/cyberbeest-fasttrack"
UPDATER="$(dirname "$(readlink -f "$0")")/cyberbeest-update.sh"
mkdir -p "$STATE_DIR"

exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0

find_repo() {
	local d
	for d in "$HOME/provisioning-bleeding" "$HOME/provisioning"; do
		if [ -d "$d/.git" ]; then echo "$d"; return; fi
	done
}

while :; do
	sleep "$INTERVAL"
	[ -e /etc/cyberbeest/fasttrack-disabled ] && continue
	[ -e "$STATE_DIR/paused" ] && continue
	repo="$(find_repo)"
	[ -n "$repo" ] || continue
	[ "$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)" = main ] || continue

	remote="$(curl -fsS --max-time 20 --connect-timeout 10 --max-filesize 256 \
		--proto '=https' --max-redirs 0 -A cyberbeest-fasttrack/1 "$URL" 2>/dev/null | tr -d '[:space:]')"
	[[ "$remote" =~ ^[0-9a-f]{40}$ ]] || continue

	echo "$remote" > "$STATE_DIR/remote"   # read by the panel icon

	local_head="$(git -C "$repo" rev-parse HEAD 2>/dev/null)" || continue
	[ "$remote" = "$local_head" ] && continue
	[ "$remote" = "$(cat "$STATE_DIR/offered" 2>/dev/null)" ] && continue
	# Already contained locally (checkout is ahead of the server's view).
	git -C "$repo" merge-base --is-ancestor "$remote" HEAD 2>/dev/null && continue

	echo "$remote" > "$STATE_DIR/offered"
	"$UPDATER" --fast-track
done
