#!/bin/bash
# Renames Thunar to the friendlier "Files" (German: "Dateien") throughout the
# user-visible UI, without patching or recompiling the Thunar binary itself:
#
#  - App menu / Whisker: local .desktop overrides in
#    ~/.local/share/applications/ rename thunar.desktop ("Files") and
#    thunar-settings.desktop ("Files Preferences"), and hide the separate
#    xfce4-file-manager.desktop redirector (`exo-open --launch FileManager`)
#    that otherwise shows up as a second, differently-named "File Manager"
#    entry -- it's kept functional (other apps' "open containing folder"
#    actions use it) but no longer listed.
#
#  - Window titles: the "<folder> - Thunar" suffix is not routed through
#    gettext, so a translation catalog can't rename it -- instead this sets
#    Thunar's own misc-window-title-style=1 (FOLDER_NAME_WITHOUT_THUNAR_SUFFIX)
#    so windows just show the folder name, no branding at all (same style as
#    GNOME Files / macOS Finder).
#
#  - Everything else Thunar-branded that *is* translatable (About dialog,
#    Preferences window title, tooltips, Bulk Rename dialog, etc.) is renamed
#    via a generated gettext catalog: this derives en_US and de overrides
#    from whatever en_GB/de thunar.mo ships with the installed Thunar
#    version (rather than shipping a prebuilt .mo that could drift out of
#    sync with msgids across Thunar versions), replacing whole-word "Thunar"
#    with "Files"/"Dateien" in the translated strings only (msgids, i.e. the
#    lookup keys, are left untouched).
#
# Idempotent: safe to re-run (backs up anything it overwrites the first
# time, with a .pre-cyberbeest / .bak-cyberbeest suffix, and skips the
# backup step on subsequent runs).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/33-rename-thunar-to-files.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date) : renaming Thunar to Files ==="

TARGET_USER="${SUDO_USER:-cyberbeest}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"

echo "--- Ensuring gettext tools are present ---"
command -v msgunfmt >/dev/null 2>&1 && command -v msgfmt >/dev/null 2>&1 || \
	apt-get -o DPkg::Lock::Timeout=60 install -y gettext-base

echo "--- Installing app-menu overrides to $TARGET_HOME/.local/share/applications ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.local/share/applications"

cat > "$TARGET_HOME/.local/share/applications/thunar.desktop" <<'EOF'
[Desktop Entry]
Name=Files
Name[de]=Dateien
GenericName=File Manager
GenericName[de]=Dateiverwaltung
Comment=Browse the filesystem with the file manager
Comment[de]=Das Dateisystem im Dateimanager anzeigen
Exec=thunar %U
Icon=org.xfce.thunar
Terminal=false
StartupNotify=true
Type=Application
Categories=System;Core;GTK;FileTools;FileManager;
MimeType=inode/directory;
Actions=open-home;open-computer;open-trash;

[Desktop Action open-home]
Name=Home
Name[de]=Persönlicher Ordner
Exec=thunar %U

[Desktop Action open-computer]
Name=Computer
Exec=thunar computer:///

[Desktop Action open-trash]
Name=Trash
Name[de]=Papierkorb
Exec=thunar trash:///
EOF

cat > "$TARGET_HOME/.local/share/applications/thunar-settings.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Name=Files Preferences
Name[de]=Dateien-Einstellungen
Comment=Configure the Files file manager
Comment[de]=Dateimanager Dateien einrichten
Keywords=thunar;files;settings;preferences;configure;thumbnails;file size;date format;shortcuts pane;tree view;tabs;
Exec=thunar-settings
Icon=org.xfce.thunar
Terminal=false
Type=Application
Categories=XFCE;GTK;Settings;DesktopSettings;X-XFCE-SettingsDialog;X-XFCE-PersonalSettings;
StartupNotify=true
EOF

# The generic "default file manager" redirector -- a distinct .desktop-id
# from thunar.desktop, so renaming thunar.desktop alone leaves this showing
# up as a second, stale-named "File Manager" entry in Whisker. Hide it
# (NoDisplay=true) rather than delete it: exo-open --launch FileManager is
# used by other apps' "open containing folder" actions.
if [ -e /usr/share/applications/xfce4-file-manager.desktop ]; then
	sed '/^Name\[/d; /^Comment\[/d; /^Keywords\[/d; /^Name=/d; /^Comment=/d; /^Keywords=/d' \
		/usr/share/applications/xfce4-file-manager.desktop \
		> "$TARGET_HOME/.local/share/applications/xfce4-file-manager.desktop"
	{
		echo "Name=File Manager"
		echo "Comment=Browse the file system"
		echo "NoDisplay=true"
	} >> "$TARGET_HOME/.local/share/applications/xfce4-file-manager.desktop"
fi

chown "$TARGET_USER:$TARGET_USER" \
	"$TARGET_HOME/.local/share/applications/thunar.desktop" \
	"$TARGET_HOME/.local/share/applications/thunar-settings.desktop"
[ -e "$TARGET_HOME/.local/share/applications/xfce4-file-manager.desktop" ] && \
	chown "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.local/share/applications/xfce4-file-manager.desktop"

command -v update-desktop-database >/dev/null 2>&1 && \
	su - "$TARGET_USER" -c "update-desktop-database '$TARGET_HOME/.local/share/applications' 2>/dev/null" || true

