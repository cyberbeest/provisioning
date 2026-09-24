#!/bin/bash
# Watches the X11 CLIPBOARD selection and writes a small status file
# describing its current content type + a short preview, for
# clipboard-status-genmon.sh to display. Event-driven via clipnotify
# (XFixes), with a slow poll fallback in case an event is ever missed
# (owner dies without a clean handoff, X server hiccup, etc).
#
# State file format (one KEY=VALUE per line, VALUE shell-quoted):
#   TYPE=text|image|files|empty|unknown
#   PREVIEW=<first ~80 chars, single line>
#   CHANGED=<unix timestamp of last observed change>

# systemd --user services don't reliably inherit DISPLAY/XAUTHORITY,
# especially right after boot (before the desktop session has imported its
# environment into the systemd user manager) -- without these, clipnotify
# fails instantly ("cannot open display") and every xclip call in
# classify_and_write silently fails too (stderr redirected to /dev/null),
# so the loop spins tight rewriting TYPE=empty forever regardless of the
# real clipboard contents. Same fix as lock-shutdown-watcher.sh: export
# them explicitly rather than relying on the unit file or inheritance.
export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

STATE_FILE="$HOME/.config/cyberbeest/clipboard-status.state"
CONFIG_FILE="$HOME/.config/cyberbeest/clipboard-status.conf"
AUTO_CLEAR_PID_FILE="$HOME/.config/cyberbeest/clipboard-auto-clear.pid"
CLIPNOTIFY="$HOME/.local/bin/clipnotify"
FALLBACK_POLL_SECS=60
DEFAULT_AUTO_CLEAR_SECS=900
# Substituted at install time by 11a-clipboard-status.sh to match the
# panel's genmon rc filename for this widget -- see xfce4-panel.xml.template.
GENMON_WIDGET_NAME=__GENMON_WIDGET__

auto_clear_seconds() {
    local val
    val=$(grep '^AUTO_CLEAR_SECONDS=' "$CONFIG_FILE" 2>/dev/null | tail -n1 | cut -d= -f2)
    echo "${val:-$DEFAULT_AUTO_CLEAR_SECS}"
}

# Schedules a clipboard clear `delay` seconds from now. Kills whatever
# timer this function scheduled previously before starting a new one --
# without this, a long delay (e.g. 30m) combined with frequent copies
# would pile up one sleeping background process per change, each still
# alive and idle for up to the full delay. Only ever one timer is live at
# a time; the CHANGED-stamp check below is now just a belt-and-suspenders
# guard against the narrow race where a new change lands between the kill
# and the new sleep actually starting.
schedule_auto_clear() {
    local type="$1" changed_at="$2" delay old_pid

    # The PID file holds the actual `sleep` process's own PID, not the
    # wrapping subshell's -- killing the subshell doesn't reach a foreground
    # child it's blocked on (bash doesn't forward the signal down), so the
    # sleep just kept running orphaned. Caught this by testing: 5 rapid
    # copies left 5 live `sleep` processes instead of 1. Killing `sleep`
    # itself makes the subshell's `wait` return immediately instead.
    if [ -f "$AUTO_CLEAR_PID_FILE" ]; then
        old_pid=$(cat "$AUTO_CLEAR_PID_FILE" 2>/dev/null)
        [ -n "$old_pid" ] && kill "$old_pid" 2>/dev/null
        rm -f "$AUTO_CLEAR_PID_FILE"
    fi

    # Nothing left to auto-clear (clipboard just went empty, manually or
    # via the timer that just fired) -- the kill above already cancelled
    # any leftover timer from the content that was there before.
    [ "$type" != "empty" ] || return

    delay=$(auto_clear_seconds)
    [ "$delay" -gt 0 ] 2>/dev/null || return
    (
        sleep "$delay" &
        sleep_pid=$!
        echo "$sleep_pid" > "$AUTO_CLEAR_PID_FILE"
        # A killed sleep means a newer change superseded this timer -- bail
        # out. Don't rely on the CHANGED check alone: it has 1s resolution,
        # and copying an image often fires two clipboard events within the
        # same second, so the superseded timer saw a "matching" stamp and
        # cleared the brand-new image immediately.
        wait "$sleep_pid" 2>/dev/null || exit 0
        current_changed=$(grep '^CHANGED=' "$STATE_FILE" 2>/dev/null | cut -d= -f2)
        if [ "$current_changed" = "$changed_at" ]; then
            xclip -selection clipboard -i /dev/null
        fi
    ) &
    disown
}

