#!/bin/bash
# Installs the Cyberbeest panel (gopanel, experimental/gopanel): the pure-Go X11 panel that
# replaces the XFCE panel -- same layout and plugins (it reads the xfce4-panel config), but no
# flicker at startup, a faster menu and far lower memory use.
#
# It is the default panel: this script switches the running session over (and at every login
# cyberbeest-panel-choice.sh, autostart, starts the chosen panel and stops the other). Cyberbeest Settings > Panel switches back; that choice is kept in
# ~/.config/cyberbeest/panel.conf and this script never overrides it once it exists. The XFCE
# panel stays installed and is what xfce-panel-watchdog brings back if gopanel ever dies.
#
# The binaries are not built here: release.sh (experimental/gopanel) builds them on the dev
# machine and publishes a tarball at cyberbeest.com/gopanel/, named after its own hash. The
# SHA-256 below is pinned in this (public, GitHub-hosted) script and verified after the
# download, so a changed host cannot swap the panel. Publishing a new version = run
# release.sh --publish, which updates these three pins; committing them rolls it out.
#
# Depends on: 12-xfce-panel-layout.sh (the config gopanel mirrors), 46-cyberbeest-keyboard-
# shortcuts.sh (Super key -> cyberbeest-whisker-key.sh), 60-xfce-panel-watchdog.sh (honours the
# "XFCE panel stopped on purpose" marker). Needs network for the download; if it fails, the
# XFCE panel simply stays the panel.
# Idempotent: safe to re-run. A running gopanel is restarted into a new version (`gopanel
# restart`, helpers keep running).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/69-cyberbeest-panel.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest panel ==="

GOPANEL_VERSION="0.21.15"
GOPANEL_SHA256="fa6d91b37a736c87ed904bb602017e1aff6a829376106acf03f52ea963fb951d"
GOPANEL_BYTES=8432375
GOPANEL_URL="https://cyberbeest.com/gopanel/gopanel-${GOPANEL_SHA256:0:12}.tar.gz"

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="${GOPANEL_INSTALL_HOME:-$(getent passwd "$TARGET_USER" | cut -d: -f6)}" # the override is for testing only
TARGET_UID="$(id -u "$TARGET_USER")"
LIBDIR="$TARGET_HOME/.local/lib/gopanel"
BINDIR="$TARGET_HOME/.local/bin"
CONF_DIR="$TARGET_HOME/.config/cyberbeest"
SRC="$DIR/experimental/gopanel"

if [ "$GOPANEL_SHA256" = "$(printf '0%.0s' $(seq 64))" ]; then
	echo "No release is pinned in this script yet (run experimental/gopanel/release.sh --publish) -- nothing to install." >&2
	exit 1
fi

echo "--- Runtime packages (pactl for the volume icon, a font for the text) ---"
need=()
for p in pulseaudio-utils fonts-dejavu-core; do
	dpkg -s "$p" >/dev/null 2>&1 || need+=("$p")
done
if [ "${#need[@]}" -gt 0 ]; then
	apt-get -o DPkg::Lock::Timeout=60 update -qq
	apt-get -o DPkg::Lock::Timeout=60 install -y --no-install-recommends "${need[@]}"
fi

echo "--- Panel files (version $GOPANEL_VERSION) ---"
if [ "$(cat "$LIBDIR/.sha256" 2>/dev/null)" = "$GOPANEL_SHA256" ] && [ -x "$LIBDIR/gopanel" ]; then
	echo "already installed, nothing to download"
