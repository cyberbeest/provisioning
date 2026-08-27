#!/bin/bash
# Recategorizes a handful of apps that ship their own .desktop file straight
# from their Debian/upstream package -- unlike the messengers/wallets
# (38-, 39-, 40-) or Thunar (33-), nothing in this repo generates these, so
# there's no heredoc to edit at the source. Instead this makes a local
# ~/.local/share/applications override of each pristine /usr/share file
# (same technique as 45-hide-redundant-terminals.sh), always re-copied from
# the system original so re-running after a package upgrade doesn't compound
# old edits on top of new ones.
#
# What moves where, and why:
#   - Tor Browser + its launcher settings -> Darknet (was Internet)
#   - Kleopatra -> Mail (was Accessories via Utility; not a cryptocurrency
#     tool, so Wallets was wrong, and it's the one app that actually
#     motivates having a Mail category at all)
#   - GnuPG Log Viewer (bundled with Kleopatra) -> hidden. A raw GnuPG
#     protocol log isn't something a non-technical user needs surfaced.
#   - Software (GNOME Software) -> Settings (was System, which this drops
#     entirely -- see below)
#   - Print Settings, Sensor Viewer, Task Manager -> keep their existing
#     Settings/Utility membership, just drop the redundant System tag
#   - Xfce Terminal -> Accessories (drop System, add Utility) -- xterm/uxterm
#     are already hidden by 45-, so this is the one terminal left standing
#   - LibreOffice Draw, Ristretto, XSane -> Multimedia (drop Graphics, which
#     this drops entirely -- folds a mostly-empty category into Multimedia
#     rather than keeping a separate one for three apps)
# Once every app tagged System/Graphics is gone, those two categories have
# nothing left in them and Whisker just doesn't show them -- no menu-file
# change needed for that half, see 48-whisker-menu-categories.sh for the
# submenus this depends on (Darknet, Mail).
#
# Depends on: 48-whisker-menu-categories.sh (Darknet/Mail need to exist as
# actual Whisker submenus for tagging apps with those categories to do
# anything visible; harmless either way if run out of order).
# Idempotent: safe to re-run (always re-copies from the pristine
# /usr/share/applications original first).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/49-whisker-category-cleanup.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : cleaning up Whisker menu categories ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
APPDIR="$TARGET_HOME/.local/share/applications"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$APPDIR"

# Copies $1 (a desktop-file basename in /usr/share/applications) into the
# user's local override dir, if the source exists. Skips quietly if the
# package that owns it isn't installed on this machine.
override() {
	local base="$1" src="/usr/share/applications/$1"
	if [ ! -f "$src" ]; then
		echo "skipping $base: $src not found (package not installed)"
		return 1
	fi
	cp "$src" "$APPDIR/$base"
	return 0
}

echo "--- Darknet: Tor Browser ---"
for f in torbrowser.desktop torbrowser-settings.desktop; do
	override "$f" || continue
	sed -i 's/^Categories=Network;WebBrowser;$/Categories=Darknet;/' "$APPDIR/$f"
done

echo "--- Mail: Kleopatra ---"
if override org.kde.kleopatra.desktop; then
	sed -i 's/^Categories=Qt;KDE;Utility;$/Categories=Mail;/' "$APPDIR/org.kde.kleopatra.desktop"
fi

echo "--- Hiding GnuPG Log Viewer (not something a typical user needs) ---"
if override org.kde.kwatchgnupg.desktop; then
	if grep -q '^NoDisplay=' "$APPDIR/org.kde.kwatchgnupg.desktop"; then
		sed -i 's/^NoDisplay=.*/NoDisplay=true/' "$APPDIR/org.kde.kwatchgnupg.desktop"
	else
		echo 'NoDisplay=true' >> "$APPDIR/org.kde.kwatchgnupg.desktop"
	fi
fi

echo "--- Settings: Software, Print Settings, Sensor Viewer, Task Manager ---"
if override org.gnome.Software.desktop; then
	sed -i 's/^Categories=GNOME;GTK;System;PackageManager;$/Categories=GNOME;GTK;Settings;PackageManager;/' "$APPDIR/org.gnome.Software.desktop"
fi
if override system-config-printer.desktop; then
	sed -i 's/^Categories=GNOME;GTK;Settings;HardwareSettings;X-GNOME-Settings-Panel;X-Unity-Settings-Panel;System;Printing;$/Categories=GNOME;GTK;Settings;HardwareSettings;X-GNOME-Settings-Panel;X-Unity-Settings-Panel;Printing;/' "$APPDIR/system-config-printer.desktop"
fi
if override xfce4-sensors.desktop; then
	sed -i 's/^Categories=X-XFCE;Utility;System;Monitor;$/Categories=X-XFCE;Utility;Monitor;/' "$APPDIR/xfce4-sensors.desktop"
fi
if override xfce4-taskmanager.desktop; then
	sed -i 's/^Categories=System;Utility;$/Categories=Utility;/' "$APPDIR/xfce4-taskmanager.desktop"
fi

echo "--- Accessories: Xfce Terminal (the one terminal left after 45-) ---"
if override xfce4-terminal.desktop; then
	sed -i 's/^Categories=GTK;System;TerminalEmulator;$/Categories=GTK;Utility;TerminalEmulator;/' "$APPDIR/xfce4-terminal.desktop"
fi

echo "--- Multimedia: LibreOffice Draw, Ristretto, XSane (folding in Graphics) ---"
if override libreoffice-draw.desktop; then
	sed -i 's/^Categories=Office;FlowChart;Graphics;2DGraphics;VectorGraphics;$/Categories=Office;FlowChart;AudioVideo;2DGraphics;VectorGraphics;/' "$APPDIR/libreoffice-draw.desktop"
fi
if override org.xfce.ristretto.desktop; then
	sed -i 's/^Categories=GTK;Graphics;Viewer;$/Categories=GTK;AudioVideo;Viewer;/' "$APPDIR/org.xfce.ristretto.desktop"
fi
if override xsane.desktop; then
	sed -i 's/^Categories=Application;Graphics;GTK;RasterGraphics;Scanning;OCR;2DGraphics;$/Categories=Application;AudioVideo;GTK;RasterGraphics;Scanning;OCR;2DGraphics;/' "$APPDIR/xsane.desktop"
fi
# ImageMagick's "display" tool has no menu entry on a stock install (checked
# on both the dev machine and a provisioned one) -- included for completeness
# in case a future imagemagick version adds one back.
if override display-im7.q16.desktop; then
	sed -i 's/^Categories=Graphics;$/Categories=AudioVideo;/' "$APPDIR/display-im7.q16.desktop"
fi

chown -R "$TARGET_USER:$TARGET_USER" "$APPDIR"

echo "--- Refreshing a live panel, if one is running ---"
command -v update-desktop-database >/dev/null 2>&1 && \
	sudo -u "$TARGET_USER" update-desktop-database "$APPDIR" 2>/dev/null || true
PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
if [ -n "$PANEL_PID" ]; then
	DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"
	rm -f "$TARGET_HOME/.cache/menus"/*.menu 2>/dev/null || true
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
fi

echo "=== $(date) : done ==="
