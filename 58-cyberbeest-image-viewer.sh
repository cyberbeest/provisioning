#!/bin/bash
# Installs Cyberbeest Image Viewer (see lib/cyberbeest_image_viewer.py) as
# the default double-click handler for image files in Thunar/Files.
#
# Deliberately minimal for now: no zoom/pan/next-image controls, just a
# window at the image's native pixel size (downscaled only if it's bigger
# than the screen). That downscale is gamma-correct -- sRGB is a
# gamma-encoded signal, so averaging pixel bytes directly (what most image
# scalers do) darkens fine bright detail. The image is uploaded at full
# resolution as a GL_SRGB8_ALPHA8 texture, so the GPU's texture unit
# decodes sRGB -> linear before its mipmap/bilinear filtering does the
# actual downscale -- gamma-correct scaling done in hardware, not CPU
# resampling. Falls back to a CPU (Pillow/numpy) gamma-correct resize if
# PyOpenGL isn't available.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/58-cyberbeest-image-viewer.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest Image Viewer ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing dependencies (GTK bindings, Pillow, numpy, PyOpenGL) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y \
    python3-gi gir1.2-gtk-3.0 python3-pil python3-numpy python3-opengl

echo "--- Installing script to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
    "$DIR/lib/cyberbeest_image_viewer.py" \
    "$TARGET_HOME/.local/bin/cyberbeest_image_viewer.py"

echo "--- Installing .desktop entry (handler only, not menu-launchable) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-image-viewer.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Image Viewer
Comment=View an image
Exec=python3 $TARGET_HOME/.local/bin/cyberbeest_image_viewer.py %f
Terminal=false
NoDisplay=true
Categories=Graphics;Viewer;
MimeType=image/png;image/jpeg;image/gif;image/bmp;image/webp;image/tiff;
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-image-viewer.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" >/dev/null 2>&1 || true

echo "--- Registering as the default handler for image mimetypes ---"
for mime in image/png image/jpeg image/gif image/bmp image/webp image/tiff; do
    sudo -u "$TARGET_USER" xdg-mime default cyberbeest-image-viewer.desktop "$mime"
done

echo "=== $(date) : done ==="
