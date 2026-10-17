#!/bin/bash
# Installs "Drawing" (Debian package `drawing`), a small GTK3 paint program
# in the spirit of MS Paint: pencil, brush, eraser, fill, shapes, text,
# selection/crop/rescale, PNG/JPEG/BMP/WebP export. ~5 MB, pure Python/GTK,
# in Debian main, no repo setup needed. Deliberately NOT set as the default
# image handler -- the Cyberbeest Image Viewer (58-) stays that; Drawing is
# reached via "Open with" or the Multimedia menu (the user-level .desktop
# override below moves it out of Graphics, same category as the image viewer).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/67-drawing-app.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Drawing ==="
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y drawing

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
APPS="$TARGET_HOME/.local/share/applications"
SRC=/usr/share/applications/com.github.maoschanz.drawing.desktop
echo "--- Moving Drawing to the Multimedia (AudioVideo) menu category ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APPS"
sed 's/^Categories=.*/Categories=AudioVideo;GTK;/' "$SRC" > "$APPS/com.github.maoschanz.drawing.desktop"
chown "$TARGET_USER:$TARGET_USER" "$APPS/com.github.maoschanz.drawing.desktop"

echo "=== done ==="
