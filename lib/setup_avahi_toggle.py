#!/usr/bin/env python3
"""Sets up the "Enable LAN Printer Discovery" opt-in toggle for avahi-daemon.

avahi-daemon (mDNS/DNS-SD, aka Bonjour/Zeroconf) is OFF by default -- masked
and stopped by 62-lan-printer-discovery.sh -- because it broadcasts this
machine's hostname and puts 3 UDP ports within reach of anyone on the LAN
for a feature (auto-discovering network printers/scanners, browsing other
Zeroconf devices in Thunar) most people use rarely if ever. This is the
opposite default from lib/setup_dot_toggle.py's encrypted-DNS toggle (on by
default, escape hatch to turn off) -- here the escape hatch runs the other
way: off by default, opt in when you actually want to add a LAN printer.

Whisker launcher "Enable LAN Printer Discovery" starts avahi-daemon and adds
a reminder panel icon (genmon plugin-230); clicking the icon (or a reboot,
since the enable step deliberately only starts the service rather than
enabling it) turns discovery back off. The genmon script itself also polls
live service state and self-removes if it finds avahi already stopped again
(e.g. after that reboot, or someone disabling it by hand), so the icon can
never go stale -- ported from the same self-healing idea in
setup_dot_toggle.py.

Needs the scoped sudoers rule from 62-lan-printer-discovery.sh (root, via
the RUNME convention) to unmask/start/stop/mask avahi-daemon without a
password prompt on every toggle -- this script only writes user-owned
files.

Idempotent: safe to re-run.
"""

import os
import subprocess
import sys

HOME = os.path.expanduser("~")
BIN_DIR = os.path.join(HOME, ".local", "bin")
APPS_DIR = os.path.join(HOME, ".local", "share", "applications")
DESKTOP_FILE = os.path.join(APPS_DIR, "avahi-enable.desktop")

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Enable LAN Printer Discovery
Comment=Temporarily turns on network device discovery (mDNS/Bonjour/Zeroconf) so a network printer, scanner, or other LAN device can find this computer while you set it up. Turns itself back off on the next reboot.
Exec=%s/avahi-enable.sh
Icon=/usr/share/icons/gnome/24x24/devices/printer-network.png
Categories=Network;
Terminal=false
""" % BIN_DIR

AVAHI_ENABLE_SH = """#!/bin/bash
# Temporarily turns on LAN device discovery (avahi-daemon) and shows a
# reminder panel icon. Launched from the Whisker menu. Only starts the
# service (doesn't re-enable it), so a reboot always restores the
# off-by-default state -- this is a session-scoped opt-in, not a
# permanent-on switch.

set -uo pipefail

sudo -n systemctl unmask avahi-daemon.service avahi-daemon.socket
sudo -n systemctl start avahi-daemon.service avahi-daemon.socket
"$HOME/.local/bin/avahi-panel-icon.sh" add

notify-send --urgency=normal --app-name="LAN Printer Discovery" \\
    "LAN discovery enabled" "This computer is now visible to other devices on the network. Click the panel icon to turn it back off, or it'll turn itself off on the next reboot." 2>/dev/null || true
"""

AVAHI_DISABLE_SH = """#!/bin/bash
# Turns LAN device discovery back off (avahi-daemon) and removes the
# reminder panel icon. Run from the panel icon's menu, or automatically by
# avahi-genmon.sh if it notices avahi is already stopped again (e.g. after
# a reboot).

set -uo pipefail

sudo -n systemctl stop avahi-daemon.service avahi-daemon.socket
sudo -n systemctl mask avahi-daemon.service avahi-daemon.socket
"$HOME/.local/bin/avahi-panel-icon.sh" remove

notify-send --urgency=low --app-name="LAN Printer Discovery" \\
    "LAN discovery disabled" 2>/dev/null || true
"""

AVAHI_PANEL_ICON_SH = """#!/bin/bash
# Adds/removes the "LAN discovery enabled" genmon panel icon (plugin-230).
# Called by avahi-enable.sh/avahi-disable.sh/avahi-genmon.sh -- not meant
# to be run standalone.
#
# Usage: avahi-panel-icon.sh add|remove
#
# NOTE: xfconf-query's -a flag is --force-array, NOT "append" -- the whole
# plugin-ids array must be replaced in a single call (repeated -t int -s id
# pairs after -n -a), never built up with a loop of separate -a calls, or
# every earlier value gets clobbered down to just the last one.

set -uo pipefail

PLUGIN_ID=230
ACTION="${1:-}"