else
	WORK="$(mktemp -d /var/tmp/gopanel-install.XXXXXX)"
	trap 'rm -rf "$WORK"' EXIT
	echo "Downloading $GOPANEL_URL"
	curl -fsSL --retry 3 --connect-timeout 20 "$GOPANEL_URL" -o "$WORK/gopanel.tar.gz"
	ACTUAL_BYTES="$(stat -c %s "$WORK/gopanel.tar.gz")"
	ACTUAL_SHA256="$(sha256sum "$WORK/gopanel.tar.gz" | cut -d' ' -f1)"
	if [ "$ACTUAL_SHA256" != "$GOPANEL_SHA256" ]; then
		echo "Checksum mismatch: expected $GOPANEL_SHA256, got $ACTUAL_SHA256 ($ACTUAL_BYTES bytes) -- discarded, panel not installed." >&2
		exit 1
	fi
	tar -xzf "$WORK/gopanel.tar.gz" -C "$WORK" --no-same-owner
	[ -x "$WORK/gopanel/gopanel" ] || { echo "tarball has no gopanel binary" >&2; exit 1; }
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/lib"
	rm -rf "$LIBDIR.new"
	mv "$WORK/gopanel" "$LIBDIR.new"
	printf '%s' "$GOPANEL_SHA256" > "$LIBDIR.new/.sha256"
	chown -R "$TARGET_USER:$TARGET_USER" "$LIBDIR.new"
	# rename over the old tree: a running panel keeps its open binary and the helpers' paths
	# resolve to the new files at their next (re)start
	rm -rf "$LIBDIR.old"
	[ -d "$LIBDIR" ] && mv "$LIBDIR" "$LIBDIR.old"
	mv "$LIBDIR.new" "$LIBDIR"
	rm -rf "$LIBDIR.old"
	echo "installed to $LIBDIR"
fi

echo "--- Launchers and switcher ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$BINDIR" "$CONF_DIR" "$TARGET_HOME/.config/autostart"
ln -sfn "$LIBDIR/gopanel" "$BINDIR/gopanel"
chown -h "$TARGET_USER:$TARGET_USER" "$BINDIR/gopanel"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$SRC/cyberbeest-panel-choice.sh" "$BINDIR/cyberbeest-panel-choice.sh"
install -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$SRC/cyberbeest-whisker-key.sh" "$BINDIR/cyberbeest-whisker-key.sh"
cat > "$TARGET_HOME/.config/autostart/cyberbeest-panel-choice.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Cyberbeest panel choice
Comment=Start the panel chosen in Cyberbeest Settings
Exec=$BINDIR/cyberbeest-panel-choice.sh login
Terminal=false
X-GNOME-Autostart-enabled=true
EOF
chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/autostart/cyberbeest-panel-choice.desktop"

echo "--- Default panel ---"
if [ -e "$CONF_DIR/panel.conf" ]; then
	echo "keeping the existing choice: $(tr '\n' ' ' < "$CONF_DIR/panel.conf")"
else
	echo "PANEL=gopanel" > "$CONF_DIR/panel.conf"
	chown "$TARGET_USER:$TARGET_USER" "$CONF_DIR/panel.conf"
	echo "no choice yet: gopanel it is"
fi

# Switching: a panel that is already running restarts into the new binary (exec: same pid,
# helpers keep running and reconnect). Otherwise, if the saved choice is gopanel and the XFCE
# panel is what the user is looking at, switch right now rather than leaving "after the next
# login" for them to puzzle over: cyberbeest-panel-choice.sh starts gopanel, waits until it has
# its window up, and only then stops the XFCE panel. Session environment comes from
# xfce4-session, as lib/xfce-panel-reload.sh does.
run_as_user() {
	local pid env_args=() line
	pid="$(pgrep -u "$TARGET_USER" -x xfce4-session | head -1)" || true
	if [ -n "$pid" ]; then
		while IFS= read -r -d '' line; do
			case "$line" in
				DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|XDG_*=*|DESKTOP_SESSION=*) env_args+=("$line") ;;
			esac
		done < "/proc/$pid/environ"
	fi
	env_args+=("XDG_RUNTIME_DIR=/run/user/$TARGET_UID")
	sudo -u "$TARGET_USER" env "${env_args[@]}" "$@"
}

if pgrep -u "$TARGET_USER" -x gopanel >/dev/null; then
	echo "--- Restarting the running panel into the new version ---"
	run_as_user "$LIBDIR/gopanel" restart || echo "restart failed (it will pick up the new version at next login)" >&2
elif pgrep -u "$TARGET_USER" -x xfce4-panel >/dev/null && [ "$(sed -n 's/^PANEL=//p' "$CONF_DIR/panel.conf")" = gopanel ]; then
	echo "--- Switching the running session from the XFCE panel to the Cyberbeest panel ---"
	run_as_user "$BINDIR/cyberbeest-panel-choice.sh" login || echo "switch failed; the XFCE panel stays" >&2
fi

echo "=== done ==="
