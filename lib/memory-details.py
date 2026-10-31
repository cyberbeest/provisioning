#!/usr/bin/env python3
"""Detailed memory view opened from the mem-liquid panel item's menu.

Lists the biggest process groups by proportional set size (PSS), the same
measure the panel tooltip uses, but far longer than its top three.
"""

import glob
import math
import os
import re
import threading

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from i18n import t

MAX_ROWS = 100
MIN_KIB = 512
REFRESH_S = 3


def kib_field(text, key):
    for ln in text.split("\n"):
        if ln.startswith(key):
            try:
                return int(ln[len(key):].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def level_color(f):
    """Same blue -> yellow -> red scale as the panel's mem-liquid tank."""
    lo, mid, hi, stop = (0.20, 0.55, 0.90), (0.95, 0.75, 0.15), (0.90, 0.15, 0.15), 0.75
    a, b, t = (lo, mid, f / stop) if f <= stop else (mid, hi, (f - stop) / (1 - stop))
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


def tank_icon(level, size=64):
    """The panel tank frozen at the current RAM level, used as the window icon."""
    m, r = size * 0.10, size * 0.16 * 0.8 * 2
    cs = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    c = cairo.Context(cs)

    def tank():
        x, y, w = m, m, size - 2 * m
        c.new_sub_path()
        c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        c.arc(x + w - r, y + w - r, r, 0, math.pi / 2)
        c.arc(x + r, y + w - r, r, math.pi / 2, math.pi)
        c.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        c.close_path()

    tank()
    c.set_source_rgb(0.08, 0.10, 0.13)
    c.fill()
    c.save()
    tank()
    c.clip()
    w = size - 2 * m
    top = size - m - level * w
    col = level_color(level)
    c.move_to(m, size)
    for i in range(int(w) + 1):
        c.line_to(m + i, top + 0.028 * w * math.sin(i / w * 2 * math.pi + 0.6))
    c.line_to(size - m, size)
    c.close_path()
    g = cairo.LinearGradient(0, top, 0, size - m)
    g.add_color_stop_rgb(0, *[min(1, v + 0.2) for v in col])
    g.add_color_stop_rgb(1, *[v * 0.7 for v in col])
    c.set_source(g)
    c.fill()
    c.restore()
    tank()
    c.set_source_rgba(0.55, 0.60, 0.65, 0.9)
    c.set_line_width(max(1, size * 0.03))
    c.stroke()
    return Gdk.pixbuf_get_from_surface(cs, 0, 0, size, size)


def count_mapped():
    """The panel's "count memory-mapped files as used" setting (on unless its rc file says otherwise)."""
    for path in glob.glob(os.path.expanduser("~/.config/xfce4/panel/mem-liquid-*.rc")):
        try:
            with open(path) as f:
                for ln in f:
                    k, _, v = ln.strip().partition("=")
                    if k == "CountMapped":
                        return v == "true"
        except OSError:
            pass
        break
    return True


def used_kib(mi):
    """Same figure as the panel tank: with mapped files counted, only passive file cache is free."""
    if not count_mapped():
        return max(0, mi["MemTotal"] - mi.get("MemAvailable", 0))
    passive = max(0, mi.get("Cached", 0) - mi.get("Mapped", 0) - mi.get("Shmem", 0))
    return max(0, mi["MemTotal"] - (mi.get("MemFree", 0) + mi.get("Buffers", 0) + passive))


def meminfo():
    d = {}
    with open("/proc/meminfo") as f:
        for ln in f:
            k, _, v = ln.partition(":")
            d[k] = int(v.split()[0])
    return d


VERSION_COMM = re.compile(r"^\d+(\.\d+)+$")


def claude_name(pid, comm):
    """Claude Code runs from .../claude/versions/<version>, so the kernel names it by version."""
    try:
        if "/claude/versions/" not in os.readlink(f"/proc/{pid}/exe"):
            return comm
        with open(f"/proc/{pid}/cmdline") as f:
            cmd = f.read()
    except OSError:
        return comm
    if "bg-spare" in cmd or "/spare/" in cmd:
        return "claude (standby)"
    if VERSION_COMM.match(comm) or "bg-pty-host" in cmd:
        return "claude (background)"
    return "claude"


def script_name(pid, comm):
    """Python programs all have the kernel name python3; the script's file name is what tells them apart."""
    try:
        with open(f"/proc/{pid}/cmdline") as f:
            args = f.read().split("\0")
    except OSError:
        return comm
    for a in args[1:]:
        if a and not a.startswith("-"):
            return os.path.basename(a)
    return comm


def describe(name):
    text = t("proc." + name)
    return text if text != "proc." + name else t("memdetails.unknown_proc")


def scan():
    groups = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                st = f.read()
        except OSError:
            continue
        name = ""
        for ln in st.split("\n"):
            if ln.startswith("Name:"):
                name = ln[5:].strip()
                break
        rss = kib_field(st, "VmRSS:")
        if not name or rss is None:
            continue
        if name.startswith("python"):
            name = script_name(pid, name)
        if name == "claude" or VERSION_COMM.match(name):
            name = claude_name(pid, name)
        pss = rss
        try:
            with open(f"/proc/{pid}/smaps_rollup") as f:
                v = kib_field(f.read(), "Pss:")
            if v is not None:
                pss = v
        except OSError:
            pass
        if pss < MIN_KIB:
            continue
        n, total = groups.get(name, (0, 0))
        groups[name] = (n + 1, total + pss)
    rows = [(k, n, kib) for k, (n, kib) in groups.items()]
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:MAX_ROWS]


