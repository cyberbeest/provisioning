#!/bin/bash
# Installs the microphone-recording panel indicator: a genmon widget
# (plugin-220, which 12-xfce-panel-layout.sh's template wires into the panel
# between the systray and the volume plugin) that is invisible while nothing
# records and flashes a red dot while an app records from a real microphone;
# the tooltip names the app(s). Security rationale: a breached app can
# record the room, and PulseAudio has no per-app permission for it -- this
# makes any recording visible. Names and PIDs are what each client claims,
# so it is a tripwire, not proof of who records.
#
# lib/mic-recording-watcher.sh (systemd --user service) follows
# `pactl subscribe` and keeps a state file under $XDG_RUNTIME_DIR;
# lib/mic-recording-genmon.sh (500 ms) renders it. Dictate's own recording
# shows up too, which is expected.
#
# Runs as 11b (after 11a, before 12-xfce-panel-layout.sh) for the same reason
# 11a does: the widget's script and rc must exist before the layout script
# wires plugin-220 into the panel and reloads it. 12 depends on this script
# having run, not the other way around.
#
# Idempotent: safe to re-run.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/11b-mic-recording-indicator.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing microphone-recording panel indicator ==="

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_UID="$(id -u "$TARGET_USER")"

# Must match the plugin-ids/xfce4-panel.xml.template slot 12-xfce-panel-
# layout.sh reserves for this widget.
GENMON_WIDGET="genmon-220"

echo "--- Installing dependencies (pactl, jq) ---"
apt-get -o DPkg::Lock::Timeout=60 update -qq
apt-get -o DPkg::Lock::Timeout=60 install -y pulseaudio-utils jq

echo "--- Installing scripts to $TARGET_HOME/.local/bin ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/mic-recording-watcher.sh" "$TARGET_HOME/.local/bin/mic-recording-watcher.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 \
	"$DIR/lib/mic-recording-genmon.sh" "$TARGET_HOME/.local/bin/mic-recording-genmon.sh"

# The watcher resolves its i18n catalogs relative to its own location, so
# they need a copy next to it -- same per-installed-directory duplication
# convention as 11a-clipboard-status.sh.
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 "$DIR/lib/i18n.sh" "$TARGET_HOME/.local/bin/i18n.sh"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/bin/i18n"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/i18n/strings.en.sh" "$DIR/lib/i18n/strings.de.sh" \
	"$TARGET_HOME/.local/bin/i18n/"

echo "--- Installing systemd user unit ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 644 \
	"$DIR/lib/mic-recording-watcher.service" \
	"$TARGET_HOME/.config/systemd/user/mic-recording-watcher.service"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/systemd/user/default.target.wants"
ln -sf ../mic-recording-watcher.service \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/mic-recording-watcher.service"
chown -h "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.config/systemd/user/default.target.wants/mic-recording-watcher.service"

echo "--- Writing $GENMON_WIDGET.rc ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel"
sed "s|__HOME__|$TARGET_HOME|g" "$DIR/lib/xfce-panel-layout/mic-recording-genmon.rc.template" \
	> "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4/panel/$GENMON_WIDGET.rc"

echo "--- Starting the watcher now, if the target user has an active session ---"
if [ -d "/run/user/$TARGET_UID" ]; then
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user daemon-reload
	sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
		systemctl --user restart mic-recording-watcher.service || true
else
	echo "no active session for $TARGET_USER -- it'll start at next login"
fi

echo "=== $(date) : done ==="
