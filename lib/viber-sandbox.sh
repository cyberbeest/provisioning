#!/bin/bash
# Launches Viber sandboxed with firejail, using its stock firejail-profiles
# entry (already whitelists ~/.ViberPC and ~/Downloads -- no override
# needed) -- see 40-jail-wallets-viber.sh.
. "$HOME/bin/jail-lib.sh" 2>/dev/null || jail_exec() { shift; exec firejail "$@"; }
jail_exec viber /opt/viber/Viber "$@"
