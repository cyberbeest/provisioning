#!/bin/bash
# Launches Signal sandboxed with firejail, using the stock signal-desktop
# profile (whitelists ~/.config/Signal) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
#
# Signal Desktop has a known, unfixed upstream bug where its SQLCipher key
# retrieval from a real OS keyring (gnome_libsecret/kwallet) intermittently
# returns a key that doesn't match the database, crashing with
# "sqlcipher_page_cipher: hmac check failed for pgno=1" --
# https://github.com/signalapp/Signal-Desktop/issues/7439 (open, no fix).
# Reproduced repeatedly on real hardware 2026-09-25, including on a single,
# ordinary, non-concurrent launch -- not specific to autologin/VM machines
# or to firejail. --password-store=basic skips the keyring entirely,
# avoiding the bug. The disk is already LUKS-encrypted, so storing the key
# unwrapped this way isn't a meaningful security loss.
#
# Only forced on a profile with no existing backend opinion -- forcing it
# onto an existing keyring-backed key breaks decryption instead, the same
# "file is not a database" failure (confirmed 2026-09-25: an unsandboxed
# signal-desktop run had already created a gnome_libsecret-keyed profile,
# and forcing basic on top of that broke it).
CONFIG="$HOME/.config/Signal/config.json"
EXTRA_ARGS=()
if ! grep -q '"safeStorageBackend"' "$CONFIG" 2>/dev/null; then
	EXTRA_ARGS+=(--password-store=basic)
fi
exec firejail /opt/Signal/signal-desktop "${EXTRA_ARGS[@]}" "$@"
