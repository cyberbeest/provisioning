#!/usr/bin/env python3
"""Click action for the security-update-check genmon icon (update-genmon.sh):
shows the log of the last check/install run. A plain GTK dialog rather than
zenity --text-info, which always adds a Cancel button alongside OK -- there's
nothing to cancel here, it's a read-only log view.
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

LOG_FILE = "/var/log/security-update-check-last.log"


def show_log():
    try:
        with open(LOG_FILE) as f:
            content = f.read()
    except OSError:
        content = None

    dialog = Gtk.Dialog(title=t("update_genmon.log_title"))
    dialog.set_default_size(800, 600)
    dialog.add_button(t("update_genmon.close"), Gtk.ResponseType.CLOSE)

    box = dialog.get_content_area()
    if content is None:
        label = Gtk.Label(label=t("update_genmon.log_missing"))
        label.set_margin_top(20)
        label.set_margin_bottom(20)
        label.set_margin_start(20)
        label.set_margin_end(20)
        box.add(label)
    else:
        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_cursor_visible(False)
        textview.set_monospace(True)
        for setter in ("set_left_margin", "set_right_margin", "set_top_margin", "set_bottom_margin"):
            getattr(textview, setter)(8)
        textview.get_buffer().set_text(content)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add(textview)
        box.pack_start(scroller, True, True, 0)

    dialog.show_all()
    dialog.run()
    dialog.destroy()


if __name__ == "__main__":
    show_log()
