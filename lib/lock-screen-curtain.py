#!/usr/bin/python3
# Lock-screen curtain: an opaque gray window with a padlock that is painted
# BEFORE the screen gets locked, so the last desktop frame can never flash
# in front of a bystander while the lock dialog is still coming up (worst
# right as the screen wakes from DPMS blank and the unlock dialog hasn't
# repainted yet). It stays up for the whole locked period underneath
# xfce4-screensaver's own windows and goes away the moment the session
# unlocks.
#
# Flow (see lib/cyberbeest-lock, which every lock path goes through):
#   cyberbeest-lock -> Show() on this daemon -> returns once the curtain has
#   really been painted -> xfce4-screensaver-command --lock.
# The screensaver's windows are mapped after the curtain, so they sit on top
# of it. This is why the curtain is an override-redirect window (a GTK POPUP):
# no window manager involvement at all, so no decorations, no taskbar entry,
# no stacking surprises, exact monitor geometry -- and it can only ever be
# shown through Show(), never as a side effect of the WM restoring or
# un-minimizing windows (the earlier xterm-based curtain kept resurfacing).
#
# Fail-safes, so a curtain can never trap the user behind a gray screen:
#   * if the screen is still not locked FAILSAFE_SECONDS after Show(), the
#     curtain removes itself;
#   * Show() never blocks longer than PAINT_TIMEOUT_MS waiting for the paint,
#     so a broken curtain can only delay a lock, never prevent it;
#   * the window belongs to this process, so if the daemon dies the window
#     dies with it.
#
# Toggle: CURTAIN_ENABLED in ~/.config/cyberbeest/power-settings.conf
# (default true), read fresh on every Show().

import math
import os
import socket
import sys
import time

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("XAUTHORITY", os.path.expanduser("~/.Xauthority"))

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

BUS_NAME = "com.cyberbeest.Curtain"
OBJECT_PATH = "/com/cyberbeest/Curtain"
INTERFACE_XML = """
<node>
  <interface name="com.cyberbeest.Curtain">
    <method name="Show"/>
    <method name="Hide"/>
  </interface>
</node>
"""

POWER_SETTINGS = os.path.expanduser("~/.config/cyberbeest/power-settings.conf")
PAINT_TIMEOUT_MS = 1500
PAINT_SETTLE_MS = 30
FAILSAFE_SECONDS = 8

BACKGROUND = (0.17, 0.18, 0.20)
SYMBOL = (0.70, 0.72, 0.76)


def curtain_enabled():
    value = "true"
    try:
        with open(POWER_SETTINGS) as f:
            for line in f:
                if line.startswith("CURTAIN_ENABLED="):
                    value = line.split("=", 1)[1].strip() or "true"
    except OSError:
        pass
    return value == "true"


def wait_for_x(timeout=60):
    # At login the service can start before the X server accepts
    # connections.
    path = "/tmp/.X11-unix/X0"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX)
            s.connect(path)
            s.close()
            return
        except OSError:
            time.sleep(0.5)


def draw_padlock(cr, width, height):
    cr.set_source_rgb(*BACKGROUND)
    cr.paint()

    body_w = min(width, height) * 0.24
    body_h = body_w * 0.78
    radius = body_w * 0.30
    line = body_w * 0.11
    shackle_h = radius * 0.8 + radius
    total = shackle_h + body_h
    cx = width / 2
    top = height / 2 - total / 2
    body_y = top + shackle_h
    body_x = cx - body_w / 2

    cr.set_source_rgb(*SYMBOL)

    # Shackle: two legs and a half circle on top.
    cr.set_line_width(line)
    cr.set_line_cap(1)  # round
    cr.new_path()
    cr.move_to(cx - radius, body_y + line)
    cr.line_to(cx - radius, top + radius)
    cr.arc(cx, top + radius, radius, math.pi, 2 * math.pi)
    cr.line_to(cx + radius, body_y + line)
    cr.stroke()

    # Body: rounded rectangle.
    r = body_w * 0.10
    cr.new_path()
    cr.arc(body_x + r, body_y + r, r, math.pi, 1.5 * math.pi)
    cr.arc(body_x + body_w - r, body_y + r, r, 1.5 * math.pi, 2 * math.pi)
    cr.arc(body_x + body_w - r, body_y + body_h - r, r, 0, 0.5 * math.pi)
    cr.arc(body_x + r, body_y + body_h - r, r, 0.5 * math.pi, math.pi)
    cr.close_path()
    cr.fill()

    # Keyhole.
    kx, ky = cx, body_y + body_h * 0.42
    kr = body_w * 0.085
    cr.set_source_rgb(*BACKGROUND)
    cr.arc(kx, ky, kr, 0, 2 * math.pi)
    cr.fill()
    cr.set_line_width(kr * 0.95)
    cr.move_to(kx, ky)
    cr.line_to(kx, body_y + body_h * 0.74)
    cr.stroke()


