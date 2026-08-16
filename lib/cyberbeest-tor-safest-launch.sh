#!/bin/bash
# Wrapper that replaces torbrowser-launcher as the actual Exec target of the
# Tor Browser launcher/icon (see the ~/.local/share/applications/
# torbrowser.desktop override installed alongside this script). Needed
# because torbrowser-launcher downloads/extracts/updates the real browser
# as part of the SAME invocation that then launches it -- there is no
# separate "already installed, about to start" moment to hook from outside,
# and a login-time autostart hook would always miss the very first launch
# of a session (nothing to patch yet at login).
#
# Instead this races a short polling loop against torbrowser-launcher's own
# download+extract+launch sequence in the background, while the real
# torbrowser-launcher runs in the foreground exactly as it would without
# this wrapper. profile.default typically appears (created during
# extraction) several seconds before the extracted Firefox binary is
# actually spawned and reads it, so the loop reliably wins even on a cold
# first-ever download. If Tor Browser is already installed, the profile
# already exists and the very first iteration patches it before
# torbrowser-launcher gets anywhere near spawning the browser process.
#
# Deliberately no -e: this must never prevent the real launch.
set -uo pipefail

(
	for _ in $(seq 1 450); do  # ~90s at 0.2s -- comfortably longer than a cold download+extract
		/usr/local/lib/cyberbeest/cyberbeest-tor-safest.sh || true
		shopt -s nullglob
		profiles=("$HOME"/.local/share/torbrowser/tbb/*/tor-browser/Browser/TorBrowser/Data/Browser/profile.default)
		[ "${#profiles[@]}" -gt 0 ] && break
		sleep 0.2
	done
) &
disown

exec torbrowser-launcher "$@"
