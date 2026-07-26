#!/bin/bash
# Tests whether the machine's LUKS master password and/or cyberbeest login
# (short) password still match the value recorded at initial-password-set
# time (see cyberbeest-record-initial-password.sh). Prints one KEY=VALUE
# line per password type that has a recorded initial value:
#
#   MASTER_STILL_DEFAULT=0|1
#   MASTER_TAG=weak|secure     (only present when MASTER_STILL_DEFAULT=1)
#   SHORT_STILL_DEFAULT=0|1
#   SHORT_TAG=weak|secure      (only present when SHORT_STILL_DEFAULT=1)
#
# Prints nothing at all for a type with no recorded initial value (e.g. a
# self-installer who picked their own password during Debian install, and
# never ran cyberbeest-record-initial-password.sh) -- callers should treat
# "no line for this type" the same as "not still default", i.e. no nag.
#
# Needs python3-legacycrypt (Python 3.13 dropped the stdlib crypt module
# that used to do this -- legacycrypt is the upstream-recommended, still
# crypt(3)-backed replacement, so it correctly handles whatever hash scheme
# is actually in use, e.g. Debian 12+'s yescrypt default) -- installed by
# 21-default-password-nag.sh.
#
# Must run as root: reads /etc/shadow and tests the LUKS header directly.
# Installed with a narrowly-scoped NOPASSWD sudoers rule (exact path, no
# arguments) by 21-default-password-nag.sh, so the login-time nag
# (cyberbeest-password-nag.py) can call this without an interactive auth
# prompt -- it's read-only and never prints the actual password values.
set -euo pipefail

CONF=/etc/cyberbeest/initial-passwords.conf
DEVICE=/dev/sda3

[ -r "$CONF" ] || exit 0
# shellcheck source=/dev/null
source "$CONF"

if [ -n "${MASTER_VALUE:-}" ]; then
	if printf '%s\n' "$MASTER_VALUE" | cryptsetup luksOpen "$DEVICE" --test-passphrase --key-slot 0 2>/dev/null; then
		echo "MASTER_STILL_DEFAULT=1"
		echo "MASTER_TAG=${MASTER_TAG:-weak}"
	else
		echo "MASTER_STILL_DEFAULT=0"
	fi
fi

if [ -n "${SHORT_VALUE:-}" ]; then
	hash="$(getent shadow cyberbeest | cut -d: -f2)"
	if [ -n "$hash" ] && python3 -c '
import legacycrypt as crypt, sys
candidate, existing = sys.argv[1], sys.argv[2]
sys.exit(0 if crypt.crypt(candidate, existing) == existing else 1)
' "$SHORT_VALUE" "$hash"; then
		echo "SHORT_STILL_DEFAULT=1"
		echo "SHORT_TAG=${SHORT_TAG:-weak}"
	else
		echo "SHORT_STILL_DEFAULT=0"
	fi
fi
