#!/bin/bash
# Configures the LightDM login screen and the xfce4-screensaver lock
# screen: Cyberbeest background on the login screen, single-user lockdown
# (no manual/remote/guest login, no user switching -- just the one
# cyberbeest account tile), and the same "Enter short password to unlock
# desktop" message via PAM's pam_echo.so on both screens (lightdm-gtk-greeter
# has no native custom-text option, so this is the standard mechanism).
set -euo pipefail

SRC="$(dirname "$(readlink -f "$0")")/lightdm"

echo "--- Installing login background image ---"
install -m 644 "$SRC/cyberbeest-login-background.png" \
	/usr/share/backgrounds/cyberbeest-login-background.png

echo "--- Installing single-user lockdown drop-in ---"
install -m 644 "$SRC/60-single-user.conf" /etc/lightdm/lightdm.conf.d/60-single-user.conf

echo "--- Configuring lightdm-gtk-greeter.conf ---"
GREETER_FILE="/etc/lightdm/lightdm-gtk-greeter.conf"
backup="${GREETER_FILE}.pre-cyberbeest"
[ -e "$backup" ] || cp -p "$GREETER_FILE" "$backup"

set_greeter_var() {
	local key="$1" value="$2"
	if grep -qE "^${key}=" "$GREETER_FILE"; then
		sed -i "s|^${key}=.*|${key}=${value}|" "$GREETER_FILE"
	else
		sed -i "/^\[greeter\]/a ${key}=${value}" "$GREETER_FILE"
	fi
}
set_greeter_var background /usr/share/backgrounds/cyberbeest-login-background.png
set_greeter_var user-background false

echo "--- Writing shared welcome message ---"
MSG_FILE="/etc/lightdm/welcome-message.txt"
echo "Enter short password to unlock desktop" > "$MSG_FILE"
chmod 644 "$MSG_FILE"

PAM_LINE="auth      optional  pam_echo.so file=$MSG_FILE"

# lightdm: insert right after pam_nologin.so, before common-auth is
# included, so the message shows before the password prompt.
LIGHTDM_PAM=/etc/pam.d/lightdm
LIGHTDM_MARKER="# custom login message (added by setup-login-lock-screen.sh)"
if grep -qF "$LIGHTDM_MARKER" "$LIGHTDM_PAM" 2>/dev/null; then
	echo "$LIGHTDM_PAM: already patched."
else
	cp -p "$LIGHTDM_PAM" "${LIGHTDM_PAM}.pre-cyberbeest"
	sed -i "/pam_nologin\.so/a\\
\\
$LIGHTDM_MARKER\\
$PAM_LINE" "$LIGHTDM_PAM"
	echo "$LIGHTDM_PAM: patched."
fi

# xfce4-screensaver: insert before the "auth include common-auth" line,
# which is what actually prompts for the password, so the message shows first.
SCREENSAVER_PAM=/etc/pam.d/xfce4-screensaver
SCREENSAVER_MARKER="# custom lock screen message (added by setup-login-lock-screen.sh)"
if grep -qF "$SCREENSAVER_MARKER" "$SCREENSAVER_PAM" 2>/dev/null; then
	echo "$SCREENSAVER_PAM: already patched."
else
	cp -p "$SCREENSAVER_PAM" "${SCREENSAVER_PAM}.pre-cyberbeest"
	sed -i "/^auth\s\+include\s\+common-auth/i\\
$SCREENSAVER_MARKER\\
$PAM_LINE\\
" "$SCREENSAVER_PAM"
	echo "$SCREENSAVER_PAM: patched."
fi
