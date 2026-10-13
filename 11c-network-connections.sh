#!/bin/bash
# Installs the network-connections panel icon: a genmon widget (plugin-221,
# which 12-xfce-panel-layout.sh's template wires into the panel next to the
# clipboard icon) whose tooltip lists which apps hold established TCP
# connections and how many, incoming and outgoing separately. Incoming should
# normally be zero (the firewall blocks it), so any incoming connection puts
# a red marker next to the globe. Security rationale: a breached app phones
# home through the same connections, so this makes them visible per app.
#
# Firejail hides sandboxed processes from ss, even from their own user, so
# the 10 s tooltip says "unknown" for those. Clicking the icon opens
# lib/connections-window.py, which asks each sandbox (firejail --join) which
# of its processes holds the socket and names the app. Apps in a separate
# network namespace (firejail --net) stay invisible; none of ours use it.
#
# Runs as 11c (after 11b, before 12-xfce-panel-layout.sh) for the same reason
# 11a/11b do: the widget's script and rc must exist before the layout script
# wires plugin-221 into the panel and reloads it.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/11c-network-connections.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing network-connections panel icon ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

# Must match the plugin-ids/xfce4-panel.xml.template slot 12-xfce-panel-
# layout.sh reserves for this widget.
GENMON_WIDGET="genmon-221"

echo "--- Installing dependencies (ss, GTK bindings, firejail) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y iproute2 python3-gi gir1.2-gtk-3.0 firejail

echo "--- Installing scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/connections-genmon.sh" "$TARGET_HOME/.local/bin/connections-genmon.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/connections-window.py" "$TARGET_HOME/.local/bin/connections-window.py"

# i18n.sh/i18n.py only resolve their catalogs relative to their own
# location, so they need a copy next to the scripts -- same per-installed-
# directory duplication convention as 11a-clipboard-status.sh.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.py" "$TARGET_HOME/.local/bin/i18n.py"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" \
	"$DIR/lib/i18n/strings_en.py" "$DIR/lib/i18n/strings_de.py" \
	"$TARGET_HOME/.local/bin/i18n/"

echo "--- Writing $GENMON_WIDGET.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$DIR/lib/xfce-panel-layout/connections-genmon.rc.template" \
	> "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"

echo "=== $(date) : done ==="