# Renames whole-word "Thunar" -> $2 in the msgstr (translated) lines only of
# the .mo at $1, writing the result to $3. Leaves msgids (lookup keys)
# untouched so existing translated strings still resolve correctly.
rename_catalog() {
	local src_mo="$1" brand="$2" out_mo="$3" tmp
	tmp="$(mktemp -d)"
	msgunfmt "$src_mo" -o "$tmp/catalog.po"
	python3 - "$tmp/catalog.po" "$brand" <<'PYEOF'
import re, sys
path, brand = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    lines = f.readlines()
out, in_msgstr = [], False
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith("msgid"):
        in_msgstr = False
    elif stripped.startswith("msgstr"):
        in_msgstr = True
    elif stripped.startswith("#") or stripped == "\n":
        in_msgstr = False
    if in_msgstr:
        line = re.sub(r"\bThunar\b", brand, line)
    out.append(line)
with open(path, "w", encoding="utf-8") as f:
    f.writelines(out)
PYEOF
	# Collapse the few phrases that become redundant/ungrammatical once
	# "Thunar" is replaced by a plain-language brand word (English: "Thunar
	# File Manager" -> just "Files File Manager" reads redundant; German
	# genitive "Thunars" isn't caught by the \b-bounded regex above since a
	# following "s" is a word character).
	if [ "$brand" = "Files" ]; then
		sed -i \
			-e 's/^msgstr "Files File Manager"$/msgstr "Files"/' \
			-e "s/^msgstr \"Edit Files's Preferences\"\$/msgstr \"Edit Files Preferences\"/" \
			"$tmp/catalog.po"
	elif [ "$brand" = "Dateien" ]; then
		sed -i \
			-e 's/^msgstr "Dateimanager Dateien"$/msgstr "Dateimanager"/' \
			-e 's/^msgstr "Dateien Einstellungen"$/msgstr "Dateien-Einstellungen"/' \
			-e 's/^msgstr "Thunars Einstellungen bearbeiten"$/msgstr "Dateien-Einstellungen bearbeiten"/' \
			"$tmp/catalog.po"
	fi
	msgfmt "$tmp/catalog.po" -o "$out_mo"
	rm -rf "$tmp"
}

install_catalog() {
	local base_mo="$1" brand="$2" dest="$3"
	[ -f "$base_mo" ] || { echo "skipping $dest: $base_mo not found"; return 0; }
	mkdir -p "$(dirname "$dest")"
	if [ -f "$dest" ] && [ ! -f "$dest.pre-cyberbeest" ]; then
		cp -a "$dest" "$dest.pre-cyberbeest"
		echo "backed up existing $dest"
	fi
	local tmp_out
	tmp_out="$(mktemp)"
	rename_catalog "$base_mo" "$brand" "$tmp_out"
	install -m 644 "$tmp_out" "$dest"
	rm -f "$tmp_out"
	echo "installed $brand-branded catalog to $dest"
}

echo "--- Installing renamed translation catalogs ---"
# en_US has no thunar.mo of its own (English is the untranslated fallback),
# so derive it from en_GB, which ships as a near-identity English catalog.
install_catalog /usr/share/locale/en_GB/LC_MESSAGES/thunar.mo Files \
	/usr/share/locale/en_US/LC_MESSAGES/thunar.mo
install_catalog /usr/share/locale/de/LC_MESSAGES/thunar.mo Dateien \
	/usr/share/locale/de/LC_MESSAGES/thunar.mo

echo "--- Setting Thunar's window-title style (drop the app-name suffix) ---"
install -d -o "$TARGET_USER" -g "$TARGET_USER" "$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml"
THUNAR_XML="$TARGET_HOME/.config/xfce4/xfconf/xfce-perchannel-xml/thunar.xml"
if [ ! -e "$THUNAR_XML" ]; then
	cat > "$THUNAR_XML" <<'EOF'
<?xml version="1.1" encoding="UTF-8"?>

<channel name="thunar" version="1.0">
  <property name="misc-window-title-style" type="int" value="1"/>
</channel>
EOF
elif ! grep -q 'name="misc-window-title-style"' "$THUNAR_XML"; then
	[ -e "$THUNAR_XML.pre-cyberbeest" ] || cp -a "$THUNAR_XML" "$THUNAR_XML.pre-cyberbeest"
	sed -i 's|</channel>|  <property name="misc-window-title-style" type="int" value="1"/>\n</channel>|' "$THUNAR_XML"
else
	sed -i 's|<property name="misc-window-title-style" type="int" value="[0-9]*"/>|<property name="misc-window-title-style" type="int" value="1"/>|' "$THUNAR_XML"
fi
chown -R "$TARGET_USER:$TARGET_USER" "$TARGET_HOME/.config/xfce4"

echo "--- Refreshing a live session, if one is running ---"
PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)"
if [ -n "$PANEL_PID" ]; then
	DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"

	# Thunar's daemon process name is capitalized ("Thunar"), not "thunar".
	pkill -u "$TARGET_USER" -x Thunar || true
	sleep 1
	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' nohup thunar >/dev/null 2>&1 & disown" || true

	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
fi

echo "=== $(date) : done ==="