# Never use `xfce4-panel -r`: it asks the still-running process to restart
# itself from whatever config it already has cached client-side, then
# persists that stale state back to xfconfd -- silently clobbering the
# xfconf write this script just made. A graceful kill has the same problem
# (exiting also re-persists in-memory config). See provisioning-bleeding's
# lib/xfce-panel-reload.sh, which this is ported from (via
# setup_dot_toggle.py's dot-panel-icon.sh): SIGKILL xfce4-panel outright,
# then launch a completely fresh panel process so it has no cached state
# to fall back on.
#
# Deliberately does NOT kill xfconfd -- see dot-panel-icon.sh's own comment
# on the tower i2pd-icon incident this avoids.
panel_dbus_addr() {
    local panel_pid
    panel_pid="$(pgrep -x xfce4-panel | head -n1)"
    [ -z "$panel_pid" ] && return 1
    PANEL_DBUS_ADDR="$(tr '\\0' '\\n' <"/proc/$panel_pid/environ" 2>/dev/null | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')"
    PANEL_DBUS_ADDR="${PANEL_DBUS_ADDR:-unix:path=/run/user/$(id -u)/bus}"
}

# Flocks the same file lib/xfce-panel-reload.sh and the panel watchdog use
# so a kill+relaunch here can never interleave with one of theirs -- see
# xfce-panel-reload.sh's own comment on xfce_panel_reload_lock for the full
# story. /run/user, not $HOME, so a stale lock can never survive a reboot.
PANEL_RELOAD_LOCK_FILE="/run/user/$(id -u)/cyberbeest-panel-reload.lock"

reload_panel() {
    if [ -e "$PANEL_RELOAD_LOCK_FILE" ] && ! : 2>/dev/null >>"$PANEL_RELOAD_LOCK_FILE"; then
        echo "warning: panel-reload lock file isn't writable by us -- removing a likely stale root-owned copy" >&2
        rm -f "$PANEL_RELOAD_LOCK_FILE" 2>/dev/null || true
    fi
    (
        flock -x 200
        reload_panel_impl
    ) 200>"$PANEL_RELOAD_LOCK_FILE"
}

reload_panel_impl() {
    local old_pid
    old_pid="$(pgrep -x xfce4-panel | head -n1)"
    panel_dbus_addr || return 0

    pkill -9 -x xfce4-panel 2>/dev/null || true

    local waited=0
    while pgrep -x xfce4-panel >/dev/null 2>&1; do
        sleep 0.5
        waited=$((waited + 1))
        if [ "$waited" -ge 10 ]; then
            echo "warning: xfce4-panel still running 5s after SIGKILL" >&2
            break
        fi
    done

    DISPLAY="${DISPLAY:-:0}" DBUS_SESSION_BUS_ADDRESS="$PANEL_DBUS_ADDR" \\
        setsid xfce4-panel >/dev/null 2>&1 </dev/null &
    disown

    local new_pid=""
    waited=0
    while [ "$waited" -lt 10 ]; do
        new_pid="$(pgrep -x xfce4-panel | head -n1)"
        if [ -n "$new_pid" ] && [ "$new_pid" != "$old_pid" ]; then
            break
        fi
        sleep 0.5
        waited=$((waited + 1))
    done
    if [ -z "$new_pid" ]; then
        echo "warning: xfce4-panel did not come back up" >&2
        return 1
    fi
    if [ "$new_pid" = "$old_pid" ]; then
        echo "warning: xfce4-panel pid unchanged after launch (old process never died?)" >&2
        return 1
    fi

    sleep 1.5
    local settled_pid
    settled_pid="$(pgrep -x xfce4-panel | head -n1)"
    if [ "$settled_pid" != "$new_pid" ]; then
        echo "warning: xfce4-panel pid changed again during settle (pid $new_pid -> ${settled_pid:-gone})" >&2
        return 1
    fi
}

get_plugin_ids() {
    xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids | grep -E '^[0-9]+$'
}

find_clock_id() {
    local id
    for id in $(get_plugin_ids); do
        if [ "$(xfconf-query -c xfce4-panel -p "/plugins/plugin-${id}" 2>/dev/null)" = "clock" ]; then
            echo "$id"
            return 0
        fi
    done
    return 1
}

set_plugin_ids() {
    local args=(-c xfce4-panel -p /panels/panel-1/plugin-ids -n -a)
    for id in "$@"; do
        args+=(-t int -s "$id")
    done
    xfconf-query "${args[@]}"
}

apply_add() {
    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -n -t string -s genmon 2>/dev/null \\
        || xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -s genmon

    mkdir -p "$HOME/.config/xfce4/panel"
    cat >"$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc" <<EOF
Command=$HOME/.local/bin/avahi-genmon.sh
UpdatePeriod=15000
UseLabel=0
Text=(genmon)
Font=Sans 10
EOF

    clock_id="$(find_clock_id || true)"

    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    inserted=0
    for id in "${ids[@]}"; do
        [ "$id" = "$PLUGIN_ID" ] && continue
        if [ -n "$clock_id" ] && [ "$id" = "$clock_id" ]; then
            new_ids+=("$PLUGIN_ID")
            inserted=1
        fi
        new_ids+=("$id")
    done
    if [ "$inserted" -eq 0 ]; then
        new_ids+=("$PLUGIN_ID")
    fi

    set_plugin_ids "${new_ids[@]}"
}

