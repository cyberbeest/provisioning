#!/bin/bash
# Wraps Signal, Telegram, and Element in firejail, using their stock
# community profiles (firejail-profiles package) so each app can only see
# its own data plus ~/Downloads -- same policy as the browser sandbox
# (see 10-browser-sandbox.sh and the manual's "Security decisions" chapter).
#
# Telegram's stock profile already whitelists ~/Downloads and is
# seccomp/apparmor hardened as shipped; its ".local" override only adds
# ~/Pictures (lib/telegram-desktop.local). Signal and Element only whitelist
# their own config dir by default, so their ".local" overrides add both
# ~/Downloads and ~/Pictures (see lib/signal-desktop.local, lib/element-desktop.local).
#
# Tor Browser is deliberately NOT jailed here: the stock torbrowser-launcher
# profile makes Tor itself fail with "Tor exited during startup", and it
# persists even with seccomp, seccomp.block-secondary, protocol, and
# netfilter all relaxed (2026-08-18 debugging session) -- something else in
# the profile (caps.drop, restrict-namespaces, or a private-bin gap) is the
# real cause. lib/torbrowser-sandbox.sh is kept around for when this gets
# picked back up, but nothing installs or wires it in yet.
#
# Viber, Sparrow, and Feather have no stock firejail profile and are NOT
# covered here -- they'd need hand-built profiles from scratch, more like
# lib/firefox-drm.profile than a one-line override. Left as a follow-up.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/38-jail-messengers.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : jailing messengers/comms apps ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing firejail-profiles (in case 10-browser-sandbox.sh hasn't run) ---"
apt-get -o DPkg::Lock::Timeout=60 install -y firejail firejail-profiles

echo "--- Installing Downloads/Pictures-access overrides for Signal, Element, and Telegram ---"
install -m 644 "$DIR/lib/signal-desktop.local" /etc/firejail/signal-desktop.local
install -m 644 "$DIR/lib/element-desktop.local" /etc/firejail/element-desktop.local
install -m 644 "$DIR/lib/telegram-desktop.local" /etc/firejail/telegram-desktop.local

echo "--- Allowing userns_create in the firejail-default AppArmor profile (needed by Electron's own internal sandbox) ---"
# Signal/Element/Telegram are Electron apps -- Electron's own Chromium-based
# sandbox creates a user namespace as part of its own hardening. Without
# this, it fails immediately with a FATAL sandbox/credentials.cc error and
# the app never starts at all. Not a dpkg-managed file (apparmor_parser
# creates it empty on first profile compile if missing), so this is safe to
# write directly, no conffile-upgrade risk.
cat > /etc/apparmor.d/local/firejail-default <<'EOF'
# Needed by Electron's own internal (Chromium) sandbox -- see
# 38-jail-messengers.sh.
userns,
EOF
apparmor_parser -r /etc/apparmor.d/firejail-default

echo "--- Installing sandbox wrapper scripts to $TARGET_HOME/bin/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/bin"
for f in signal-sandbox.sh telegram-sandbox.sh element-sandbox.sh; do
	install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$DIR/lib/$f" "$TARGET_HOME/bin/$f"
done

echo "--- Pre-seeding Element's safeStorage backend (skips the OS keyring) ---"
# Same underlying issue as Signal's --password-store=basic (see
# lib/signal-sandbox.sh): Electron's keyring detection fails whenever there's
# no usable gnome-keyring/kwallet/libsecret backend. Signal just breaks
# silently in that case; Element is more upfront and shows a blocking
# "System unsupported" dialog on its very first launch, requiring a manual
# click through "Use weaker encryption" before it'll start at all. Once
# accepted it remembers the choice in this same file (safeStorageBackend),
# so pre-seeding it here avoids that first-launch dialog outright (confirmed
# 2026-09-25 in the KVM test VM). Only sets the key if the file doesn't
# already have an opinion, so it won't clobber a real backend Element
# already detected and is using successfully.
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/Element"
sudo -u "$TARGET_USER" python3 -c "
import json, os

path = os.path.expanduser('~/.config/Element/electron-config.json')
try:
    with open(path) as f:
        cfg = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}
