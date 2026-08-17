#!/bin/bash
# Launches Element sandboxed with firejail, using the stock element-desktop
# profile (whitelists ~/.config/Element) plus a .local override adding
# ~/Downloads -- see 38-jail-messengers.sh.
exec firejail /opt/Element/element-desktop "$@"
