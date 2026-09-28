#!/usr/bin/env python3
import os
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GdkPixbuf, Gdk, Gio
import subprocess
import sys

from i18n import t


LOGO_PATH = os.path.expanduser("~/.local/share/cyberbeest/icons/Cyberbeest-green.png")

ACTIONS = [
    (t("logout.lock"), ["xflock4"]),
    (t("logout.restart"), ["xfce4-session-logout", "--reboot"]),
    (t("logout.shutdown"), ["xfce4-session-logout", "--halt"]),
]

CSS = b"""
window { background-color: #1a1a1a; }
button {
    background: #2a2a2a;
    color: #eeeeee;
    border: 1px solid #444;
    border-radius: 8px;
    padding: 14px;
    font-size: 14px;
}
button:hover { background: #3a3a3a; border-color: #7a5cff; }
"""


class LogoutDialog(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=t("logout.title"))
        self.set_decorated(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_default_size(360, 260)
        self.set_keep_above(True)
        self.connect("key-press-event", self.on_key)

        screen = Gdk.Screen.get_default()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_border_width(24)
        self.add(outer)

        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                LOGO_PATH, 64, 64, True
            )
            logo = Gtk.Image.new_from_pixbuf(pixbuf)
            outer.pack_start(logo, False, False, 0)
        except Exception:
            pass

        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_column_homogeneous(True)
        outer.pack_start(grid, True, True, 0)

        for i, (label, cmd) in enumerate(ACTIONS):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self.on_action, cmd)
            grid.attach(btn, 0, i, 1, 1)

        cancel = Gtk.Button(label=t("logout.cancel"))
        cancel.connect("clicked", lambda *_: self.get_application().quit())
        outer.pack_start(cancel, False, False, 0)

    def on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.get_application().quit()

    def on_action(self, _widget, cmd):
        self.get_application().quit()
        subprocess.Popen(cmd)


class LogoutApp(Gtk.Application):
    # A single well-known application ID makes GTK/GIO handle repeat
    # launches for us: a second `run()` while one is already open just
    # forwards "activate" to the first instance over D-Bus and returns,
    # instead of opening another window -- this is what used to stack up
    # a dialog per power-button press (each press ran a brand new,
    # independent process with no idea another one was already open).
    def __init__(self):
        super().__init__(application_id="com.cyberbeest.Logout",
                          flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = LogoutDialog(self)
            self.window.show_all()
        self.window.present()


if __name__ == "__main__":
    app = LogoutApp()
    sys.exit(app.run(None))
