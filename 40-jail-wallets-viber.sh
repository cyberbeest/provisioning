#!/bin/bash
# Extends the app jailing started in 38-jail-messengers.sh to Viber and the
# two crypto wallets (Sparrow, Feather). None of these three had a stock
# firejail community profile that was safe to use as-is:
#
#   - Viber DOES ship a stock profile (firejail-profiles package) that
#     already whitelists ~/.ViberPC and ~/Downloads -- used as-is, just
#     wrapped like Signal/Telegram/Element.
#   - Sparrow and Feather have no stock profile at all, so lib/sparrow.profile
#     and lib/feather.profile are hand-built. Both deliberately omit
#     `private-dev` and `nogroups` -- both wallets support hardware wallets
#     (Trezor/Ledger/BitBox/Jade/KeepKey) over libusb, and those two
#     directives would silently break USB access (private-dev's minimal
#     /dev omits /dev/bus/usb; nogroups strips the plugdev membership some
#     of the udev rules require). See the profile files for the full
#     reasoning.
#
# Tor Browser remains deliberately unsandboxed -- see 38-jail-messengers.sh.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/40-jail-wallets-viber.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : jailing Viber, Sparrow, and Feather ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing firejail-profiles (in case earlier steps haven't run) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y firejail firejail-profiles

echo "--- Installing custom profiles for Sparrow and Feather ---"
install -m 644 "$DIR/lib/sparrow.profile" /etc/firejail/sparrow.profile
install -m 644 "$DIR/lib/feather.profile" /etc/firejail/feather.profile

echo "--- Installing sandbox wrapper scripts to $TARGET_HOME/bin/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
for f in viber-sandbox.sh sparrow-sandbox.sh; do
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/$f" "$TARGET_HOME/bin/$f"
done

echo "--- Re-deploying Feather's launcher wrapper (now runs under firejail) ---"
if [ -x "$DIR/39-feather-tor-ondemand.sh" ]; then
	"$DIR/39-feather-tor-ondemand.sh"
else
	echo "WARNING: 39-feather-tor-ondemand.sh not found or not executable, skipping Feather wrapper redeploy"
fi

echo "--- Installing .desktop overrides to $TARGET_HOME/.local/share/applications/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"

cat > "$TARGET_HOME/.local/share/applications/viber.desktop" <<EOF
[Desktop Entry]
Name=Viber
Comment=Viber for Desktop (sandboxed)
Comment[de]=Viber (isoliert/Firejail)
Exec=$TARGET_HOME/bin/viber-sandbox.sh %u
Icon=viber
Terminal=false
Type=Application
StartupWMClass=Viber
Categories=Network;InstantMessaging;Chat;
Path=
StartupNotify=false
EOF

cat > "$TARGET_HOME/.local/share/applications/com.viber.Viber.desktop" <<EOF
[Desktop Entry]
Name=Viber
Comment=Viber for Desktop (sandboxed)
Comment[de]=Viber (isoliert/Firejail)
Exec=$TARGET_HOME/bin/viber-sandbox.sh %u
Icon=viber
Terminal=false
Type=Application
StartupWMClass=Viber
Categories=Network;InstantMessaging;Chat;
Path=
StartupNotify=false
EOF

cat > "$TARGET_HOME/.local/share/applications/sparrowwallet-Sparrow.desktop" <<EOF
[Desktop Entry]
Name=Sparrow
Comment=Sparrow Bitcoin wallet (sandboxed)
Comment[de]=Sparrow Bitcoin-Wallet (isoliert/Firejail)
Exec=$TARGET_HOME/bin/sparrow-sandbox.sh %U
Icon=/opt/sparrowwallet/lib/Sparrow.png
Terminal=false
Type=Application
Categories=Finance;Network;
MimeType=application/psbt;application/bitcoin-transaction;application/pgp-signature;x-scheme-handler/bitcoin;x-scheme-handler/auth47;x-scheme-handler/lightning
StartupWMClass=Sparrow
SingleMainWindow=true
Path=
StartupNotify=false
EOF

for f in viber.desktop com.viber.Viber.desktop sparrowwallet-Sparrow.desktop; do
	chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/$f"
done

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" 2>&1 || true

echo "--- Restarting any already-running unsandboxed instances ---"
sudo -u "$TARGET_USER" pkill -f '^/opt/viber/Viber' 2>&1 || true
sudo -u "$TARGET_USER" pkill -f '^/opt/sparrowwallet/bin/Sparrow' 2>&1 || true
sudo -u "$TARGET_USER" pkill -x feather 2>&1 || true

echo "=== $(date) : done ==="
