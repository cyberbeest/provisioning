#!/bin/bash
# Starts Firefox WITHOUT the firejail sandbox, for one session only: closing
# the browser ends it and the next launch is sandboxed again.
#
# Needed when a site hands off to a desktop app (e.g. claude:// sign-in
# callbacks): inside the sandbox the handoff starts a second, isolated copy
# of the app that cannot reach the running one.
#
# Firefox is single-instance per profile, so a running (sandboxed) Firefox
# has to be closed first. While this session runs, browser-sandbox.sh
# forwards links to it instead of starting a second, sandboxed instance.

MARK="${XDG_RUNTIME_DIR:-/tmp}/browser-unsandboxed.pid"

# --- Red browser chrome while unsandboxed -----------------------------------
# userChrome.css (toolbar and tabs red) exists only while an unsandboxed
# session runs: this script writes it at start and removes it at exit, and
# browser-sandbox.sh removes it (--reset-marker) before every sandboxed launch,
# so a crashed session cannot leave sandboxed windows red. (A -moz-bool-pref
# media query would be tidier but does not apply in browser chrome.) Firefox
# reads the stylesheet at startup only, so the profile must not be in use.
# Same profile on purpose: logins and tabs carry over.

ff_profile() {
	local p
	p=$(awk '/^\[Install/{i=1;next} /^\[/{i=0} i&&/^Default=/{sub(/^Default=/,"");print;exit}' \
		"$HOME/.mozilla/firefox/profiles.ini" 2>/dev/null)
	[ -n "$p" ] && [ -d "$HOME/.mozilla/firefox/$p" ] && echo "$HOME/.mozilla/firefox/$p"
}

set_marker() {	# $1 = true: red chrome on | false: off
	local d f
	d=$(ff_profile) || return 0
	f="$d/user.js"
	{
		grep -v -e 'legacyUserProfileCustomizations' -e 'cyberbeest.unsandboxed' "$f" 2>/dev/null
		echo 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
	} > "$f.new" && mv "$f.new" "$f"
	if [ "$1" = true ]; then
		mkdir -p "$d/chrome"
		cat > "$d/chrome/userChrome.css" <<'CSS'
:root {
	--toolbar-bgcolor: #b3261e !important;
	--toolbar-color: #fff !important;
}
#navigator-toolbox, #TabsToolbar, #nav-bar, #PersonalToolbar, #titlebar {
	background-color: #b3261e !important;
	background-image: none !important;
	color: #fff !important;
}
CSS
	else
		rm -f "$d/chrome/userChrome.css"
	fi
}

if [ "$1" = "--reset-marker" ]; then
	set_marker false
	exit 0
fi

case "$(. /etc/default/locale 2>/dev/null; echo "${LANG:-en_US}")" in
de*)
	T_CLOSE_TITLE="Browser läuft bereits"
	T_CLOSE_TEXT="Bitte zuerst den Browser schließen, dann diese Funktion erneut starten."
	T_ASK_TITLE="Browser ohne Schutz starten?"
	T_ASK_TEXT="Der Browser läuft dann ohne seine Schutzumgebung (Sandbox). Webseiten haben mehr Möglichkeiten, auf Ihren Computer zuzugreifen.\n\nNur für vertrauenswürdige Seiten verwenden, etwa für eine Anmeldung. Sobald Sie den Browser schließen, ist der Schutz wieder aktiv."
	T_START="Ohne Schutz starten"
	T_CANCEL="Abbrechen"
	T_BANNER_TITLE="Firefox ohne Schutz"
	T_BANNER_TEXT="Die rote Werkzeugleiste zeigt: Der Browser läuft ohne Schutzumgebung. Schließen Sie ihn, um den Schutz wieder zu aktivieren."
	;;
*)
	T_CLOSE_TITLE="Browser is already running"
	T_CLOSE_TEXT="Please close the browser first, then start this again."
	T_ASK_TITLE="Start the browser without protection?"
	T_ASK_TEXT="The browser will run without its protective sandbox. Websites have more ways to reach your computer.\n\nUse this only for sites you trust, such as a sign-in. As soon as you close the browser, protection is back on."
	T_START="Start without protection"
	T_CANCEL="Cancel"
	T_BANNER_TITLE="Firefox without protection"
	T_BANNER_TEXT="The red toolbar shows that the browser is running without its protective sandbox. Close it to switch protection back on."
	;;
esac

if pgrep -u "$(id -u)" -x firefox-esr >/dev/null; then
	zenity --info --width=360 --title="$T_CLOSE_TITLE" --text="$T_CLOSE_TEXT"
	exit 1
fi

zenity --question --width=420 --icon-name=dialog-warning \
	--title="$T_ASK_TITLE" --text="$T_ASK_TEXT" \
	--ok-label="$T_START" --cancel-label="$T_CANCEL" || exit 0

echo $$ > "$MARK"
set_marker true
trap 'rm -f "$MARK"; set_marker false' EXIT
# The red toolbar is the lasting reminder; this just explains it once.
notify-send --icon=dialog-warning --expire-time=15000 "$T_BANNER_TITLE" "$T_BANNER_TEXT" 2>/dev/null

# Not exec: the cleanup above must run when Firefox exits.
/usr/bin/firefox-esr "$@"
