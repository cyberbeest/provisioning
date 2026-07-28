#!/bin/bash
# Installs the always-on secure-comms set directly: Signal, Element (Matrix),
# Telegram, and Tor Browser -- see lib/install-secure-messengers.sh for
# per-app reasoning (why these and not qTox/Gajim/Nheko/Dino, why Proton
# Mail is a bookmark not an install). Also deploys the cyberbeest-install:
# URI scheme handler, which lets optional apps (Viber so far) be installed
# on demand via a link on a cyberbeest.com info page instead of by default.
#
# Depends on 02-gnome-software-store.sh (needs the appstream/PackageKit
# stack for the desktop entries to show up nicely, though these are plain
# apt installs, not catalog-only entries).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/03-secure-messengers.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : provisioning secure messengers ==="
bash "$DIR/lib/install-secure-messengers.sh"
echo "=== done ==="
