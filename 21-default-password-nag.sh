#!/bin/bash
# Installs the change-password GUI (lib/disk_password_gui.py, as
# "cyberbeest-change-password") plus a login-time nag that checks whether
# the LUKS master password and/or the cyberbeest login (short) password
# still match whatever they were initially set to, and if so prompts the
# user to change them -- opening the change-password GUI with the relevant
# tab preselected, then re-checking and nagging again after it closes (see
# lib/cyberbeest-password-nag.py).
#
# The actual initial-password value is NEVER part of this repo or this
# script -- it only exists, if at all, in /etc/cyberbeest/initial-
# passwords.conf, a root-only local file you create by hand, once, right
# after actually setting the password:
#
#   sudo cyberbeest-record-initial-password master '<the value you just set it to>' weak
#   sudo cyberbeest-record-initial-password short '<the value you just set it to>' weak
#
# For a shipped unit, generate a real per-device passphrase (e.g. via the
# change-password GUI's own "Generate" button), put it on a sticker, set it
# as the actual password, and record it tagged "secure" instead of "weak" --
# secure-tagged defaults get a "keep it" option in the nag instead of only
# "change now". A self-installer who sets their own password during Debian
# install never runs the record command at all, so there's nothing to check
# and the nag never appears.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/21-default-password-nag.log"
exec > "$LOG" 2>&1

echo "=== $(date) : installing default-password nag ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Installing dependencies ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
# python3-gi/gir1.2-gtk-3.0: both GUIs. python3-legacycrypt: Python 3.13
# dropped the stdlib crypt module the checker used to verify the short
# password's /etc/shadow hash; legacycrypt is the upstream-recommended,
# still crypt(3)-backed replacement (correctly handles yescrypt, Debian
# 12+'s default). cryptsetup: normally already present on an encrypted
# install, but installed defensively here too.
apt-get -o DPkg::Lock::Timeout=60 install -y python3-gi gir1.2-gtk-3.0 python3-legacycrypt cryptsetup

echo "--- Installing cyberbeest-change-password (disk_password_gui.py) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/disk_password_gui.py" "$TARGET_HOME/.local/bin/cyberbeest-change-password"
# WORDLISTS_DIR in disk_password_gui.py is resolved relative to the script's
# own path, so the wordlists have to live alongside it here.
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/wordlists"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/wordlists/wordlist_en.txt" "$DIR/lib/wordlists/wordlist_de.txt" \
	"$TARGET_HOME/.local/bin/wordlists/"

echo "--- Installing icon (in case 08-cyberbeest-power-settings.sh hasn't run) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/Pictures"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" "$TARGET_HOME/Pictures/Cyberbeest-black.png"

echo "--- Installing app menu entry (Whisker menu, Settings category) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"
cat > "$TARGET_HOME/.local/share/applications/cyberbeest-change-password.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest Change Password
Comment=Change the master (disk) or short (login) password
Exec=$TARGET_HOME/.local/bin/cyberbeest-change-password
Icon=$TARGET_HOME/Pictures/Cyberbeest-black.png
Terminal=false
Categories=Cyberbeest;Settings;
StartupNotify=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/cyberbeest-change-password.desktop"

echo "--- Installing root checker + recorder tools ---"
install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-check-default-passwords.sh" /usr/local/sbin/cyberbeest-check-default-passwords
install -o root -g root -m 755 \
	"$DIR/lib/cyberbeest-record-initial-password.sh" /usr/local/sbin/cyberbeest-record-initial-password

echo "--- Installing narrowly-scoped NOPASSWD sudoers rule for the checker ---"
# Exact path, no arguments -- lets the login-time nag run the (read-only,
# no-secrets-printed) checker without an interactive auth prompt, without
# granting any broader passwordless root access.
SUDOERS_TMP="$(mktemp)"
echo "$TARGET_USER ALL=(root) NOPASSWD: /usr/local/sbin/cyberbeest-check-default-passwords \"\"" > "$SUDOERS_TMP"
if /usr/sbin/visudo -c -f "$SUDOERS_TMP"; then
	install -o root -g root -m 440 "$SUDOERS_TMP" /etc/sudoers.d/cyberbeest-check-default-passwords
else
	echo "Generated sudoers rule failed validation -- NOT installing it." >&2
	rm -f "$SUDOERS_TMP"
	exit 1
fi
rm -f "$SUDOERS_TMP"

echo "--- Installing login-time nag script ---"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/cyberbeest-password-nag.py" "$TARGET_HOME/.local/bin/cyberbeest-password-nag"

echo "--- Installing autostart entry ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/autostart"
sed "s|/home/cyberbeest/|$TARGET_HOME/|g" "$DIR/lib/cyberbeest-password-nag.desktop" \
	> "$TARGET_HOME/.config/autostart/cyberbeest-password-nag.desktop"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-password-nag.desktop"

echo "--- Auto-recording dev-default passwords from the environment, if applicable ---"
# Convenience for repeat local/VM test runs only: if nothing has been
# recorded yet AND you've exported CYBERBEEST_DEV_MASTER_PASSWORD /
# CYBERBEEST_DEV_SHORT_PASSWORD in your own shell (e.g. your local
# ~/.bashrc -- NEVER committed to this repo) before running this script,
# record them as "weak" so you don't have to run
# cyberbeest-record-initial-password by hand every time. Silently does
# nothing if the conf already exists (something's already recorded) or the
# env vars aren't set -- this is not how a shipped unit's real per-device
# password gets recorded, that's still always the manual "secure"-tagged
# step described in README.md.
#
# `sudo` strips the environment by default, so these only come through if
# you invoke this script (or menu.sh/run-all.sh) with `sudo -E`.
if [ ! -e /etc/cyberbeest/initial-passwords.conf ]; then
	if [ -n "${CYBERBEEST_DEV_MASTER_PASSWORD:-}" ]; then
		/usr/local/sbin/cyberbeest-record-initial-password master "$CYBERBEEST_DEV_MASTER_PASSWORD" weak
	fi
	if [ -n "${CYBERBEEST_DEV_SHORT_PASSWORD:-}" ]; then
		/usr/local/sbin/cyberbeest-record-initial-password short "$CYBERBEEST_DEV_SHORT_PASSWORD" weak
	fi
fi

echo "=== $(date) : done. Nag runs at next login; run cyberbeest-password-nag now to test. ==="
