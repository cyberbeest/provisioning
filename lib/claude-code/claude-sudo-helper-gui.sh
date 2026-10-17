#!/bin/bash
# Graphical, always-on RUNME-marker runner (see ~/claude/CLAUDE.md for the
# RUNME convention). Runs as the normal user (NOT under sudo), watches
# ~/claude for RUNME-* markers, and when one shows up, pops a desktop
# notification + a zenity password prompt to run the script as root.
#
# It types your sudo password into `sudo -S` for you automatically once you
# approve a dialog. The old manual `claude-sudo-helper.sh` (run by hand via
# `sudo ...` in a terminal you watch) was retired -- this panel-icon-driven
# daemon is the only sudo helper now.
#
# Usage: run as your normal user, e.g. from autostart:
#   ~/claude/claude-sudo-helper-gui.sh
# (Do NOT run this one with sudo — it calls sudo itself, per-script.)

set -uo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SELF_LOG="$DIR/claude-sudo-helper-gui.log"
PIDFILE="$DIR/claude-sudo-helper-gui.pid"
ACTIVE_JOB_FILE="$DIR/claude-sudo-helper-gui.active-job"
CONFIRM_MODE_FILE="$DIR/claude-sudo-helper-gui.confirm-mode"
CACHE_NOW_FILE="$DIR/claude-sudo-helper-gui.cache-password-now"
CHECK_NOW_FILE="$DIR/claude-sudo-helper-gui.check-now"
POLL_INTERVAL=2
RETRY_DELAY=300  # how long to wait before re-prompting for a declined marker

# Whether a script run off the cached password (see cached_pass below) still
# gets a one-click confirmation, or runs straight away. Re-read on every
# marker so claude-sudo-helper-confirm-toggle.sh can flip it live without
# restarting the daemon. "ask" is the safer default -- defaults to it if the
# file is missing or holds anything else.
get_confirm_mode() {
    local mode
    mode="$(cat "$CONFIRM_MODE_FILE" 2>/dev/null)"
    [[ "$mode" == "auto" ]] && echo "auto" || echo "ask"
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$SELF_LOG"
}

if [[ "$(id -u)" -eq 0 ]]; then
    echo "Don't run this with sudo — it prompts for sudo itself, per script." >&2
    exit 1
fi

# Single-instance guard + pidfile, so the panel toggle/status icon
# (claude-sudo-helper-toggle.sh / claude-sudo-helper-status-genmon.sh) has
# something reliable to check and kill.
#
# A pidfile surviving a reboot is only meaningful if the PID it names is
# *this* script -- low PIDs get reused fast right after boot, so a bare
# `kill -0 $old_pid` can match an unrelated process and make autostart
# silently believe it's "already running" (exit 1, no log, no
# notification -- discovered 2026-07-30 after a reboot ate 5 minutes of
# autostart before a manual restart was needed). Check /proc/<pid>/cmdline
# too, not just liveness (comm is truncated to 15 chars, so match cmdline
# instead of relying on it).
if [[ -f "$PIDFILE" ]]; then
    old_pid="$(cat "$PIDFILE" 2>/dev/null)"
    old_cmdline="$(tr '\0' ' ' <"/proc/$old_pid/cmdline" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null && [[ "$old_cmdline" == *claude-sudo-helper-gui.sh* ]]; then
        # Kill rather than refuse to start, so a manual re-run (e.g. after
        # the panel icon vanishes -- see feedback_xfce_panel_reload_as_root
        # / the 12-xfce-panel-layout.sh wipe issue) is always a safe way to
        # get a known-good instance running again, without first having to
        # go hunt down and kill the old pid by hand.
        log "already running (pid $old_pid), killing it to restart"
        kill "$old_pid" 2>/dev/null
        for _ in $(seq 1 20); do
            kill -0 "$old_pid" 2>/dev/null || break
            sleep 0.1
        done
        kill -0 "$old_pid" 2>/dev/null && kill -9 "$old_pid" 2>/dev/null
    fi
    old_pid="" # avoid the "stale pidfile ignored" log below misfiring on the pid we just killed
fi
echo "$$" >"$PIDFILE"
cleanup() { rm -f "$PIDFILE"; }
trap cleanup EXIT

notify() {
    # urgency: low|normal|critical
    local urgency="$1" title="$2" body="$3"
    notify-send --urgency="$urgency" --app-name="Claude sudo helper" "$title" "$body" 2>/dev/null || true
}

# Persistent (non-expiring) notification for the "running" phase, so it
# doesn't silently vanish while a long script (e.g. a GRUB update) is still
# going. Prints its notification id on stdout so it can be replaced later.
notify_start() {
    local title="$1" body="$2"
    notify-send --urgency=low --app-name="Claude sudo helper" \
        --expire-time=0 --print-id "$title" "$body" 2>/dev/null || true
}

