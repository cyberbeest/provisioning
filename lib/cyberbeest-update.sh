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

REPO_DIR=""
for candidate in "$HOME/provisioning" "$HOME/provisioning-bleeding"; do
	if [ -d "$candidate/.git" ]; then
		REPO_DIR="$candidate"
		break
	fi
done

if [ -z "$REPO_DIR" ]; then
	zenity --error --title="Cyberbeest Update" --width=380 \
		--text="No provisioning checkout found at ~/provisioning or ~/provisioning-bleeding.

Run beestify.sh first (see cyberbeest.com)."
	exit 1
fi

# Whichever branch beestify.sh (stable) or beestify-bleeding.sh (main) left
# this checkout on -- ff-only below stays correct either way.
BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

zenity --question --title="Cyberbeest Update" --width=380 --text="Pull the latest Cyberbeest provisioning updates ($BRANCH branch) and apply anything new?

You'll be asked for your password once per changed step, same as during setup." || exit 0

if ! PULL_OUTPUT="$(git -C "$REPO_DIR" fetch origin "$BRANCH" 2>&1 && git -C "$REPO_DIR" merge --ff-only "origin/$BRANCH" 2>&1)"; then
	zenity --error --title="Cyberbeest Update" --width=460 \
		--text="git pull failed:

$PULL_OUTPUT"
	exit 1
fi

exec python3 "$REPO_DIR/run-gui.py" --run-changed
