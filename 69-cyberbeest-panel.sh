#!/bin/bash
# Installs the Cyberbeest panel (gopanel, experimental/gopanel): the pure-Go X11 panel that
# replaces the XFCE panel -- same layout and plugins (it reads the xfce4-panel config), but no
# flicker at startup, a faster menu and far lower memory use.
#
# Installing does not switch anything: the XFCE panel stays the panel until the user picks the
# Cyberbeest panel in Cyberbeest Settings > Panel (Apply/OK). That choice is kept in
# ~/.config/cyberbeest/panel.conf, which this script never writes or overrides; at every login
# cyberbeest-panel-choice.sh (autostart) starts the chosen panel (XFCE when there is no choice).
# The XFCE panel stays installed and is what xfce-panel-watchdog brings back if gopanel dies.
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
# restart`, helpers keep running); that is an update, not a switch.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/69-cyberbeest-panel.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest panel ==="

GOPANEL_VERSION="0.21.19"
GOPANEL_SHA256="85486775d51a3e2f3d07eb236c5b2973fb684977d91e717c745870b029e6574f"
GOPANEL_BYTES=8449428
GOPANEL_URL="https://cyberbeest.com/gopanel/gopanel-${GOPANEL_SHA256:0:12}.tar.gz"

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="${GOPANEL_INSTALL_HOME:-$(getent passwd "$TARGET_USER" | cut -d: -f6)}" # the override is for testing only
TARGET_UID="$(id -u "$TARGET_USER")"
LIBDIR="$TARGET_HOME/.local/lib/gopanel"
BINDIR="$TARGET_HOME/.local/bin"
CONF_DIR="$TARGET_HOME/.config/cyberbeest"
SRC="$DIR/experimental/gopanel"
OLD_VERSION="$(cat "$LIBDIR/VERSION" 2>/dev/null || true)" # what is installed now, before this run replaces it

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

# A panel that is already running moves to the new binary. Switching panels is the user's choice
# in Settings, never done here.
#   - 0.21.19 and later: `gopanel restart` (exec: same pid, helpers keep running).
#   - older ones cannot do that after their files were replaced (the exec found no binary and the
#     panel exited, then the XFCE watchdog brought the XFCE panel back: tower, 2026-10-13), so
#     they are quit and the new binary is started in its own unit (like cyberbeest-panel-choice.sh
#     does), well inside the watchdog's 15 s grace.
GOPID="$(pgrep -u "$TARGET_USER" -x gopanel | head -1)" || true
if [ -n "$GOPID" ]; then
	echo "--- Moving the running panel to the new version ---"
	if [ -n "$OLD_VERSION" ] && [ "$(printf '%s\n0.21.19\n' "$OLD_VERSION" | sort -V | head -1)" = "0.21.19" ]; then
		sudo -u "$TARGET_USER" env XDG_RUNTIME_DIR="/run/user/$TARGET_UID" DISPLAY="${DISPLAY:-:0}" \
			"$LIBDIR/gopanel" restart || echo "restart failed" >&2
	else
		env_args=("XDG_RUNTIME_DIR=/run/user/$TARGET_UID" "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$TARGET_UID/bus")
		while IFS= read -r -d '' line; do
			case "$line" in
				DISPLAY=*|XAUTHORITY=*|XDG_CURRENT_DESKTOP=*|XDG_SESSION_TYPE=*|DBUS_SESSION_BUS_ADDRESS=*) env_args+=("$line") ;;
			esac
		done < "/proc/$GOPID/environ"
		sudo -u "$TARGET_USER" env "${env_args[@]}" "$LIBDIR/gopanel" quit || true
		for _ in $(seq 40); do pgrep -u "$TARGET_USER" -x gopanel >/dev/null || break; sleep 0.25; done
		sudo -u "$TARGET_USER" env "${env_args[@]}" systemd-run --user --collect --quiet \
			--unit="panel-choice-$(date +%s%N)" -p KillMode=process \
			--setenv=DISPLAY --setenv=XAUTHORITY --setenv=XDG_CURRENT_DESKTOP --setenv=XDG_SESSION_TYPE \
			-- "$LIBDIR/gopanel" || echo "could not start the new panel; it starts at next login" >&2
	fi
fi

echo "=== done ==="
