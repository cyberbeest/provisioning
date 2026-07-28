#!/bin/bash
# Installs the always-on secure-comms set directly: Signal, Element (Matrix),
# Telegram, and Tor Browser. All always end-to-end-encrypt 1:1 chats by
# default except Telegram (opt-in "Secret Chats" only) -- Telegram is
# included anyway per user request since it's mainstream enough that people
# expect it preinstalled.
#
# - Signal/Element: proper apt vendor repos, set up via cyberbeest-pkg-helper.sh.
# - Telegram: ships in Debian, but only via trixie-backports, not trixie main
#   -- enabled below alongside contrib.
# - Tor Browser: installed via Debian's own torbrowser-launcher package
#   (downloads/verifies/self-updates the actual browser from the Tor
#   Project), which lives in the "contrib" component -- enabled below.
#
# Everything else (Viber, and whatever else gets added later) is optional,
# installed on demand via the cyberbeest-install: URI scheme -- see
# cyberbeest-web-install-handler.sh -- typically triggered by an "Install"
# link on a cyberbeest.com info page rather than forced on every machine.
# Deliberately NOT included even as defaults: qTox, Gajim, Nheko, Dino (too
# niche for a general-audience machine, and redundant with Element/Signal
# covering the same protocols). Proton Mail has no real native Linux package
# (Snap-only, wrapping their web app), so it's just a browser bookmark.
#
# Run with sudo (normally invoked via ../03-secure-messengers.sh).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/install-secure-messengers.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') install-secure-messengers.sh ==="
HELPER="$DIR/cyberbeest-pkg-helper.sh"

echo "--- Enabling 'contrib' component (needed for torbrowser-launcher) ---"
SOURCES=/etc/apt/sources.list
if grep -qE '^deb http://deb\.debian\.org/debian/ trixie main non-free-firmware$' "$SOURCES" \
   && ! grep -qE '^deb http://deb\.debian\.org/debian/ trixie main contrib non-free-firmware$' "$SOURCES"; then
    sed -i 's|^deb http://deb\.debian\.org/debian/ trixie main non-free-firmware$|deb http://deb.debian.org/debian/ trixie main contrib non-free-firmware|' "$SOURCES"
    echo "Enabled contrib on the trixie main line"
else
    echo "contrib already enabled (or line format unexpected), skipping edit"
fi

echo "--- Enabling trixie-backports (needed for telegram-desktop) ---"
BACKPORTS_LIST=/etc/apt/sources.list.d/cyberbeest-backports.list
if [ ! -e "$BACKPORTS_LIST" ]; then
    echo "deb http://deb.debian.org/debian trixie-backports main contrib non-free non-free-firmware" > "$BACKPORTS_LIST"
    echo "Enabled trixie-backports via $BACKPORTS_LIST"
else
    echo "trixie-backports already enabled, skipping"
fi

echo "--- Setting up Signal and Element apt repos ---"
"$HELPER" setup-repo signal
"$HELPER" setup-repo element

echo "--- apt-get update ---"
apt-get -o DPkg::Lock::Timeout=60 update

echo "--- Installing signal-desktop, element-desktop, telegram-desktop, torbrowser-launcher ---"
apt-get -o DPkg::Lock::Timeout=60 install -y signal-desktop element-desktop telegram-desktop torbrowser-launcher

echo "--- Installing Proton Mail webapp launcher (no native Linux app exists) ---"
cat > /usr/share/applications/cyberbeest-proton-mail.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Proton Mail
Comment=End-to-end encrypted email (opens as a web app, no native Linux client exists)
Exec=firefox-esr --new-window https://mail.proton.me
Icon=internet-mail
Categories=Network;Email;
Terminal=false
EOF

echo "--- Deploying the cyberbeest-install: web-install handler ---"
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/cyberbeest-pkg-helper.sh" /usr/local/lib/cyberbeest/cyberbeest-pkg-helper.sh
install -m 755 "$DIR/cyberbeest-web-install-handler.sh" /usr/local/lib/cyberbeest/cyberbeest-web-install-handler.sh
install -m 644 "$DIR/i18n.sh" /usr/local/lib/cyberbeest/i18n.sh
cp -a "$DIR/i18n" /usr/local/lib/cyberbeest/i18n

install -m 644 "$DIR/com.cyberbeest.web-install.policy" /usr/share/polkit-1/actions/com.cyberbeest.web-install.policy
install -m 644 "$DIR/cyberbeest-web-install-handler.desktop" /usr/share/applications/cyberbeest-web-install-handler.desktop
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true

# System-wide default so any account on the machine can click an install
# link, not just whichever user last ran `xdg-mime default` interactively.
mkdir -p /etc/xdg
if [ -f /etc/xdg/mimeapps.list ] && ! grep -q '^\[Default Applications\]' /etc/xdg/mimeapps.list; then
    printf '\n[Default Applications]\n' >> /etc/xdg/mimeapps.list
elif [ ! -f /etc/xdg/mimeapps.list ]; then
    printf '[Default Applications]\n' > /etc/xdg/mimeapps.list
fi
if ! grep -q '^x-scheme-handler/cyberbeest-install=' /etc/xdg/mimeapps.list; then
    sed -i '/^\[Default Applications\]/a x-scheme-handler/cyberbeest-install=cyberbeest-web-install-handler.desktop' /etc/xdg/mimeapps.list
fi

echo "=== done ==="
