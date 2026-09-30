#!/bin/bash
# Launches Google Chrome sandboxed with firejail, using the stock
# google-chrome-stable profile (firejail-profiles package) plus a .local
# override adding ~/Downloads and ~/Pictures -- see 40a-jail-chrome.sh.
# Firejail privatizes $HOME, so Chrome only sees its own config/cache dirs,
# ~/Downloads and ~/Pictures.
exec firejail /usr/bin/google-chrome-stable "$@"