notify_replace() {
    local id="$1" urgency="$2" title="$3" body="$4"
    if [[ -z "$id" ]]; then
        notify "$urgency" "$title" "$body"
        return
    fi
    notify-send --urgency="$urgency" --app-name="Claude sudo helper" \
        --replace-id="$id" "$title" "$body" 2>/dev/null || true
}

# Opens a terminal window that tails the script's log live and closes once
# the script (watch_pid) finishes -- the CPU meter is otherwise the only
# sign of life for something slow like a GRUB update.
run_log_terminal() {
    local name="$1" log="$2" watch_pid="$3"
    local helper="$DIR/.claude-sudo-helper-tail-watch.sh"
    if command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --title="Running as root: $name" -x "$helper" "$log" "$watch_pid" >/dev/null 2>&1 &
    elif command -v xterm >/dev/null 2>&1; then
        xterm -title "Running as root: $name" -e "$helper" "$log" "$watch_pid" >/dev/null 2>&1 &
    fi
    disown 2>/dev/null || true
}

marker_to_script() {
    echo "$DIR/${1#RUNME-}"
}

list_pending() {
    local ts marker script
    while IFS=' ' read -r ts marker; do
        script="$(marker_to_script "$marker")"
        [[ -f "$script" ]] || continue
        # Stale only if the script was edited *after* the marker (strictly
        # newer) -- an equal timestamp (marker and script written back to
        # back fast enough to land on the same mtime) must still count as
        # fresh, or the marker gets silently ignored here.
        [[ "$script" -nt "$DIR/$marker" ]] && continue
        echo "$marker"
    done < <(find "$DIR" -maxdepth 1 -type f -name 'RUNME-*' -printf '%T@ %f\n' 2>/dev/null | sort -n)
}

# Associative array of marker -> unix timestamp when we can next prompt for it
# (used to back off after the user cancels/gets the password wrong).
declare -A next_prompt_at

# Sudo password cached in memory for the life of this daemon process, so the
# user isn't re-prompted for every single RUNME script -- same idea as
# run-gui.py's RunGuiWindow._get_sudo_password()/cached-askpass.sh. Since
# this daemon runs indefinitely (not just for one GUI window's lifetime),
# it's cleared whenever a script run fails, on the assumption it might be
# stale/wrong (see below), and always on daemon restart.
cached_pass=""

# Prompts for the sudo password (up to 3 attempts, validated via `sudo -v`),
# caching it into $cached_pass on success. Returns non-zero if the user
# cancelled or got it wrong 3 times, leaving $cached_pass untouched. Shared by
# handle_marker (first RUNME script of the daemon's life) and the standalone
# "cache it now" trigger below, so auto mode can be primed before any script
# shows up.
prompt_and_cache_password() {
    local prompt_text="$1" pass attempt rc
    attempt=0
    while (( attempt < 3 )); do
        attempt=$((attempt + 1))
        pass="$(zenity --password --title="Claude sudo helper" \
            --text="$prompt_text" 2>/dev/null)"
        rc=$?

        if [[ $rc -ne 0 ]]; then
            return 1
        fi

        if printf '%s\n' "$pass" | sudo -k -S -p '' -v 2>/dev/null; then
            cached_pass="$pass"
            return 0
        fi
        pass=""
        if (( attempt < 3 )); then
            zenity --error --title="Claude sudo helper" --text="Wrong password. Try again ($attempt/3)." 2>/dev/null
        fi
    done
    return 1
}

