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
#    via a generated gettext catalog, built at install time from whatever
#    thunar.mo ships with the installed Thunar version (rather than shipping
#    a prebuilt .mo that could drift out of sync with msgids across Thunar
#    versions):
#     - en_US has no thunar.mo of its own (English is the untranslated
#       fallback), so it can't be derived by patching an existing one --
#       building it from en_GB's catalog (as a first cut of this script did)
#       silently inherits *all* of en_GB's regionalisms, not just Thunar's
#       name. One of those turned out to be a keeper: en_GB renames "Trash"
#       -> "Wastebasket" everywhere, consistently (sidebar, dialogs, desktop
#       icon) -- which reads as a deliberate, charming choice once you
#       notice it, so this keeps that rename on purpose. Everything *else*
#       en_GB differs on is unrelated noise, so: build a true identity-
#       English catalog (every msgstr set equal to its msgid) from en_GB's
#       msgid list, except entries whose msgid mentions "trash"/"Trash" --
#       those keep en_GB's actual (Wastebasket) translation verbatim. Then
#       rename the Thunar brand on top of that.
#       xfdesktop (draws the desktop icons, separate translation domain from
#       Thunar) gets the same identity+keep-Wastebasket treatment, with no
#       brand rename step, so the desktop's own Trash icon matches Thunar's
#       sidebar instead of the two disagreeing.
#     - de's thunar.mo is a real, direct German translation (not a regional
#       variant of another translation), so it's patched in place: only the
#       whole-word "Thunar" -> "Dateien" swap, msgids untouched. (German
#       doesn't have a Wastebasket-style pun to preserve -- "Papierkorb" is
#       already what it is.)
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
Name=Wastebasket
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

# Rewrites the .po at $1 in place so every msgstr equals its own msgid (true
# identity English), instead of whatever translation the source .mo actually
# held -- used so the en_US catalog doesn't inherit en_GB's regionalisms
# wholesale. Entries whose msgid matches the extended regex $2 are left
# completely untouched (kept exactly as en_GB translated them) -- this is
# how the deliberate "Trash" -> "Wastebasket" rename survives while
# everything else reverts to plain English. Preserves msgctxt (disambiguates
# otherwise-identical msgids like two "_Cancel" entries), msgid_plural/
# msgstr[n] pairs, and leaves the header entry (msgid "") alone since its
# msgstr carries charset/plural-forms metadata, not translatable text.
identitize_po() {
	python3 - "$1" "$2" <<'PYEOF'
import re, sys
path, keep_regex = sys.argv[1], sys.argv[2]
keep_re = re.compile(keep_regex) if keep_regex else None
with open(path, encoding="utf-8") as f:
    content = f.read()
entries = re.split(r'\n\n+', content.strip('\n'))
out_entries = []
for idx, entry in enumerate(entries):
    lines = entry.split('\n')
    comment_lines = [l for l in lines if l.lstrip().startswith('#')]
    msgctxt_lines, msgid_lines, msgid_plural_lines = [], [], []
    mode = None
    for l in lines:
        s = l.lstrip()
        if s.startswith('#'):
            continue
        if s.startswith('msgctxt'):
            mode = 'ctxt'; msgctxt_lines.append(l)
        elif s.startswith('msgid_plural'):
            mode = 'plural'; msgid_plural_lines.append(l)
        elif s.startswith('msgid'):
            mode = 'id'; msgid_lines.append(l)
        elif s.startswith('msgstr'):
            mode = 'str'
        elif s.startswith('"'):
            if mode == 'ctxt':
                msgctxt_lines.append(l)
            elif mode == 'id':
                msgid_lines.append(l)
            elif mode == 'plural':
                msgid_plural_lines.append(l)
    if not msgid_lines:
        out_entries.append(entry)
        continue
    is_header = (idx == 0) and msgid_lines[0].strip() == 'msgid ""'
    if is_header:
        out_entries.append(entry)
        continue
    msgid_text = ' '.join(msgid_lines + msgid_plural_lines)
    if keep_re and keep_re.search(msgid_text):
        out_entries.append(entry)
        continue
    rebuilt = list(comment_lines) + msgctxt_lines + msgid_lines
    if msgid_plural_lines:
        rebuilt += msgid_plural_lines
        m = re.match(r'\s*msgid\s+(".*")\s*$', msgid_lines[0])
        rebuilt.append('msgstr[0] ' + (m.group(1) if m else '""'))
        m2 = re.match(r'\s*msgid_plural\s+(".*")\s*$', msgid_plural_lines[0])
        rebuilt.append('msgstr[1] ' + (m2.group(1) if m2 else '""'))
    else:
        for l in msgid_lines:
            m = re.match(r'(\s*)msgid(\s+)(".*")\s*$', l)
            rebuilt.append(f'{m.group(1)}msgstr{m.group(2)}{m.group(3)}' if m else l)
    out_entries.append('\n'.join(rebuilt))
with open(path, "w", encoding="utf-8") as f:
    f.write('\n\n'.join(out_entries) + '\n')
PYEOF
}

