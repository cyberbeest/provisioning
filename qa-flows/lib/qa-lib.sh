#!/bin/bash
# Shared helpers for cyberbeest QA flows.
# Source this from a flow script: source "$(dirname "$0")/lib/qa-lib.sh"

QA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QA_SHOTS="$QA_ROOT/shots"
QA_LOGS="$QA_ROOT/logs"
QA_FLOW_NAME="${QA_FLOW_NAME:-$(basename "$0" .sh)}"
QA_LOG_FILE="$QA_LOGS/${QA_FLOW_NAME}.log"
QA_STEP=0
QA_FAILED=0
QA_OPENED_WINDOWS=()
QA_TRACKED_PATTERNS=()

mkdir -p "$QA_SHOTS" "$QA_LOGS"
: > "$QA_LOG_FILE"

qa_log() {
    echo "[$(date '+%H:%M:%S')] $*" | tee -a "$QA_LOG_FILE"
}

qa_fail() {
    QA_FAILED=1
    qa_log "FAIL: $*"
}

qa_pass() {
    qa_log "PASS: $*"
}

# Must be called before any simulated keystroke/click/screenshot,
# per feedback_warn_before_desktop_automation. Prefers the dev machine's own
# warning sound/script when present; falls back to a generic beep + pause on
# any other machine (this repo is published standalone, not dev-machine-only
# - see provisioning/qa-flows), so a physical user at that machine's screen
# still gets a heads-up before automation starts moving their mouse/keyboard.
qa_warn_automation() {
    if [ -x "$HOME/claude/warn-desktop-automation.sh" ]; then
        "$HOME/claude/warn-desktop-automation.sh"
    else
        (command -v canberra-gtk-play >/dev/null 2>&1 && canberra-gtk-play -i dialog-warning) \
            || (command -v paplay >/dev/null 2>&1 && paplay /usr/share/sounds/freedesktop/stereo/dialog-warning.oga 2>/dev/null) \
            || printf '\a'
        sleep 2
    fi
}

# Find the X window id of the frontmost/active window whose name matches a pattern.
# Usage: qa_wait_for_window <name-substring> [timeout-seconds]
qa_wait_for_window() {
    local pattern="$1" timeout="${2:-15}" deadline id=""
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        id=$(xdotool search --name "$pattern" 2>/dev/null | head -1)
        if [ -n "$id" ]; then
            echo "$id"
            return 0
        fi
        sleep 0.5
    done
    return 1
}

# Screenshot a specific window id to $QA_SHOTS/<flow>-<step>.png, returns the path.
qa_screenshot_window() {
    local win_id="$1"
    QA_STEP=$((QA_STEP + 1))
    local out="$QA_SHOTS/${QA_FLOW_NAME}-$(printf '%02d' "$QA_STEP").png"
    import -window "$win_id" "$out"
    echo "$out"
}

# Full OCR text dump of an image.
qa_ocr_text() {
    tesseract "$1" stdout 2>/dev/null
}

# Assert that OCR text of an image contains a substring (case-insensitive).
# Usage: qa_assert_contains <image> <expected-substring> <description>
qa_assert_contains() {
    local img="$1" needle="$2" desc="$3"
    local text
    text="$(qa_ocr_text "$img")"
    if echo "$text" | grep -qi -- "$needle"; then
        qa_pass "$desc (found '$needle')"
        return 0
    else
        qa_fail "$desc (did not find '$needle')"
        return 1
    fi
}

# Poll a window with OCR until expected text appears or timeout elapses.
# Usage: qa_wait_ocr_contains <window_id> <expected-substring> <description> [timeout-seconds]
qa_wait_ocr_contains() {
    local win_id="$1" needle="$2" desc="$3" timeout="${4:-15}" deadline shot
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        shot=$(qa_screenshot_window "$win_id")
        if qa_ocr_text "$shot" | grep -qi -- "$needle"; then
            qa_pass "$desc (found '$needle')"
            return 0
        fi
        sleep 1
    done
    qa_fail "$desc (did not find '$needle' within ${timeout}s)"
    return 1
}

