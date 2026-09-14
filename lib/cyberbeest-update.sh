#!/bin/bash
# Cyberbeest Update (Whisker menu entry, installed by 52-cyberbeest-update.sh):
# pulls the latest commits into whichever provisioning checkout this machine
# tracks, then opens run-gui.py so the user can review and run whatever's
# new themselves. The confirm dialog also offers switching tracks (beta <->
# stable) instead, tucked into a dropdown -- see do_switch_track() below and
# lib/cyberbeest-update-confirm.py's docstring for why that's a small GTK
# dialog and not zenity.
#
# Confirms first: the git pull itself is harmless, but the NN-*.sh scripts
# it may then run are not (they change system config), so the user should
# see what's about to happen rather than have it start on a stray click of
# the menu entry.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/i18n.sh"

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

if [ "$BRANCH" = "stable" ]; then
	TRACK="$(t update.track_stable)"
else
	TRACK="$(t update.track_beta)"
fi

# The other track's checkout dir/branch/label -- ~/provisioning is always
# stable and ~/provisioning-bleeding always main, per beestify.sh /
# beestify-bleeding.sh (see README.md), regardless of what branch this
# particular checkout happens to be on.
if [ "$REPO_DIR" = "$HOME/provisioning" ]; then
	OTHER_DIR="$HOME/provisioning-bleeding"
	OTHER_BRANCH="main"
	OTHER_TRACK="$(t update.track_beta)"
else
	OTHER_DIR="$HOME/provisioning"
	OTHER_BRANCH="stable"
	OTHER_TRACK="$(t update.track_stable)"
fi

# A pulsating progress dialog while a git command runs -- without this, a
# slow connection leaves the user staring at nothing for several seconds
# after confirming, easy to mistake for the tool having silently died.
# Closed by killing the process directly (not by closing its stdin) since
# --pulsate mode doesn't reliably exit on EOF the way percentage mode does.
#
# Padding out to a fixed minimum duration too: on a fast (e.g. LAN)
# connection the git command can finish in well under a second, closing
# the dialog before it's even had a chance to render -- just a flash in
# the taskbar, easy to mistake for nothing having happened at all.
#
# Sets GIT_CMD_OUTPUT and returns the wrapped command's exit status.
run_git_with_progress() {
	local msg="$1"
	shift
	zenity --progress --title="$(t update.title)" --text="$msg" --pulsate --no-cancel --width=380 &
	local progress_pid=$!
	local started_at
	started_at=$(date +%s%N)

	local status=0
	GIT_CMD_OUTPUT="$("$@" 2>&1)" || status=$?

	local min_ms=600
	local elapsed_ms=$(( ($(date +%s%N) - started_at) / 1000000 ))
	if [ "$elapsed_ms" -lt "$min_ms" ]; then
		sleep "0.$(printf '%03d' $((min_ms - elapsed_ms)))"
	fi
	kill "$progress_pid" 2>/dev/null || true
	return "$status"
}

# Convenience for do_switch_track(): a script carried over unchanged from
# the old checkout to the new one doesn't need re-running, so copy its .log
# over too (this is what run-gui.py's script_is_done() checks against) --
# most machines end up with almost everything already marked done. Only
# copies when the script's content is byte-identical between the two
# checkouts; the log's mtime just needs to be newer than "now" (the fresh
# clone's mtime), which a plain non-preserving `cp` gives for free.
#
# Echoes the number of logs copied.
copy_matching_logs() {
	local old_dir="$1" new_dir="$2"
	local count=0
	local new_script name old_script old_log
	shopt -s nullglob
	for new_script in "$new_dir"/[0-9][0-9]-*.sh "$new_dir"/[0-9][0-9][a-z]-*.sh; do
		name="$(basename "$new_script")"
		old_script="$old_dir/$name"
		old_log="$old_dir/${name%.sh}.log"
		if [ -f "$old_script" ] && [ -f "$old_log" ] \
			&& [ "$old_log" -nt "$old_script" ] \
			&& cmp -s "$new_script" "$old_script"; then
			cp "$old_log" "$new_dir/${name%.sh}.log"
			count=$((count + 1))
		fi
	done
	shopt -u nullglob
	echo "$count"
}

