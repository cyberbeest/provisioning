#!/usr/bin/env python3
"""Sets up the "Disable Encrypted DNS (DoT)" troubleshooting toggle.

Encrypted DNS (dnscrypt-proxy, see 37-encrypted-dns.sh) is on by default and
stays on -- this only adds an escape hatch for two known failure modes:
1) the class of bug found with fritz.box (see cyberbeest_fritzbox_dns_dot_conflict
   memory): a router-vendor domain that resolves differently through a public
   encrypted resolver than it does through the router's own plain DNS, and we
   can't pre-populate a forwarding_rules exception for every vendor.
2) captive portals (hotel/airport wifi login pages), which work by hijacking
   plain DNS to redirect any lookup to the login page -- encrypted DNS bypasses
   that hijack entirely, so the portal never shows up and nothing resolves.

Whisker launcher "Disable Encrypted DNS" stops dnscrypt-proxy and adds a
warning panel icon (genmon plugin-29); clicking the icon re-enables it and
removes itself. Deliberately does NOT disable the systemd units -- a reboot
always brings encrypted DNS back, so forgetting to re-enable doesn't leave
the machine unencrypted past the next boot. The genmon script itself also
polls live service state and self-removes if it finds DoT already back on
(e.g. after that reboot), so the icon can never go stale.

Needs the scoped sudoers rule from setup-dot-toggle-sudoers.sh (root, via
the RUNME convention) to start/stop dnscrypt-proxy without a password
prompt on every toggle -- this script only writes user-owned files.

Idempotent: safe to re-run.
"""

import os
import subprocess
import sys

HOME = os.path.expanduser("~")
BIN_DIR = os.path.join(HOME, ".local", "bin")
APPS_DIR = os.path.join(HOME, ".local", "share", "applications")
DESKTOP_FILE = os.path.join(APPS_DIR, "dot-disable.desktop")

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Disable Encrypted DNS
Comment=Troubleshooting: temporarily turns off DNS-over-TLS if a local hostname (e.g. a router's admin page) won't resolve, or if a hotel/airport wifi captive portal login page won't show up. Re-enables itself on the next reboot.
Exec=%s/dot-disable.sh
Icon=stock_lock-broken
Categories=Network;
Terminal=false
""" % BIN_DIR

DOT_DISABLE_SH = """#!/bin/bash
# Temporarily turns off encrypted DNS and shows a warning panel icon.
# Launched from the Whisker menu. Does NOT disable the systemd units, so a
# reboot always restores encrypted DNS -- this is a session-scoped
# troubleshooting toggle, not a permanent opt-out.

set -uo pipefail

sudo -n systemctl stop dnscrypt-proxy-resolvconf.service dnscrypt-proxy.socket dnscrypt-proxy.service
"$HOME/.local/bin/dot-panel-icon.sh" add

notify-send --urgency=normal --app-name="Encrypted DNS" \\
    "Encrypted DNS disabled" "Plain DNS is in use until you re-enable it (panel icon) or reboot." 2>/dev/null || true
"""

DOT_ENABLE_SH = """#!/bin/bash
# Turns encrypted DNS back on and removes the warning panel icon. Run from
# the panel icon's menu, or automatically by dot-genmon.sh if it notices
# encrypted DNS is already active again (e.g. after a reboot).

set -uo pipefail

sudo -n systemctl start dnscrypt-proxy.socket
sleep 1
if command -v dig >/dev/null 2>&1; then
    dig @127.0.2.1 anthropic.com +short +time=3 +tries=1 >/dev/null 2>&1
fi
"$HOME/.local/bin/dot-panel-icon.sh" remove

notify-send --urgency=low --app-name="Encrypted DNS" \\
    "Encrypted DNS re-enabled" 2>/dev/null || true
"""

DOT_PANEL_ICON_SH = """#!/bin/bash
# Adds/removes the "Encrypted DNS disabled" genmon panel icon (plugin-29).
# Called by dot-disable.sh/dot-enable.sh/dot-genmon.sh -- not meant to be
# run standalone.
#
# Usage: dot-panel-icon.sh add|remove
#
# NOTE: xfconf-query's -a flag is --force-array, NOT "append" -- the whole
# plugin-ids array must be replaced in a single call (repeated -t int -s id
# pairs after -n -a), never built up with a loop of separate -a calls, or
# every earlier value gets clobbered down to just the last one.

set -uo pipefail

PLUGIN_ID=29
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

# Finds the plugin id whose type is "clock", by type rather than a
# hardcoded id -- ids are assigned per-machine by xfce, so a fixed id
# would only be valid on the machine it was captured from.
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
Command=$HOME/.local/bin/dot-genmon.sh
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
        # Land right before the clock, in the "running programs" group at
        # the panel's right end -- works whether or not other dev-only
        # icons (e.g. the sudo-helper/i2pd/VPN genmons) are present.
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

DOT_GENMON_SH = """#!/bin/bash
# Panel item: shown only while encrypted DNS is disabled. Click opens a
# menu to re-enable it. If it finds encrypted DNS already active again --
# e.g. a reboot brought it back, since dot-disable.sh deliberately never
# disables the systemd units -- it removes itself instead of showing a
# stale warning.

if systemctl is-active --quiet dnscrypt-proxy.service; then
    "$HOME/.local/bin/dot-panel-icon.sh" remove
    exit 0
fi

ICON=/usr/share/icons/gnome/24x24/status/stock_lock-broken.png
echo "<img>${ICON}</img>"
echo "<tool>Encrypted DNS is disabled.&#10;Click to re-enable.</tool>"
echo "<click>$HOME/.local/bin/dot-menu.py</click>"
"""

DOT_MENU_PY = '''#!/usr/bin/env python3
"""Popup menu for the "Encrypted DNS disabled" panel icon (genmon plugin-29)."""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

HOME_BIN = os.path.join(os.path.expanduser("~"), ".local", "bin")


def launch(*args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def enable_dot(_item):
    launch(f"{HOME_BIN}/dot-enable.sh")
    Gtk.main_quit()


def build_menu():
    menu = Gtk.Menu()

    enable_item = Gtk.MenuItem(label="Re-enable Encrypted DNS")
    enable_item.connect("activate", enable_dot)
    menu.append(enable_item)

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
    "dot-disable.sh": DOT_DISABLE_SH,
    "dot-enable.sh": DOT_ENABLE_SH,
    "dot-panel-icon.sh": DOT_PANEL_ICON_SH,
    "dot-genmon.sh": DOT_GENMON_SH,
    "dot-menu.py": DOT_MENU_PY,
}


def log(msg):
    print(f"[setup_dot_toggle] {msg}")


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
    log("Installed DoT toggle scripts")


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


def teardown():
    """Undo everything this script writes. Re-enables DoT first if it was
    left disabled, so uninstalling the toggle can't leave DNS unencrypted."""
    enable_script = os.path.join(BIN_DIR, "dot-enable.sh")
    if os.path.exists(enable_script):
        subprocess.run([enable_script], capture_output=True, text=True, timeout=30)

    for name in TOGGLE_SCRIPTS:
        path = os.path.join(BIN_DIR, name)
        if os.path.exists(path):
            os.remove(path)

    if os.path.exists(DESKTOP_FILE):
        os.remove(DESKTOP_FILE)

    subprocess.run(["update-desktop-database", APPS_DIR], capture_output=True)
    log("Removed DoT toggle scripts and launcher")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        teardown()
        log("Done")
        return
    ensure_toggle_scripts()
    ensure_desktop_entry()
    log("Done")


if __name__ == "__main__":
    main()
