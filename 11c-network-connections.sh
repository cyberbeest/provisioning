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
# Opt-in country flags: see lib/geo.py and cyberbeest-vserver/geo/.
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
apt-get -o DPkg::Lock::Timeout=60 install -y iproute2 python3-gi gir1.2-gtk-3.0 firejail iso-codes

echo "--- Installing scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/connections-genmon.sh" "$TARGET_HOME/.local/bin/connections-genmon.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/connections-window.py" "$TARGET_HOME/.local/bin/connections-window.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/connections_lookup.py" "$TARGET_HOME/.local/bin/connections_lookup.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/geo.py" "$TARGET_HOME/.local/bin/geo.py"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/connections-names.txt" "$TARGET_HOME/.local/bin/connections-names.txt"

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

# Country flags (opt-in in Settings): the weekly list refresh is a user timer
# that does nothing while the option is off, and the flag font is installed by
# Settings when the option is first turned on, through this scoped sudo rule.
echo "--- Installing the weekly country-list refresh timer and the font sudo rule ---"
UNITS="$TARGET_HOME/.config/systemd/user"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$UNITS" "$UNITS/timers.target.wants"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/geo-update.service" "$DIR/lib/geo-update.timer" "$UNITS/"
ln -sf ../geo-update.timer "$UNITS/timers.target.wants/geo-update.timer"
chown -h "$TARGET_USER:$TARGET_USER" "$UNITS/timers.target.wants/geo-update.timer"
SUDOERS_TMP="$(mktemp)"
echo "$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/apt-get install -y fonts-noto-color-emoji" > "$SUDOERS_TMP"
visudo -c -f "$SUDOERS_TMP"
install -m 0440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/cyberbeest-emoji-font
rm -f "$SUDOERS_TMP"
TARGET_UID="$(id -u "$TARGET_USER")"

# Host names in the connections window (opt-in in Settings): a small service that
# only captures packets reads the DNS answers on loopback and answers "name for
# this IP?" over a socket (lib/cyberbeest-dns-watch.py). Installed here but not
# started; Settings enables/disables it through the scoped sudo rule below.
echo "--- Installing the (disabled) DNS name watcher service ---"
id cyberbeest-dnswatch >/dev/null 2>&1 || \
	useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin cyberbeest-dnswatch
install -d -m 755 -o root -g root /usr/local/lib/cyberbeest-dns-watch
install -m 755 -o root -g root "$DIR/lib/cyberbeest-dns-watch.py" /usr/local/lib/cyberbeest-dns-watch/cyberbeest-dns-watch.py
sed -e "s|__GROUP__|$(id -gn "$TARGET_USER")|" -e "s|__UID__|$TARGET_UID|" \
	"$DIR/lib/cyberbeest-dns-watch.service.template" > /etc/systemd/system/cyberbeest-dns-watch.service
chmod 644 /etc/systemd/system/cyberbeest-dns-watch.service
systemctl daemon-reload
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<SUDOERS
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl enable --now cyberbeest-dns-watch.service
$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl disable --now cyberbeest-dns-watch.service
SUDOERS
visudo -c -f "$SUDOERS_TMP"
install -m 0440 -o root -g root "$SUDOERS_TMP" /etc/sudoers.d/cyberbeest-dns-watch
rm -f "$SUDOERS_TMP"

if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user start geo-update.timer || true
fi

echo "--- Writing $GENMON_WIDGET.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$DIR/lib/xfce-panel-layout/connections-genmon.rc.template" \
	> "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"

echo "=== $(date) : done ==="
