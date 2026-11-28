#!/bin/bash
# Shared jail-mode logic for the *-sandbox.sh wrappers (installed next to them
# as ~/bin/jail-lib.sh). Source it, then use `jail_exec APP firejail-opts... CMD...`
# in place of `exec firejail firejail-opts... CMD...`.
#
# Config: ~/.config/cyberbeest/jail.conf (written by jail-settings.py)
#   MODE=all|some|none      default: all
#   APPS="firefox signal"   only read for MODE=some: the apps that ARE jailed
# App ids: firefox chrome signal element telegram viber sparrow feather
JAIL_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/cyberbeest/jail.conf"
JAIL_ALL_APPS="firefox chrome signal element telegram viber sparrow feather"
# Jailed by default when the user first picks "some": the apps holding secrets.
JAIL_DEFAULT_SOME="signal element telegram viber sparrow feather"

jail_mode() {
	local m=""
	[ -r "$JAIL_CONF" ] && m="$(sed -n 's/^MODE=//p' "$JAIL_CONF" | tail -n1)"
	case "$m" in all | some | none) echo "$m" ;; *) echo all ;; esac
}

jail_apps() {	# jailed app list for MODE=some
	local a=""
	[ -r "$JAIL_CONF" ] && a="$(sed -n 's/^APPS=//p' "$JAIL_CONF" | tail -n1 | tr -d '"')"
	[ -n "$a" ] || a="$JAIL_DEFAULT_SOME"
	echo "$a"
}

# True (0) if APP should currently run jailed.
jail_enabled() {
	case "$(jail_mode)" in
	all) return 0 ;;
	none) return 1 ;;
	*) case " $(jail_apps) " in *" $1 "*) return 0 ;; esac; return 1 ;;
	esac
}

# jail_exec APP [--firejail-opt ...] CMD [ARGS...]
# Jailed: exec firejail <all of it>. Not jailed: drop the leading --options
# (they only mean something to firejail) and exec the command directly.
jail_exec() {
	local app="$1"
	shift
	if jail_enabled "$app"; then
		exec firejail "$@"
	fi
	while [ "${1#--}" != "$1" ]; do shift; done
	exec "$@"
}

# Same as jail_exec but runs the command as a child and returns its status
# (for wrappers that must do something after the app exits).
jail_run() {
	local app="$1"
	shift
	if jail_enabled "$app"; then
		firejail "$@"
		return
	fi
	while [ "${1#--}" != "$1" ]; do shift; done
	"$@"
}
