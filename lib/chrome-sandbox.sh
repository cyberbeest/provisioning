#!/bin/bash
# Launches Google Chrome sandboxed with firejail, using the stock
# google-chrome-stable profile (firejail-profiles package) plus a .local
# override adding ~/Downloads and ~/Pictures -- see 40a-jail-chrome.sh.
# Firejail privatizes $HOME, so Chrome only sees its own config/cache dirs,
# ~/Downloads and ~/Pictures.
#
# The jail also hides ibus's socket (~/.cache/ibus), but the desktop session
# sets GTK_IM_MODULE=ibus. Chrome then swallows every plain keystroke while
# mouse and some shortcuts still work. Force GTK's built-in input method
# inside the jail instead. (Unsetting the variables is not enough: GTK then
# falls back to ibus.)
exec firejail \
	--env=GTK_IM_MODULE=gtk-im-context-simple \
	--env=QT_IM_MODULE=simple \
	--env=XMODIFIERS=@im=none \
	--env=IBUS_ADDRESS= \
	/usr/bin/google-chrome-stable "$@"
