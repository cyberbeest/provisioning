#!/bin/bash
# Sets up Cyberbeest's Whisker Menu category structure -- found to be missing
# from provisioning entirely on 2026-08-27 (same class of gap as
# 46-cyberbeest-keyboard-shortcuts.sh): several installer scripts have
# already been tagging their .desktop files with Categories=Cyberbeest;
# (21-, 22-, 25-, 42-, 43-, 44-) but nothing ever wrote the actual "Cyberbeest"
# submenu into ~/.config/menus/xfce-applications.menu, so on a freshly
# provisioned machine those apps fell into the generic "Other" bucket instead
# of their own category. This script adds that submenu, plus four more that
# split up what used to be one big undifferentiated "Internet" list:
#   - Cyberbeest: this project's own GUIs (was silently missing, see above)
#   - Messengers: Signal/Element/Telegram/Viber/Cwtch
#   - Wallets: Sparrow/Feather
#   - Darknet: Tor Browser, i2pd
#   - Mail: Kleopatra, Proton Mail
# Only the menu scaffolding (the submenu definitions + their .directory
# label/icon files) lives here. The actual Categories= tag on each app's
# .desktop file is set at the point that app is installed (10-, 22-, 29-,
# 33-, 38-, 39-, 40-, 45-), not overridden after the fact from here --
# keeping one source of truth per app instead of a second script racing the
# first. If an app referenced above isn't installed on a given machine, its
# category just renders empty and Whisker hides it -- see
# 45-hide-redundant-terminals.sh's NoDisplay approach for the general
# principle of hiding rather than fighting the menu system.
# Idempotent: safe to re-run (this script fully owns every file it writes,
# so no pre-existing content to back up, unlike 33-/46- which patch into
# files other scripts or Debian itself might also touch).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/48-whisker-menu-categories.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : setting up Whisker menu categories ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

MENU_DIR="$TARGET_HOME/.config/menus"
DIRS_DIR="$TARGET_HOME/.local/share/desktop-directories"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$MENU_DIR" "$DIRS_DIR"

# .local/share/cyberbeest/icons is the fixed, non-user-facing location used
# throughout provisioning (09-, 12-, 21-, 22-, 25-) specifically because
# ~/Pictures gets translated (e.g. to ~/Bilder under a German locale) by
# xdg-user-dirs -- a hardcoded ~/Pictures/... path silently breaks this icon
# on any non-English-locale install.
ICONS_DIR="$TARGET_HOME/.local/share/cyberbeest/icons"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$ICONS_DIR"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/assets/Cyberbeest-black.png" "$ICONS_DIR/Cyberbeest-black.png"

echo "--- Writing $MENU_DIR/xfce-applications.menu ---"
cat > "$MENU_DIR/xfce-applications.menu" <<'EOF'
<!DOCTYPE Menu PUBLIC "-//freedesktop//DTD Menu 1.0//EN"
 "http://www.freedesktop.org/standards/menu-spec/menu-1.0.dtd">
<Menu>
  <Name>Xfce</Name>
  <MergeFile type="parent">/etc/xdg/menus/xfce-applications.menu</MergeFile>

  <Menu>
    <Name>Cyberbeest</Name>
    <Directory>cyberbeest.directory</Directory>
    <Include>
      <Category>Cyberbeest</Category>
    </Include>
  </Menu>

  <Menu>
    <Name>Messengers</Name>
    <Directory>messengers.directory</Directory>
    <Include>
      <Category>Messengers</Category>
    </Include>
  </Menu>

  <Menu>
    <Name>Wallets</Name>
    <Directory>wallets.directory</Directory>
    <Include>
      <Category>Wallets</Category>
    </Include>
  </Menu>

  <Menu>
    <Name>Darknet</Name>
    <Directory>darknet.directory</Directory>
    <Include>
      <Category>Darknet</Category>
    </Include>
  </Menu>

  <Menu>
    <Name>Mail</Name>
    <Directory>mail.directory</Directory>
    <Include>
      <Category>Mail</Category>
    </Include>
  </Menu>
</Menu>
EOF
chown "$TARGET_USER:$TARGET_USER" "$MENU_DIR/xfce-applications.menu"

echo "--- Writing $DIRS_DIR/*.directory ---"

# Cyberbeest is a brand name -- no Name[de], same as everywhere else the
# product name itself appears (see cyberbeest-*.desktop files: only their
# *descriptions* get Comment[de], never the "Cyberbeest" in the Name).
cat > "$DIRS_DIR/cyberbeest.directory" <<EOF
[Desktop Entry]
Version=1.0
Type=Directory
Name=Cyberbeest
Icon=$ICONS_DIR/Cyberbeest-black.png
EOF

cat > "$DIRS_DIR/messengers.directory" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Directory
Name=Messengers
Name[de]=Messenger
Icon=internet-group-chat
EOF

cat > "$DIRS_DIR/wallets.directory" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Directory
Name=Wallets
Name[de]=Wallets
Icon=/opt/sparrowwallet/lib/Sparrow.png
EOF

cat > "$DIRS_DIR/darknet.directory" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Directory
Name=Darknet
Name[de]=Darknet
Icon=user-invisible
EOF

cat > "$DIRS_DIR/mail.directory" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Directory
Name=Mail
Name[de]=Mail
Icon=internet-mail
EOF

chown "$TARGET_USER:$TARGET_USER" \
	"$DIRS_DIR/cyberbeest.directory" \
	"$DIRS_DIR/messengers.directory" \
	"$DIRS_DIR/wallets.directory" \
	"$DIRS_DIR/darknet.directory" \
	"$DIRS_DIR/mail.directory"

echo "--- Refreshing a live panel, if one is running ---"
PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
if [ -n "$PANEL_PID" ]; then
	DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
	rm -f "$TARGET_HOME/.cache/menus"/*.menu 2>/dev/null || true
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
fi

echo "=== $(date) : done ==="
