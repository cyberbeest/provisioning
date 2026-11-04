#!/bin/bash
# The panel xfce4-session starts at login (its Failsafe session entry Client2_Command points here,
# see 69-cyberbeest-panel.sh). Starting the chosen panel directly means the XFCE panel never shows
# up first and gets stopped again by cyberbeest-panel-choice.sh.
#   - saved choice xfce, or no gopanel binary: the XFCE panel, exactly as before.
#   - otherwise: gopanel, after creating the "XFCE panel stopped on purpose" marker so that
#     xfce-panel-watchdog does not start the XFCE panel beside it. If gopanel dies, the watchdog
#     drops the marker and brings the XFCE panel back (see lib/xfce-panel-watchdog.sh).

CONF="$HOME/.config/cyberbeest/panel.conf"
MARKER="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/cyberbeest-xfce-panel-stopped"

if [ "$(sed -n 's/^PANEL=//p' "$CONF" 2>/dev/null | tail -1)" != xfce ]; then
	for p in "$HOME/.local/bin/gopanel" "$(command -v gopanel)" "$HOME/claude/gopanel/gopanel"; do
		if [ -n "$p" ] && [ -x "$p" ]; then
			touch "$MARKER"
			exec "$p"
		fi
	done
fi
exec xfce4-panel
