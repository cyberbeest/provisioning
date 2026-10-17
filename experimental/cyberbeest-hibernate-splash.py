#!/usr/bin/env python3
"""Full-screen "HIBERNATING" splash. Launched directly by
cyberbeest-logout.py's and shutdown-timer-menu.py's hibernate action
handlers, ~0.5s before they actually trigger hibernate -- NOT from the
systemd-sleep hook's "pre" step, which is too late: systemd-sleep freezes
the whole user session (X included) as its own first step, before any
hook gets a chance to run, so a process spawned from the hook is frozen
before it can render anything (confirmed live 2026-09-28).

Process state (including this window, still running) is part of what
hibernate's saved image captures -- the exact same process resumes
untouched once the machine powers back on and restores the image, so the
systemd-sleep hook's "post hibernate" step can just kill it by the pid
written below. This is NOT suspend-to-RAM's DRM re-init fragility:
hibernate is a real power cycle, so the display driver gets a completely
fresh probe on the resume-boot, same as any cold boot.

Known residual gap: xfce4-screensaver auto-locks as part of hibernate
prep, and its unlock dialog is override-redirect, which always renders
above this (a normal WM-managed window) once it maps a moment later --
so this is only visible for well under a second before being covered.
Accepted rather than chased further; see the conversation this shipped
from for why.

"""
import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gtk

# i18n.py does `from i18n import t`, which only resolves if i18n.py (and
# its strings_*.py catalogs) sit next to this installed script -- see
# lib/i18n.py. enable-hibernate-splash.sh installs both alongside this
# file, same convention as cyberbeest-logout.py etc.
from i18n import t

PIDFILE = os.path.expanduser("~/.cache/cyberbeest-hibernate-splash.pid")
LOGO_PATH = os.path.expanduser("~/.local/share/cyberbeest/icons/Cyberbeest-green.png")

CSS = b"""
window { background-color: #000000; }
label { color: #eeeeee; font-size: 40px; }
"""


def main():
    os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
    with open(PIDFILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    win = Gtk.Window(type_hint=Gdk.WindowTypeHint.SPLASHSCREEN)
    win.set_decorated(False)
    win.set_keep_above(True)
    # Requested before show_all(), not after: a fullscreen request on an
    # already-mapped window needs an extra round-trip to the window
    # manager to resize/reposition it, which risks losing the race
    # against the incoming device freeze entirely. Setting the hint first
    # means it's fullscreen as part of the initial map.
    win.fullscreen()

    screen = Gdk.Screen.get_default()
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    box.set_valign(Gtk.Align.CENTER)
    box.set_halign(Gtk.Align.CENTER)
    win.add(box)

    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(LOGO_PATH, 96, 96, True)
        box.pack_start(Gtk.Image.new_from_pixbuf(pixbuf), False, False, 0)
    except Exception:
        pass

    box.pack_start(Gtk.Label(label=t("hibernate.splash_text")), False, False, 0)

    win.show_all()

    # Force the initial paint to actually happen now, synchronously,
    # rather than relying on the hook's external sleep to outlast
    # whatever's still queued in GTK's event loop -- the background
    # painted fine without this (it's set via CSS at window creation) but
    # the logo/label content didn't consistently make it to screen before
    # the incoming device freeze cut rendering off.
    while Gtk.events_pending():
        Gtk.main_iteration()
    Gdk.Display.get_default().sync()

    Gtk.main()


if __name__ == "__main__":
    main()
