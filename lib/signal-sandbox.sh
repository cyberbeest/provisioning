#!/bin/bash
# Launches Signal sandboxed with firejail, using the stock signal-desktop
# profile (whitelists ~/.config/Signal) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
#
# --password-store=basic skips the OS keyring (gnome-keyring/libsecret) for
# Signal's DB encryption key. On autologin machines the login keyring never
# gets a passphrase to auto-unlock with, so Signal blocks on an interactive
# keyring-unlock prompt at every startup, and if it's not answered in time
# it silently regenerates its key and corrupts its own database (confirmed
# 2026-09-25 in the KVM test VM: repeated "sql.initialize was unsuccessful").
# The disk is already LUKS-encrypted, so storing the key unwrapped here
# isn't a meaningful security loss.
exec firejail /opt/Signal/signal-desktop --password-store=basic "$@"
