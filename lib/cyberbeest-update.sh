#!/bin/bash
# Cyberbeest Update (Whisker menu entry, installed by 52-cyberbeest-update.sh):
# pulls the latest commits into whichever provisioning checkout this machine
# tracks, then opens run-gui.py straight into "Run changed only" so anything
# new gets applied without the user having to find and click that button
# themselves.
#
# Confirms first via zenity: the git pull itself is harmless, but the
# NN-*.sh scripts it may then run are not (they change system config), so
# the user should see what's about to happen rather than have it start
# on a stray click of the menu entry.
set -euo pipefail
. "$(cd "$(dirname "$0")" && pwd)/i18n.sh"

REPO_DIR=""
for candidate in "$HOME/provisioning" "$HOME/provisioning-bleeding"; do
	if [ -d "$candidate/.git" ]; then
		REPO_DIR="$candidate"
		break
	fi
done

if [ -z "$REPO_DIR" ]; then
	zenity --error --title="$(t update.title)" --width=380 --text="$(t update.no_repo_message)"
	exit 1
fi

# Whichever branch beestify.sh (stable) or beestify-bleeding.sh (main) left
# this checkout on -- reset --hard below stays correct either way.
BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

confirm_msg="$(t update.confirm_message)"
confirm_msg="${confirm_msg//BRANCH/$BRANCH}"
zenity --question --title="$(t update.title)" --width=380 --text="$confirm_msg" || exit 0

# reset --hard (not merge --ff-only): a plain fast-forward only touches
# paths that actually changed in the new commits, so a tracked file that
# got deleted or hand-edited locally -- by accident, or by an older/buggy
# NN-*.sh -- stays that way forever even though the branch pointer moves.
# This is meant to make the checkout match upstream exactly, the same as a
# fresh clone would, so hard-reset it instead. No local commits or edits
# are expected on an end-user checkout, so there's nothing legitimate this
# could discard.
#
# A pulsating progress dialog while the fetch/reset runs -- without this,
# a slow connection leaves the user staring at nothing for several seconds
# after confirming, easy to mistake for the tool having silently died.
# Closed by killing the process directly (not by closing its stdin) since
# --pulsate mode doesn't reliably exit on EOF the way percentage mode does.
zenity --progress --title="$(t update.title)" --text="$(t update.progress_message)" \
	--pulsate --no-cancel --width=380 &
progress_pid=$!
progress_started_at=$(date +%s%N)

# On a fast (e.g. LAN) connection the fetch/reset below can finish in well
# under a second, closing the dialog before it's even had a chance to
# render -- just a flash in the taskbar, easy to mistake for nothing having
# happened at all. Padding out to a fixed minimum keeps it visible
# regardless of how fast the actual work was.
wait_out_min_progress_time() {
	local min_ms=600
	local elapsed_ms=$(( ($(date +%s%N) - progress_started_at) / 1000000 ))
	if [ "$elapsed_ms" -lt "$min_ms" ]; then
		sleep "0.$(printf '%03d' $((min_ms - elapsed_ms)))"
	fi
}

if ! PULL_OUTPUT="$(git -C "$REPO_DIR" fetch origin "$BRANCH" 2>&1 && git -C "$REPO_DIR" reset --hard "origin/$BRANCH" 2>&1)"; then
	wait_out_min_progress_time
	kill "$progress_pid" 2>/dev/null || true
	failed_msg="$(t update.pull_failed_message)"
	zenity --error --title="$(t update.title)" --width=460 --text="${failed_msg//OUTPUT/$PULL_OUTPUT}"
	exit 1
fi

wait_out_min_progress_time
kill "$progress_pid" 2>/dev/null || true

exec python3 "$REPO_DIR/run-gui.py" --run-changed
