#!/bin/bash
# Rewrites the Firefox menu entries to match the current jail mode (run by
# jail-settings.py after every change, and once at install). Runs as the user.
#
# Whisker always shows TWO Firefox entries: "Firefox (protected)" and
# "Firefox (unprotected)". Desktop-file ids are by ROLE, not by name:
#   browser-sandbox.desktop      = the DEFAULT one (favorite, http/https handler,
#                                  x-www-browser, Butler) -- protected or
#                                  unprotected depending on the mode
#   browser-unsandboxed.desktop  = the OTHER one, for a one-off exception
# So everything that points at browser-sandbox.desktop follows the mode.
# Entries pass BROWSER_JAIL=on|off so they behave the same whatever the mode.
#
# browser-open-file.desktop (hidden) handles html files double-clicked in
# Files: always the unprotected browser, since a jailed Firefox cannot see
# files outside Downloads/Pictures. browser-unsandboxed.sh shows the warning
# when jailing is on and stays silent when it is off.
APPS="${HOME}/.local/share/applications"
BIN="$HOME/bin"
. "$BIN/jail-lib.sh" || exit 1
mkdir -p "$APPS"

case "$(. /etc/default/locale 2>/dev/null; echo "${LANG:-en_US}")" in
de*)
	N_ON="Firefox (geschützt)"
	N_OFF="Firefox (ungeschützt)"
	C_ON="Browser in der Schutzumgebung (Firejail)"
	C_OFF="Browser ohne Schutzumgebung"
	C_DEF=" – Standard"
	;;
*)
	N_ON="Firefox (protected)"
	N_OFF="Firefox (unprotected)"
	C_ON="Browser inside the protective sandbox (Firejail)"
	C_OFF="Browser without the protective sandbox"
	C_DEF=" - default"
	;;
esac
E_ON="env BROWSER_JAIL=on $BIN/browser-sandbox.sh %u"
E_OFF="env BROWSER_JAIL=off $BIN/browser-unsandboxed.sh %u"

entry() {	# file name comment exec
	cat >"$1.new" <<EOT
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$4
Icon=firefox-esr
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;text/xml;application/xhtml+xml;application/xml;application/vnd.mozilla.xul+xml;x-scheme-handler/http;x-scheme-handler/https;
StartupNotify=false
EOT
	mv "$1.new" "$1"
}

if jail_enabled firefox; then
	entry "$APPS/browser-sandbox.desktop" "$N_ON" "$C_ON$C_DEF" "$E_ON"
	entry "$APPS/browser-unsandboxed.desktop" "$N_OFF" "$C_OFF" "$E_OFF"
else
	entry "$APPS/browser-sandbox.desktop" "$N_OFF" "$C_OFF$C_DEF" "$E_OFF"
	entry "$APPS/browser-unsandboxed.desktop" "$N_ON" "$C_ON" "$E_ON"
fi
# The non-default entry must not claim the web MIME types.
sed -i '/^MimeType=/d' "$APPS/browser-unsandboxed.desktop"

cat >"$APPS/browser-open-file.desktop.new" <<EOT
[Desktop Entry]
Type=Application
Name=Firefox (local files)
Exec=$BIN/browser-unsandboxed.sh %U
Icon=firefox-esr
Terminal=false
NoDisplay=true
Categories=Network;WebBrowser;
MimeType=text/html;application/xhtml+xml;
StartupNotify=false
EOT
mv "$APPS/browser-open-file.desktop.new" "$APPS/browser-open-file.desktop"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null
xdg-mime default browser-open-file.desktop text/html application/xhtml+xml 2>/dev/null
exit 0
