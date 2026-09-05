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
# this checkout on -- ff-only below stays correct either way.
BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

confirm_msg="$(t update.confirm_message)"
confirm_msg="${confirm_msg//BRANCH/$BRANCH}"
zenity --question --title="$(t update.title)" --width=380 --text="$confirm_msg" || exit 0

if ! PULL_OUTPUT="$(git -C "$REPO_DIR" fetch origin "$BRANCH" 2>&1 && git -C "$REPO_DIR" merge --ff-only "origin/$BRANCH" 2>&1)"; then
	failed_msg="$(t update.pull_failed_message)"
	zenity --error --title="$(t update.title)" --width=460 --text="${failed_msg//OUTPUT/$PULL_OUTPUT}"
	exit 1
fi

exec python3 "$REPO_DIR/run-gui.py" --run-changed
