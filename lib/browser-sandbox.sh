#!/bin/bash
# Launches Firefox sandboxed with firejail, in the normal cyberbeest session.
# Firejail's stock firefox-esr.profile privatizes $HOME so Firefox only ever
# sees ~/.mozilla, ~/.cache/mozilla/firefox, ~/Downloads and ~/.pki -
# everything else in home (Element data, keys, etc.) is invisible to it even
# if the sandbox is exploited.
set -e
exec firejail /usr/bin/firefox-esr "$@"
