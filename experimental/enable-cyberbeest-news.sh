#!/bin/bash
# EXPERIMENTAL: Cyberbeest News headlines in the Whisker menu.
#
# Every ~2 hours (after a real security-update run) the machine fetches one
# small static list of headlines from https://news.cyberbeest.com/headlines.json
# (conditional GET: unchanged = body-less 304, no cookies, no machine ID,
# no server-side access logs), accumulates them locally and shows the newest 5
# as menu entries in a last-placed category "Ω Cyberbeest News". Clicking one
# opens the page in Firefox. The Ω makes Whisker's own category sort put the
# category last: Greek letters sort after the Latin alphabet (checked for
# en_US only -- check on a German machine).
#
# What it changes:
#  1. /usr/local/sbin/cyberbeest-news-fetch.sh (lib/cyberbeest-news-fetch.sh)
#     and /var/lib/cyberbeest-news/ (headline archive + ETag).
#  2. /etc/systemd/system/security-update-check.service.d/cyberbeest-news.conf:
#     an ExecStopPost= that runs the fetch (failures ignored, 40 s timeout).
#     Nothing in the mainline security-update scripts is edited.
#  3. The user's ~/.config/menus/xfce-applications.menu gets a CyberbeestNews
#     submenu and ~/.local/share/desktop-directories/cyberbeest-news.directory
#     is written. NOTE: re-running 48-whisker-menu-categories.sh rewrites that
#     menu file without the submenu; re-run this script afterwards.
#
# Opt-out without uninstalling: sudo touch /etc/cyberbeest/news-disabled
# Usage: sudo bash enable-cyberbeest-news.sh
# Undo:  sudo bash disable-cyberbeest-news.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/enable-cyberbeest-news.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing Cyberbeest News ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

if ! systemctl cat security-update-check.service >/dev/null 2>&1; then
	echo "security-update-check.service not found -- run 07-security-update-timer.sh first." >&2
	exit 1
fi

echo "--- Fetch script ---"
install -D -m 755 "$DIR/lib/cyberbeest-news-fetch.sh" /usr/local/sbin/cyberbeest-news-fetch.sh
install -d -m 755 /var/lib/cyberbeest-news /etc/cyberbeest

echo "--- systemd drop-in ---"
install -d -m 755 /etc/systemd/system/security-update-check.service.d
cat > /etc/systemd/system/security-update-check.service.d/cyberbeest-news.conf <<'EOF'
[Service]
# Leading "-": a failure never marks the security check as failed. The fetch
# script throttles itself to about one real request per 2 hours.
ExecStopPost=-/usr/bin/timeout 40 /usr/local/sbin/cyberbeest-news-fetch.sh
EOF
systemctl daemon-reload

echo "--- Menu category ---"
MENU_DIR="$TARGET_HOME/.config/menus"
DIRS_DIR="$TARGET_HOME/.local/share/desktop-directories"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$MENU_DIR" "$DIRS_DIR"

cat > "$DIRS_DIR/cyberbeest-news.directory" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Directory
Name=Ω Cyberbeest News
Name[de]=Ω Cyberbeest Neuigkeiten
Icon=news-subscribe
EOF
chown "$TARGET_USER:$TARGET_USER" "$DIRS_DIR/cyberbeest-news.directory"

MENU_FILE="$MENU_DIR/xfce-applications.menu"
if [ ! -e "$MENU_FILE" ]; then
	cat > "$MENU_FILE" <<'EOF'
<!DOCTYPE Menu PUBLIC "-//freedesktop//DTD Menu 1.0//EN"
 "http://www.freedesktop.org/standards/menu-spec/menu-1.0.dtd">
<Menu>
  <Name>Xfce</Name>
  <MergeFile type="parent">/etc/xdg/menus/xfce-applications.menu</MergeFile>
</Menu>
EOF
	chown "$TARGET_USER:$TARGET_USER" "$MENU_FILE"
fi
python3 - "$MENU_FILE" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
if "<Name>CyberbeestNews</Name>" in s:
    print("menu already has the CyberbeestNews submenu")
else:
    blk = """
  <Menu>
    <Name>CyberbeestNews</Name>
    <Directory>cyberbeest-news.directory</Directory>
    <Include>
      <Category>CyberbeestNews</Category>
    </Include>
  </Menu>
"""
    i = s.rstrip().rfind("</Menu>")
    s = s[:i].rstrip("\n") + "\n" + blk + s[i:]
    open(p, "w").write(s)
    print("added the CyberbeestNews submenu")
PYEOF

echo "--- First fetch (best-effort) ---"
CYBERBEEST_NEWS_FORCE=1 /usr/local/sbin/cyberbeest-news-fetch.sh || true

echo "=== $(date) : done ==="
