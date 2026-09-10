#!/bin/bash
# Mitigates the lock-screen race where the desktop can be briefly visible
# before xfce4-screensaver's own password dialog has painted over it --
# worst right as the screen wakes from DPMS blank (or right at the
# moment of an idle/manual lock) and the dialog hasn't repainted yet.
# NOT a suspend/resume concern on Cyberbeest units: mask-sleep-targets.sh
# blocks suspend entirely, so that path never comes up here. Keeps a
# black, borderless xterm window *created* at all
# times (never destroyed/recreated) and just maps/unmaps it -- no window
# creation/paint lag at the moment it matters, since the X server can
# refill the solid background_pixel on remap without our process doing
# any drawing.
#
# Shows/hides via XMapRaised/XUnmapWindow, NOT XRaiseWindow/XLowerWindow
# on an always-mapped window -- confirmed live (2026-09-07) that xfwm4
# sometimes just ignores windowlower on this window for reasons never
# fully pinned down (not simply focus -- a fix for that alone didn't
# help either; nor did raising every other window instead of lowering
# this one). Unmapping sidesteps the question entirely: an unmapped
# window cannot be visible, full stop, no stacking-order ambiguity
# possible.
#
# Deliberately event-driven (dbus-monitor on ActiveChanged), NOT polled --
# lock-shutdown-watcher.sh's 15s poll is fine for its own power-saving
# minimize/shutdown timers, but far too slow to matter here.
#
# Layering approach: the curtain stays a plain WM-managed NORMAL-layer
# window, deliberately NOT override-redirect. xfce4-screensaver's own
# dialog IS override-redirect, and confirmed live (2026-09-07, every
# screenshot taken while locked): a mapped override-redirect window
# unconditionally renders above every WM-managed window, regardless of
# timing -- that's a structural X11 guarantee, not a race. Keeping the
# curtain WM-managed means it can never end up on top of the real dialog
# and block password entry, no matter when either one maps. (Making the
# curtain override-redirect too was considered and rejected: it would
# turn this into an unguaranteed map-order race between two
# override-redirect windows instead.)
#
# Mapping+raising the curtain is the very first synchronous thing
# curtain_up() does, so it's already topmost among normal-layer windows
# the instant it's shown -- this does NOT depend on minimizing anything
# else. (Deliberately doesn't duplicate lock-shutdown-watcher.sh's own
# delayed/optional window-minimize -- that's a separate power-saving
# feature with a user-facing "Never" setting; minimizing everything here
# wouldn't even close the one gap that matters, see below.)
#
# Also marked unfocusable (WM_HINTS input=False, set in
# ensure_curtain()): confirmed live that xfwm4 hands the curtain focus
# as its fallback choice once the screensaver's window closes on
# unlock. Kept as defense in depth even though unmapping alone already
# makes the curtain invisible regardless of focus/stacking.
#
# Residual, accepted failure mode: a window that pops itself to the
# foreground in the gap between the lock signal firing and this script's
# XMapRaised call (or is created fresh after that, e.g. a notification
# popup) could briefly sit above the curtain. Considered acceptable --
# closing it fully would mean fighting every future foreground-stealing
# window forever, for a window measured in milliseconds.
#
# Tested live several times on 2026-09-07, four stuck-curtain incidents
# found and fixed in turn: an xterm CLI-flag bug (-cursorColor/
# -internalBorder aren't real flags), fullscreen state pinning the
# window into an elevated xfwm4 layer that windowlower can't undo,
# xfwm4 handing the curtain focus on unlock (auto-raising it), and
# finally windowlower on this window proving unreliable even once focus
# was ruled out -- which is what led to switching the whole show/hide
# mechanism to map/unmap. Two clean lock/unlock cycles confirmed after
# that fix before this shipped.
#
# Toggle: CURTAIN_ENABLED in ~/.config/cyberbeest/power-settings.conf
# (default true), surfaced as a checkbox in the Extended Power Options
# dialog alongside the other lock-related settings. Read fresh on every
# lock rather than gating the whole service, so flipping it takes effect
# on the very next lock without a restart.

set -uo pipefail

export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

