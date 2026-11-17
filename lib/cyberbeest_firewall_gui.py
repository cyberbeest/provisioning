#!/usr/bin/env python3
"""Firewall.

Lists the ports the firewall lets through, and lets the user open more.

The firewall itself is 63-firewall.sh's default-deny-inbound nftables
ruleset. Its own ports (SSH, mDNS) are shown greyed out and can't be
removed here. Ports the user opens are kept in two root-owned, world-readable
files written by lib/cyberbeest-firewall-helper.sh:
  /etc/cyberbeest/firewall-extra-user.nft   the accept rules nftables loads
  /etc/cyberbeest/firewall-user-ports       the same list as "proto port name"
The GUI reads the second one; every change goes through pkexec to the helper,
which validates the list, checks the whole ruleset and puts the old rules back
if anything fails.

The lower list shows ports that a program on this machine is listening on but
that the firewall blocks (e.g. LocalSend on 53317), each with a button that
opens it. It uses the same idea as the auto-lock tooltip's "Listening ports
blocked by firewall" line.
"""

import os
import re
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from i18n import t  # noqa: E402

HOME = os.path.realpath(os.path.expanduser("~"))
HELPER = "/usr/local/lib/cyberbeest/cyberbeest-firewall-helper.sh"
BUILTIN_FILE = "/etc/cyberbeest/firewall-allowed-ports"
USER_FILE = "/etc/cyberbeest/firewall-user-ports"
NAME_BAD = re.compile(r"[^A-Za-z0-9 ._+-]")
NAME_MAX = 32
PKEXEC_DISMISSED = (126, 127)  # password prompt cancelled / not authorised


def clean_name(name):
    """The helper only accepts a short plain-ASCII name; strip the rest."""
    return NAME_BAD.sub("", name).strip()[:NAME_MAX].strip()


def read_list(path):
    """[(proto, port, name)] from a "proto port name" file; [] if absent."""
    out = []
    try:
        with open(path) as f:
            for line in f:
                parts = line.split(None, 2)
                if len(parts) >= 2 and parts[1].isdigit():
                    out.append((parts[0], int(parts[1]),
                                parts[2].strip() if len(parts) > 2 else ""))
    except OSError:
        pass
    return out


def firewall_active():
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", "nftables.service"],
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def listening():
    """{(proto, port): process name or ""} for sockets listening on a
    non-loopback address -- the same ones the auto-lock tooltip considers."""
    try:
        out = subprocess.run(["ss", "-tulnpH"], capture_output=True, text=True,
                             timeout=10, env={**os.environ, "LC_ALL": "C"}).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        f = line.split()
        if len(f) < 5 or f[0] not in ("tcp", "udp"):
            continue
        addr, _, port = f[4].rpartition(":")
        addr = addr.split("%")[0].strip("[]") if "%virbr" not in addr else ""
        if not port.isdigit() or not addr or addr.startswith("127.") \
                or addr == "::1" or addr.startswith("fe80:"):
            continue
        m = re.search(r'\("([^"]+)"', line)
        key = (f[0], int(port))
        if key not in found or (m and not found[key]):
            found[key] = m.group(1) if m else ""
    return found


