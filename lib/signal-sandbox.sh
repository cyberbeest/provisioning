#!/bin/bash
# Launches Signal sandboxed with firejail, using the stock signal-desktop
# profile (whitelists ~/.config/Signal) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
exec firejail /opt/Signal/signal-desktop "$@"
