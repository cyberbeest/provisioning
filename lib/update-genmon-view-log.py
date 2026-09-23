#!/usr/bin/env python3
"""Click action for the security-update-check genmon icon (update-genmon.sh):
shows the log of the last check/install run, plus a "Run updates now" button.
A plain GTK dialog rather than zenity --text-info, which always adds a
Cancel button alongside OK -- there's nothing to cancel here, it's a
read-only log view.
"""

import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

LOG_FILE = "/var/log/security-update-check-last.log"
FORCE_UNIT = "security-update-check-force.service"
CHECK_UNIT = "security-update-check.service"


def _unit_active(unit):
    try:
        state = subprocess.run(
            ["systemctl", "show", "-p", "ActiveState", "--value", unit],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False
    return state in ("active", "activating")


def run_updates_now(button):
    if _unit_active(CHECK_UNIT) or _unit_active(FORCE_UNIT):
        _info(t("update_genmon.run_now_already_running"))
        return
    # The NOPASSWD sudoers rule installed by setup-security-update-timer.sh
    # scopes this to exactly this one systemctl invocation.
    result = subprocess.run(
        ["sudo", "-n", "systemctl", "start", FORCE_UNIT],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        _info(t("update_genmon.run_now_started"))
    else:
        _info(t("update_genmon.run_now_failed"))


def _info(message):
    dialog = Gtk.MessageDialog(
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=message,
    )
    dialog.run()
    dialog.destroy()


def show_log():
    try:
        with open(LOG_FILE) as f:
            content = f.read()
    except OSError:
        content = None

    dialog = Gtk.Dialog(title=t("update_genmon.log_title"))
    dialog.set_default_size(800, 600)
    run_now_button = dialog.add_button(t("update_genmon.run_now"), Gtk.ResponseType.APPLY)
    run_now_button.connect("clicked", run_updates_now)
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
