#!/bin/bash
# Builds the curated AppStream catalog so GNOME Software's Explore/search can
# find and install a hand-picked set of secure messengers (Telegram, Signal,
# Element, Dino, Nheko, Gajim, qTox), with the 5 most established ones
# (Telegram/Signal/Element/Dino/Gajim) surfaced as Featured tiles -- see
# ../build_messenger_catalog.py for how metadata/icons are pulled from each
# package's own upstream files, and ../install-messenger-catalog.sh for the
# wrapper that also disables Debian's stock GNOME Circle featured list (which
# otherwise floods the same carousel once real archive metadata is fetched).
#
# Depends on 02-gnome-software-store.sh (needs the appstream/PackageKit
# stack) and on the Cyberbeest Package Manager's helper
# (../cyberbeest-pkg-helper.sh + its polkit policy) already being deployed,
# since Signal/Element's vendor apt repos are set up through it.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/03-curated-messenger-catalog.log"
exec > "$LOG" 2>&1

echo "=== $(date) : provisioning curated messenger catalog ==="
bash "$DIR/../install-messenger-catalog.sh"
echo "=== done ==="
