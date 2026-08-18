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
#   torbrowser-launcher ships its own real AppArmor profile
#   (/etc/apparmor.d/torbrowser.Browser.firefox, profile name
#   torbrowser_firefox) already covering the downloaded browser -- but it
#   predates AppArmor's dedicated "userns" rule (it only grants the older
#   sys_admin/sys_chroot capabilities), so Firefox still can't get its
#   unprivileged-user-namespace content-process sandboxing layer and warns
#   about it. Fixed below via the profile's own local-override hook rather
#   than adding a competing profile.
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

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

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
# Check all apt source files, not just our own -- registering the same
# Release target twice (e.g. it's already in sources.list from the Debian
# installer) makes apt log "configured multiple times" warnings and floods
# the security-update-check log with repeated "delayed item" retries.
if grep -rqs "^deb .*trixie-backports" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null; then
    echo "trixie-backports already enabled, skipping"
elif [ ! -e "$BACKPORTS_LIST" ]; then
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

echo "--- Enabling userns in Tor Browser's AppArmor profile ---"
# torbrowser-launcher's shipped profile already includes this local-override
# hook (empty by default) specifically so admins can extend it without
# editing the shipped file. Verified end-to-end: after adding this and
# reloading, Tor Browser's own security-warning notice about its sandbox is
# gone (torbrowser_firefox stays in `enforce` mode throughout, unaffected).
cat > /etc/apparmor.d/local/torbrowser.Browser.firefox <<EOF
# Needed for Firefox's unprivileged-user-namespace content-process
# sandboxing layer -- the shipped profile grants the older sys_admin/
# sys_chroot capabilities for this but not the newer explicit "userns"
# rule that current AppArmor/kernel versions actually gate on.
userns,
EOF
apparmor_parser -r /etc/apparmor.d/torbrowser.Browser.firefox

echo "--- Defaulting Tor Browser's security level to Safest ---"
# Two layers, in order of preference:
#
# 1. Pre-download Tor Browser right now, headlessly, so profile.default
#    already exists (and gets patched) before the user ever clicks the
#    icon for real -- no race at all for the normal case. torbrowser-
#    launcher's download-verify-extract-run chain runs unattended once its
#    window appears (no click needed), so it just needs a display: Xvfb
#    provides a throwaway virtual one. Since nobody's watching that headless
#    session, it doesn't matter if it briefly runs Tor Browser under
#    "Standard" before we catch and patch it -- we only care that user.js
#    is correct on disk afterward, and we kill the headless session either
#    way once that's done.
#
# 2. If that predownload fails or times out (no network, slow mirror,
#    etc.), or the user later uses Tor Browser's own "start over"/
#    redownload, fall back to catching it live: override the launcher/
#    icon's Exec (via a user-level torbrowser.desktop, which XDG prefers
#    over the package's own /usr/share/applications/torbrowser.desktop) to
#    run through a wrapper that races a polling loop against the real
#    download+extract+launch sequence -- see cyberbeest-tor-safest-
#    launch.sh for why that race reliably wins even when it does have to
#    run live.
install -d /usr/local/lib/cyberbeest
install -m 755 "$DIR/cyberbeest-tor-safest.sh" /usr/local/lib/cyberbeest/cyberbeest-tor-safest.sh
install -m 755 "$DIR/cyberbeest-tor-safest-launch.sh" /usr/local/lib/cyberbeest/cyberbeest-tor-safest-launch.sh

install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/torbrowser.desktop" <<'EOF'
[Desktop Entry]
Name=Tor Browser
Comment=Launch Tor Browser
Exec=/usr/local/lib/cyberbeest/cyberbeest-tor-safest-launch.sh %u
Terminal=false
Type=Application
Icon=torbrowser
Categories=Network;WebBrowser;
StartupWMClass=Tor Browser
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/torbrowser.desktop"

echo "--- Pre-downloading Tor Browser headlessly (layer 1 above) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y xvfb

TBB_PROFILE_GLOB="$TARGET_HOME/.local/share/torbrowser/tbb/*/tor-browser/Browser/TorBrowser/Data/Browser/profile.default"
shopt -s nullglob
existing_profiles=($TBB_PROFILE_GLOB)
if [ "${#existing_profiles[@]}" -gt 0 ]; then
	echo "Tor Browser already installed for $TARGET_USER, skipping predownload"
	su - "$TARGET_USER" -c /usr/local/lib/cyberbeest/cyberbeest-tor-safest.sh
else
	echo "Launching torbrowser-launcher headlessly under Xvfb to trigger the download..."
	su - "$TARGET_USER" -c "xvfb-run -a torbrowser-launcher" \
		> "$DIR/tor-browser-predownload.log" 2>&1 &

	echo "Waiting for the profile to appear (up to 10 minutes -- real network download)..."
	found=0
	for _ in $(seq 1 600); do
		shopt -s nullglob
		profiles=($TBB_PROFILE_GLOB)
		if [ "${#profiles[@]}" -gt 0 ]; then
			found=1
			break
		fi
		sleep 1
	done

	if [ "$found" -eq 1 ]; then
		echo "Profile appeared -- patching to Safest"
		su - "$TARGET_USER" -c /usr/local/lib/cyberbeest/cyberbeest-tor-safest.sh
	else
		echo "WARNING: Tor Browser predownload timed out -- see tor-browser-predownload.log. Falling back to the launch-time wrapper (layer 2) for the user's first real launch." >&2
	fi

	echo "Stopping the headless torbrowser-launcher session..."
	# The final "run" task execs the real firefox binary in place of the
	# start-tor-browser script that launched it, so it has to be matched by
	# its path under the user's own torbrowser dir specifically (never a
	# bare "firefox" pattern -- that could hit an unrelated regular Firefox
	# session for this user).
	for pattern in torbrowser-launcher start-tor-browser \
		".local/share/torbrowser/.*/Browser/firefox" xvfb-run Xvfb; do
		pkill -u "$TARGET_USER" -f "$pattern" 2>/dev/null || true
	done
	sleep 2
	for pattern in torbrowser-launcher start-tor-browser \
		".local/share/torbrowser/.*/Browser/firefox" xvfb-run Xvfb; do
		pkill -9 -u "$TARGET_USER" -f "$pattern" 2>/dev/null || true
	done
fi

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
