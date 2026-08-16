#!/bin/bash
# Ensures Tor Browser's security level defaults to "Safest" (disables JS,
# most image/font/video formats, etc. site-wide) rather than upstream's
# "Standard" default. Runs as the end user, not root -- torbrowser-launcher
# downloads/extracts the actual browser into the user's own home directory
# on first launch, so there's nothing to patch until then.
#
# Sets both the legacy Torbutton pref and the newer integrated one, since
# which one a given Tor Browser version actually reads has changed over
# time upstream; setting both is harmless and covers either. security_custom
# is forced false too -- Torbutton ignores the slider value entirely while
# that's true.
#
# Safe/cheap to run repeatedly with nothing to do (e.g. every login, before
# Tor Browser has ever been downloaded, or after torbrowser-launcher updates
# the browser binaries): only touches user.js, and only appends prefs that
# aren't already present.
set -euo pipefail

shopt -s nullglob
for profile in "$HOME"/.local/share/torbrowser/tbb/*/tor-browser/Browser/TorBrowser/Data/Browser/profile.default; do
	[ -d "$profile" ] || continue
	userjs="$profile/user.js"
	touch "$userjs"
	for pref in \
		'user_pref("extensions.torbutton.security_slider", 1);' \
		'user_pref("browser.security_level.security_slider", 1);' \
		'user_pref("extensions.torbutton.security_custom", false);'; do
		grep -qxF "$pref" "$userjs" || echo "$pref" >> "$userjs"
	done
done
