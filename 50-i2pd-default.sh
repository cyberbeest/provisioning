#!/bin/bash
# Installs i2pd by default (2026-08-27 policy change: i2pd moves from an
# opt-in Cyberbeest Package Manager row to the same default tier as
# Signal/Firefox/etc -- see lib/cyberbeest_package_manager_gui.py, which no
# longer lists it). Only the *package* is default; actually running it
# stays a manual choice -- i2pd.service is disabled from boot-autostart and
# only the "Start I2P (i2pd)" Whisker launcher (Darknet category) or a
# restored previous session starts it. qBittorrent remains its own opt-in
# row, unrelated to this script.
#
# Reuses the exact same root-side setup as the (former) opt-in path --
# lib/cyberbeest-pkg-helper.sh's setup-i2pd-toggle installs the scoped
# NOPASSWD sudoers rule the toggle scripts need and disables boot-autostart;
# see that file's header comment for why it's safe to call directly here
# instead of through pkexec (provisioning already runs as root). The
# unprivileged half (Firefox eepsite profile, toggle scripts, Darknet
# launcher) is lib/setup_i2p_extras.py, run here as the target user instead
# of from the package manager GUI.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/50-i2pd-default.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing i2pd (default, off until started) ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing i2pd ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y i2pd

echo "--- Setting up the on-demand toggle (sudoers rule, disables boot-autostart) ---"
"$DIR/lib/cyberbeest-pkg-helper.sh" setup-i2pd-toggle

# Debian's i2pd postinst starts the service immediately on a fresh install
# (before the disable above takes effect on the *next* boot) -- stop it now
# so a freshly provisioned machine doesn't have it running until the user
# actually asks for it.
systemctl stop i2pd 2>/dev/null || true

echo "--- Installing the eepsite Firefox profile + toggle scripts/launchers as $TARGET_USER ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/setup_i2p_extras.py" "$TARGET_HOME/.local/bin/setup_i2p_extras.py"
sudo -u "$TARGET_USER" python3 "$TARGET_HOME/.local/bin/setup_i2p_extras.py"

echo "=== $(date) : done ==="