def apply_list(entries):
    """Hand the whole user list to the root helper. Returns (ok, cancelled, msg)."""
    data = "".join("%s %d %s\n" % e for e in entries)
    try:
        r = subprocess.run(["pkexec", HELPER, "set"], input=data, capture_output=True,
                           text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, False, str(exc)
    if r.returncode == 0:
        return True, False, ""
    if r.returncode in PKEXEC_DISMISSED:
        return False, True, ""
    lines = (r.stderr or r.stdout).strip().splitlines()
    return False, False, lines[-1] if lines else "error %d" % r.returncode


import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib  # noqa: E402

# Must happen before Gtk is imported -- see cyberbeest_shared_folders_gui.py.
GLib.set_prgname("cyberbeest-firewall")
GLib.set_application_name(t("firewall.window_title"))

from gi.repository import GdkPixbuf, Gtk  # noqa: E402

ICON_PATH = os.path.join(HOME, ".local", "share", "cyberbeest", "icons", "Cyberbeest-black.png")

OPEN_PORT, OPEN_PROTO, OPEN_NAME, OPEN_KIND, OPEN_USER = range(5)
BLK_PORT, BLK_PROTO, BLK_APP = range(3)


class FirewallWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("firewall.window_title"))
        self.set_default_size(560, 520)
        try:
            self.set_icon_list([GdkPixbuf.Pixbuf.new_from_file_at_size(ICON_PATH, n, n)
                                for n in (16, 32, 48, 64, 128)])
        except GLib.Error:
            pass
        self.busy = False
        self.user_entries = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(10)
        self.add(root)

        self.banner = Gtk.Label(xalign=0)
        self.banner.set_line_wrap(True)
        self.banner.set_no_show_all(True)
        root.pack_start(self.banner, False, False, 0)

        # --- open ports ----------------------------------------------------
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>%s</b>" % GLib.markup_escape_text(t("firewall.open_heading")))
        root.pack_start(head, False, False, 0)

        intro = Gtk.Label(label=t("firewall.intro"), xalign=0)
        intro.set_line_wrap(True)
        root.pack_start(intro, False, False, 0)

        self.open_store = Gtk.ListStore(int, str, str, str, bool)
        self.open_view = Gtk.TreeView(model=self.open_store)
        for title, col, expand in ((t("firewall.col_port"), OPEN_PORT, False),
                                   (t("firewall.col_proto"), OPEN_PROTO, False),
                                   (t("firewall.col_name"), OPEN_NAME, True),
                                   (t("firewall.col_kind"), OPEN_KIND, False)):
            c = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=col, sensitive=OPEN_USER)
            c.set_expand(expand)
            c.set_resizable(True)
            self.open_view.append_column(c)
        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self.open_view)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_btn = Gtk.Button(label="+")
        self.add_btn.set_tooltip_text(t("firewall.add_tip"))
        self.add_btn.set_size_request(36, 36)
        self.add_btn.connect("clicked", self.on_add)
        self.remove_btn = Gtk.Button(label="−")
        self.remove_btn.set_tooltip_text(t("firewall.remove_tip"))
        self.remove_btn.set_size_request(36, 36)
        self.remove_btn.connect("clicked", self.on_remove)
        side.pack_start(self.add_btn, False, False, 0)
        side.pack_start(self.remove_btn, False, False, 0)

        row = Gtk.Box(spacing=6)
        row.pack_start(scroll, True, True, 0)
        row.pack_start(side, False, False, 0)
        root.pack_start(row, True, True, 0)

        # --- listening but blocked -----------------------------------------
        head2 = Gtk.Label(xalign=0)
        head2.set_markup("<b>%s</b>" % GLib.markup_escape_text(t("firewall.blocked_heading")))
        root.pack_start(head2, False, False, 0)
        note2 = Gtk.Label(label=t("firewall.blocked_note"), xalign=0)
        note2.set_line_wrap(True)
        root.pack_start(note2, False, False, 0)

        self.blk_store = Gtk.ListStore(int, str, str)
        self.blk_view = Gtk.TreeView(model=self.blk_store)
        for title, col, expand in ((t("firewall.col_port"), BLK_PORT, False),
                                   (t("firewall.col_proto"), BLK_PROTO, False),
                                   (t("firewall.col_app"), BLK_APP, True)):
            c = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=col)
            c.set_expand(expand)
            c.set_resizable(True)
            self.blk_view.append_column(c)
        self.blk_view.connect("row-activated", lambda *_: self.on_open_blocked(None))
        scroll2 = Gtk.ScrolledWindow()
        scroll2.set_shadow_type(Gtk.ShadowType.IN)
        scroll2.set_min_content_height(110)
        scroll2.add(self.blk_view)
        root.pack_start(scroll2, True, True, 0)

        btnrow = Gtk.Box(spacing=8)
        self.open_blocked_btn = Gtk.Button(label=t("firewall.open_selected"))
        self.open_blocked_btn.connect("clicked", self.on_open_blocked)
        btnrow.pack_start(self.open_blocked_btn, False, False, 0)
        root.pack_start(btnrow, False, False, 0)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_line_wrap(True)
        self.status.set_no_show_all(True)
        self._hide_timeout = None
        root.pack_start(self.status, False, False, 0)

        self.reload()
        GLib.timeout_add_seconds(5, self.tick)
        self.connect("focus-in-event", lambda *_: self.reload())
        self.connect("destroy", Gtk.main_quit)

    # -- display ------------------------------------------------------------
    def reload(self):
        builtin = read_list(BUILTIN_FILE)
        self.user_entries = read_list(USER_FILE)
        active = firewall_active()
        if active:
            self.banner.hide()
        else:
            self.banner.set_markup("<b>%s</b>" % GLib.markup_escape_text(t("firewall.inactive")))
            self.banner.show()

        open_rows = []
        for rows, kind, mine in ((builtin, t("firewall.kind_builtin"), False),
                                 (self.user_entries, t("firewall.kind_user"), True)):
            for proto, port, name in sorted(rows, key=lambda e: (e[1], e[0])):
                open_rows.append([port, proto.upper(), name, kind, mine])

        blk_rows = []
        if active:
            allowed = {(p, n) for p, n, _ in builtin + self.user_entries}
            for (proto, port), app in sorted(listening().items(), key=lambda kv: (kv[0][1], kv[0][0])):
                if (proto, port) not in allowed:
                    blk_rows.append([port, proto.upper(), app])

        self.fill(self.open_view, self.open_store, open_rows, (OPEN_PORT, OPEN_PROTO))
        self.fill(self.blk_view, self.blk_store, blk_rows, (BLK_PORT, BLK_PROTO))
        self.open_blocked_btn.set_sensitive(len(self.blk_store) > 0 and not self.busy)
        return False

    @staticmethod
    def fill(view, store, rows, key_cols):
        """Replace STORE's rows with ROWS, but only if they differ, and keep the
        selected row selected -- the 5 s refresh must not drop the user's
        selection (or flicker the lists) when nothing has changed."""
        if [list(r) for r in store] == rows:
            return
        model, it = view.get_selection().get_selected()
        keep = tuple(model[it][c] for c in key_cols) if it else None
        store.clear()
        for r in rows:
            new_it = store.append(r)
            if keep is not None and tuple(r[c] for c in key_cols) == keep:
                view.get_selection().select_iter(new_it)

    def tick(self):
        if not self.busy:
            self.reload()
        return True

    def flash(self, text, error=False):
        if self._hide_timeout:
            GLib.source_remove(self._hide_timeout)
        self.status.set_markup(
            ("<span foreground='#b00020'>%s</span>" if error else "%s")
            % GLib.markup_escape_text(text))
        self.status.show()
        self._hide_timeout = GLib.timeout_add_seconds(8, self._hide_status)

    def _hide_status(self):
        self.status.hide()
        self._hide_timeout = None
        return False

    # -- changing the list --------------------------------------------------
    def commit(self, entries, done_text):
        """Send ENTRIES to the helper in a thread (the password prompt blocks)."""
        if self.busy:
            return
        self.busy = True
        for w in (self.add_btn, self.remove_btn, self.open_blocked_btn):
            w.set_sensitive(False)

        def work():
            res = apply_list(entries)
            GLib.idle_add(self.committed, res, done_text)

        threading.Thread(target=work, daemon=True).start()

    def committed(self, res, done_text):
        ok, cancelled, msg = res
        self.busy = False
        for w in (self.add_btn, self.remove_btn):
            w.set_sensitive(True)
        self.reload()
        if ok:
            self.flash(done_text)
        elif not cancelled:
            self.flash(t("firewall.err_failed").format(msg=msg), error=True)
        return False

    def merged(self, new):
        """The user list plus NEW [(proto, port, name)], without duplicates."""
        have = {(p, n) for p, n, _ in self.user_entries}
        builtin = {(p, n) for p, n, _ in read_list(BUILTIN_FILE)}
        out = list(self.user_entries)
        for proto, port, name in new:
            if (proto, port) not in have and (proto, port) not in builtin:
                out.append((proto, port, clean_name(name)))
                have.add((proto, port))
        return out

    def on_add(self, _btn):
        dlg = Gtk.Dialog(title=t("firewall.add_title"), transient_for=self, modal=True)
        dlg.add_button(t("firewall.cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(t("firewall.open_btn"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        grid.set_border_width(12)
        spin = Gtk.SpinButton.new_with_range(1, 65535, 1)
        spin.set_value(53317)
        spin.set_activates_default(True)
        combo = Gtk.ComboBoxText()
        for label in (t("firewall.proto_both"), "TCP", "UDP"):
            combo.append_text(label)
        combo.set_active(0)
        name = Gtk.Entry()
        name.set_max_length(NAME_MAX)
        name.set_activates_default(True)
        name.set_placeholder_text(t("firewall.name_hint"))
        for i, (label, widget) in enumerate(((t("firewall.col_port"), spin),
                                             (t("firewall.col_proto"), combo),
                                             (t("firewall.col_name"), name))):
            lab = Gtk.Label(label=label, xalign=0)
            grid.attach(lab, 0, i, 1, 1)
            widget.set_hexpand(True)
            grid.attach(widget, 1, i, 1, 1)
        dlg.get_content_area().add(grid)
        dlg.show_all()
        resp = dlg.run()
        port, proto_idx, label = spin.get_value_as_int(), combo.get_active(), name.get_text()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        protos = (("tcp", "udp"), ("tcp",), ("udp",))[proto_idx]
        new = self.merged([(p, port, label) for p in protos])
        if len(new) == len(self.user_entries):
            self.flash(t("firewall.already_open"))
            return
        self.commit(new, t("firewall.opened"))

    def on_open_blocked(self, _btn):
        model, it = self.blk_view.get_selection().get_selected()
        if not it:
            return
        port, proto, app = model[it][BLK_PORT], model[it][BLK_PROTO].lower(), model[it][BLK_APP]
        self.commit(self.merged([(proto, port, app)]), t("firewall.opened"))

    def on_remove(self, _btn):
        model, it = self.open_view.get_selection().get_selected()
        if not it or not model[it][OPEN_USER]:
            if it:
                self.flash(t("firewall.err_builtin"))
            return
        drop = (model[it][OPEN_PROTO].lower(), model[it][OPEN_PORT])
        self.commit([e for e in self.user_entries if (e[0], e[1]) != drop],
                    t("firewall.closed"))


if __name__ == "__main__":
    win = FirewallWindow()
    win.show_all()
    Gtk.main()
