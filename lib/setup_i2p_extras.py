#!/usr/bin/env python3
"""Post-install setup for the I2P + qBittorrent package manager entry.

Runs unprivileged, as the user, after cyberbeest-pkg-helper.sh has already
apt-installed i2pd and qbittorrent (and, root-side, set up the on-demand
sudoers rule -- see do_setup_i2pd_toggle in cyberbeest-pkg-helper.sh).
Handles everything that doesn't need root: a dedicated Firefox profile for
eepsites (proxied through i2pd, Alpenglow theme so it's visually distinct
from normal browsing), its Whisker launcher, flipping qBittorrent's I2P
setting on, and the on-demand start/stop toggle (Whisker entry -> starts
i2pd + spawns a panel icon; clicking the icon opens a menu to stop i2pd,
open the I2P Firefox profile, or start qBittorrent; state persists across
logins via a state file).

Run with "remove" as the first argument to tear the user-owned half of
this back out (called when the package manager row is unchecked) --
stops i2pd/removes the panel icon if live, then deletes everything this
script wrote. It deliberately does NOT touch the Firefox profile/qBittorrent
config on removal, matching the rest of the package manager's behavior of
leaving user data (bookmarks, torrents, ...) in place when unchecking a box.

Idempotent: safe to re-run (e.g. if the package manager row is
unchecked/rechecked, or this is run again after a manual tweak).
"""

import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROFILE_DIR = os.path.join(HOME, ".mozilla", "firefox", "i2p-profile")
PROFILES_INI = os.path.join(HOME, ".mozilla", "firefox", "profiles.ini")
DESKTOP_FILE = os.path.join(HOME, ".local", "share", "applications", "firefox-i2p.desktop")
QBT_CONF = os.path.join(HOME, ".config", "qBittorrent", "qBittorrent.conf")
PAC_FILE = os.path.join(PROFILE_DIR, "i2p-proxy.pac")

BIN_DIR = os.path.join(HOME, ".local", "bin")
APPS_DIR = os.path.join(HOME, ".local", "share", "applications")
AUTOSTART_DIR = os.path.join(HOME, ".config", "autostart")
STATE_DIR = os.path.join(HOME, ".config", "cyberbeest")
STATE_FILE = os.path.join(STATE_DIR, "i2pd_state")
START_DESKTOP_FILE = os.path.join(APPS_DIR, "i2pd-start.desktop")
RESTORE_DESKTOP_FILE = os.path.join(AUTOSTART_DIR, "i2pd-restore-session.desktop")

USER_JS = """// I2P eepsite browsing profile — proxies *.i2p through i2pd's HTTP proxy via
// a PAC file (i2p-proxy.pac); everything else goes DIRECT, so this profile
// also works as a normal browser for clearnet sites.
user_pref("network.proxy.type", 2);
user_pref("network.proxy.autoconfig_url", "file://%s");
user_pref("extensions.activeThemeID", "firefox-alpenglow@mozilla.org");
""" % PAC_FILE

PAC_FILE_CONTENT = """// I2P eepsite browsing profile PAC: .i2p hosts are proxied through i2pd;
// everything else goes DIRECT, so this profile also works as a normal
// browser for clearnet sites instead of showing i2pd's confusing proxy
// error page for them.
function FindProxyForURL(url, host) {
    if (dnsDomainIs(host, ".i2p")) {
        return "PROXY 127.0.0.1:4444";
    }
    return "DIRECT";
}
"""

DESKTOP_ENTRY = """[Desktop Entry]
Name=Firefox (I2P)
Comment=Browse I2P eepsites via i2pd's HTTP proxy
Exec=firefox -no-remote -P i2p --class=I2PFirefox http://console.i2p
Terminal=false
Type=Application
Icon=network-vpn
Categories=Network;WebBrowser;
StartupWMClass=I2PFirefox
StartupNotify=true
"""

START_DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Start I2P (i2pd)
Comment=Starts the i2pd anonymous-network daemon and adds a panel icon to monitor/stop it
Exec=%s/i2pd-start.sh
Icon=network-vpn
Categories=Network;
Terminal=false
""" % BIN_DIR

RESTORE_DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=i2pd session restore
Comment=Restarts i2pd (and its panel icon) if it was running at the end of the last session; does nothing otherwise.
Exec=%s/i2pd-restore-session.sh
X-GNOME-Autostart-Phase=Application
X-GNOME-Autostart-Delay=5
NoDisplay=true
""" % BIN_DIR

