#!/bin/bash
# QA flow: open Firefox the way a real user would (whisker menu -> search ->
# launch), navigate to a URL, and OCR-check that expected page content rendered.
set -u
source "$(dirname "$0")/lib/qa-lib.sh"

TARGET_URL="${1:-https://example.com}"
EXPECT_TEXT="${2:-Example Domain}"

qa_log "Starting flow: whisker-launch firefox, url=$TARGET_URL expect='$EXPECT_TEXT'"

qa_launch_via_whisker "firefox"

WIN_ID=$(qa_wait_for_window "Mozilla Firefox" 20) || {
    qa_fail "Firefox window did not appear within 20s"
    qa_summary
}
qa_log "Found Firefox window: $WIN_ID"
# Firejailed app: getwindowpid would report firejail's in-namespace PID, not
# the real host PID, so track it by process pattern instead of window id.
qa_track_process "firejail.*firefox-esr"

xdotool windowactivate "$WIN_ID"
sleep 1

# Simulate an actual user: focus the address bar, type the URL, hit Enter.
qa_warn_automation
xdotool key --window "$WIN_ID" ctrl+l
sleep 0.3
xdotool type --window "$WIN_ID" --delay 30 -- "$TARGET_URL"
xdotool key --window "$WIN_ID" Return

qa_wait_ocr_contains "$WIN_ID" "$EXPECT_TEXT" "page content loaded for $TARGET_URL" 20

# Leave the window open for now; a later flow step can close it if desired.
qa_summary
