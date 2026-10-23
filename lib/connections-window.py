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
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from connections_lookup import read_connections  # noqa: E402
from i18n import t  # noqa: E402

REFRESH_MS = 5000
LOCK_PATH = f"/run/user/{os.getuid()}/cyberbeest-connections-window.lock"

rdns_cache = {}  # ip -> hostname, "" if lookup failed, None while pending
rdns_lock = threading.Lock()


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
        self.set_default_size(620, 460)
        self.set_icon_name("network-wired")

        # app/remote, port/count, direction, host, row colour
        self.store = Gtk.TreeStore(str, str, str, str, str)
        view = Gtk.TreeView(model=self.store)
        titles = (t("connections.col_app"), t("connections.col_port"), t("connections.col_direction"), t("connections.col_host"))
        for i, title in enumerate(titles):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i, foreground=4)
            col.set_resizable(True)
            view.append_column(col)
        self.view = view

        scroll = Gtk.ScrolledWindow()
        scroll.add(view)

        self.status = Gtk.Label(xalign=0)
        self.status.set_margin_start(6)
        self.status.set_margin_end(6)
        self.status.set_margin_top(4)
        self.status.set_margin_bottom(4)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(scroll, True, True, 0)
        box.pack_start(self.status, False, False, 0)
        self.add(box)

        self.expanded = set()
        view.connect("row-expanded", lambda v, it, p: self.expanded.add(self.store[it][0]))
        view.connect("row-collapsed", lambda v, it, p: self.expanded.discard(self.store[it][0]))

        self.refresh()
        GLib.timeout_add(REFRESH_MS, self.refresh)

    def refresh(self):
        apps = read_connections()
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
            parent = self.store.append(
                None, [app, str(len(conns)), t("connections.n_incoming").format(n=n_in) if n_in else "", "", colour]
            )
            for rip, rport, is_in in sorted(conns, key=lambda c: (not c[2], c[0], c[1])):
                self.store.append(
                    parent,
                    [rip, rport, t("connections.dir_incoming") if is_in else t("connections.dir_outgoing"), rdns(rip),
                     "#c00000" if is_in else None],
                )
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
