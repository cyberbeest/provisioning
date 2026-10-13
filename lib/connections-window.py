#!/usr/bin/env python3
"""Window listing established outgoing TCP connections grouped by app.

Opened by clicking the connections genmon panel icon. Top-level rows are apps
(with connection count), child rows are the remote endpoints. Hostnames come
from reverse DNS, looked up in the background and cached, so they are only a
hint: CDN addresses often resolve to unrelated provider names or to nothing.
"""
import fcntl
import os
import re
import socket
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

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


def split_endpoint(ep):
    host, _, port = ep.rpartition(":")
    return host.strip("[]"), port


def is_loopback(ip):
    return ip.startswith("127.") or ip == "::1"


def uid_name(uid):
    try:
        import pwd
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return f"uid {uid}"


def listening_ports(env):
    out = subprocess.run(
        ["ss", "-tlnH"], capture_output=True, text=True, env=env,
    ).stdout
    return {split_endpoint(l.split()[3])[1] for l in out.splitlines() if len(l.split()) >= 4}


SANDBOX_SH = r"""
for d in /proc/[0-9]*/fdinfo/*; do
    p=${d%%/fdinfo/*}
    [ -S "$p/fd/${d##*/}" ] || continue
    while read k v; do
        [ "$k" = "ino:" ] && { read c < "$p/comm"; echo "$v $c"; }
    done < "$d"
done
"""


def sandbox_sockets(env):
    """{socket inode: app name} for firejail sandboxes. Firejail hides its
    processes from ss, but inside the sandbox they are visible."""
    out = subprocess.run(
        ["firejail", "--list"], capture_output=True, text=True, env=env,
    ).stdout
    owners = {}
    for line in out.splitlines():
        pid = line.split(":")[0]
        if not pid.isdigit():
            continue
        try:
            res = subprocess.run(
                ["firejail", f"--join={pid}", "sh", "-c", SANDBOX_SH],
                capture_output=True, text=True, env=env, timeout=5,
            ).stdout
        except subprocess.TimeoutExpired:
            continue
        for l in res.splitlines():
            ino, _, name = l.partition(" ")
            if name:
                owners[ino] = name
    return owners


def read_connections():
    """Returns {app: [(ip, port, incoming), ...]}.

    A connection is incoming when its local port is one a local socket is
    listening on.
    """
    env = dict(os.environ, LC_ALL="C")
    listening = listening_ports(env)
    out = subprocess.run(
        ["ss", "-tnpeH", "state", "established"],
        capture_output=True, text=True, env=env,
    ).stdout
    apps = {}
    sandboxed = None
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        lip, lport = split_endpoint(cols[2])
        rip, rport = split_endpoint(cols[3])
        if is_loopback(lip) or is_loopback(rip):
            continue
        m = re.search(r'\(\("([^"]+)"', line)
        if m:
            app = m.group(1)
        else:
            u = re.search(r"uid:(\d+)", line)
            if not u or int(u.group(1)) >= 1000:
                ino = re.search(r"ino:(\d+)", line)
                if sandboxed is None:
                    sandboxed = sandbox_sockets(env)
                name = sandboxed.get(ino.group(1)) if ino else None
                app = f"{name} ({t('connections.sandboxed')})" if name else t("connections.unknown")
            else:
                app = f"{uid_name(u.group(1))} ({t('connections.system_service')})"
        apps.setdefault(app, []).append((rip, rport, lport in listening))
    return apps


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