class Curtain:
    def __init__(self):
        self.windows = []
        self.pending_draws = 0
        self.waiting = []  # method invocations to answer once painted
        self.failsafe_id = 0
        self.conn = None

    # -- D-Bus ---------------------------------------------------------

    def on_bus_acquired(self, conn, name):
        self.conn = conn
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        conn.register_object(OBJECT_PATH, node.interfaces[0], self.on_method_call, None, None)
        conn.signal_subscribe(
            "org.xfce.ScreenSaver", "org.xfce.ScreenSaver", "ActiveChanged",
            "/org/xfce/ScreenSaver", None, Gio.DBusSignalFlags.NONE,
            self.on_active_changed, None)

    def on_name_lost(self, conn, name):
        # Another instance owns the name (or the bus went away).
        sys.exit(1)

    def on_method_call(self, conn, sender, path, iface, method, params, invocation):
        if method == "Show":
            self.show(invocation)
        elif method == "Hide":
            self.hide()
            invocation.return_value(None)

    def on_active_changed(self, conn, sender, path, iface, signal, params, data):
        if not params.unpack()[0]:
            self.hide()

    # -- Curtain -------------------------------------------------------

    def show(self, invocation):
        if self.windows:
            if self.pending_draws:
                self.waiting.append(invocation)
            else:
                invocation.return_value(None)
            return
        if not curtain_enabled():
            invocation.return_value(None)
            return

        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            geometry = display.get_monitor(i).get_geometry()
            win = Gtk.Window(type=Gtk.WindowType.POPUP)
            win.set_app_paintable(True)
            win.set_accept_focus(False)
            win.move(geometry.x, geometry.y)
            win.set_default_size(geometry.width, geometry.height)
            win.resize(geometry.width, geometry.height)
            win.connect("draw", self.on_draw)
            self.windows.append(win)
        self.pending_draws = len(self.windows)
        self.waiting.append(invocation)
        for win in self.windows:
            win.show_all()
            win.get_window().raise_()

        GLib.timeout_add(PAINT_TIMEOUT_MS, self.answer_waiting)
        self.failsafe_id = GLib.timeout_add_seconds(FAILSAFE_SECONDS, self.failsafe)

    def on_draw(self, win, cr):
        draw_padlock(cr, win.get_allocated_width(), win.get_allocated_height())
        if not getattr(win, "painted", False):
            win.painted = True
            self.pending_draws -= 1
            if self.pending_draws <= 0:
                # Let the X server finish the paint before the caller locks.
                Gdk.Display.get_default().sync()
                GLib.timeout_add(PAINT_SETTLE_MS, self.answer_waiting)
        return True

    def answer_waiting(self):
        waiting, self.waiting = self.waiting, []
        for invocation in waiting:
            invocation.return_value(None)
        return False

    def hide(self):
        for win in self.windows:
            win.destroy()
        self.windows = []
        self.pending_draws = 0
        if self.failsafe_id:
            GLib.source_remove(self.failsafe_id)
            self.failsafe_id = 0
        self.answer_waiting()

    def failsafe(self):
        self.failsafe_id = 0
        if not self.screen_locked():
            self.hide()
        return False

    def screen_locked(self):
        try:
            reply = self.conn.call_sync(
                "org.xfce.ScreenSaver", "/org/xfce/ScreenSaver", "org.xfce.ScreenSaver",
                "GetActive", None, GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 1000, None)
            return reply.unpack()[0]
        except GLib.Error:
            # Can't tell: assume locked rather than uncover a desktop.
            return True


def main():
    wait_for_x()
    if not Gtk.init_check()[0]:
        sys.exit("could not open display")
    curtain = Curtain()
    Gio.bus_own_name(
        Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
        curtain.on_bus_acquired, None, curtain.on_name_lost)
    Gtk.main()


if __name__ == "__main__":
    main()