I2PD_START_SH = """#!/bin/bash
# Starts i2pd and shows the panel icon. Callable from the Whisker menu
# entry, or by i2pd-restore-session.sh at login if last session had it
# running. i2pd.service is disabled from boot-autostart on purpose --
# this script (or the restore-session one) is the only thing that starts it.

set -uo pipefail

STATE_DIR="$HOME/.config/cyberbeest"
STATE_FILE="$STATE_DIR/i2pd_state"
mkdir -p "$STATE_DIR"

sudo -n systemctl start i2pd
"$HOME/.local/bin/i2pd-panel-icon.sh" add
echo "running" >"$STATE_FILE"

notify-send --urgency=low --app-name="i2pd" \\
    "i2pd started" "Panel icon added — click it to stop." 2>/dev/null || true
"""

I2PD_STOP_SH = """#!/bin/bash
# Stops i2pd and removes its panel icon (the "Stop i2pd" menu item, hence
# "and itself" per the design: stopping i2pd also removes the icon that
# controls it).

set -uo pipefail

STATE_DIR="$HOME/.config/cyberbeest"
STATE_FILE="$STATE_DIR/i2pd_state"
mkdir -p "$STATE_DIR"

sudo -n systemctl stop i2pd
echo "stopped" >"$STATE_FILE"
"$HOME/.local/bin/i2pd-panel-icon.sh" remove

notify-send --urgency=low --app-name="i2pd" \\
    "i2pd stopped" 2>/dev/null || true
"""

I2PD_PANEL_ICON_SH = """#!/bin/bash
# Adds/removes the i2pd genmon panel icon (plugin-27) from the live panel.
# Called by i2pd-start.sh/i2pd-stop.sh -- not meant to be run standalone.
#
# Usage: i2pd-panel-icon.sh add|remove
#
# NOTE: xfconf-query's -a flag is --force-array, NOT "append" -- the whole
# plugin-ids array must be replaced in a single call (repeated -t int -s id
# pairs after -n -a), never built up with a loop of separate -a calls, or
# every earlier value gets clobbered down to just the last one.

set -uo pipefail

PLUGIN_ID=27
ACTION="${1:-}"

panel_dbus_env() {
    local panel_pid
    panel_pid="$(pgrep -x xfce4-panel | head -n1)"
    [ -z "$panel_pid" ] && return 1
    grep -z '^DBUS_SESSION_BUS_ADDRESS=' "/proc/$panel_pid/environ" 2>/dev/null | tr -d '\\0'
}

reload_panel() {
    local env_line
    env_line="$(panel_dbus_env)"
    if [ -n "$env_line" ]; then
        env "$env_line" xfce4-panel -r >/dev/null 2>&1
    else
        xfce4-panel -r >/dev/null 2>&1
    fi
}

# xfconf-query prints a "Value is an array with N items:" header plus a
# blank line before an array's values (even without -v) -- filter to just
# the numeric plugin ids.
get_plugin_ids() {
    xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids | grep -E '^[0-9]+$'
}

set_plugin_ids() {
    # $@ = the full ordered list of plugin ids to write.
    local args=(-c xfce4-panel -p /panels/panel-1/plugin-ids -n -a)
    for id in "$@"; do
        args+=(-t int -s "$id")
    done
    xfconf-query "${args[@]}"
}

case "$ACTION" in
add)
    if xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" >/dev/null 2>&1; then
        exit 0 # already present
    fi
    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -n -t string -s genmon

    mkdir -p "$HOME/.config/xfce4/panel"
    cat >"$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc" <<EOF
Command=$HOME/.local/bin/i2pd-genmon.sh
UpdatePeriod=15000
UseLabel=0
Text=(genmon)
Font=Sans 10
EOF

    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    inserted=0
    for id in "${ids[@]}"; do
        new_ids+=("$id")
        if [ "$id" = "26" ]; then
            new_ids+=("$PLUGIN_ID")
            inserted=1
        fi
    done
    if [ "$inserted" -eq 0 ]; then
        new_ids+=("$PLUGIN_ID")
    fi

    set_plugin_ids "${new_ids[@]}"
    reload_panel
    ;;
remove)
    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    for id in "${ids[@]}"; do
        [ "$id" = "$PLUGIN_ID" ] && continue
        new_ids+=("$id")
    done

    set_plugin_ids "${new_ids[@]}"

    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -r -R >/dev/null 2>&1
    rm -f "$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc"

    reload_panel
    ;;
*)
    echo "Usage: $0 add|remove" >&2
    exit 1
    ;;
esac
"""

