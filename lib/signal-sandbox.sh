#!/bin/bash
# Launches Signal sandboxed with firejail, using the stock signal-desktop
# profile (whitelists ~/.config/Signal) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
#
# Firejail keeps Signal from reliably reaching the real OS keyring
# (gnome-keyring/libsecret) even when it's unlocked and working fine
# outside the sandbox (confirmed 2026-09-25 on a real machine with an
# unlocked login keyring: firejailed Signal still silently fell back to
# unencrypted key storage). On autologin machines (QA/test VM images) the
# keyring is additionally locked outright, so Signal blocks on an
# interactive unlock prompt at every startup and, if unanswered, corrupts
# its own database by regenerating its encryption key each time.
#
# --password-store=basic sidesteps all of that by skipping the keyring
# entirely -- but it must never be forced onto a profile that already has
# a keyring-backed key, since Signal can't transparently re-wrap an
# existing key under a different backend: forcing the switch breaks
# decryption of the real database instead (confirmed 2026-09-25: "sqlite
# error(SQLITE_NOTADB): file is not a database" on an already-linked
# install). So only use it for a profile that doesn't already have an
# opinion recorded.
CONFIG="$HOME/.config/Signal/config.json"
EXTRA_ARGS=()
if ! grep -q '"safeStorageBackend"' "$CONFIG" 2>/dev/null; then
	EXTRA_ARGS+=(--password-store=basic)
fi
exec firejail /opt/Signal/signal-desktop "${EXTRA_ARGS[@]}" "$@"