class Details(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("memdetails.title"))
        self.set_default_size(460, 560)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(10)
        self.add(box)

        self.summary = Gtk.Label(xalign=0)
        box.pack_start(self.summary, False, False, 0)

        self.store = Gtk.ListStore(str, str, str, str, float, str)
        view = Gtk.TreeView(model=self.store)
        view.set_headers_visible(True)
        for i, (key, align) in enumerate([("memdetails.col_process", 0), ("memdetails.col_count", 1),
                                           ("memdetails.col_memory", 1), ("memdetails.col_share", 1)]):
            r = Gtk.CellRendererText(xalign=align)
            col = Gtk.TreeViewColumn(t(key), r, text=i if i != 3 else 3)
            col.set_expand(i == 0)
            if i == 3:
                col.set_sort_column_id(4)
            elif i == 2:
                col.set_sort_column_id(4)
            view.append_column(col)
        view.set_tooltip_column(5)
        self.view = view
        sw = Gtk.ScrolledWindow()
        self.adj = sw.get_vadjustment()
        sw.add(view)
        box.pack_start(sw, True, True, 0)

        self.iters = {}
        self.store.set_sort_column_id(4, Gtk.SortType.DESCENDING)
        self.busy = False
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_S, self.refresh)

    def refresh(self):
        if not self.busy:
            self.busy = True
            threading.Thread(target=self._work, daemon=True).start()
        return True

    def _work(self):
        try:
            rows, mi = scan(), meminfo()
        except Exception:
            rows, mi = [], None
        GLib.idle_add(self._show, rows, mi)

    def _show(self, rows, mi):
        self.busy = False
        if mi:
            total, used = mi["MemTotal"], used_kib(mi)
            gib = 1048576
            text = t("memdetails.ram").format(used=used / gib, total=total / gib)
            if mi.get("SwapTotal"):
                text += "    " + t("memdetails.swap").format(
                    used=(mi["SwapTotal"] - mi["SwapFree"]) / gib, total=mi["SwapTotal"] / gib)
            self.summary.set_text(text)
            total_kib = total
            self.set_icon(tank_icon(min(1, used / total)))
        else:
            total_kib = 0
        # update rows in place: clearing and refilling the store makes the list flicker and jump
        seen = set()
        for name, n, kib in rows:
            mb = kib / 1024
            mem = f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.0f} MB"
            share = f"{kib / total_kib * 100:.1f} %" if total_kib else ""
            vals = [name, str(n), mem, share, float(kib), describe(name)]
            seen.add(name)
            it = self.iters.get(name)
            if it is None:
                self.iters[name] = self.store.append(vals)
            else:
                for col, v in enumerate(vals):
                    if self.store[it][col] != v:
                        self.store[it][col] = v
        for name in [n for n in self.iters if n not in seen]:
            self.store.remove(self.iters.pop(name))
        return False


win = Details()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
