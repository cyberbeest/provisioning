#!/bin/bash
# Launches Sparrow sandboxed with firejail, using the hand-built
# lib/sparrow.profile -- see 40-jail-wallets-viber.sh.
. "$HOME/bin/jail-lib.sh" 2>/dev/null || jail_exec() { shift; exec firejail "$@"; }
jail_exec sparrow /opt/sparrowwallet/bin/Sparrow "$@"
