#!/bin/bash
# Jails Google Chrome (opt-in via the package manager) with firejail, the
# same way 38-jail-messengers.sh jails the Electron messengers: stock
# google-chrome-stable profile from firejail-profiles, plus a .local
# override adding ~/Downloads and ~/Pictures.
#
# The launcher override is hidden until Chrome is actually installed
# (TryExec), so nothing shows up in Whisker for users who never opt in.
# Firefox stays the default browser: 10-browser-sandbox.sh registers its
# wrapper in x-www-browser at priority 300, above Chrome's 200.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/40a-jail-chrome.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : jailing Google Chrome ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing firejail-profiles (in case earlier steps haven't run) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y firejail firejail-profiles

echo "--- Installing Downloads/Pictures-access override for Chrome ---"
install -m 644 "$DIR/lib/google-chrome-stable.local" /etc/firejail/google-chrome-stable.local

echo "--- Allowing userns_create in the firejail-default AppArmor profile (needed by Chrome's own internal sandbox) ---"
# Same requirement and same file as 38-jail-messengers.sh; only written if
# that step hasn't already.
if ! grep -qx 'userns,' /etc/apparmor.d/local/firejail-default 2>/dev/null; then
	cat > /etc/apparmor.d/local/firejail-default <<'INNER'
# Needed by Electron's/Chrome's own internal (Chromium) sandbox -- see
# 38-jail-messengers.sh and 40a-jail-chrome.sh.
userns,
INNER
	apparmor_parser -r /etc/apparmor.d/firejail-default
fi

echo "--- Installing sandbox wrapper to $TARGET_HOME/bin/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/chrome-sandbox.sh" "$TARGET_HOME/bin/chrome-sandbox.sh"

echo "--- Redirecting bare google-chrome-stable / google-chrome / chrome (and joke alias) commands to the wrapper ---"
# /usr/local/bin comes before /usr/bin in PATH, so these shadow the real
# binaries for terminal and script launches. The wrapper execs
# /usr/bin/google-chrome-stable by absolute path, so there is no recursion.
for name in google-chrome-stable google-chrome chrome that-google-browser-thing i-feel-googly-today give-all-my-data-away; do
	cat > "/usr/local/bin/$name" <<'INNER'
#!/bin/bash
# Redirects the bare command to the firejail-sandboxed Chrome (see
# 40a-jail-chrome.sh).
exec "$HOME/bin/chrome-sandbox.sh" "$@"
INNER
	chmod 755 "/usr/local/bin/$name"
done

echo "--- Installing .desktop override to $TARGET_HOME/.local/share/applications/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/google-chrome.desktop" <<INNER
[Desktop Entry]
Version=1.0
Name=Google Chrome
Comment=Access the Internet (sandboxed)
Comment[de]=Internet-Zugriff (isoliert/Firejail)
GenericName=Web Browser
TryExec=/usr/bin/google-chrome-stable
Exec=$TARGET_HOME/bin/chrome-sandbox.sh %U
StartupNotify=true
StartupWMClass=google-chrome
Terminal=false
Icon=google-chrome
Type=Application
Categories=Network;WebBrowser;
MimeType=text/html;application/xhtml+xml;x-scheme-handler/http;x-scheme-handler/https;x-scheme-handler/google-chrome;
Actions=new-window;new-private-window;
Path=

[Desktop Action new-window]
Name=New Window
Exec=$TARGET_HOME/bin/chrome-sandbox.sh

[Desktop Action new-private-window]
Name=New Incognito Window
Exec=$TARGET_HOME/bin/chrome-sandbox.sh --incognito
INNER
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/google-chrome.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" 2>&1 || true

echo "=== $(date) : done ==="
