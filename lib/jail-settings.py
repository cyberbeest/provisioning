#!/usr/bin/env python3
"""App-protection (jail) settings: all apps / only ticked apps / none.

Writes ~/.config/cyberbeest/jail.conf (read by jail-lib.sh) and then runs
jail-apply.sh so the Firefox menu entries follow the new default. Opened from
the panel icon (jail-status-genmon.sh) and Cyberbeest Settings.
"""

import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from i18n import t

CONF = os.path.expanduser("~/.config/cyberbeest/jail.conf")
APPLY = os.path.expanduser("~/bin/jail-apply.sh")
# (id, label, binary that must exist for the app to be listed)
APPS = [
    ("firefox", "Firefox", "/usr/bin/firefox-esr"),
    ("chrome", "Chrome", "/usr/bin/google-chrome-stable"),
    ("signal", "Signal", "/opt/Signal/signal-desktop"),
    ("element", "Element", "/opt/Element/element-desktop"),
    ("telegram", "Telegram", "/usr/bin/telegram-desktop"),
    ("viber", "Viber", "/opt/viber/Viber"),
    ("sparrow", "Sparrow", "/opt/sparrowwallet/bin/Sparrow"),
    ("feather", "Feather", "/usr/bin/feather"),
]
# Must match JAIL_DEFAULT_SOME in jail-lib.sh.
DEFAULT_SOME = "signal element telegram viber sparrow feather"


def read():
    mode, apps = "all", DEFAULT_SOME
    try:
        with open(CONF, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == "MODE" and v in ("all", "some", "none"):
                    mode = v
                elif k == "APPS":
                    apps = v.strip('"')
    except OSError:
        pass
    return mode, apps.split()


def write(mode, apps):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f'MODE={mode}\nAPPS="{" ".join(apps)}"\n')
    os.replace(tmp, CONF)
    if os.path.exists(APPLY):
        subprocess.run([APPLY], check=False)


def build(app):
    mode, apps = read()
    win = Gtk.ApplicationWindow(application=app, title=t("jail.title"))
    win.set_border_width(12)
    win.set_default_size(440, -1)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    win.add(box)

    def label(text, markup=False):
        lb = Gtk.Label(label=text)
        lb.set_xalign(0)
        lb.set_line_wrap(True)
        lb.set_max_width_chars(60)
        return lb

    box.pack_start(label(t("jail.intro")), False, False, 0)

    checks = {}
    state = {"mode": mode}
    apps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    apps_box.set_margin_start(28)

    def save(*_):
        chosen = [a for a, c in checks.items() if c.get_active()]
        write(state["mode"], chosen)

    def sync_sensitive():
        apps_box.set_sensitive(state["mode"] == "some")

    group = None
    for m in ("all", "some", "none"):
        rb = Gtk.RadioButton.new_with_label_from_widget(group, t(f"jail.mode_{m}"))
        group = rb
        rb.set_active(m == mode)

        def on_toggled(rb, m=m):
            if rb.get_active():
                state["mode"] = m
                sync_sensitive()
                save()

        rb.connect("toggled", on_toggled)
        box.pack_start(rb, False, False, 0)
        if m == "some":
            box.pack_start(apps_box, False, False, 0)

    for app_id, name, binary in APPS:
        if not os.path.exists(binary):
            continue
        cb = Gtk.CheckButton(label=name)
        cb.set_active(app_id in apps)
        cb.connect("toggled", save)
        checks[app_id] = cb
        apps_box.pack_start(cb, False, False, 0)
    sync_sensitive()

    box.pack_start(label(t("jail.note_firefox")), False, False, 6)
    box.pack_start(label(t("jail.restart_note")), False, False, 0)
    btn = Gtk.Button(label=t("jail.close"))
    btn.set_halign(Gtk.Align.END)
    btn.connect("clicked", lambda b: win.destroy())
    box.pack_start(btn, False, False, 4)
    win.show_all()


def on_activate(app):
    # Single instance: a second launch (panel icon clicked again) just raises
    # the window that is already open.
    wins = app.get_windows()
    if wins:
        wins[0].present()
    else:
        build(app)


if __name__ == "__main__":
    app = Gtk.Application(application_id="com.cyberbeest.JailSettings")
    app.connect("activate", on_activate)
    app.run(None)
