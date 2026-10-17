#!/bin/bash
# Shared helper for telling the Cyberbeest panel (gopanel) that something it shows has changed, for
# a script that runs as root (via sudo) on behalf of TARGET_USER. The counterpart of
# lib/xfce-panel-reload.sh: where that one kills and relaunches the XFCE panel, gopanel is asked
# over its control socket and rebuilds in place (no kill, no flicker, helpers keep running).
#
# Must run as root with TARGET_USER already set. Both functions do nothing and return 0 when
# gopanel is not installed or not running for that user, so a script can call them after (or
# instead of) the XFCE reload on any machine:
#
#   . "$DIR/lib/gopanel-reload.sh"
#   gopanel_reload            # re-read the panel config now (gopanel also does this by itself, see below)
#   gopanel_restart           # replace the process with the installed binary (new version, menu layout)
#
# What needs which: panel items / plugin settings written to xfconf or the panel's rc files need
# nothing: gopanel watches those (watch.go) and reloads by itself. A new gopanel
# binary or a change gopanel only reads at startup -> gopanel_restart (69-cyberbeest-panel.sh does
# its own, with the session environment). New or changed .desktop files need neither: the menu
# notices the applications folder changing when it is opened.

_gopanel_ctl() {
	local cmd="$1" home bin pid
	home="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
	bin="$home/.local/lib/gopanel/gopanel"
	[ -x "$bin" ] || return 0
	pid="$(pgrep -u "$TARGET_USER" -x gopanel | head -1)" || true
	[ -n "$pid" ] || return 0
	if timeout 10 sudo -u "$TARGET_USER" env XDG_RUNTIME_DIR="/run/user/$(id -u "$TARGET_USER")" \
		"$bin" "$cmd" >/dev/null 2>&1; then
		echo "gopanel: $cmd done"
	else
		echo "--- warning: gopanel $cmd did not go through; it picks the change up at next login ---" >&2
	fi
	return 0
}

gopanel_reload() { _gopanel_ctl reload; }
gopanel_restart() { _gopanel_ctl restart; }