CURTAIN_CLASS="CyberbeestCurtain"
# Blue, kept deliberately rather than switched to black once testing
# confirmed the mechanism: black would be indistinguishable from the
# monitor just being DPMS-blanked/off (no way to tell "curtain is
# covering the desktop" from "nothing is drawing anything" at a glance),
# and there's no real cosmetic reason to prefer black here -- the real
# screensaver dialog is what's actually visible during a normal lock.
CURTAIN_COLOR="blue"
WATCHDOG_INTERVAL=5   # seconds between fail-safe sanity checks

POWER_SETTINGS="$HOME/.config/cyberbeest/power-settings.conf"

read_setting() {
    # read_setting KEY DEFAULT
    [ -f "$POWER_SETTINGS" ] || { echo "$2"; return; }
    local value
    value=$(grep "^$1=" "$POWER_SETTINGS" | tail -n1 | cut -d= -f2-)
    echo "${value:-$2}"
}

curtain_enabled() {
    [ "$(read_setting CURTAIN_ENABLED true)" = "true" ]
}

is_locked() {
    dbus-send --session --dest=org.xfce.ScreenSaver --type=method_call \
        --print-reply /org/xfce/ScreenSaver org.xfce.ScreenSaver.GetActive \
        2>/dev/null | grep -q "boolean true"
}

find_curtain_id() {
    xdotool search --class "$CURTAIN_CLASS" 2>/dev/null | head -n1
}

