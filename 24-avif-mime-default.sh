#!/bin/bash
# Sets Firefox as the default handler for AVIF images. No installed GUI image
# viewer (Ristretto included) ships a gdk-pixbuf loader for AVIF -- only the
# underlying libavif/libheif codec libraries are present, which is enough for
# tools like ImageMagick to decode AVIF but not for double-click viewing.
# Firefox decodes AVIF natively, so route the mimetype there instead of
# leaving it unhandled. Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/24-avif-mime-default.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting Firefox as default AVIF viewer ==="
TARGET_USER="${SUDO_USER:-cyberbeest}"

FIREFOX_DESKTOP="firefox-esr.desktop"
if [ -f /usr/share/applications/firefox.desktop ]; then
    FIREFOX_DESKTOP="firefox.desktop"
fi

su - "$TARGET_USER" -c "xdg-mime default $FIREFOX_DESKTOP image/avif"

echo "=== done ==="
