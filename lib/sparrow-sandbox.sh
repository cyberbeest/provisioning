#!/bin/bash
# Launches Sparrow sandboxed with firejail, using the hand-built
# lib/sparrow.profile -- see 40-jail-wallets-viber.sh.
exec firejail /opt/sparrowwallet/bin/Sparrow "$@"
