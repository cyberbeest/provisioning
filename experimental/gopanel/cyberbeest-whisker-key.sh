#!/bin/bash
# Windows key: open the application menu of whichever panel is running (gopanel's
# when it is up, otherwise the XFCE panel's Whisker menu). Bound in xfconf as
# /commands/custom/Super_L of xfce4-keyboard-shortcuts.
GOPANEL="$(command -v gopanel || echo "$HOME/.local/bin/gopanel")"
[ -x "$GOPANEL" ] || GOPANEL="$HOME/claude/gopanel/gopanel"
if pgrep -x gopanel >/dev/null && [ -x "$GOPANEL" ]; then
	exec "$GOPANEL" menu
fi
exec xfce4-popup-whiskermenu
