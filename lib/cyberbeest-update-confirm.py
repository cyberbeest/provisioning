#!/usr/bin/env python3
"""Confirm dialog for cyberbeest-update.sh -- not zenity, because zenity's
--question dialog always adds its own Yes/No first internally and stacks
any --extra-button above them (verified against zenity 4.1.90's source and
a live render), with no CLI way to reorder that. That put "Switch to X
instead" -- a rare, destructive action -- visually ahead of the everyday
Yes/No choice. A small dedicated GTK3 dialog (matching cyberbeest-askpass.py
and the rest of Cyberbeest's own dialogs) instead packs it as a secondary
button-box widget, which GTK renders on the opposite side from Yes/No --
there on request, but not competing for attention.

Prints exactly one of "yes", "no" or "switch" to stdout and exits 0.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from i18n import t

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

RESPONSE_SWITCH = 100


_RELATIVE_UNITS = (
    ("year", 31536000), ("month", 2592000), ("day", 86400),
    ("hour", 3600), ("minute", 60),
)


def relative_time(when):
    seconds = (datetime.datetime.now() - when).total_seconds()
    for unit, unit_seconds in _RELATIVE_UNITS:
        n = int(seconds // unit_seconds)
        if n >= 1:
            key = f"relative.{unit}_ago" if n == 1 else f"relative.{unit}s_ago"
            return t(key).format(n=n)
    return t("relative.just_now")


def last_pull_text(repo_dir):
    # git touches .git/FETCH_HEAD on every fetch (including the fetch this
    # tool's own "Yes" does), so its mtime is a reliable "last pull" marker
    # without needing a separate state file.
    fetch_head = os.path.join(repo_dir, ".git", "FETCH_HEAD")
    try:
        when = datetime.datetime.fromtimestamp(os.path.getmtime(fetch_head))
    except OSError:
        return t("update.last_pull_never")
    return t("update.last_pull_message").format(
        when=when.strftime("%Y-%m-%d %H:%M"), relative=relative_time(when)
    )


def main():
    track, other_track, repo_dir = sys.argv[1], sys.argv[2], sys.argv[3]

    dialog = Gtk.Dialog(title=t("update.title"))
    dialog.set_default_size(420, -1)
    dialog.add_buttons(
        t("update.button_no"), Gtk.ResponseType.NO,
        t("update.button_yes"), Gtk.ResponseType.YES,
    )
    dialog.set_default_response(Gtk.ResponseType.YES)
    dialog.get_widget_for_response(Gtk.ResponseType.YES).get_style_context().add_class(
        "suggested-action"
    )

    box = dialog.get_content_area()
    box.set_border_width(12)
    box.set_spacing(8)

    heading = Gtk.Image.new_from_icon_name("dialog-question", Gtk.IconSize.DIALOG)
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row.pack_start(heading, False, False, 0)
    label = Gtk.Label(xalign=0)
    label.set_markup(t("update.confirm_message").format(track=track))
    label.set_line_wrap(True)
    row.pack_start(label, True, True, 0)
    box.pack_start(row, True, True, 0)

    last_pull_label = Gtk.Label(xalign=0)
    last_pull_label.set_markup(f"<small>{last_pull_text(repo_dir)}</small>")
    box.pack_start(last_pull_label, False, False, 0)

    # A MenuButton (same pattern as run-gui.py's "more actions" dropdown)
    # rather than a plain button, so picking "switch" is a deliberate
    # two-click action, not a stray single click next to No/Yes.
    switch_button = Gtk.MenuButton(label=t("update.switch_button"))
    switch_menu = Gtk.Menu()
    switch_item = Gtk.MenuItem(label=t("update.switch_menu_item").format(track=other_track))
    switch_item.connect("activate", lambda _mi: dialog.response(RESPONSE_SWITCH))
    switch_menu.append(switch_item)
    switch_menu.show_all()
    switch_button.set_popup(switch_menu)

    # set_child_secondary puts it on the opposite end of the action area's
    # button box from Yes/No (the same mechanism a dialog's "Help" button
    # uses to sit apart from OK/Cancel) -- this is what actually achieves
    # the ordering zenity couldn't.
    action_area = dialog.get_action_area()
    action_area.pack_start(switch_button, False, False, 0)
    action_area.set_child_secondary(switch_button, True)

    dialog.show_all()
    response = dialog.run()
    dialog.destroy()

    if response == Gtk.ResponseType.YES:
        print("yes")
    elif response == RESPONSE_SWITCH:
        print("switch")
    else:
        print("no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
