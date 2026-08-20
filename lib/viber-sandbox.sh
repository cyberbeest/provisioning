#!/bin/bash
# Launches Viber sandboxed with firejail, using its stock firejail-profiles
# entry (already whitelists ~/.ViberPC and ~/Downloads -- no override
# needed) -- see 40-jail-wallets-viber.sh.
exec firejail /opt/viber/Viber "$@"
