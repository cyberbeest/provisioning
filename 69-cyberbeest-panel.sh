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
# No binary is shipped: the panel is built here, on the machine, from the source in
# experimental/gopanel (the Go modules it uses are fetched at build time and verified against the hashes pinned in go.sum). The Go
# compiler (golang-1.26-go from trixie-backports, ~50 MB download) is installed for the build and
# removed again right afterwards -- unless it was already installed (a Go developer), in which
# case it is never touched. The build is skipped when the source is unchanged since the last
# build, and a failed build keeps the panel that is installed now.
#
# Depends on: 12-xfce-panel-layout.sh (the config gopanel mirrors), 46-cyberbeest-keyboard-
# shortcuts.sh (Super key -> cyberbeest-whisker-key.sh), 60-xfce-panel-watchdog.sh (honours the
# "XFCE panel stopped on purpose" marker). Needs network for the compiler; if the build fails, the
# XFCE panel simply stays the panel.
# Idempotent: safe to re-run. A running gopanel is restarted into a new version (`gopanel
# restart`, helpers keep running); that is an update, not a switch.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/69-cyberbeest-panel.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : installing the Cyberbeest panel ==="

GOLANG_PKG=golang-1.26-go # backports; go.mod requires Go 1.26 (Debian trixie main has 1.24)
GO_BIN=/usr/lib/go-1.26/bin/go

TARGET_USER="${SUDO_USER:?SUDO_USER not set -- run this via sudo, not as a raw root shell}"
TARGET_HOME="${GOPANEL_INSTALL_HOME:-$(getent passwd "$TARGET_USER" | cut -d: -f6)}" # the override is for testing only
TARGET_UID="$(id -u "$TARGET_USER")"
LIBDIR="$TARGET_HOME/.local/lib/gopanel"
BINDIR="$TARGET_HOME/.local/bin"
CONF_DIR="$TARGET_HOME/.config/cyberbeest"
SRC="$DIR/experimental/gopanel"
OLD_VERSION="$(cat "$LIBDIR/VERSION" 2>/dev/null || true)" # what is installed now, before this run replaces it

echo "--- Runtime packages (pactl for the volume icon, a font for the text) ---"
need=()
for p in pulseaudio-utils fonts-dejavu-core; do
	dpkg -s "$p" >/dev/null 2>&1 || need+=("$p")
done
if [ "${#need[@]}" -gt 0 ]; then
	apt-get -o DPkg::Lock::Timeout=60 update -qq
	apt-get -o DPkg::Lock::Timeout=60 install -y --no-install-recommends "${need[@]}"
fi

echo "--- Panel files (built from source) ---"
# hash of everything the build depends on (sources, go.mod/sum), not of any binary
SRC_HASH="$(cd "$SRC" && find . -type f \( -name '*.go' -o -name go.mod -o -name go.sum \) -print0 \
	| LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
if [ "$(cat "$LIBDIR/.srchash" 2>/dev/null)" = "$SRC_HASH" ] && [ -x "$LIBDIR/gopanel" ]; then
	echo "already built from this source, nothing to do"
else
	WORK="$(mktemp -d /var/tmp/gopanel-build.XXXXXX)"
	WE_INSTALLED_GO=0
	cleanup() {
		rm -rf "$WORK"
		# only remove the compiler if this run installed it; autoremove keeps it when something
		# the user installed (e.g. golang-go) depends on it
		if [ "$WE_INSTALLED_GO" = 1 ]; then
			echo "Removing the Go compiler again"
			apt-get -o DPkg::Lock::Timeout=60 purge -y --auto-remove "$GOLANG_PKG" golang-1.26-src >/dev/null 2>&1 \
				|| echo "could not remove $GOLANG_PKG (harmless)" >&2
		fi
	}
	trap cleanup EXIT
	if ! dpkg -s "$GOLANG_PKG" >/dev/null 2>&1; then
		echo "Installing the Go compiler for the build"
		apt-get -o DPkg::Lock::Timeout=60 update -qq
		apt-get -o DPkg::Lock::Timeout=60 install -y --no-install-recommends -t trixie-backports "$GOLANG_PKG"
		apt-mark auto "$GOLANG_PKG" golang-1.26-src >/dev/null
		WE_INSTALLED_GO=1
	fi
	cp -a "$SRC" "$WORK/src"
	mkdir -p "$WORK/out/helpers"
	build_env=(HOME="$WORK/home" GOCACHE="$WORK/cache" GOPATH="$WORK/gopath" GOFLAGS=-mod=readonly GOTOOLCHAIN=local CGO_ENABLED=0 PATH="/usr/lib/go-1.26/bin:$PATH")
	echo "Building (this takes a few minutes on a slow machine)"
	if ! ( cd "$WORK/src" && env "${build_env[@]}" "$GO_BIN" build -trimpath -ldflags="-s -w" -o "$WORK/out/gopanel" . \
		&& for d in helpers/*/; do
			n="$(basename "$d")"
			env "${build_env[@]}" "$GO_BIN" build -trimpath -ldflags="-s -w" -o "$WORK/out/helpers/$n/$n" "./helpers/$n"
		done ); then
		if [ -x "$LIBDIR/gopanel" ]; then
			echo "Build failed -- keeping the panel that is installed now." >&2
			exit 0
		fi
		echo "Build failed -- panel not installed, the XFCE panel stays the panel." >&2
		exit 1
	fi
	GOPANEL_VERSION="$("$WORK/out/gopanel" version | awk '{print $2}')"
	echo "$GOPANEL_VERSION" > "$WORK/out/VERSION"
	cp "$DIR/LICENSE" "$WORK/out/LICENSE"
	# the binaries embed third-party Go modules (BSD/MIT/Apache): ship their licence texts too
	{
		echo "gopanel is part of Cyberbeest (see LICENSE). It is built with these Go modules:"
		find "$WORK/gopath/pkg/mod" -path "$WORK/gopath/pkg/mod/cache" -prune -o -type f \( -name 'LICENSE*' -o -name 'COPYING*' \) -print | LC_ALL=C sort | while read -r f; do
			printf '\n================ %s ================\n' "${f#"$WORK"/gopath/pkg/mod/}"
			cat "$f"
		done
	} > "$WORK/out/THIRD_PARTY_LICENSES.txt"
	chmod 755 "$WORK/out" "$WORK/out/helpers" "$WORK/out/helpers"/*
	printf '%s' "$SRC_HASH" > "$WORK/out/.srchash"
	install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/lib"
	rm -rf "$LIBDIR.new"
	mv "$WORK/out" "$LIBDIR.new"
	chown -R "$TARGET_USER:$TARGET_USER" "$LIBDIR.new"
	# rename over the old tree: a running panel keeps its open binary and the helpers' paths
	# resolve to the new files at their next (re)start
	rm -rf "$LIBDIR.old"
	[ -d "$LIBDIR" ] && mv "$LIBDIR" "$LIBDIR.old"
	mv "$LIBDIR.new" "$LIBDIR"
	rm -rf "$LIBDIR.old"
	echo "built $GOPANEL_VERSION and installed to $LIBDIR"
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