handle_marker() {
    local marker="$1" script log name pass attempt status notif_id job_pid running_marker
    script="$(marker_to_script "$marker")"
    log="${script%.sh}.log"
    name="$(basename "$script")"

    if [[ -n "$cached_pass" ]]; then
        pass="$cached_pass"
        if [[ "$(get_confirm_mode)" == "ask" ]]; then
            # A notification action button, unlike a zenity dialog, never
            # takes keyboard focus -- confirmed live (2026-08-07) that even
            # with xfwm4's focus_new=false + prevent_focus_stealing=true, a
            # zenity dialog still got re-focused by GTK ~1-1.5s after
            # opening (a "present" call the WM's stealing-heuristic treats
            # as legitimate), so a stray keypress right after could land on
            # whichever button was default-focused. --default-cancel made
            # that safe rather than dangerous, but this removes the
            # keyboard from the equation entirely: the action requires an
            # actual mouse click on the notification, so a stray keypress
            # anywhere else literally cannot reach it.
            action="$(notify-send --app-name="Claude sudo helper" --urgency=normal --expire-time=0 \
                -A run=Run -A postpone="Not now" \
                "Sudo script ready" "Run \"$name\" as root, using your already-entered sudo password?" 2>/dev/null)"
            if [[ "$action" != "run" ]]; then
                log "declined: $marker (confirm notification dismissed/postponed)"
                notify low "Postponed" "\"$name\" was not run."
                next_prompt_at["$marker"]=$(( $(date +%s) + RETRY_DELAY ))
                return
            fi
        else
            notify normal "Sudo script ready" "\"$name\" wants to run as root (auto-confirm mode)."
        fi
    else
        notify normal "Sudo script ready" "\"$name\" wants to run as root."
        if ! prompt_and_cache_password "Enter your sudo password to run:\n\n$name"; then
            log "declined: $marker (password prompt cancelled/failed)"
            notify low "Postponed" "\"$name\" was not run. Will ask again later, or run it yourself with:\nsudo bash $script"
            next_prompt_at["$marker"]=$(( $(date +%s) + RETRY_DELAY ))
            return
        fi
        pass="$cached_pass"
    fi

    # Atomically claim the marker before running it: a rename only succeeds
    # for one caller, so this is what actually prevents the same script
    # being run twice if this daemon gets stopped and restarted while a run
    # is still in flight -- see claude-sudo-helper-gui.pid handling below
    # for why that can happen.
    running_marker="RUNNING-${marker#RUNME-}"
    if ! mv -- "$DIR/$marker" "$DIR/$running_marker" 2>/dev/null; then
        log "already claimed elsewhere, skipping: $marker"
        unset 'next_prompt_at[$marker]'
        return
    fi

    log "running: $marker as root"
    notif_id="$(notify_start "Running" "\"$name\" is running as root — log window opened.")"

    # Don't redirect stdout/stderr here: every RUNME script already does its
    # own `exec > >(tee -a "$LOG") 2>&1`, and piling another >>"$log" on top
    # makes tee's inherited stdout land on the same file as its explicit
    # `-a "$LOG"` write, duplicating every line (discovered 2026-08-01 after
    # remove-parole.sh's log showed each line twice).
    ( printf '%s\n' "$pass" | sudo -S -p '' bash "$script" ) &
    job_pid=$!
    pass=""
    # pid+name, not just a presence flag, so a stale file left behind by an
    # ungraceful daemon exit is self-healing: whoever reads it checks
    # `kill -0 <pid>` rather than trusting the file's mere existence.
    echo "$job_pid $name" >"$ACTIVE_JOB_FILE"

    run_log_terminal "$name" "$log" "$job_pid"

    wait "$job_pid"
    status=$?
    rm -f "$ACTIVE_JOB_FILE"

    if [[ $status -eq 0 ]]; then
        log "finished OK: $marker"
        notify_replace "$notif_id" normal "Done" "\"$name\" finished successfully (exit 0)."
        mv -f -- "$DIR/$running_marker" "$DIR/DONE-${marker#RUNME-}"
    else
        log "failed ($status): $marker"
        notify_replace "$notif_id" critical "Failed" "\"$name\" exited with status $status. Check $log"
        mv -f -- "$DIR/$running_marker" "$DIR/DONE-${marker#RUNME-}"
        # A nonzero exit is almost always the script's own failure, not a bad
        # password -- clearing the cache unconditionally here meant one
        # legitimate script failure forced a re-prompt for every script after
        # it (seen live 2026-09-20 on tower). Only clear it if sudo itself no
        # longer accepts the cached password.
        if [[ -n "$cached_pass" ]] && ! printf '%s\n' "$cached_pass" | sudo -k -S -p '' -v 2>/dev/null; then
            cached_pass=""
        fi
    fi
    unset 'next_prompt_at[$marker]'
}

log "started (pid $$)"
notify low "Claude sudo helper (GUI) started" "Watching $DIR for RUNME-* scripts."

while true; do
    now=$(date +%s)

    if [[ -f "$CHECK_NOW_FILE" ]]; then
        # Manual "run pending scripts now" trigger (menu item), for when a
        # marker got declined/postponed (5 min backoff, see RETRY_DELAY) or
        # the daemon somehow missed a new RUNME-* on a poll -- clears the
        # backoff on every marker so the scan right below picks them all up
        # immediately instead of waiting out next_prompt_at.
        rm -f "$CHECK_NOW_FILE"
        if (( ${#next_prompt_at[@]} > 0 )); then
            log "check-now trigger: clearing backoff on ${#next_prompt_at[@]} postponed marker(s)"
        fi
        next_prompt_at=()
    fi

    if [[ -f "$CACHE_NOW_FILE" ]]; then
        rm -f "$CACHE_NOW_FILE"
        if [[ -n "$cached_pass" ]]; then
            notify low "Already cached" "Sudo password is already cached -- nothing to do."
        else
            notify normal "Enter sudo password" "Priming auto mode: enter your sudo password now so the next script can run with no prompt."
            if prompt_and_cache_password "Enter your sudo password to cache it for auto mode:"; then
                log "password cached proactively (panel menu)"
                notify low "Password cached" "The next RUNME script will run without a password prompt."
            else
                log "proactive password caching cancelled/failed"
                notify low "Not cached" "Password entry was cancelled or failed."
            fi
        fi
    fi

    mapfile -t markers < <(list_pending)
    for marker in "${markers[@]}"; do
        due="${next_prompt_at[$marker]:-0}"
        if (( now >= due )); then
            handle_marker "$marker"
            break  # re-scan from the top after handling one, in case list changed
        fi
    done
    sleep "$POLL_INTERVAL"
done
