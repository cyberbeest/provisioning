#!/usr/bin/env python3
"""Popup menu for the VPN panel icon (genmon plugin-228).

Lists imported profiles with a checkmark on whichever is connected,
lets you connect/disconnect, import a new profile, or delete one.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

# i18n.py only resolves `from i18n import t` if i18n.py (and its
# strings_*.py catalogs) sit next to this installed script -- true both
# here in the repo checkout and once deployed to ~/.local/bin, since
# Python always adds a script's own directory to sys.path.
from i18n import t

HOME = os.path.expanduser("~")
BIN = os.path.join(HOME, ".local", "bin")
STATE_DIR = os.path.join(HOME, ".config", "cyberbeest")
PROFILES_FILE = os.path.join(STATE_DIR, "vpn_profiles")
ACTIVE_FILE = os.path.join(STATE_DIR, "vpn_active")


def launch(*args):
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_lines(path):
    try:
        with open(path) as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


def get_profiles():
    # De-duplicate while preserving order, in case of any past double-writes.
    seen = []
    for name in read_lines(PROFILES_FILE):
        if name not in seen:
            seen.append(name)
    return seen


def get_active():
    lines = read_lines(ACTIVE_FILE)
    return lines[0] if lines else None


def connect(_item, name):
    launch(f"{BIN}/vpn-connect.sh", name)
    Gtk.main_quit()


def disconnect(_item):
    launch(f"{BIN}/vpn-disconnect.sh")
    Gtk.main_quit()


def import_profile(_item):
    launch(f"{BIN}/vpn-import.sh")
    Gtk.main_quit()


def remove_profile(_item, name):
    launch(f"{BIN}/vpn-remove-profile.sh", name)
    Gtk.main_quit()


def build_menu():
    menu = Gtk.Menu()
    profiles = get_profiles()
    active = get_active()

    if not profiles:
        empty_item = Gtk.MenuItem(label=t("vpn.menu_empty"))
        empty_item.set_sensitive(False)
        menu.append(empty_item)
        menu.append(Gtk.SeparatorMenuItem())

    for name in profiles:
        label = (
            t("vpn.menu_connected").format(name=name)
            if name == active
            else t("vpn.menu_connect").format(name=name)
        )
        item = Gtk.MenuItem(label=label)
        if name == active:
            item.set_sensitive(False)
        else:
            item.connect("activate", connect, name)
        menu.append(item)

    if active:
        menu.append(Gtk.SeparatorMenuItem())
        disconnect_item = Gtk.MenuItem(label=t("vpn.disconnect"))
        disconnect_item.connect("activate", disconnect)
        menu.append(disconnect_item)

    menu.append(Gtk.SeparatorMenuItem())

    import_item = Gtk.MenuItem(label=t("vpn.menu_import"))
    import_item.connect("activate", import_profile)
    menu.append(import_item)

    if profiles:
        remove_menu = Gtk.Menu()
        for name in profiles:
            remove_item = Gtk.MenuItem(label=name)
            remove_item.connect("activate", remove_profile, name)
            remove_menu.append(remove_item)
        remove_root = Gtk.MenuItem(label=t("vpn.menu_remove"))
        remove_root.set_submenu(remove_menu)
        menu.append(remove_root)

    menu.show_all()
    return menu


def main():
    menu = build_menu()
    menu.connect("deactivate", lambda _m: Gtk.main_quit())
    menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())
    Gtk.main()


if __name__ == "__main__":
    main()
