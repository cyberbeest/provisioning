#!/bin/bash
# Installs firejail and a browser-sandbox.sh wrapper that runs Firefox
# through it, so a compromised page can't reach the rest of home (Element
# data, keys, etc.) -- see lib/browser-sandbox.sh and README's "Browser
# sandbox" architecture note.
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/10-browser-sandbox.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing browser sandbox ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing firejail + profiles, and firefox-esr if not already present ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y firejail firejail-profiles firefox-esr

echo "--- Allowing pulseaudio/dbus through the sandbox (firefox-esr.local override) ---"
install -m 644 "$DIR/lib/firefox-esr.local" /etc/firejail/firefox-esr.local

echo "--- Installing firefox-drm.profile (DRM/Widevine seccomp override) to $TARGET_HOME/.config/firejail/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/firejail"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/firefox-drm.profile" \
	"$TARGET_HOME/.config/firejail/firefox-drm.profile"

echo "--- Installing wrapper to $TARGET_HOME/bin/browser-sandbox.sh ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/browser-sandbox.sh" \
	"$TARGET_HOME/bin/browser-sandbox.sh"

echo "--- Installing browser-sandbox.desktop launcher (used as the Whisker menu favorite) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/browser-sandbox.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Firefox
Comment=Secured browser (Firejail)
Comment[de]=Abgesicherter Browser (Firejail)
Exec=$TARGET_HOME/bin/browser-sandbox.sh %u
Icon=firefox-esr
Terminal=false
Categories=Network;WebBrowser;
MimeType=text/html;text/xml;application/xhtml+xml;application/xml;application/vnd.mozilla.xul+xml;x-scheme-handler/http;x-scheme-handler/https;
Path=
StartupNotify=false
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/browser-sandbox.desktop"

echo "=== $(date) : done ==="
