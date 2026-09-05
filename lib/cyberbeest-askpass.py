#!/usr/bin/env python3
"""SUDO_ASKPASS helper for run-gui.py -- see zenity-askpass.sh's history for
why this isn't zenity: this Debian's zenity (4.1.90, the GTK4 rewrite)
either ignores --text on a --password dialog entirely (always showing its
own fixed, formally-addressed "Sie" built-in prompt instead of anything we
pass it) or, via --forms (which does respect custom text/labels), never
wires Enter to the default button at all -- confirmed both ways by hand,
including on a plain --add-entry field, so it's not specific to password
fields. A small dedicated dialog sidesteps both and matches the rest of
Cyberbeest's own GTK3 dialogs instead of zenity's differently-styled one.

Prints the entered password to stdout and exits 0 on OK; prints nothing
and exits 1 on Cancel/close, same contract a `SUDO_ASKPASS` program is
expected to follow.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from i18n import t

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


def main():
    dialog = Gtk.Dialog(title=t("askpass.title"))
    dialog.set_default_size(360, -1)
    dialog.set_resizable(False)
    dialog.add_buttons(
        Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
        Gtk.STOCK_OK, Gtk.ResponseType.OK,
    )
    dialog.set_default_response(Gtk.ResponseType.OK)

    box = dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)

    heading = Gtk.Label(label=t("askpass.heading"), xalign=0)
    heading.set_line_wrap(True)
    box.pack_start(heading, False, False, 0)

    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    row.pack_start(Gtk.Label(label=t("askpass.field_label")), False, False, 0)
    entry = Gtk.Entry(visibility=False)
    # Makes Enter trigger the dialog's default response (OK) same as
    # clicking it -- the whole reason this replaces zenity, see module
    # docstring.
    entry.set_activates_default(True)
    row.pack_start(entry, True, True, 0)
    box.pack_start(row, False, False, 0)

    dialog.show_all()
    entry.grab_focus()
    response = dialog.run()
    password = entry.get_text() if response == Gtk.ResponseType.OK else ""
    dialog.destroy()

    if not password:
        return 1
    print(password)
    return 0


if __name__ == "__main__":
    sys.exit(main())