# Locate a word via OCR TSV output and click its bounding-box center, relative
# to the window's on-screen origin. Robust to layout/resolution differences
# because it doesn't rely on hardcoded pixel coordinates.
# Usage: qa_ocr_click_text <window_id> <word-to-find>
qa_ocr_click_text() {
    local win_id="$1" needle="$2"
    local shot; shot=$(qa_screenshot_window "$win_id")
    local geom; geom=$(xdotool getwindowgeometry --shell "$win_id")
    local win_x win_y
    win_x=$(echo "$geom" | grep '^X=' | cut -d= -f2)
    win_y=$(echo "$geom" | grep '^Y=' | cut -d= -f2)

    local line
    line=$(tesseract "$shot" stdout tsv 2>/dev/null | awk -F'\t' -v needle="$needle" '
        BEGIN { IGNORECASE=1 }
        NR>1 && $12 ~ needle { print $7, $8, $9, $10; exit }
    ')
    if [ -z "$line" ]; then
        qa_fail "ocr_click_text: '$needle' not found on screen"
        return 1
    fi
    read -r left top width height <<< "$line"
    local cx=$((win_x + left + width / 2))
    local cy=$((win_y + top + height / 2))
    qa_warn_automation
    xdotool mousemove "$cx" "$cy" click 1
    qa_pass "clicked '$needle' at ($cx,$cy)"
}

# Cyberhornet whisker-menu button, fixed panel position (top-left, 36px panel).
QA_WHISKER_X=15
QA_WHISKER_Y=18

# Launch an app the way a real user would: click whisker, type its name into
# the search box, press Enter on the top (best) match.
# Usage: qa_launch_via_whisker "firefox"
qa_launch_via_whisker() {
    local query="$1"
    qa_warn_automation
    xdotool mousemove "$QA_WHISKER_X" "$QA_WHISKER_Y" click 1
    sleep 0.5
    xdotool type --delay 40 -- "$query"
    sleep 0.5
    xdotool key Return
    qa_log "launched '$query' via whisker menu"
}

qa_summary() {
    if [ "$QA_FAILED" -eq 0 ]; then
        qa_log "=== $QA_FLOW_NAME: ALL PASSED ==="
        exit 0
    else
        qa_log "=== $QA_FLOW_NAME: FAILED ==="
        exit 1
    fi
}

# Close every window/process this flow opened, so it never leaves stray app
# instances for the next flow to trip over.
#
# Plain (non-sandboxed) windows: SIGTERM the window's owning process directly
# rather than going through the WM_DELETE_WINDOW handshake via `xdotool
# windowclose` - under firejail --x11=xorg (untrusted-client mode), that
# handshake has been observed to crash Firefox instead of closing it cleanly
# (see cyberbeest_firefox_x11_isolation). `xdotool getwindowpid` also reports
# the PID as seen *inside* firejail's own PID namespace, not the real host
# PID, so it can't be used to kill a firejailed app at all - use
# qa_track_process for those instead (pattern-matched via pkill -f).
qa_close_all_windows() {
    local id pid pattern

    if [ "${#QA_OPENED_WINDOWS[@]}" -gt 0 ]; then
        for id in "${QA_OPENED_WINDOWS[@]}"; do
            pid=$(xdotool getwindowpid "$id" 2>/dev/null)
            [ -n "$pid" ] && kill "$pid" 2>/dev/null
        done

        local deadline; deadline=$(( $(date +%s) + 5 ))
        local remaining=("${QA_OPENED_WINDOWS[@]}")
        while [ "$(date +%s)" -lt "$deadline" ] && [ "${#remaining[@]}" -gt 0 ]; do
            sleep 0.5
            local still=()
            for id in "${remaining[@]}"; do
                xdotool getwindowname "$id" >/dev/null 2>&1 && still+=("$id")
            done
            remaining=("${still[@]}")
        done

        for id in "${remaining[@]}"; do
            pid=$(xdotool getwindowpid "$id" 2>/dev/null)
            qa_log "window $id did not close gracefully, force-killing pid $pid"
            [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
        done

        qa_log "closed ${#QA_OPENED_WINDOWS[@]} window(s) opened by this flow"
    fi

    if [ "${#QA_TRACKED_PATTERNS[@]}" -gt 0 ]; then
        for pattern in "${QA_TRACKED_PATTERNS[@]}"; do
            pkill -f -- "$pattern" 2>/dev/null
        done
        sleep 1
        for pattern in "${QA_TRACKED_PATTERNS[@]}"; do
            pkill -9 -f -- "$pattern" 2>/dev/null
        done
        qa_log "closed ${#QA_TRACKED_PATTERNS[@]} tracked process pattern(s)"
    fi
}

trap qa_close_all_windows EXIT

# Register a window id (obtained via qa_wait_for_window or similar) for
# auto-close on exit. Call this explicitly in flow scripts - qa_wait_for_window
# can't self-register when called as `id=$(qa_wait_for_window ...)`, since
# command substitution runs it in a subshell whose array appends are lost.
qa_track_window() {
    QA_OPENED_WINDOWS+=("$1")
}

# Register a `pgrep -f` pattern for auto-kill on exit. Use this for anything
# launched under firejail (or otherwise not killable via its window's
# reported PID) - matches and kills the real host process(es) by cmdline.
qa_track_process() {
    QA_TRACKED_PATTERNS+=("$1")
}
