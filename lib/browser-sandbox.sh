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
# --x11=xorg marks Firefox as an untrusted client via the X11 Security
# extension: it can no longer read other windows' contents or steal/inject
# input events from other apps on the same X server, even if the sandbox is
# escaped. No separate nested X server needed - firejail docs confirm
# Firefox works correctly in this mode (unlike e.g. Chromium/xterm).
exec firejail --x11=xorg --profile="${HOME}/.config/firejail/firefox-drm.profile" /usr/bin/firefox-esr "$@"
