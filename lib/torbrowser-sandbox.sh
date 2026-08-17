#!/bin/bash
# Launches Tor Browser sandboxed with firejail, using the stock
# torbrowser-launcher profile (already whitelists ~/Downloads,
# seccomp/apparmor hardened -- no .local override needed). The launcher
# internally execs the real Tor Browser binary inside the same sandbox.
exec firejail /usr/bin/torbrowser-launcher "$@"
