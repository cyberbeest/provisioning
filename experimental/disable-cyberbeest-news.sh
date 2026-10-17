#!/bin/bash
# Undoes enable-cyberbeest-news.sh: removes the systemd drop-in, the fetch
# script, the headline entries and archive, and the "Ω Cyberbeest News" menu
# category. Leaves /etc/cyberbeest/news-disabled alone if present.
# Usage: sudo bash disable-cyberbeest-news.sh
# Idempotent: safe to re-run.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/disable-cyberbeest-news.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : removing Cyberbeest News ==="

if [ "$(id -u)" -ne 0 ]; then
	echo "Must run as root (sudo bash $0)." >&2
	exit 1
fi
TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

rm -f /etc/systemd/system/security-update-check.service.d/cyberbeest-news.conf
rmdir /etc/systemd/system/security-update-check.service.d 2>/dev/null || true
systemctl daemon-reload

rm -f /usr/share/applications/cyberbeest-news-*.desktop
rm -f /usr/local/sbin/cyberbeest-news-fetch.sh
rm -rf /var/lib/cyberbeest-news
rmdir /etc/cyberbeest 2>/dev/null || true

rm -f "$TARGET_HOME/.local/share/desktop-directories/cyberbeest-news.directory"
MENU_FILE="$TARGET_HOME/.config/menus/xfce-applications.menu"
if [ -e "$MENU_FILE" ]; then
	python3 - "$MENU_FILE" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
n = re.sub(r"\n  <Menu>\n    <Name>CyberbeestNews</Name>.*?</Menu>\n", "\n", s, flags=re.S)
if n != s:
    open(p, "w").write(n)
    print("removed the CyberbeestNews submenu")
PYEOF
fi

echo "=== $(date) : done ==="
