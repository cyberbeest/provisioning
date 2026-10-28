#!/bin/bash
# Launches Telegram sandboxed with firejail, using the stock telegram
# profile (already whitelists ~/Downloads, seccomp/apparmor hardened --
# no .local override needed). "$@" carries through both the normal %u
# launch and the -autostart / -quit variants.
#
# Telegram's own "Launch on startup" toggle cannot work inside the sandbox:
# it asks xdg-desktop-portal to create the autostart entry, and letting the
# jail talk to that portal would let a compromised Telegram register any
# command to run unsandboxed at login. So this wrapper, which runs outside
# the sandbox, manages one fixed autostart entry itself and offers the
# choice through a short notification: on a normal start "Start at login?",
# on an autostart a brief "Telegram started at login" with an undo button.
AUTOSTART_FILE="$HOME/.config/autostart/org.telegram.desktop.desktop"

case "${LANG%%_*}" in
de)
	T_OFFER="Telegram beim Anmelden starten?"
	T_OFFER_YES="Ja, automatisch starten"
	T_NOTE="Telegram wurde beim Anmelden gestartet"
	T_NOTE_NO="Nicht mehr"
	;;
*)
	T_OFFER="Start Telegram at login?"
	T_OFFER_YES="Yes, start automatically"
	T_NOTE="Telegram started at login"
	T_NOTE_NO="Stop doing this"
	;;
esac

enable_autostart() {
	mkdir -p "${AUTOSTART_FILE%/*}"
	cat >"$AUTOSTART_FILE" <<ENTRY
[Desktop Entry]
Name=Telegram Desktop
Comment=Official desktop version of Telegram messaging app
TryExec=telegram-desktop
Exec=$HOME/bin/telegram-sandbox.sh -autostart
Icon=telegram
Terminal=false
StartupWMClass=TelegramDesktop
Type=Application
Categories=Network;
SingleMainWindow=true
X-GNOME-UsesNotifications=true
X-GNOME-SingleWindow=true
ENTRY
}

disable_autostart() { rm -f "$AUTOSTART_FILE"; }

# Runs detached so it neither delays nor dies with the exec below.
notify_choice() {
	local timeout="$1" summary="$2" label="$3" on_click="$4" action
	command -v notify-send >/dev/null || return 0
	(
		action="$(notify-send -u low -e -i telegram -t "$timeout" \
			-A "go=$label" "$summary" 2>/dev/null)"
		[ "$action" = go ] && "$on_click"
	) >/dev/null 2>&1 </dev/null &
	disown 2>/dev/null
}

case " $* " in
*" -quit "*) ;;
*" -autostart "*)
	if [ -e "$AUTOSTART_FILE" ]; then
		notify_choice 2500 "$T_NOTE" "$T_NOTE_NO" disable_autostart
	fi
	;;
*)
	# Only on a fresh start: a second launch just raises the running window.
	if [ ! -e "$AUTOSTART_FILE" ] &&
		! pgrep -u "$(id -u)" -f '^/usr/bin/telegram-desktop' >/dev/null; then
		notify_choice 6000 "$T_OFFER" "$T_OFFER_YES" enable_autostart
	fi
	;;
esac

exec firejail /usr/bin/telegram-desktop "$@"