# Renames whole-word "Thunar" -> $2 in the msgstr (translated) lines only of
# the .mo at $1, writing the result to $3. Leaves msgids (lookup keys)
# untouched so existing translated strings still resolve correctly. If $4
# ("identity") is "1", the catalog is first rewritten to identity English
# (see identitize_po above), keeping en_GB's own translation verbatim for
# any entry whose msgid matches $5, before the brand rename is applied on
# top of that.
rename_catalog() {
	local src_mo="$1" brand="$2" out_mo="$3" identity="${4:-0}" keep_regex="${5:-}" tmp
	tmp="$(mktemp -d)"
	msgunfmt "$src_mo" -o "$tmp/catalog.po"
	if [ "$identity" = "1" ]; then
		identitize_po "$tmp/catalog.po" "$keep_regex"
	fi
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
	local base_mo="$1" brand="$2" dest="$3" identity="${4:-0}" keep_regex="${5:-}"
	[ -f "$base_mo" ] || { echo "skipping $dest: $base_mo not found"; return 0; }
	mkdir -p "$(dirname "$dest")"
	if [ -f "$dest" ] && [ ! -f "$dest.pre-cyberbeest" ]; then
		cp -a "$dest" "$dest.pre-cyberbeest"
		echo "backed up existing $dest"
	fi
	local tmp_out
	tmp_out="$(mktemp)"
	rename_catalog "$base_mo" "$brand" "$tmp_out" "$identity" "$keep_regex"
	install -m 644 "$tmp_out" "$dest"
	rm -f "$tmp_out"
	echo "installed catalog to $dest"
}

echo "--- Installing renamed translation catalogs ---"
# en_US has no thunar.mo/xfdesktop.mo of its own (English is the
# untranslated fallback), so derive both from en_GB as identity-English,
# keeping en_GB's "Trash" -> "Wastebasket" rename on purpose (see header
# comment) and renaming the Thunar brand on top for thunar.mo.
install_catalog /usr/share/locale/en_GB/LC_MESSAGES/thunar.mo Files \
	/usr/share/locale/en_US/LC_MESSAGES/thunar.mo 1 '[Tt]rash'
install_catalog /usr/share/locale/en_GB/LC_MESSAGES/xfdesktop.mo "" \
	/usr/share/locale/en_US/LC_MESSAGES/xfdesktop.mo 1 '[Tt]rash'
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

# Kills process $2 (exact name) for user $1, waits up to 5s for it to
# actually exit (not just for pkill to return -- the old process can hang
# onto X resources like desktop/root-window management for a moment after
# being signalled), then runs $3 to relaunch it and waits up to 5s for the
# new instance to show up in the process table. Without the exit-wait, a
# relaunch can race the old instance's X cleanup and start "successfully"
# (visible in `pgrep`) without actually taking over -- e.g. xfdesktop
# leaving the desktop blank (no icons) until manually kicked again, which
# is what happened restarting it live while developing this script.
restart_and_confirm() {
	local user="$1" proc="$2" relaunch_cmd="$3" i
	pkill -u "$user" -x "$proc" || true
	for i in $(seq 1 10); do
		pgrep -u "$user" -x "$proc" >/dev/null 2>&1 || break
		sleep 0.5
	done
	su - "$user" -c "$relaunch_cmd" || true
	for i in $(seq 1 10); do
		pgrep -u "$user" -x "$proc" >/dev/null 2>&1 && break
		sleep 0.5
	done
	if pgrep -u "$user" -x "$proc" >/dev/null 2>&1; then
		echo "$proc restarted"
	else
		echo "WARNING: $proc did not come back up after restart"
	fi
}

echo "--- Refreshing a live session, if one is running ---"
PANEL_PID="$(pgrep -u "$TARGET_USER" -x xfce4-panel | head -1)" || true
if [ -n "$PANEL_PID" ]; then
	DBUS_ADDR="$(cat "/proc/$PANEL_PID/environ" 2>/dev/null | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')" || true
	DBUS_ADDR="${DBUS_ADDR:-unix:path=/run/user/$(id -u "$TARGET_USER")/bus}"

	# Both relaunches need DBUS_SESSION_BUS_ADDRESS, not just DISPLAY --
	# without it each lands on the wrong (or no) session bus, and xfdesktop
	# in particular then can't see later xfconf changes at all (e.g. picking
	# a wallpaper in Desktop Settings silently does nothing until next
	# login/reboot spawns a properly session-launched xfdesktop instead).

	# Thunar's daemon process name is capitalized ("Thunar"), not "thunar".
	# --daemon: just re-register the file-manager service so the desktop/menu
	# pick up the renamed identity -- without it, relaunching with no running
	# instance to hand off to pops open a visible browser window at the
	# default folder instead of starting quietly in the background.
	restart_and_confirm "$TARGET_USER" Thunar \
		"DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' nohup thunar --daemon >/dev/null 2>&1 & disown"

	# xfdesktop draws the desktop icons (including the Trash/Wastebasket
	# one) -- restart it so the new catalog picks up immediately instead of
	# waiting for next login.
	restart_and_confirm "$TARGET_USER" xfdesktop \
		"DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' nohup xfdesktop >/dev/null 2>&1 & disown"

	su - "$TARGET_USER" -c "DISPLAY='${DISPLAY:-:0}' DBUS_SESSION_BUS_ADDRESS='$DBUS_ADDR' xfce4-panel -r" || true
fi

echo "=== $(date) : done ==="
