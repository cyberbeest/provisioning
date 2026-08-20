#!/bin/bash
# Sets up on-demand Tor for Feather: the Debian feather-wallet package does
# NOT bundle a Tor daemon (only upstream's AppImage does -- Debian packaging
# policy disallows vendoring another project's binary), so it Recommends the
# system `tor` package instead. Left as apt installs it, tor.service runs
# always-on in the background regardless of whether Feather is even open --
# a persistent, heavy service nobody asked for. Feather is the only
# Tor-dependent app shipped by default, so rather than leaving tor
# always-on (or building a manual toggle like 22-i2p-package-manager.sh's
# i2pd icon, which makes sense there because i2p usage is its own
# independent session), this wraps Feather's own launcher: it starts tor
# right before Feather opens and stops it again when Feather exits. No
# panel icon needed -- Tor's lifecycle is tied invisibly to Feather's own.
#
# Depends on 36-crypto-wallets.sh having installed feather-wallet (which
# pulls in `tor` as a Recommends).
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/39-feather-tor-ondemand.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting up on-demand Tor for Feather ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing scoped NOPASSWD sudoers rule for tor start/stop/is-active ---"
SUDOERS_FILE=/etc/sudoers.d/feather-tor-toggle
TMP_FILE="$(mktemp)"
cat > "$TMP_FILE" <<EOF
# Allow $TARGET_USER to start/stop/query the tor service without a password,
# so Feather's launcher wrapper can bring it up/down around its own
# lifecycle. Scoped to exactly these three invocations -- no wildcard/
# general systemctl access. Written by 39-feather-tor-ondemand.sh.
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start tor
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop tor
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active tor
EOF
if visudo -c -f "$TMP_FILE"; then
    install -m 0440 -o root -g root "$TMP_FILE" "$SUDOERS_FILE"
    echo "Installed $SUDOERS_FILE"
else
    echo "visudo syntax check FAILED, not installing $SUDOERS_FILE"
    rm -f "$TMP_FILE"
    exit 1
fi
rm -f "$TMP_FILE"

echo "--- Disabling tor boot autostart (leaves current running state alone) ---"
systemctl disable tor || echo "systemctl disable tor failed (non-fatal, may already be disabled)"
echo "tor.service enabled state is now: $(systemctl is-enabled tor 2>&1 || true)"

echo "--- Installing Feather launcher wrapper ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
cat > "$TARGET_HOME/.local/bin/feather-wrapper.sh" <<'EOF'
#!/bin/bash
# Starts the system Tor daemon before Feather opens and stops it again when
# Feather exits, so Tor isn't a heavy always-on background service --
# Feather is the only Tor-dependent app shipped by default. Skips the stop
# if another Feather window/instance is still running. Runs Feather itself
# under firejail (lib/feather.profile, see 40-jail-wallets-viber.sh) so the
# Tor start/stop stays outside the sandbox while the wallet process is
# isolated. Written by provisioning/39-feather-tor-ondemand.sh.
set -uo pipefail

sudo -n /usr/bin/systemctl start tor

for _ in $(seq 1 40); do
    if ss -tln 2>/dev/null | grep -q "127.0.0.1:9050"; then
        break
    fi
    sleep 0.25
done

firejail /usr/bin/feather "$@"

if ! pgrep -x feather >/dev/null; then
    sudo -n /usr/bin/systemctl stop tor
fi
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/bin/feather-wrapper.sh"
chmod 755 "$TARGET_HOME/.local/bin/feather-wrapper.sh"

echo "--- Overriding Feather's desktop launcher to use the wrapper ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/feather.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Feather Wallet
GenericName=Monero Wallet
Comment=A free Monero desktop wallet
Icon=feather
Exec=$TARGET_HOME/.local/bin/feather-wrapper.sh
Terminal=false
Categories=Network;
StartupNotify=false
StartupWMClass=feather
Keywords=crypto;currency;XMR
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/feather.desktop"

echo "=== $(date) : done ==="
