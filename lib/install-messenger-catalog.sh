#!/bin/bash
# Installs a curated AppStream catalog (built by build_messenger_catalog.py)
# so GNOME Software can find and install a hand-picked set of secure
# messengers by name/search, working around Debian not publishing
# archive-wide AppStream metadata. Also pre-configures the Signal and
# Element vendor apt repos so their entries are actually installable
# through GNOME Software's own Install button.
#
# Run with sudo:
#   sudo bash ~/provisioning/lib/install-messenger-catalog.sh (normally invoked via ../03-curated-messenger-catalog.sh)

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/install-messenger-catalog.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') install-messenger-catalog.sh ==="

# Debian's stock org.gnome.Software.Featured.xml references ~59 GNOME Circle
# apps by ID. Most never resolved before, but now that real archive-wide
# AppStream data (dep11) is being fetched, some of them (e.g. Dialect) DO
# resolve, and flood the Explore page's Featured carousel alongside our
# curated messengers. Disable it so only our own curated set is featured.
STOCK_FEATURED=/usr/share/swcatalog/xml/org.gnome.Software.Featured.xml
if [ -f "$STOCK_FEATURED" ]; then
    mv "$STOCK_FEATURED" "$STOCK_FEATURED.disabled"
    echo "Disabled stock GNOME Circle featured list ($STOCK_FEATURED.disabled)"
fi

python3 "$DIR/build_messenger_catalog.py"

echo "Catalog build finished."

# Kill any running instance so the next launch picks up the rebuilt catalog
# (GNOME Software runs as a background GApplication service and otherwise
# keeps serving stale data after closing its window).
pkill -x gnome-software && echo "Killed running gnome-software so it picks up the new catalog on next launch." || true
