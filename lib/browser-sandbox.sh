#!/bin/bash
# Launches Firefox sandboxed with firejail, in the normal cyberbeest session.
# Firejail's stock firefox-esr.profile privatizes $HOME so Firefox only ever
# sees ~/.mozilla, ~/.cache/mozilla/firefox, ~/Downloads and ~/.pki -
# everything else in home (Element data, keys, etc.) is invisible to it even
# if the sandbox is exploited.
set -e
# Needed for the Widevine CDM (Prime Video etc.) to execute: firejail's
# disable-exec.inc sets `noexec ${HOME}` by default, which blocks the CDM
# binary under ~/.mozilla/firefox/*/gmp-widevinecdm/. The stock profile has
# a matching `?BROWSER_ALLOW_DRM: ignore noexec` override that only fires
# when this env var is set.
export BROWSER_ALLOW_DRM=yes
# Also needed for Widevine: see lib/firefox-drm.profile for why mount/chroot
# have to be unblocked, and why it has to be done via a --profile include
# rather than a CLI --seccomp flag.
# --x11=xorg (untrusted X11 Security-extension client) was tried here to
# block input/content snooping across X clients, but firejail's untrusted
# mode reduces AltGr to a plain Alt key for the sandboxed app - no 3rd-level
# keys reachable at all (e.g. AltGr+E for a German-layout Euro sign). Dropped
# in favor of a working keyboard; see cyberbeest_firefox_x11_isolation memory
# for the isolation rationale and cyberbeest_firefox_xephyr_spike_not_shipped
# for why the stronger --x11=xephyr alternative wasn't shipped either.
# An unsandboxed session is running (browser-unsandboxed.sh): hand the URL to
# that instance. A second, sandboxed Firefox on the same profile would only
# fail on the profile lock.
UNSANDBOXED_MARK="${XDG_RUNTIME_DIR:-/tmp}/browser-unsandboxed.pid"
if [ -f "$UNSANDBOXED_MARK" ] && kill -0 "$(cat "$UNSANDBOXED_MARK")" 2>/dev/null; then
	exec /usr/bin/firefox-esr "$@"
fi
# Drop the red unsandboxed look (and any stale marker from a crashed session).
[ -x "$HOME/bin/browser-unsandboxed.sh" ] && "$HOME/bin/browser-unsandboxed.sh" --reset-marker
exec firejail --profile="${HOME}/.config/firejail/firefox-drm.profile" /usr/bin/firefox-esr "$@"