do_switch_track() {
	local switch_confirm_msg
	switch_confirm_msg="$(t update.switch_confirm_message)"
	switch_confirm_msg="${switch_confirm_msg//CURRENT/$TRACK}"
	switch_confirm_msg="${switch_confirm_msg//OTHER/$OTHER_TRACK}"
	zenity --question --title="$(t update.title)" --width=420 --text="$switch_confirm_msg" || exit 0

	if [ -e "$OTHER_DIR" ]; then
		local exists_msg
		exists_msg="$(t update.switch_exists_message)"
		exists_msg="${exists_msg//OTHER/$OTHER_TRACK}"
		exists_msg="${exists_msg//PATH/$OTHER_DIR}"
		zenity --error --title="$(t update.title)" --width=420 --text="$exists_msg"
		exit 1
	fi

	local origin_url
	origin_url="$(git -C "$REPO_DIR" remote get-url origin)"

	local switch_progress_msg
	switch_progress_msg="$(t update.switch_progress_message)"
	switch_progress_msg="${switch_progress_msg//TRACK/$OTHER_TRACK}"
	if ! run_git_with_progress "$switch_progress_msg" \
		git clone --branch "$OTHER_BRANCH" --single-branch "$origin_url" "$OTHER_DIR"; then
		rm -rf "$OTHER_DIR"
		local clone_failed_msg
		clone_failed_msg="$(t update.switch_clone_failed_message)"
		zenity --error --title="$(t update.title)" --width=460 --text="${clone_failed_msg//OUTPUT/$GIT_CMD_OUTPUT}"
		exit 1
	fi

	local copied
	copied="$(copy_matching_logs "$REPO_DIR" "$OTHER_DIR")"

	# Only remove the old checkout once the new one is confirmed good --
	# an interrupted or failed clone above must never cost the user their
	# working checkout.
	rm -rf "$REPO_DIR"

	local done_msg
	done_msg="$(t update.switch_done_message)"
	done_msg="${done_msg//TRACK/$OTHER_TRACK}"
	done_msg="${done_msg//COUNT/$copied}"
	zenity --info --title="$(t update.title)" --width=420 --text="$done_msg"

	exec python3 "$OTHER_DIR/run-gui.py"
}

# Fetched up front (before the confirm dialog even shows) so that dialog
# can list exactly which files the pull would touch -- git diff against
# origin/$BRANCH below needs the fetch to have already happened.
if ! run_git_with_progress "$(t update.progress_message)" \
	git -C "$REPO_DIR" fetch origin "$BRANCH"; then
	failed_msg="$(t update.check_failed_message)"
	zenity --error --title="$(t update.title)" --width=460 --text="${failed_msg//OUTPUT/$GIT_CMD_OUTPUT}"
	exit 1
fi

# Appends the date of the newest incoming commit touching each path, as an
# extra tab-separated field -- cyberbeest-update-confirm.py's date column.
# For a rename/copy line, $path is the new path (last name-status field);
# looking that up still finds the rename commit since it touches the new
# path too.
CHANGED_FILES=""
while IFS=$'\t' read -r -a fields; do
	[ "${#fields[@]}" -eq 0 ] && continue
	path="${fields[-1]}"
	date="$(git -C "$REPO_DIR" log -1 --format=%ad --date=short "HEAD..origin/$BRANCH" -- "$path")"
	line="$(IFS=$'\t'; echo "${fields[*]}")"
	CHANGED_FILES+="$line"$'\t'"$date"$'\n'
done <<<"$(git -C "$REPO_DIR" diff --name-status HEAD "origin/$BRANCH")"

# Passed as "origin/$BRANCH" (not a precomputed diff) so the confirm dialog
# can run `git diff` per file on demand, only for whichever row the user
# double-clicks -- most users never open one.
case "$(printf '%s' "$CHANGED_FILES" | python3 "$SCRIPT_DIR/cyberbeest-update-confirm.py" "$TRACK" "$OTHER_TRACK" "$REPO_DIR" "origin/$BRANCH")" in
	yes)
		;;
	switch)
		do_switch_track
		exit 0
		;;
	*)
		exit 0
		;;
esac

# reset --hard (not merge --ff-only): a plain fast-forward only touches
# paths that actually changed in the new commits, so a tracked file that
# got deleted or hand-edited locally -- by accident, or by an older/buggy
# NN-*.sh -- stays that way forever even though the branch pointer moves.
# This is meant to make the checkout match upstream exactly, the same as a
# fresh clone would, so hard-reset it instead. No local commits or edits
# are expected on an end-user checkout, so there's nothing legitimate this
# could discard. origin/$BRANCH is already up to date from the fetch above.
if ! run_git_with_progress "$(t update.apply_message)" \
	git -C "$REPO_DIR" reset --hard "origin/$BRANCH"; then
	failed_msg="$(t update.apply_failed_message)"
	zenity --error --title="$(t update.title)" --width=460 --text="${failed_msg//OUTPUT/$GIT_CMD_OUTPUT}"
	exit 1
fi

exec python3 "$REPO_DIR/run-gui.py"