cfg.setdefault('safeStorageBackend', 'basic_text')
with open(path, 'w') as f:
    json.dump(cfg, f, indent='\t')
"

echo "--- Installing .desktop overrides to $TARGET_HOME/.local/share/applications/ ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"

cat > "$TARGET_HOME/.local/share/applications/signal-desktop.desktop" <<EOF
[Desktop Entry]
Name=Signal
Exec=$TARGET_HOME/bin/signal-sandbox.sh %U
Terminal=false
Type=Application
Icon=signal-desktop
StartupWMClass=signal
Comment=Private messaging from your desktop (sandboxed)
Comment[de]=Private Nachrichten (isoliert/Firejail)
MimeType=x-scheme-handler/sgnl;x-scheme-handler/signalcaptcha;
Categories=Messengers;
Path=
StartupNotify=false
EOF

cat > "$TARGET_HOME/.local/share/applications/element-desktop.desktop" <<EOF
[Desktop Entry]
Name=Element
Exec=$TARGET_HOME/bin/element-sandbox.sh %U
Terminal=false
Type=Application
Icon=element-desktop
StartupWMClass=Element
Comment=Element: the future of secure communication (sandboxed)
Comment[de]=Element: sichere Kommunikation (isoliert/Firejail)
MimeType=x-scheme-handler/io.element.desktop;x-scheme-handler/element;
Categories=Messengers;
Path=
StartupNotify=false
EOF

cat > "$TARGET_HOME/.local/share/applications/org.telegram.desktop.desktop" <<EOF
[Desktop Entry]
Name=Telegram
Comment=Telegram messaging app (sandboxed)
Comment[de]=Telegram (isoliert/Firejail)
TryExec=telegram-desktop
Exec=$TARGET_HOME/bin/telegram-sandbox.sh -- %u
Icon=telegram
Terminal=false
StartupWMClass=TelegramDesktop
Type=Application
Categories=Messengers;
MimeType=x-scheme-handler/tg;
Keywords=tg;chat;im;messaging;messenger;sms;tdesktop;
Actions=quit;
SingleMainWindow=true
X-GNOME-UsesNotifications=true
X-GNOME-SingleWindow=true
Path=
StartupNotify=false

[Desktop Action quit]
Exec=$TARGET_HOME/bin/telegram-sandbox.sh -quit
Name=Quit Telegram
Icon=application-exit
EOF

echo "--- Updating Telegram's autostart entry to launch sandboxed too ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
cat > "$TARGET_HOME/.config/autostart/org.telegram.desktop.desktop" <<EOF
[Desktop Entry]
Name=Telegram Desktop
Comment=Official desktop version of Telegram messaging app
TryExec=telegram-desktop
Exec=$TARGET_HOME/bin/telegram-sandbox.sh -autostart
Icon=telegram
Terminal=false
StartupWMClass=TelegramDesktop
Type=Application
Categories=Messengers;
Keywords=tg;chat;im;messaging;messenger;sms;tdesktop;
Actions=quit;
SingleMainWindow=true
X-GNOME-UsesNotifications=true
X-GNOME-SingleWindow=true
EOF

for f in signal-desktop.desktop element-desktop.desktop org.telegram.desktop.desktop; do
	chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/$f"
done
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/org.telegram.desktop.desktop"

echo "--- Refreshing desktop database ---"
sudo -u "$TARGET_USER" update-desktop-database "$TARGET_HOME/.local/share/applications" 2>&1 || true

echo "--- Restarting any already-running unsandboxed instances ---"
sudo -u "$TARGET_USER" pkill -f '^/opt/Signal/signal-desktop' 2>&1 || true
sudo -u "$TARGET_USER" pkill -f '^/opt/Element/element-desktop' 2>&1 || true
sudo -u "$TARGET_USER" pkill -f 'telegram-desktop -autostart' 2>&1 || true
sleep 1

PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
if [ -n "$PANEL_PID" ]; then
	DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' '$TARGET_HOME/bin/telegram-sandbox.sh' -autostart >/dev/null 2>&1 &" || true
else
	echo "note: no logged-in panel session found, Telegram will just relaunch sandboxed next time it's started"
fi

echo "=== $(date) : done ==="
