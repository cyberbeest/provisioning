#!/bin/bash
# Turns off the keyboard "AccessX" shortcuts for everyone: holding Shift for 8 seconds
# (slow keys) or pressing it five times (sticky keys) otherwise switches those features on
# by accident, and the keyboard then behaves strangely until someone finds the setting.
# Sticky, slow and bounce keys themselves are switched off as well. The X server forgets
# these controls at every start, so an autostart entry applies them at each login
# (and the script applies them to the running session once, if it can reach it).
# Depends on: nothing. Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/46a-disable-sticky-keys.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : disabling AccessX / sticky keys ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

if ! dpkg -s xkbset >/dev/null 2>&1; then
	apt-get -o DPkg::Lock::Timeout=60 install -y xkbset
fi

echo "--- Autostart entry ---"
cat > /etc/xdg/autostart/cyberbeest-no-sticky-keys.desktop <<'EOF2'
[Desktop Entry]
Type=Application
Name=Cyberbeest: no sticky keys
Comment=Switches off the Shift shortcuts for sticky and slow keys
Exec=xkbset -a -sticky -slowkeys -bouncekeys
NoDisplay=true
OnlyShowIn=XFCE;
X-XFCE-Autostart-Phase=Initialization
EOF2

echo "--- Applying to the running session (if there is one) ---"
if [ -S /tmp/.X11-unix/X0 ]; then
	sudo -u "$TARGET_USER" env DISPLAY=:0 XAUTHORITY="$TARGET_HOME/.Xauthority" \
		xkbset -a -sticky -slowkeys -bouncekeys && echo "applied" || echo "could not reach the session; takes effect at next login"
else
	echo "no X session; takes effect at next login"
fi

echo "=== $(date) : done ==="
