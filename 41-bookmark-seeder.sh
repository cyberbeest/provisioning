#!/bin/bash
# Installs the Cyberbeest Bookmark Seeder: a small GTK text editor/tool
# (see lib/cyberbeest_bookmark_seeder_gui.py) that turns a "Category: item,
# item" text file into Firefox bookmarks, routed to whichever of the three
# installed browsers actually owns that category -- Tor Browser for
# "Tor:", the dedicated i2p Firefox profile for "i2p:" (see
# setup_i2p_extras.py), everything else into the normal default Firefox
# profile.
#
# This is a provisioning-time convenience, not a daily-use app -- it's
# meant for seeding a freshly provisioned machine with a starter set of
# bookmarks, not for routine operation (it closes whichever browser owns
# the profile it's writing to). So it's installed to ~/.local/bin for
# manual/on-demand use, deliberately without a Whisker menu entry.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/41-bookmark-seeder.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing cyberbeest-bookmark-seeder ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing python3-gi (GTK bindings the GUI needs) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0 lsof

echo "--- Installing GUI script to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_bookmark_seeder_gui.py" \
    "$TARGET_HOME/.local/bin/cyberbeest_bookmark_seeder_gui.py"

echo "=== done ==="
