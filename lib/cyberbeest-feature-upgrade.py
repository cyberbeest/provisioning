#!/usr/bin/env python3
"""Dialog for the auto-lock panel menu's "Run feature updates..." item: lists the pending
non-security package upgrades with a checkbox each, installs the ticked ones through
pkexec -> cyberbeest-feature-upgrade-helper.sh, and follows the output live.

The automatic updater only installs security fixes (see lib/setup-security-update-timer.sh),
so everything else waits here until the user picks it."""

import os
import shutil
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from feature_upgrades import pending_feature_upgrades
from i18n import t

HELPER = "/usr/local/lib/cyberbeest/cyberbeest-feature-upgrade-helper.sh"
GENMON_WIDGET_NAME = "genmon-211"


def refresh_panel():
    """Same idea as shutdown-timer-menu.py's refresh_genmon(): nudge the panel so the
    tooltip's upgradable count updates now rather than at its next poll."""
    def running(name):
        return subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0
    if running("gopanel"):
        exe = os.path.expanduser("~/.local/bin/gopanel")
        if not os.access(exe, os.X_OK):
            exe = shutil.which("gopanel")
        if exe:
            subprocess.Popen([exe, "refresh"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif running("xfce4-panel"):
        subprocess.Popen(["xfce4-panel", f"--plugin-event={GENMON_WIDGET_NAME}:refresh:bool:true"])


class FeatureUpgradeDialog:
    def __init__(self, app):
        self.proc = None
        self.checks = []

        self.dialog = Gtk.Dialog(title=t("feature_upgrade.title"))
        self.dialog.set_default_size(620, 460)
        app.add_window(self.dialog)
        self.close_button = self.dialog.add_button(t("feature_upgrade.close"), Gtk.ResponseType.CLOSE)
        self.install_button = self.dialog.add_button(t("feature_upgrade.install"), Gtk.ResponseType.APPLY)
        self.install_button.get_style_context().add_class("suggested-action")
        self.dialog.connect("response", self._on_response)
        self.dialog.get_action_area().set_margin_top(12)

        box = self.dialog.get_content_area()
        box.set_spacing(8)
        for setter in ("set_margin_top", "set_margin_start", "set_margin_end"):
            getattr(box, setter)(12)

        self.intro = Gtk.Label(label=t("feature_upgrade.intro"), xalign=0)
        self.intro.set_line_wrap(True)
        box.pack_start(self.intro, False, False, 0)

        self.stack = Gtk.Stack()
        box.pack_start(self.stack, True, True, 0)

        # Page 1: the checkbox list.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        all_btn = Gtk.Button(label=t("feature_upgrade.select_all"))
        none_btn = Gtk.Button(label=t("feature_upgrade.select_none"))
        all_btn.connect("clicked", lambda _b: self._set_all(True))
        none_btn.connect("clicked", lambda _b: self._set_all(False))
        toolbar.pack_start(all_btn, False, False, 0)
        toolbar.pack_start(none_btn, False, False, 0)
        page.pack_start(toolbar, False, False, 0)

        listbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for name, old, new in pending_feature_upgrades():
            check = Gtk.CheckButton(label=f"{name}   {old} → {new}" if old else f"{name}   {new}")
            check.set_active(True)
            check.connect("toggled", lambda _c: self._update_install_button())
            check.pkg_name = name
            self.checks.append(check)
            listbox.pack_start(check, False, False, 0)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(listbox)
        page.pack_start(scroller, True, True, 0)
        self.stack.add_named(page, "list")

        # Page 2: live output.
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_monospace(True)
        self.buffer = self.textview.get_buffer()
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.add(self.textview)
        self.stack.add_named(log_scroller, "log")

        self.status = Gtk.Label(xalign=0)
        box.pack_start(self.status, False, False, 0)

        self.dialog.show_all()
        if not self.checks:
            self.intro.set_text(t("feature_upgrade.none"))
        self._update_install_button()

    def _set_all(self, value):
        for check in self.checks:
            check.set_active(value)

    def _selected(self):
        return [c.pkg_name for c in self.checks if c.get_active()]

    def _update_install_button(self):
        self.install_button.set_sensitive(self.proc is None and bool(self._selected()))

    def present(self):
        self.dialog.present()

    def _on_response(self, _dialog, response):
        if response == Gtk.ResponseType.APPLY:
            self._install()
        elif self.proc is None:
            self.dialog.destroy()

    def _append(self, text):
        self.buffer.insert(self.buffer.get_end_iter(), text)
        GLib.idle_add(lambda: self.textview.scroll_to_mark(
            self.buffer.get_insert(), 0.0, False, 0.0, 1.0) or False)
        self.buffer.place_cursor(self.buffer.get_end_iter())

    def _install(self):
        names = self._selected()
        if not names or self.proc is not None:
            return
        try:
            self.proc = subprocess.Popen(
                ["pkexec", HELPER, "install"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except OSError:
            self.status.set_text(t("feature_upgrade.failed_start"))
            return
        self.proc.stdin.write(("\n".join(names) + "\n").encode())
        self.proc.stdin.close()
        self.install_button.set_sensitive(False)
        self.close_button.set_sensitive(False)
        self.intro.set_text(t("feature_upgrade.installing"))
        self.status.set_text("")
        self.stack.set_visible_child_name("log")
        GLib.io_add_watch(self.proc.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP, self._on_output)

    def _on_output(self, fd, condition):
        data = os.read(fd, 4096) if condition & GLib.IO_IN else b""
        if data:
            self._append(data.decode(errors="replace"))
            return True
        code = self.proc.wait()
        self.proc.stdout.close()
        self.proc = None
        self.close_button.set_sensitive(True)
        self.install_button.hide()
        if code == 0:
            self.intro.set_text(t("feature_upgrade.done"))
        elif code in (126, 127):
            # pkexec: authentication dismissed or not authorised.
            self.intro.set_text(t("feature_upgrade.cancelled"))
        else:
            self.intro.set_text(t("feature_upgrade.failed"))
        refresh_panel()
        return False


def main():
    # One window at a time: a second launch just raises the running one.
    app = Gtk.Application(application_id="com.cyberbeest.FeatureUpgrade",
                          flags=Gio.ApplicationFlags.FLAGS_NONE)
    dialog = []

    def on_activate(_app):
        if dialog and dialog[0].dialog.get_realized():
            dialog[0].present()
        else:
            dialog[:] = [FeatureUpgradeDialog(app)]

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
