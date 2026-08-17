#!/bin/bash
# Launches Telegram sandboxed with firejail, using the stock telegram
# profile (already whitelists ~/Downloads, seccomp/apparmor hardened --
# no .local override needed). "$@" carries through both the normal %u
# launch and the -autostart / -quit variants.
exec firejail /usr/bin/telegram-desktop "$@"
