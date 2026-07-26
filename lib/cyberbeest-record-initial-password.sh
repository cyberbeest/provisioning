#!/bin/bash
# Records the plaintext initial value of the LUKS master password or the
# cyberbeest login (short) password, purely locally on this machine, so
# cyberbeest-check-default-passwords can later test whether it's still in
# use and the login-time nag (cyberbeest-password-nag.py) knows to prompt
# the user to change it.
#
# Run this once, by hand, right after actually setting the password to the
# value you're recording here -- whether that's a throwaway dev default
# ("weak") or a securely random per-device passphrase you're putting on a
# sticker for a shipped unit ("secure", which lets the nag offer "keep it"
# instead of forcing a change).
#
# Never commit the resulting /etc/cyberbeest/initial-passwords.conf (or any
# value passed to this script) to git -- it's local-only, root-readable-only
# (mode 600), and deliberately outside this repo's tracked files. This
# script itself has no password embedded, so it's fine to keep here.
#
# Usage: cyberbeest-record-initial-password.sh master|short <value> weak|secure
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (writes /etc/cyberbeest/initial-passwords.conf)." >&2
	exit 1
fi

type="${1:-}"
value="${2:-}"
tag="${3:-}"

case "$type" in
master) prefix=MASTER ;;
short) prefix=SHORT ;;
*)
	echo "Usage: $0 master|short <value> weak|secure" >&2
	exit 1
	;;
esac

case "$tag" in
weak | secure) ;;
*)
	echo "Usage: $0 master|short <value> weak|secure" >&2
	exit 1
	;;
esac

if [ -z "$value" ]; then
	echo "Usage: $0 master|short <value> weak|secure" >&2
	exit 1
fi

CONF=/etc/cyberbeest/initial-passwords.conf
install -d -m 700 /etc/cyberbeest
touch "$CONF"
chmod 600 "$CONF"

# Drop any existing lines for this type, then append the new ones.
grep -v "^${prefix}_VALUE=\|^${prefix}_TAG=" "$CONF" >"$CONF.tmp" 2>/dev/null || true
mv "$CONF.tmp" "$CONF"
{
	printf '%s_VALUE=%q\n' "$prefix" "$value"
	printf '%s_TAG=%s\n' "$prefix" "$tag"
} >>"$CONF"
chmod 600 "$CONF"

echo "Recorded initial $type password (tag: $tag) in $CONF."
