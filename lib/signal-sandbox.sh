#!/bin/bash
# Launches Signal sandboxed with firejail, using the stock signal-desktop
# profile (whitelists ~/.config/Signal) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
#
# On autologin machines (QA/test VM images only -- real hardware always
# requires a real login) the login keyring never gets a passphrase to
# unlock with, so Signal blocks on an interactive keyring-unlock prompt at
# every startup and, if it's not answered in time, corrupts its own
# database by regenerating its encryption key each time. (Firejail itself
# is NOT the cause -- confirmed 2026-09-25 that a properly-launched,
# firejailed Signal on real hardware reaches gnome_libsecret just fine;
# an earlier version of this comment blamed firejail based on a flawed
# manual SSH repro that was missing XDG_CURRENT_DESKTOP/DESKTOP_SESSION,
# which Electron's backend autodetection needs and which any real desktop
# launch -- icon, autostart, whisker menu -- already carries.)
#
# --password-store=basic works around the autologin case by skipping the
# keyring entirely -- but it must never be forced onto a profile that
# already has a keyring-backed key, since Signal can't transparently
# re-wrap an existing key under a different backend: forcing the switch
# breaks decryption of the real database instead (confirmed 2026-09-25:
# "sqlite error(SQLITE_NOTADB): file is not a database" on an
# already-linked install). And it shouldn't be forced on a *fresh* real
# install either, since real hardware's keyring works fine on its own.
# So: only apply it to a fresh profile on an autologin machine.
CONFIG="$HOME/.config/Signal/config.json"
EXTRA_ARGS=()
if ! grep -q '"safeStorageBackend"' "$CONFIG" 2>/dev/null \
	&& grep -qs '^autologin-user=' /etc/lightdm/lightdm.conf.d/*.conf /etc/lightdm/lightdm.conf 2>/dev/null; then
	EXTRA_ARGS+=(--password-store=basic)
fi
exec firejail /opt/Signal/signal-desktop "${EXTRA_ARGS[@]}" "$@"