apply_remove() {
    mapfile -t ids < <(get_plugin_ids)
    new_ids=()
    for id in "${ids[@]}"; do
        [ "$id" = "$PLUGIN_ID" ] && continue
        new_ids+=("$id")
    done

    set_plugin_ids "${new_ids[@]}"

    xfconf-query -c xfce4-panel -p "/plugins/plugin-${PLUGIN_ID}" -r -R >/dev/null 2>&1
    rm -f "$HOME/.config/xfce4/panel/genmon-${PLUGIN_ID}.rc"
}

is_applied() {
    if [ "$ACTION" = add ]; then
        get_plugin_ids | grep -qx "$PLUGIN_ID"
    else
        ! get_plugin_ids | grep -qx "$PLUGIN_ID"
    fi
}

case "$ACTION" in
add | remove)
    if [ "$ACTION" = add ] && is_applied; then
        exit 0
    fi

    apply_"$ACTION"
    reload_ok=0
    for _ in 1 2 3; do
        if reload_panel; then
            reload_ok=1
            break
        fi
        sleep 1
        apply_"$ACTION"
    done
    [ "$reload_ok" -eq 1 ] || echo "warning: panel reload didn't take live effect after retries" >&2
    is_applied || echo "warning: plugin-${PLUGIN_ID} state didn't stick after retries" >&2
    ;;
*)
    echo "Usage: $0 add|remove" >&2
    exit 1
    ;;
esac
"""

AVAHI_GENMON_SH = """#!/bin/bash
# Panel item: shown only while LAN discovery (avahi-daemon) is enabled.
# Click opens a menu to turn it back off. If it finds avahi already
# stopped again -- e.g. a reboot restored the off-by-default state, since
# avahi-enable.sh deliberately only starts (never enables) the service --
# it removes itself instead of showing a stale reminder.

if ! systemctl is-active --quiet avahi-daemon.service; then
    "$HOME/.local/bin/avahi-panel-icon.sh" remove
    exit 0
fi

ICON=/usr/share/icons/gnome/24x24/devices/printer-network.png
echo "<img>${ICON}</img>"
echo "<tool>LAN device discovery is on -- this computer is visible to the network.&#10;Click to turn it back off.</tool>"
echo "<click>$HOME/.local/bin/avahi-menu.py</click>"
"""

AVAHI_MENU_PY = '''#!/usr/bin/env python3
"""Popup menu for the "LAN discovery enabled" panel icon (genmon plugin-230)."""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

HOME_BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")


def launch(*args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def disable_avahi(_item):
    launch(f"{HOME_BIN}/avahi-disable.sh")
    Gtk.main_quit()


def build_menu():
    menu = Gtk.Menu()

    disable_item = Gtk.MenuItem(label="Disable LAN Printer Discovery")
    disable_item.connect("activate", disable_avahi)
    menu.append(disable_item)

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

TOGGLE_SCRIPTS = {
    "avahi-enable.sh": AVAHI_ENABLE_SH,
    "avahi-disable.sh": AVAHI_DISABLE_SH,
    "avahi-panel-icon.sh": AVAHI_PANEL_ICON_SH,
    "avahi-genmon.sh": AVAHI_GENMON_SH,
    "avahi-menu.py": AVAHI_MENU_PY,
}


def log(msg):
    print(f"[setup_avahi_toggle] {msg}")


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
    log("Installed avahi toggle scripts")


def ensure_desktop_entry():
    os.makedirs(APPS_DIR, exist_ok=True)
    existing = None
    if os.path.exists(DESKTOP_FILE):
        with open(DESKTOP_FILE, encoding="utf-8") as f:
            existing = f.read()
    if existing != DESKTOP_ENTRY:
        with open(DESKTOP_FILE, "w", encoding="utf-8") as f:
            f.write(DESKTOP_ENTRY)
        os.chmod(DESKTOP_FILE, 0o755)
        subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)
        log("Installed Whisker launcher entry")
    else:
        log("Whisker launcher entry already up to date")


def ensure_icon_matches_state():
    """Reflect current live state immediately, in case this script is
    re-run while avahi already happens to be running -- don't wait for the
    next genmon poll to show (or hide) the icon."""
    is_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "avahi-daemon.service"]
    ).returncode == 0
    subprocess.run(
        [os.path.join(BIN_DIR, "avahi-panel-icon.sh"), "add" if is_active else "remove"],
        check=False,
    )


def teardown():
    """Undo everything this script writes. Turns avahi back off first if it
    was left enabled, so uninstalling the toggle can't leave LAN discovery
    silently running with no way to turn it off from the panel."""
    disable_script = os.path.join(BIN_DIR, "avahi-disable.sh")
    if os.path.exists(disable_script):
        subprocess.run([disable_script], capture_output=True, text=True, timeout=30)

    for name in TOGGLE_SCRIPTS:
        path = os.path.join(BIN_DIR, name)
        if os.path.exists(path):
            os.remove(path)

    if os.path.exists(DESKTOP_FILE):
        os.remove(DESKTOP_FILE)

    subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)
    log("Removed avahi toggle scripts and launcher")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        teardown()
        log("Done")
        return
    ensure_toggle_scripts()
    ensure_desktop_entry()
    ensure_icon_matches_state()
    log("Done")


if __name__ == "__main__":
    main()