I2PD_GENMON_SH = """#!/bin/bash
# Panel item: shows whether i2pd is running, click opens a menu (stop
# i2pd / open I2P Firefox / start qBittorrent). Spawned by i2pd-start.sh,
# removed by i2pd-stop.sh -- not meant to sit in the panel while i2pd is
# disabled.

ICON_RUNNING=/usr/share/icons/gnome/24x24/status/network-transmit-receive.png
ICON_STOPPED=/usr/share/icons/gnome/24x24/status/network-offline.png

if systemctl is-active --quiet i2pd; then
    echo "<img>${ICON_RUNNING}</img>"
    echo "<tool>i2pd is running.&#10;Click for options.</tool>"
else
    echo "<img>${ICON_STOPPED}</img>"
    echo "<tool>i2pd is stopped.&#10;Click for options.</tool>"
fi
echo "<click>$HOME/.local/bin/i2pd-menu.py</click>"
"""

I2PD_MENU_PY = '''#!/usr/bin/env python3
"""Popup menu for the i2pd panel icon (genmon plugin-27).

Invoked on click instead of stopping i2pd directly. Offers starting the
I2P Firefox profile / qBittorrent alongside the stop action, since those
are the things you'd actually want once i2pd is up.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

HOME_BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")


def launch(*args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_i2pd(_item):
    launch(f"{HOME_BIN}/i2pd-stop.sh")
    Gtk.main_quit()


def start_firefox(_item):
    launch("firefox", "-no-remote", "-P", "i2p", "http://console.i2p")
    Gtk.main_quit()


def start_qbittorrent(_item):
    launch("qbittorrent")
    Gtk.main_quit()


def build_menu():
    menu = Gtk.Menu()

    firefox_item = Gtk.MenuItem(label="Open I2P Firefox")
    firefox_item.connect("activate", start_firefox)
    menu.append(firefox_item)

    qbt_item = Gtk.MenuItem(label="Start qBittorrent")
    qbt_item.connect("activate", start_qbittorrent)
    menu.append(qbt_item)

    menu.append(Gtk.SeparatorMenuItem())

    stop_item = Gtk.MenuItem(label="Stop i2pd")
    stop_item.connect("activate", stop_i2pd)
    menu.append(stop_item)

    menu.show_all()
    return menu


def main():
    menu = build_menu()
    menu.connect("deactivate", lambda _m: Gtk.main_quit())
    menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())
    Gtk.main()


if __name__ == "__main__":
    main()
'''

I2PD_RESTORE_SESSION_SH = """#!/bin/bash
# Run once per login (via autostart). i2pd.service is disabled from
# boot-autostart, so this restores whatever state the user left it in at
# the end of the previous session: if the icon/i2pd was on, start it again
# and re-add the panel icon; if it was off, do nothing (no icon, no
# wasted panel space for a service most sessions won't use).

set -uo pipefail

STATE_FILE="$HOME/.config/cyberbeest/i2pd_state"

if [ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE" 2>/dev/null)" = "running" ]; then
    "$HOME/.local/bin/i2pd-start.sh"
fi
"""

TOGGLE_SCRIPTS = {
    "i2pd-start.sh": I2PD_START_SH,
    "i2pd-stop.sh": I2PD_STOP_SH,
    "i2pd-panel-icon.sh": I2PD_PANEL_ICON_SH,
    "i2pd-genmon.sh": I2PD_GENMON_SH,
    "i2pd-menu.py": I2PD_MENU_PY,
    "i2pd-restore-session.sh": I2PD_RESTORE_SESSION_SH,
}


def log(msg):
    print(f"[setup_i2p_extras] {msg}")


def ensure_profile():
    if os.path.isdir(PROFILE_DIR):
        log("Firefox i2p profile already exists")
        return
    log("Creating Firefox i2p profile")
    subprocess.run(
        ["firefox", "-CreateProfile", f"i2p {PROFILE_DIR}"],
        capture_output=True, text=True, timeout=30,
    )
    if not os.path.isdir(PROFILE_DIR):
        raise RuntimeError("Firefox profile directory was not created")


def write_user_js():
    with open(os.path.join(PROFILE_DIR, "user.js"), "w", encoding="utf-8") as f:
        f.write(USER_JS)
    log("Wrote user.js proxy config")


def write_pac_file():
    with open(PAC_FILE, "w", encoding="utf-8") as f:
        f.write(PAC_FILE_CONTENT)
    log("Wrote i2p-proxy.pac")


