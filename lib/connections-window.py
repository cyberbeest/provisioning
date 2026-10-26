#!/usr/bin/env python3
"""Window listing established outgoing TCP connections grouped by app.

Opened by clicking the connections genmon panel icon. Top-level rows are apps
(with connection count), child rows are the remote endpoints. Hostnames come
from reverse DNS, looked up in the background and cached, so they are only a
hint: CDN addresses often resolve to unrelated provider names or to nothing.
"""
import fcntl
import os
import socket
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from connections_lookup import dns_names, flags_for, read_connections  # noqa: E402
import statistics  # noqa: E402
from i18n import t  # noqa: E402

REFRESH_MS = 5000
LOCK_PATH = f"/run/user/{os.getuid()}/cyberbeest-connections-window.lock"

rdns_cache = {}  # ip -> hostname, "" if lookup failed, None while pending
rdns_lock = threading.Lock()


def country_cell(geo, ip):
    """Flag and country name for the Country column ("" when flags are off)."""
    if geo is None:
        return ""
    from connections_lookup import country_name, is_lan
    from geo import flag_emoji
    if is_lan(ip):
        return "🏠 " + t("connections.country_lan")
    cc = geo.country(ip)
    return f"{flag_emoji(cc)} {country_name(cc)}" if cc else "🌐 " + t("connections.unknown")


def latency_text(ms):
    """Round-trip time the kernel measured for a connection ("" if it has none yet)."""
    if ms is None:
        return ""
    return "<1 ms" if ms < 1 else (f"{ms:.1f} ms" if ms < 10 else f"{ms:.0f} ms")


def app_countries(geo, conns):
    """Flags and names for an app row: "🇩🇪🇺🇸 Germany, United States"."""
    if geo is None:
        return ""
    from connections_lookup import country_names, is_lan
    names = country_names([c for c in conns if not is_lan(c[0])], geo)
    if any(is_lan(c[0]) for c in conns):
        names.append(t("connections.country_lan"))
    return f"{flags_for(conns, geo)} {', '.join(names)}".strip()


def load_geo():
    try:
        from geo import load
        return load()
    except ImportError:
        return None


def _rdns_worker(ip):
    socket.setdefaulttimeout(2)
    try:
        name = socket.gethostbyaddr(ip)[0]
    except OSError:
        name = ""
    with rdns_lock:
        rdns_cache[ip] = name


def rdns(ip):
    with rdns_lock:
        if ip in rdns_cache:
            return rdns_cache[ip] or ""
        rdns_cache[ip] = None
    threading.Thread(target=_rdns_worker, args=(ip,), daemon=True).start()
    return "…"


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("connections.window_title"))
        self.set_default_size(820, 460)
        self.set_icon_name("network-wired")

        # app/remote, count, direction, country, latency, host, row colour
        self.store = Gtk.TreeStore(str, str, str, str, str, str, str)
        view = Gtk.TreeView(model=self.store)
        titles = (t("connections.col_app"), t("connections.col_count"), t("connections.col_direction"),
                  t("connections.col_country"), t("connections.col_latency"), t("connections.col_host"))
        for i, title in enumerate(titles):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i, foreground=6)
            col.set_resizable(True)
            # Only shown while country flags are on (Settings); refresh() toggles it.
            if i == 3:
                self.country_col = col
            view.append_column(col)
        self.view = view

        scroll = Gtk.ScrolledWindow()
        scroll.add(view)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.set_margin_start(6)
        self.status.set_margin_end(6)
        self.status.set_margin_top(4)
        self.status.set_margin_bottom(4)

        # Footnote for the Countries* column; shown only while that column is.
        self.country_note = Gtk.Label(xalign=0, wrap=True, label=t("connections.country_note"))
        self.country_note.set_margin_start(6)
        self.country_note.set_margin_end(6)
        self.country_note.set_margin_bottom(4)
        self.country_note.get_style_context().add_class("dim-label")
        self.country_note.set_no_show_all(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(scroll, True, True, 0)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        bar.pack_start(self.status, True, True, 0)
        settings = Gtk.Button(label=t("connections.settings_button"))
        settings.set_relief(Gtk.ReliefStyle.NONE)
        settings.connect("clicked", lambda _b: subprocess.Popen(
            [os.path.expanduser("~/.local/bin/cyberbeest-settings.py"), "--tab=connections"]))
        bar.pack_start(settings, False, False, 0)
        box.pack_start(bar, False, False, 0)
        box.pack_start(self.country_note, False, False, 0)
        self.add(box)

        self.expanded = set()
        self.known = set()  # apps shown before: new ones start expanded, later collapses stick
        view.connect("row-expanded", lambda v, it, p: self.expanded.add(self.store[it][0]))
        view.connect("row-collapsed", lambda v, it, p: self.expanded.discard(self.store[it][0]))

        self.refresh()
        GLib.timeout_add(REFRESH_MS, self.refresh)

    def refresh(self):
        apps = read_connections()
        geo = load_geo()
        asked = dns_names([c[0] for v in apps.values() for c in v])
        self.country_col.set_visible(geo is not None)
        self.country_note.set_visible(geo is not None)
        total = sum(len(v) for v in apps.values())
        incoming = sum(1 for v in apps.values() for c in v if c[2])
        self.store.clear()
        # Apps with incoming connections first (should normally be none),
        # then by connection count.
        def sort_key(kv):
            return (-sum(1 for c in kv[1] if c[2]), -len(kv[1]))

        for app, conns in sorted(apps.items(), key=sort_key):
            n_in = sum(1 for c in conns if c[2])
            colour = "#c00000" if n_in else None
            in_ports = sorted({c[3] for c in conns if c[2]}, key=int)
            if n_in:
                direction = t("connections.n_incoming_ports").format(n=n_in, ports=", ".join(in_ports))
                if n_in < len(conns):
                    direction += ", " + t("connections.n_outgoing").format(n=len(conns) - n_in)
            else:
                direction = t("connections.dir_outgoing")
            parent = self.store.append(
                None, [app, str(len(conns)), direction,
                       app_countries(geo, conns), latency_text(statistics.median(r) if (r := [c[4] for c in conns if c[4] is not None]) else None), "", colour]
            )
            for rip, rport, is_in, lport, rtt in sorted(conns, key=lambda c: (not c[2], c[0], c[1])):
                self.store.append(
                    parent,
                    [f"[{rip}]:{rport}" if ":" in rip else f"{rip}:{rport}", "",
                     t("connections.dir_incoming_port").format(port=lport) if is_in else t("connections.dir_outgoing"),
                     country_cell(geo, rip), latency_text(rtt), asked.get(rip) or rdns(rip),
                     "#c00000" if is_in else None],
                )
            if app not in self.known:
                self.known.add(app)
                self.expanded.add(app)
            if app in self.expanded or n_in:
                self.view.expand_row(self.store.get_path(parent), False)
        self.status.set_text(
            t("connections.status").format(
                total=total, incoming=incoming, apps=len(apps), secs=REFRESH_MS // 1000
            )
        )
        return True


def main():
    # One window at a time: a second click on the icon just exits.
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
    win = Window()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
