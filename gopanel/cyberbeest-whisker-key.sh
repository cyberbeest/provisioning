#!/bin/bash
# Windows key: open the application menu of whichever panel is running (gopanel's
# when it is up, otherwise the XFCE panel's Whisker menu). Bound in xfconf as
# /commands/custom/Super_L of xfce4-keyboard-shortcuts.
# Dictation (hold the key) already opened the menu itself: swallow this one shortcut.
MARK="${XDG_RUNTIME_DIR:-/tmp}/dictate-super-hold"
if [ -e "$MARK" ]; then
	fresh=$(find "$MARK" -mmin -1 2>/dev/null)
	rm -f "$MARK"
	[ -n "$fresh" ] && exit 0
fi
GOPANEL="$(command -v gopanel || echo "$HOME/.local/bin/gopanel")"
[ -x "$GOPANEL" ] || GOPANEL="$HOME/claude/gopanel/gopanel"
if pgrep -x gopanel >/dev/null && [ -x "$GOPANEL" ]; then
	exec "$GOPANEL" menu
fi
exec xfce4-popup-whiskermenu