def ensure_theme_active():
    ext_json = os.path.join(PROFILE_DIR, "extensions.json")
    if not os.path.exists(ext_json):
        log("First-run Firefox once (headless) to populate addon state")
        proc = subprocess.Popen(
            ["firefox", "-no-remote", "-P", "i2p", "-headless"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline and not os.path.exists(ext_json):
            time.sleep(1)
        subprocess.run(["pkill", "-f", "-P i2p -headless"], capture_output=True)
        proc.wait(timeout=15)
        if not os.path.exists(ext_json):
            raise RuntimeError("extensions.json never appeared after headless first-run")

    with open(ext_json, encoding="utf-8") as f:
        data = json.load(f)
    changed = False
    for addon in data.get("addons", []):
        if addon.get("id") == "default-theme@mozilla.org" and addon.get("active"):
            addon["active"] = False
            addon["userDisabled"] = True
            changed = True
        elif addon.get("id") == "firefox-alpenglow@mozilla.org" and not addon.get("active"):
            addon["active"] = True
            addon["userDisabled"] = False
            changed = True
    if changed:
        with open(ext_json, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # Force Firefox to re-derive startup state from extensions.json
        # instead of a stale cached addonStartup.json.lz4.
        cache = os.path.join(PROFILE_DIR, "addonStartup.json.lz4")
        if os.path.exists(cache):
            os.remove(cache)
        log("Activated Alpenglow theme")
    else:
        log("Alpenglow theme already active")


def ensure_desktop_entry():
    os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
    existing = None
    if os.path.exists(DESKTOP_FILE):
        with open(DESKTOP_FILE, encoding="utf-8") as f:
            existing = f.read()
    if existing != DESKTOP_ENTRY:
        with open(DESKTOP_FILE, "w", encoding="utf-8") as f:
            f.write(DESKTOP_ENTRY)
        os.chmod(DESKTOP_FILE, 0o755)
        subprocess.run(
            ["update-desktop-database", os.path.dirname(DESKTOP_FILE)],
            capture_output=True,
        )
        log("Installed Whisker launcher entry")
    else:
        log("Whisker launcher entry already up to date")


def ensure_qbittorrent_i2p_enabled():
    key = r"Session\I2P\Enabled"
    line = f"{key}=true\n"
    os.makedirs(os.path.dirname(QBT_CONF), exist_ok=True)

    if not os.path.exists(QBT_CONF):
        with open(QBT_CONF, "w", encoding="utf-8") as f:
            f.write("[BitTorrent]\n" + line)
        log("Created qBittorrent.conf with I2P enabled")
        return

    with open(QBT_CONF, encoding="utf-8") as f:
        lines = f.readlines()

    for i, existing_line in enumerate(lines):
        if existing_line.strip() == f"{key}=true":
            log("qBittorrent I2P support already enabled")
            return
        if existing_line.startswith(f"{key}="):
            lines[i] = line
            with open(QBT_CONF, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log("Updated existing I2P setting to enabled")
            return

    if "[BitTorrent]\n" in lines:
        idx = lines.index("[BitTorrent]\n") + 1
        lines.insert(idx, line)
    else:
        lines.append("\n[BitTorrent]\n")
        lines.append(line)
    with open(QBT_CONF, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log("Enabled I2P support in qBittorrent.conf")


def ensure_toggle_scripts():
    os.makedirs(BIN_DIR, exist_ok=True)
    for name, content in TOGGLE_SCRIPTS.items():
        path = os.path.join(BIN_DIR, name)
        existing = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = f.read()
        if existing != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(path, 0o755)
    log("Installed i2pd toggle scripts")


def ensure_toggle_launchers():
    os.makedirs(APPS_DIR, exist_ok=True)
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    for path, content in (
        (START_DESKTOP_FILE, START_DESKTOP_ENTRY),
        (RESTORE_DESKTOP_FILE, RESTORE_DESKTOP_ENTRY),
    ):
        existing = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = f.read()
        if existing != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(path, 0o755)
    subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)
    log("Installed i2pd toggle launchers (Whisker entry + login-restore autostart)")


def teardown():
    """Undo everything this script writes to the user's home directory.

    Called (as `setup_i2p_extras.py remove`) when the package manager row
    is unchecked. Stops i2pd/removes the live panel icon first if present
    -- both are safe no-ops if i2pd was already stopped/uninstalled.
    Leaves the Firefox profile and qBittorrent config alone, same as the
    rest of the package manager leaves user data in place on uninstall.
    """
    stop_script = os.path.join(BIN_DIR, "i2pd-stop.sh")
    if os.path.exists(stop_script):
        subprocess.run([stop_script], capture_output=True, text=True, timeout=30)

    for name in TOGGLE_SCRIPTS:
        path = os.path.join(BIN_DIR, name)
        if os.path.exists(path):
            os.remove(path)

    for path in (START_DESKTOP_FILE, RESTORE_DESKTOP_FILE, STATE_FILE):
        if os.path.exists(path):
            os.remove(path)

    subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)
    log("Removed i2pd toggle scripts and launchers")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        teardown()
        log("Done")
        return
    ensure_profile()
    write_user_js()
    write_pac_file()
    ensure_theme_active()
    ensure_desktop_entry()
    ensure_qbittorrent_i2p_enabled()
    ensure_toggle_scripts()
    ensure_toggle_launchers()
    log("Done")


if __name__ == "__main__":
    main()