# First entry of the clipboard's text/uri-list as a plain path: file://
# prefix dropped and %XX escapes decoded (a space arrives as %20).
first_uri_path() {
    local uri
    uri=$(xclip -selection clipboard -o -t text/uri-list 2>/dev/null \
        | grep -v '^#' | head -n1 | tr -d '\r')
    uri="${uri#file://}"
    printf '%b' "${uri//%/\\x}"
}

classify_and_write() {
    local targets type preview

    targets=$(xclip -selection clipboard -o -t TARGETS 2>/dev/null)

    if [ -z "$targets" ]; then
        type="empty"
        preview=""
    elif printf '%s\n' "$targets" | grep -q '^image/' \
        && printf '%s\n' "$targets" | grep -q '^text/uri-list$'; then
        # Both the pixels and the file they came from (e.g. Cyberbeest
        # Image Viewer's Copy Image) -- pasting gives either, depending on
        # the app.
        type="image_file"
        preview=$(first_uri_path)
    elif printf '%s\n' "$targets" | grep -q '^image/'; then
        type="image"
        preview=""
    elif printf '%s\n' "$targets" | grep -q '^text/uri-list$'; then
        type="files"
        preview=$(first_uri_path)
    elif printf '%s\n' "$targets" | grep -qE '^(UTF8_STRING|text/plain|STRING)$'; then
        local full
        full=$(xclip -selection clipboard -o 2>/dev/null | tr '\n' ' ')
        # Truncate by character, not by byte (head -c 80 used to cut a
        # multi-byte UTF-8 character in half at the boundary, corrupting
        # it into mojibake) -- bash substring indexing is character-based
        # under a UTF-8 locale (this machine runs en_US.UTF-8).
        if [ "${#full}" -gt 80 ]; then
            preview="${full:0:80}…"
        else
            preview="$full"
        fi
        # xclip -i /dev/null (our own "Clear") leaves itself as selection
        # owner advertising an empty text target rather than releasing
        # ownership -- treat that as empty rather than "text" with a blank
        # preview.
        if [ -z "$preview" ]; then
            type="empty"
        else
            type="text"
        fi
    else
        type="unknown"
        preview=""
    fi

    local now
    now=$(date +%s)
    {
        printf 'TYPE=%s\n' "$type"
        printf 'PREVIEW=%q\n' "$preview"
        printf 'CHANGED=%s\n' "$now"
    } > "$STATE_FILE.tmp"
    mv "$STATE_FILE.tmp" "$STATE_FILE"

    # Push the update to the panel immediately rather than waiting for
    # genmon's own poll -- same pattern shutdown-timer-menu.py and
    # lock-power-saving-dialog.py already use. This is what lets the rc's
    # UpdatePeriod be a rare fallback instead of a real 2s poll: without
    # it, genmon would only reflect a clipboard change up to one poll
    # interval late, and the state file has no other way to signal the
    # already-idle panel that something changed.
    #
    # Only fire this when xfce4-panel is actually confirmed running.
    # `xfce4-panel --plugin-event=...` is itself a full xfce4-panel
    # process: when it can't find an already-running instance to relay
    # the command to over D-Bus, it doesn't just fail on stderr (which
    # `>/dev/null 2>&1` would have silenced) -- being a GTK app with a
    # display, it pops its own native error dialog ("GDBus.Error:...
    # org.xfce.Panel was not provided by any .service files") instead.
    # This call runs on every clipboard change, including the very first
    # one right when the systemd --user service starts, which can easily
    # race the real panel's own startup right after boot/login -- unlike
    # shutdown-timer-menu.py's/lock-power-saving-dialog.py's use of the
    # same pattern, which only ever fires from a menu click, i.e. only
    # when a panel is already known to be up. Caught on a fresh
    # provisioning run + reboot, both hitting this exact race.
    if pgrep -x xfce4-panel >/dev/null 2>&1; then
        xfce4-panel "--plugin-event=${GENMON_WIDGET_NAME}:refresh:bool:true" >/dev/null 2>&1 &
        disown
    fi

    schedule_auto_clear "$type" "$now"
}

mkdir -p "$(dirname "$STATE_FILE")"
classify_and_write

while true; do
    timeout "$FALLBACK_POLL_SECS" "$CLIPNOTIFY"
    classify_and_write
done
