#!/bin/bash
# Installs a full-screen "Hibernating..." splash that shows right before
# the machine hibernates. Separate from enable-hibernation.sh (that
# script is the tested, working core feature; this is a first prototype
# of the visual polish on top of it) so it can be tried/reverted
# independently.
#
# Depends on: enable-hibernation.sh already run (hibernate.target
# unmasked) -- this only controls what's shown during hibernate, not
# whether hibernate itself works.
# Usage: sudo bash enable-hibernate-splash.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-hibernate-splash.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing hibernate splash ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi

TARGET_USER=cyberbeest
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- installing splash window script ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/cyberbeest-hibernate-splash.py" "$TARGET_HOME/.local/bin/cyberbeest-hibernate-splash.py"

# i18n.py does `from i18n import t`, which only resolves if i18n.py (and its
# strings_*.py catalogs) sit next to the installed script -- see ../lib/i18n.py.
echo "--- installing shared i18n runtime ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/../lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR"/../lib/i18n/strings_*.py "$TARGET_HOME/.local/bin/i18n/"

echo "--- installing systemd-sleep hook ---"
# /usr/lib/systemd/system-sleep, NOT /etc/systemd/system-sleep: confirmed
# via `strings` on the actual systemd-sleep binary (systemd 257) that it
# only ever scans the /usr/lib location -- no separate /etc override dir
# is compiled in for this mechanism, unlike most systemd drop-in
# conventions. A hook installed to /etc/ silently never runs at all (no
# error, no journal trace) -- cost a full debugging round-trip on
# 2026-09-28 before this was caught.
install -m 755 "$DIR/lib/cyberbeest-hibernate-splash.hook" /usr/lib/systemd/system-sleep/cyberbeest-hibernate-splash
rm -f /etc/systemd/system-sleep/cyberbeest-hibernate-splash

echo "=== $(date) : done. Next hibernate should show the splash. ==="
