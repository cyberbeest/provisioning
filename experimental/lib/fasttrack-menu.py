#!/usr/bin/env python3
"""Popup menu for the Fast Track panel icon (genmon plugin-230)."""
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

BIN = os.path.expanduser("~/.local/bin")
STATE = os.path.expanduser("~/.local/state/cyberbeest-fasttrack")
PAUSED = os.path.join(STATE, "paused")


def launch(*argv):
    subprocess.Popen(argv, start_new_session=True)


def toggle_pause(_item):
    if os.path.exists(PAUSED):
        os.remove(PAUSED)
    else:
        os.makedirs(STATE, exist_ok=True)
        open(PAUSED, "w").close()


menu = Gtk.Menu()
item = Gtk.MenuItem(label="Check for updates now")
item.connect("activate", lambda _i: launch(os.path.join(BIN, "cyberbeest-update.sh"), "--fast-track"))
menu.append(item)
item = Gtk.MenuItem(label="Open Cyberbeest Update")
item.connect("activate", lambda _i: launch(os.path.join(BIN, "cyberbeest-update.sh")))
menu.append(item)
menu.append(Gtk.SeparatorMenuItem())
item = Gtk.MenuItem(label="Resume Fast Track" if os.path.exists(PAUSED) else "Pause Fast Track")
item.connect("activate", toggle_pause)
menu.append(item)
menu.connect("deactivate", lambda _m: Gtk.main_quit())
menu.show_all()
# Legacy popup call: popup_at_pointer(None) asserts when launched from genmon <click>.
menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())
Gtk.main()
