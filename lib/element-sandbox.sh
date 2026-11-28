#!/bin/bash
# Launches Element sandboxed with firejail, using the stock element-desktop
# profile (whitelists ~/.config/Element) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
. "$HOME/bin/jail-lib.sh" 2>/dev/null || jail_exec() { shift; exec firejail "$@"; }
jail_exec element /opt/Element/element-desktop "$@"