ensure_curtain() {
    local id
    id=$(find_curtain_id)
    if [ -n "$id" ]; then
        echo "$id"
        return
    fi

    # Remember whatever currently has focus so we can hand it straight
    # back if mapping the curtain steals it.
    local prev_focus
    prev_focus=$(xdotool getactivewindow 2>/dev/null)

    xterm -class "$CURTAIN_CLASS" -name "$CURTAIN_CLASS" -title "$CURTAIN_CLASS" \
        -bg "$CURTAIN_COLOR" -fg "$CURTAIN_COLOR" -cr "$CURTAIN_COLOR" \
        -xrm "${CURTAIN_CLASS}*internalBorder: 0" -bw 0 +sb \
        -e /bin/sh -c 'exec sleep infinity' &
    disown

    local waited=0
    while [ -z "$id" ] && [ "$waited" -lt 50 ]; do
        sleep 0.1
        id=$(find_curtain_id)
        waited=$(( waited + 1 ))
    done
    if [ -z "$id" ]; then
        logger -t lock-screen-curtain "ERROR: curtain window never appeared"
        echo ""
        return
    fi

    # Deliberately NOT _NET_WM_STATE_FULLSCREEN: xfwm4 puts fullscreen
    # windows in an elevated stacking layer that windowlower can't pull
    # back below normal windows (confirmed live -- an earlier version
    # used fullscreen and the curtain got stuck showing after unlock).
    #
    # Ask for no decorations via Motif hints, but don't rely on xfwm4
    # honoring that live/exactly (confirmed live -- it left a residual
    # ~25-35px frame plus placed the window below the panel's reserved
    # strut, offset by the panel's own height). Rather than chase exact
    # decoration/strut geometry, just massively overshoot every edge --
    # functionally "opaque with no gaps" matters here, not pixel-perfect
    # placement, and a window a few hundred px past the screen edge on
    # each side is harmless.
    xprop -id "$id" -f _MOTIF_WM_HINTS 32c -set _MOTIF_WM_HINTS "0x2, 0x0, 0x0, 0x0, 0x0"
    local geom
    geom=$(xdotool getdisplaygeometry)
    local width height margin overshoot_w overshoot_h
    width=${geom% *}
    height=${geom#* }
    margin=200
    overshoot_w=$(( width + margin * 2 ))
    overshoot_h=$(( height + margin * 2 ))
    wmctrl -i -r "$id" -e "0,-${margin},-${margin},${overshoot_w},${overshoot_h}"
    wmctrl -i -r "$id" -b add,skip_taskbar,skip_pager,sticky

    # ICCCM input hint: tells the WM this window never wants keyboard
    # focus. xterm doesn't expose this as a CLI flag, so set it directly
    # via Xlib (ctypes -- no extra packages needed, libX11 is already
    # loaded by every X client on this system).
    python3 - "$id" <<'PYEOF'
import ctypes
import sys

win_id = int(sys.argv[1])
InputHint = 1 << 0

class XWMHints(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_long),
        ("input", ctypes.c_int),
        ("initial_state", ctypes.c_int),
        ("icon_pixmap", ctypes.c_ulong),
        ("icon_window", ctypes.c_ulong),
        ("icon_x", ctypes.c_int),
        ("icon_y", ctypes.c_int),
        ("icon_mask", ctypes.c_ulong),
        ("window_group", ctypes.c_ulong),
    ]

x11 = ctypes.CDLL("libX11.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
display = x11.XOpenDisplay(None)
if not display:
    sys.exit("could not open display")

hints = XWMHints(flags=InputHint, input=0)
x11.XSetWMHints(ctypes.c_void_p(display), ctypes.c_ulong(win_id), ctypes.byref(hints))
x11.XFlush(ctypes.c_void_p(display))
x11.XCloseDisplay(ctypes.c_void_p(display))
PYEOF

    # Start hidden -- unmapped, not just lowered.
    xdotool windowunmap "$id" 2>/dev/null

    if [ -n "$prev_focus" ] && [ "$prev_focus" != "$id" ]; then
        xdotool windowactivate "$prev_focus" 2>/dev/null
    fi

    logger -t lock-screen-curtain "Curtain window created ($id)"
    echo "$id"
}

curtain_up() {
    curtain_enabled || return
    local id
    id=$(ensure_curtain)
    [ -n "$id" ] || return
    xdotool windowmap "$id" 2>/dev/null
    xdotool windowraise "$id" 2>/dev/null
    logger -t lock-screen-curtain "Curtain mapped on lock"
}

curtain_down() {
    local id
    id=$(find_curtain_id)
    [ -z "$id" ] && return
    xdotool windowunmap "$id" 2>/dev/null
    logger -t lock-screen-curtain "Curtain unmapped on unlock"
}

# Create the curtain immediately at startup so the very first lock has
# nothing to wait on.
ensure_curtain >/dev/null

# curtain_state used to be a plain shell variable, but the watchdog (a
# backgrounded function -- its own subshell) and the dbus-monitor handler
# (the last stage of a pipeline -- also its own subshell, since this
# script doesn't `shopt -s lastpipe`) each get an independent COPY of any
# variable set before they forked; a write in one is invisible to the
# other. In practice this let the watchdog's own belief of curtain_state
# get stuck on "down" forever even after the dbus-monitor handler had
# genuinely raised the curtain (only ITS copy flipped to "up") -- silently
# disabling the one fail-safe this script exists to provide. Found live
# 2026-09-10 after "Curtain mapped on lock"/"unmapped on unlock" turned up
# logged twice per lock/unlock cycle, from two different subshells. Fixed
# by moving the flag to a file so every subshell reads/writes the same
# state instead of its own copy.
CURTAIN_STATE_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/cyberbeest-lock-curtain.state"
echo down > "$CURTAIN_STATE_FILE"

get_curtain_state() {
    cat "$CURTAIN_STATE_FILE" 2>/dev/null || echo down
}

set_curtain_state() {
    echo "$1" > "$CURTAIN_STATE_FILE"
}

# Fail-safe: if the real lock state and our believed curtain_state ever
# disagree for more than WATCHDOG_INTERVAL, force back in sync -- this is
# the guard against a stuck-up curtain locking the user out after a bug
# in the dbus-signal handling below.
watchdog() {
    while true; do
        sleep "$WATCHDOG_INTERVAL"
        if is_locked; then
            [ "$(get_curtain_state)" = "down" ] && { curtain_up; set_curtain_state up; }
        else
            [ "$(get_curtain_state)" = "up" ] && { curtain_down; set_curtain_state down; }
        fi
    done
}
watchdog &
WATCHDOG_PID=$!
trap 'kill "$WATCHDOG_PID" 2>/dev/null; rm -f "$CURTAIN_STATE_FILE"' EXIT

dbus-monitor --session "type='signal',interface='org.xfce.ScreenSaver',member='ActiveChanged'" 2>/dev/null |
while read -r line; do
    case "$line" in
        *"boolean true"*)
            curtain_up
            set_curtain_state up
            ;;
        *"boolean false"*)
            curtain_down
            set_curtain_state down
            ;;
    esac
done
