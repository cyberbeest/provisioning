#!/usr/bin/env python3
"""Click action for the security-update-check genmon icon (update-genmon.sh):
shows the log of the last check/install run, plus a "Run updates now" button.
While a run is in progress it follows that run's output live instead, and
switches to the finished log once the run ends.
A plain GTK dialog rather than zenity --text-info, which always adds a
Cancel button alongside OK -- there's nothing to cancel here, it's a
read-only log view.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from i18n import t

LOG_FILE = "/var/log/security-update-check-last.log"
# Written by security-update-check.sh only during a real (non-throttled)
# run, and removed when it exits -- see lib/setup-security-update-timer.sh.
LIVE_LOG_FILE = "/run/security-update-check.live.log"
FORCE_UNIT = "security-update-check-force.service"
CHECK_UNIT = "security-update-check.service"
POLL_MS = 1000


def _unit_active(unit):
    try:
        state = subprocess.run(
            ["systemctl", "show", "-p", "ActiveState", "--value", unit],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False
    return state in ("active", "activating")


def _run_active():
    return _unit_active(CHECK_UNIT) or _unit_active(FORCE_UNIT)


def _info(parent, message):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=message,
    )
    dialog.run()
    dialog.destroy()


def _read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return None


class LogDialog:
    def __init__(self):
        self.live = False
        self.live_offset = 0
        self.run_now_proc = None

        self.dialog = Gtk.Dialog(title=t("update_genmon.log_title"))
        self.dialog.set_default_size(800, 600)
        self.run_now_button = self.dialog.add_button(
            t("update_genmon.run_now"), Gtk.ResponseType.APPLY)
        self.dialog.add_button(t("update_genmon.close"), Gtk.ResponseType.CLOSE)
        self.dialog.connect("response", self._on_response)
        self.dialog.connect("destroy", lambda _w: Gtk.main_quit())

        box = self.dialog.get_content_area()

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for setter in ("set_margin_top", "set_margin_start", "set_margin_end"):
            getattr(status_box, setter)(8)
        self.spinner = Gtk.Spinner()
        self.status_label = Gtk.Label(xalign=0)
        status_box.pack_start(self.spinner, False, False, 0)
        status_box.pack_start(self.status_label, True, True, 0)
        box.pack_start(status_box, False, False, 0)

        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_monospace(True)
        for setter in ("set_left_margin", "set_right_margin", "set_top_margin", "set_bottom_margin"):
            getattr(self.textview, setter)(8)
        self.buffer = self.textview.get_buffer()

        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_vexpand(True)
        self.scroller.add(self.textview)
        box.pack_start(self.scroller, True, True, 0)

        self.dialog.show_all()
        self._refresh()
        GLib.timeout_add(POLL_MS, self._poll)

    def _at_bottom(self):
        adj = self.scroller.get_vadjustment()
        return adj.get_value() >= adj.get_upper() - adj.get_page_size() - 20

    def _scroll_to_end(self):
        self.textview.scroll_to_mark(self.buffer.get_insert(), 0.0, False, 0.0, 1.0)

    def _set_text(self, text):
        self.buffer.set_text(text)
        self.buffer.place_cursor(self.buffer.get_end_iter())
        # Scroll once the new text has been laid out.
        GLib.idle_add(self._scroll_to_end)

    def _show_final_log(self):
        self.live = False
        self.spinner.stop()
        self.spinner.hide()
        self.run_now_button.set_sensitive(True)
        content = _read(LOG_FILE)
        if content is None:
            self.status_label.set_text(t("update_genmon.log_missing"))
            self._set_text("")
        else:
            self.status_label.set_text(t("update_genmon.log_last_run"))
            self._set_text(content)

    def _enter_live(self):
        self.live = True
        self.live_offset = 0
        self.spinner.show()
        self.spinner.start()
        self.status_label.set_text(t("update_genmon.log_live"))
        self.run_now_button.set_sensitive(False)
        self._set_text("")

    def _append_live(self):
        try:
            with open(LIVE_LOG_FILE, "rb") as f:
                size = os.fstat(f.fileno()).st_size
                if size < self.live_offset:
                    # Truncated: a new run started over the same file.
                    self._set_text("")
                    self.live_offset = 0
                f.seek(self.live_offset)
                chunk = f.read()
        except OSError:
            return
        if not chunk:
            return
        self.live_offset += len(chunk)
        follow = self._at_bottom()
        self.buffer.insert(self.buffer.get_end_iter(), chunk.decode(errors="replace"))
        if follow:
            self.buffer.place_cursor(self.buffer.get_end_iter())
            GLib.idle_add(self._scroll_to_end)

    def _refresh(self):
        # Live mode keys off the live log existing, not just the unit being
        # active: the timer fires every 15 minutes and most activations exit
        # straight away (throttled) without ever creating it.
        running = os.path.exists(LIVE_LOG_FILE) and _run_active()
        if running:
            if not self.live:
                self._enter_live()
            self._append_live()
        elif self.live or self.status_label.get_text() == "":
            self._show_final_log()

    def _poll(self):
        self._check_run_now_proc()
        self._refresh()
        return True

    def _check_run_now_proc(self):
        if self.run_now_proc is None or self.run_now_proc.poll() is None:
            return
        proc, self.run_now_proc = self.run_now_proc, None
        stderr = proc.stderr.read()
        proc.stderr.close()
        if not self.live:
            self._show_final_log()
        # A failed run also makes `systemctl start` exit non-zero, and the
        # log already shows that -- only report sudo itself refusing.
        if proc.returncode != 0 and stderr.startswith("sudo:"):
            _info(self.dialog, t("update_genmon.run_now_failed"))

    def _on_response(self, _dialog, response):
        if response == Gtk.ResponseType.APPLY:
            self._run_updates_now()
        else:
            self.dialog.destroy()

    def _run_updates_now(self):
        if _run_active():
            _info(self.dialog, t("update_genmon.run_now_already_running"))
            return
        # The NOPASSWD sudoers rule installed by setup-security-update-timer.sh
        # scopes this to exactly this one systemctl invocation. `start` on a
        # oneshot unit blocks until the run finishes, so run it in the
        # background and let _poll() follow the run live meanwhile.
        try:
            self.run_now_proc = subprocess.Popen(
                ["sudo", "-n", "systemctl", "start", FORCE_UNIT],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, text=True,
            )
        except OSError:
            _info(self.dialog, t("update_genmon.run_now_failed"))
            return
        self.run_now_button.set_sensitive(False)
        self.status_label.set_text(t("update_genmon.log_starting"))


if __name__ == "__main__":
    LogDialog()
    Gtk.main()
