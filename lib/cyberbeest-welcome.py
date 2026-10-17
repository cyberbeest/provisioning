#!/usr/bin/env python3
"""Welcome window at login: dark, website-style tour in scrollable sections --
voice control, emergency security, the panel (hover an explanation and the icon lights
up in the real panel), and a few "Did you know?" tips from the Factbook (hints.json,
built by 72-welcome-screen.sh). "Close" shows it again next login, "Don't show again"
writes DISMISS_FILE and it stays away. Run with --force to show it regardless. Test flags: --scroll=0..1 (start scrolled),
--hover=KEY (start with that panel row highlighted, e.g. --hover=memory)."""

import json
import os
import random
import socket
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo
import cairo

from i18n import t, _LOCALE

HINTS = os.path.expanduser("~/.local/share/cyberbeest/hints.json")
DISMISS_FILE = os.path.expanduser("~/.config/cyberbeest/welcome-dismissed")
ICON = os.path.expanduser("~/.local/share/cyberbeest/icons/Cyberbeest-black.png")
FACTS_SHOWN = 1
SEEN_FILE = os.path.expanduser("~/.local/state/cyberbeest/welcome-facts-seen.json")
START_DELAY_S = 5   # let the desktop finish drawing first
TEAL = (0x59 / 255, 0xD6 / 255, 0xB8 / 255)

CSS = b"""
window, .page { background-color: #06080b; color: #e7eaf0; }
scrolledwindow, viewport { background-color: #06080b; }
scrollbar { background-color: #0e1218; }
scrollbar slider { background-color: #2a3442; border-radius: 6px; min-width: 10px; min-height: 40px; }
scrollbar slider:hover { background-color: #59d6b8; }
.wordmark { font-weight: 800; font-size: 30px; color: #e7eaf0; }
.wordmark-b { font-weight: 800; font-size: 30px; color: #59d6b8; }
.hero-sub { color: #8b95a7; font-size: 15px; }
.eyebrow { color: #59d6b8; font-size: 12px; font-weight: 700; letter-spacing: 2px; }
.s-title { font-size: 26px; font-weight: 800; color: #e7eaf0; }
.s-lead { font-size: 16px; color: #e7eaf0; }
.dim { color: #8b95a7; font-size: 13px; }
.card { background-color: #10151d; border: 1px solid #1d2530; border-radius: 14px; padding: 18px; }
.card-title { font-size: 16px; font-weight: 700; color: #e7eaf0; }
.card-text { font-size: 13px; color: #8b95a7; }
.keycap { background-color: #1a222d; border: 1px solid #2c3746; border-bottom: 4px solid #2c3746;
          border-bottom-color: #2c3746; background-image: none; box-shadow: none;
          border-radius: 10px; padding: 8px 18px; font-size: 22px; font-weight: 800;
          color: #59d6b8; }
.badge { background-color: rgba(89,214,184,0.14); border-radius: 12px; padding: 8px 4px;
         font-size: 15px; font-weight: 800; color: #59d6b8; min-width: 64px; }
.private { background-color: rgba(89,214,184,0.14); border-radius: 10px; padding: 10px 14px;
           color: #59d6b8; font-size: 13px; font-weight: 600; }
.row { background-color: #10151d; border: 1px solid #1d2530; border-radius: 10px; padding: 9px 14px; }
.row:hover { background-color: #15202a; border-color: #59d6b8; }
.row-name { font-weight: 700; font-size: 14px; color: #e7eaf0; }
.link-button { background-image: none; background-color: #1a222d; color: #e7eaf0;
               border: 1px solid #2c3746; border-radius: 8px; padding: 7px 16px; box-shadow: none; }
.link-button:hover { border-color: #59d6b8; color: #59d6b8; }
.footer { background-color: #0e1218; border-top: 1px solid #1d2530; padding: 12px 20px; }
.footer button { background-image: none; background-color: #1a222d; color: #e7eaf0;
                 border: 1px solid #2c3746; border-radius: 8px; padding: 7px 16px; box-shadow: none; }
.footer button:hover { border-color: #59d6b8; }
.footer button.primary { background-color: #59d6b8; color: #06080b; border-color: #59d6b8; font-weight: 700; }
.fact-big { font-size: 18px; font-weight: 400; color: #e7eaf0; padding: 14px 8px; }
.frame-a { background-color: #59d6b8; }
.frame-b { background-color: #1f7a67; }
"""


def load_tips():
    try:
        with open(HINTS, encoding="utf-8") as f:
            hints = json.load(f)
    except (OSError, ValueError):
        return []
    lang = _LOCALE if _LOCALE in ("en", "de") else "en"
    return [x for x in (h.get(lang) or h.get("en") for h in hints) if x]


class FactDeck:
    """Hands out facts in random order, none twice until all have been shown. The facts
    seen so far are remembered across logins in SEEN_FILE."""

    def __init__(self, facts):
        self.facts = facts
        try:
            with open(SEEN_FILE, encoding="utf-8") as f:
                self.seen = set(json.load(f))
        except (OSError, ValueError):
            self.seen = set()
        self.seen &= set(facts)

    def draw(self, n):
        out = []
        while len(out) < n and self.facts:
            fresh = [x for x in self.facts if x not in self.seen and x not in out]
            if not fresh:
                if len(out) >= len(self.facts):
                    break
                self.seen = set(out)   # exhausted: start a new round without repeating this page
                continue
            pick = random.choice(fresh)
            out.append(pick)
            self.seen.add(pick)
        try:
            os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
            with open(SEEN_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(self.seen), f)
        except OSError:
            pass
        return out


def dismiss(_button=None):
    os.makedirs(os.path.dirname(DISMISS_FILE), exist_ok=True)
    with open(DISMISS_FILE, "w"):
        pass
    try:   # tell them how to get it back: by voice, which is the point of the first section
        subprocess.run(["notify-send", "-i", ICON, t("welcome.hidden_title"), t("welcome.hidden_body")],
                       timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    Gtk.main_quit()


# ---------------------------------------------------------------- the panel

# (key, in panel order) -> shown when an item of the real panel matches, or always when
# there is no gopanel to ask.
STATIC_KEYS = ["menu", "taskbar", "volume", "battery", "clock"]


def panel_key(it):
    kind = it.get("kind")
    name = (it.get("name") or "").lower()
    title = (it.get("title") or "").lower()
    if kind == "whisker":
        return "menu"
    if kind == "launcher":
        return "launchers"
    if kind == "taskbar":
        return "taskbar"
    if kind == "tray":
        if "dictate" in name:
            return "dictate"
        if "blueman" in name or "bluetooth" in name:
            return "bluetooth"
        return None
    if kind == "volume":
        return "volume"
    if kind == "helper":
        return {"kitt": "cpu", "io-scanner": "disk", "network-scanner": "network",
                "mem-liquid": "memory", "wattage-panel": "wattage"}.get(name)
    if kind == "power":
        return "battery"
    if kind == "genmon":
        for word, key in (("autolock", "status"), ("clipboard", "clipboard"), ("vpn", "vpn"),
                          ("connections", "connections"), ("mic", "mic")):
            if word in title:
                return key
        return None
    if kind == "clock":
        return "clock"
    return None


def shipped(it):
    """Whether this panel item is on a provisioned machine (the dev machine has more)."""
    kind = it.get("kind")
    title = (it.get("title") or "").lower()
    name = (it.get("name") or "").lower()
    if kind == "launcher":
        return "claude" not in title and "terminal" not in title
    if kind == "xtray":
        return False
    if kind == "helper":
        return name in ("kitt", "mem-liquid", "wattage-panel")
    if kind == "genmon":
        return any(w in title for w in ("autolock", "clipboard", "vpn", "connections"))
    return True


def compact(pix, snap):
    """Cut the dev-only items out of the panel snapshot. Returns (pixbuf, snap with the
    kept items only, x-map from original to compact coordinates)."""
    cut = sorted((it["x"], it["x"] + it["w"]) for it in snap["items"] if not shipped(it))
    kept = []
    pos = 0
    for lo, hi in cut:
        if lo > pos:
            kept.append((pos, lo))
        pos = max(pos, hi)
    if pos < pix.get_width():
        kept.append((pos, pix.get_width()))
    total = sum(b - a for a, b in kept)
    out = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, pix.get_has_alpha(), 8, total, pix.get_height())
    shifts = []
    dst = 0
    for a, b in kept:
        pix.copy_area(a, 0, b - a, pix.get_height(), out, dst, 0)
        shifts.append((a, b, a - dst))
        dst += b - a

    def tomap(x):
        for a, b, d in shifts:
            if a <= x < b:
                return x - d
        return x - sum(h - l for l, h in cut if h <= x)

    tb = next((it for it in snap["items"] if it.get("kind") == "taskbar"), None)
    if tb:
        out = draw_taskbar(out, tomap(tb["x"]), tb["w"])
    return out, tomap


def draw_taskbar(pix, x, w):
    """Replace the taskbar area with a single button for this window, as a fresh machine
    would show it."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pix.get_width(), pix.get_height())
    cr = cairo.Context(surf)
    Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
    cr.paint()
    h = pix.get_height()
    px = pix.get_pixels()
    stride, nch = pix.get_rowstride(), pix.get_n_channels()
    off = 1 * stride + (x + 2) * nch   # the taskbar's own background, top-left corner
    bg = (px[off] / 255, px[off + 1] / 255, px[off + 2] / 255)
    light = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2] > 0.5
    ink = 0.05 if light else 0.95   # text follows the panel colour, as the real panel's does
    cr.set_source_rgb(*bg)
    cr.rectangle(x, 0, w, h)
    cr.fill()
    bw = min(w, 300)
    cr.set_source_rgba(ink, ink, ink, 0.14)
    cr.rectangle(x + 2, 3, bw - 4, h - 6)
    cr.fill()
    try:
        icon = GdkPixbuf.Pixbuf.new_from_file_at_size(ICON, h - 14, h - 14)
        Gdk.cairo_set_source_pixbuf(cr, icon, x + 9, 7)
        cr.paint()
    except GLib.Error:
        pass
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(Pango.FontDescription("Sans %d" % max(8, h // 3)))
    lay.set_text(t("welcome.title"), -1)
    lay.set_width((bw - h - 8) * Pango.SCALE)
    lay.set_ellipsize(Pango.EllipsizeMode.END)
    _, lh = lay.get_pixel_size()
    cr.set_source_rgb(ink, ink, ink)
    cr.move_to(x + h + 2, (h - lh) / 2)
    PangoCairo.show_layout(cr, lay)
    return Gdk.pixbuf_get_from_surface(surf, 0, 0, pix.get_width(), pix.get_height())


def fetch_panel():
    """Layout snapshot from gopanel's control socket, or None (XFCE panel, jailed, ...)."""
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "gopanel.sock")
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect(path)
        s.sendall(b"items\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        return json.loads(buf)
    except (OSError, ValueError):
        return None


def panel_entries(snap):
    """[(key, [(x, w)])] in panel order; neighbouring launchers merge into one span."""
    if not snap:
        return [(k, []) for k in STATIC_KEYS]
    groups = {}
    for it in snap["items"]:
        key = panel_key(it)
        if key and shipped(it):
            groups.setdefault(key, []).append((it["x"], it["w"]))
    out = []
    for key, rects in groups.items():
        lo = min(x for x, _ in rects)
        hi = max(x + w for x, w in rects)
        out.append((key, [(lo, hi - lo)]))
    out.sort(key=lambda e: e[1][0][0])
    return out


class Highlighter:
    """Draws a pulsing teal frame around panel items: four thin pop-up windows (works
    without a compositor) plus the same rectangle on the in-window strip."""

    def __init__(self, snap, strip):
        self.snap = snap
        self.strip = strip
        self.rects = []
        self.phase = False
        self.frames = []
        for _ in range(4):
            w = Gtk.Window(type=Gtk.WindowType.POPUP)
            w.set_decorated(False)
            w.set_accept_focus(False)
            w.set_skip_taskbar_hint(True)
            w.set_keep_above(True)
            w.get_style_context().add_class("frame-a")
            w.set_size_request(1, 1)
            self.frames.append(w)
        GLib.timeout_add(450, self._pulse)

    def _pulse(self):
        self.phase = not self.phase
        for w in self.frames:
            ctx = w.get_style_context()
            ctx.remove_class("frame-b" if not self.phase else "frame-a")
            ctx.add_class("frame-a" if not self.phase else "frame-b")
        if self.strip:
            self.strip.phase = self.phase
            self.strip.queue_draw()
        return True

    def show(self, rects, strip_rects=None):
        self.rects = rects
        if self.strip:
            self.strip.rects = rects if strip_rects is None else strip_rects
            self.strip.queue_draw()
        if not rects or not self.snap:
            self.hide_frames()
            return
        px, py, ph = self.snap["x"], self.snap["y"], self.snap["h"]
        x, w = rects[0]
        th = 3
        geo = [(px + x, py, w, th), (px + x, py + ph - th, w, th),
               (px + x, py, th, ph), (px + x + w - th, py, th, ph)]
        for win, (gx, gy, gw, gh) in zip(self.frames, geo):
            win.resize(max(gw, 1), max(gh, 1))
            win.move(gx, gy)
            win.show()

    def hide_frames(self):
        for w in self.frames:
            w.hide()

    def clear(self):
        self.show([])


class Strip(Gtk.DrawingArea):
    """Snapshot of the real panel with the highlight on it. Folded into two rows so the
    icons stay big enough to recognise."""

    GAP = 8

    def __init__(self, pixbuf, snap):
        super().__init__()
        self.pix, self.snap = pixbuf, snap
        self.rects, self.phase = [], False
        self.half = (pixbuf.get_width() + 1) // 2
        self.set_size_request(400, 2 * int(pixbuf.get_height() * 800 / self.half) + self.GAP)
        self.on_hover = None   # callback(source_x or None)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self.on_draw)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("leave-notify-event", lambda *_: self.on_hover and self.on_hover(None))

    def on_motion(self, _w, ev):
        scale = self.get_allocated_width() / self.half
        rowh = self.pix.get_height() * scale
        row = 1 if ev.y >= rowh + self.GAP / 2 else 0
        if self.on_hover:
            self.on_hover(row * self.half + ev.x / scale)
        return False

    def on_draw(self, _w, cr):
        width = self.get_allocated_width()
        scale = width / self.half
        rowh = self.pix.get_height() * scale
        colour = TEAL if not self.phase else (0.12, 0.48, 0.40)
        for r in (0, 1):
            cr.save()
            cr.translate(0, r * (rowh + self.GAP))
            cr.rectangle(0, 0, width, rowh)
            cr.clip()
            cr.save()
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, self.pix, -r * self.half, 0)
            cr.get_source().set_filter(cairo.FILTER_BEST)
            cr.paint()
            cr.restore()
            lo, hi = r * self.half, (r + 1) * self.half
            for x, w in self.rects:
                x0, x1 = max(x, lo), min(x + w, hi)
                if x1 > x0:
                    cr.set_source_rgb(*colour)
                    cr.set_line_width(2.5)
                    cr.rectangle((x0 - lo) * scale + 1.5, 1.5, (x1 - x0) * scale - 3, rowh - 3)
                    cr.stroke()
            cr.restore()
        return False


# ---------------------------------------------------------------- widgets


def label(text, css, wrap=True, xalign=0.0, width=-1):
    lab = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
    lab.set_line_wrap_mode(2)  # word-char
    if width > 0:
        lab.set_max_width_chars(width)
    lab.get_style_context().add_class(css)
    return lab


def windows_logo(size=22):
    """The Windows logo as printed on a Cyberbeest key: four panes forming a trapezoid
    that is taller on the right side. Drawn in the accent colour."""
    da = Gtk.DrawingArea()
    da.set_size_request(size, size)
    panes = (  # (x, y) corners in 0..1, top-left / bottom-left / top-right / bottom-right
        ((0.00, 0.13), (0.45, 0.07), (0.45, 0.47), (0.00, 0.47)),
        ((0.00, 0.53), (0.45, 0.53), (0.45, 0.93), (0.00, 0.87)),
        ((0.55, 0.06), (1.00, 0.00), (1.00, 0.47), (0.55, 0.47)),
        ((0.55, 0.53), (1.00, 0.53), (1.00, 1.00), (0.55, 0.94)),
    )

    def draw(_w, cr):
        cr.set_source_rgb(*TEAL)
        for pane in panes:
            cr.move_to(pane[0][0] * size, pane[0][1] * size)
            for x, y in pane[1:]:
                cr.line_to(x * size, y * size)
            cr.close_path()
        cr.fill()
        return False

    da.connect("draw", draw)
    return da


def keycap(text=None, logo=False):
    cap = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    if logo:
        inner = windows_logo()
        inner.set_margin_top(6)
        inner.set_margin_bottom(6)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        cap.pack_start(inner, False, False, 0)
    else:
        cap.pack_start(Gtk.Label(label=text), False, False, 0)
    cap.get_style_context().add_class("keycap")
    box = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.START)
    box.pack_start(cap, False, False, 0)
    return box


def card(child_box):
    child_box.get_style_context().add_class("card")
    return child_box


def section_header(box, eyebrow, title, lead=None):
    box.pack_start(label(eyebrow, "eyebrow"), False, False, 0)
    box.pack_start(label(title, "s-title"), False, False, 0)
    if lead:
        box.pack_start(label(lead, "s-lead"), False, False, 4)


def logo_widget():
    box = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER)
    try:
        pix = GdkPixbuf.Pixbuf.new_from_file_at_size(ICON, 84, 84)
        surf = Gdk.cairo_surface_create_from_pixbuf(pix, 1, None)
        da = Gtk.DrawingArea()
        da.set_size_request(84, 84)

        def draw(_w, cr):
            cr.set_source_rgb(*TEAL)
            cr.mask_surface(surf, 0, 0)
            return False

        da.connect("draw", draw)
        box.pack_start(da, False, False, 0)
    except GLib.Error:
        pass
    word = Gtk.Box(spacing=0, valign=Gtk.Align.CENTER)
    head = t("welcome.heading").upper()
    pre, _, post = head.partition("CYBERBEEST")
    word.pack_start(label(pre + "CYBER" if _ else head, "wordmark", wrap=False), False, False, 0)
    if _:
        word.pack_start(label("BEEST" + post, "wordmark-b", wrap=False), False, False, 0)
    box.pack_start(word, False, False, 0)
    return box


def build_voice():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    section_header(box, t("welcome.s1_eyebrow"), t("welcome.s1_title"), t("welcome.s1_lead"))
    grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
    for col, (cap, title, text) in enumerate((
            ("F9", t("welcome.f9_title"), t("welcome.f9_text")),
            (None, t("welcome.win_title"), t("welcome.win_text")))):
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        c.pack_start(keycap(cap, logo=cap is None), False, False, 0)
        c.pack_start(label(title, "card-title"), False, False, 0)
        c.pack_start(label(text, "card-text"), False, False, 0)
        grid.attach(card(c), col, 0, 1, 1)
    box.pack_start(grid, False, False, 6)
    return box


def build_security():
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    section_header(box, t("welcome.s2_eyebrow"), t("welcome.s2_title"))
    grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True)
    for i, k in enumerate(("lock", "off", "lid", "4x", "hold")):
        c = Gtk.Box(spacing=14)
        badge = label(t("welcome.sec_%s_badge" % k), "badge", wrap=False, xalign=0.5)
        bb = Gtk.Box(valign=Gtk.Align.START)
        bb.pack_start(badge, False, False, 0)
        c.pack_start(bb, False, False, 0)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        txt.pack_start(label(t("welcome.sec_%s_title" % k), "card-title"), False, False, 0)
        txt.pack_start(label(t("welcome.sec_%s_text" % k), "card-text"), False, False, 0)
        c.pack_start(txt, True, True, 0)
        grid.attach(card(c), i % 2, i // 2, 2 if i == 4 else 1, 1)
    box.pack_start(grid, False, False, 6)
    box.pack_start(label(t("welcome.sec_note"), "dim"), False, False, 2)
    return box


class PanelSection:
    def __init__(self, win):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.snap = fetch_panel()
        lead = t("welcome.s3_lead") if self.snap else t("welcome.s3_nohl")
        section_header(self.box, t("welcome.s3_eyebrow"), t("welcome.s3_title"), lead)
        self.strip = None
        if self.snap:
            try:
                root = Gdk.get_default_root_window()
                pix = Gdk.pixbuf_get_from_window(root, self.snap["x"], self.snap["y"],
                                                 self.snap["w"], self.snap["h"])
                if pix:
                    pix, self.tomap = compact(pix, self.snap)
                    self.strip = Strip(pix, self.snap)
                    frame = Gtk.Box()
                    frame.get_style_context().add_class("card")
                    frame.pack_start(self.strip, True, True, 0)
                    self.box.pack_start(frame, False, False, 4)
            except Exception:
                self.strip = None
        self.hl = Highlighter(self.snap, self.strip)
        win.connect("destroy", lambda _w: [f.destroy() for f in self.hl.frames])
        win.connect("focus-out-event", lambda *_: self.hl.clear())
        self.entries = dict(panel_entries(self.snap))
        if self.strip:   # the strip is drawn without the dev-only items, so it has its own x axis
            self.strip_x = {k: [(self.tomap(x), w) for x, w in r] for k, r in self.entries.items()}
            self.entries = {k: r for k, r in self.entries.items() if k in self.strip_x}
        if self.strip:
            self.build_detail()
        else:
            for key, rects in self.entries.items():
                self.box.pack_start(self.row(key, rects), False, False, 0)

    def build_detail(self):
        """One explanation box for the icon under the pointer in the snapshot."""
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        inner.get_style_context().add_class("card")
        inner.set_size_request(-1, 92)
        self.name = label("", "card-title")
        self.text = label(t("welcome.s3_hint"), "card-text")
        inner.pack_start(self.name, False, False, 0)
        inner.pack_start(self.text, False, False, 0)
        self.box.pack_start(inner, False, False, 0)
        self.current = None
        self.strip.on_hover = self.hover

    def hover(self, x):
        key = None
        if x is not None:
            for k, rects in self.strip_x.items():
                if any(rx <= x < rx + rw for rx, rw in rects):
                    key = k
                    break
        if key == self.current:
            return
        self.current = key
        if key:
            self.name.set_text(t("welcome.p_%s_n" % key))
            self.text.set_text(t("welcome.p_%s" % key))
            self.hl.show(self.entries[key], self.strip_x[key])
        else:
            self.name.set_text("")
            self.text.set_text(t("welcome.s3_hint"))
            self.hl.clear()

    def row(self, key, rects):
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.get_style_context().add_class("row")
        inner.pack_start(label(t("welcome.p_%s_n" % key), "row-name"), False, False, 0)
        inner.pack_start(label(t("welcome.p_%s" % key), "card-text"), False, False, 0)
        return inner


def factbook_launch():
    """Launcher for the full Factbook app, or None when it is not installed."""
    try:
        info = Gio.DesktopAppInfo.new("factbook.desktop")   # raises TypeError when missing
    except TypeError:
        return None
    return (lambda _b: info.launch([], None)) if info else None


def build_facts(deck):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    section_header(box, t("welcome.s4_eyebrow"), t("welcome.s4_title"))
    rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.pack_start(rows, False, False, 4)

    def reload(_b=None):
        for child in rows.get_children():
            rows.remove(child)
        for fact in deck.draw(FACTS_SHOWN):
            row = Gtk.Box()
            row.get_style_context().add_class("row")
            lab = label(fact, "fact-big", xalign=0.5)
            lab.set_justify(Gtk.Justification.CENTER)
            row.pack_start(lab, True, True, 0)
            rows.pack_start(row, False, False, 0)
        rows.show_all()

    reload()
    buttons = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
    more = Gtk.Button(label=t("welcome.facts_more"))
    more.get_style_context().add_class("link-button")
    more.connect("clicked", reload)
    buttons.pack_start(more, False, False, 0)
    launch = factbook_launch()
    if launch:
        book = Gtk.Button(label=t("welcome.facts_open"))
        book.get_style_context().add_class("link-button")
        book.connect("clicked", launch)
        buttons.pack_start(book, False, False, 0)
    box.pack_start(buttons, False, False, 4)
    return box


def main():
    force = "--force" in sys.argv
    if not force and os.path.exists(DISMISS_FILE):
        return
    facts = load_tips()
    if not force:
        time.sleep(START_DELAY_S)

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title=t("welcome.title"))
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_default_size(960, 660)
    if os.path.exists(ICON):
        win.set_icon_from_file(ICON)
    win.connect("destroy", Gtk.main_quit)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    win.add(outer)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
    scroll.set_overlay_scrolling(False)
    outer.pack_start(scroll, True, True, 0)

    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=44)
    page.get_style_context().add_class("page")
    for side in ("start", "end"):
        getattr(page, "set_margin_" + side)(40)
    page.set_margin_top(30)
    page.set_margin_bottom(30)
    scroll.add(page)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    hero.pack_start(logo_widget(), False, False, 0)
    page.pack_start(hero, False, False, 0)

    page.pack_start(build_voice(), False, False, 0)
    page.pack_start(build_security(), False, False, 0)
    panel = PanelSection(win)
    page.pack_start(panel.box, False, False, 0)
    if facts:
        page.pack_start(build_facts(FactDeck(facts)), False, False, 0)

    footer = Gtk.Box(spacing=8, halign=Gtk.Align.FILL)
    footer.get_style_context().add_class("footer")
    never = Gtk.Button(label=t("welcome.never"))
    never.connect("clicked", dismiss)
    close = Gtk.Button(label=t("welcome.close"))
    close.get_style_context().add_class("primary")
    close.connect("clicked", lambda _b: Gtk.main_quit())
    footer.pack_end(close, False, False, 0)
    footer.pack_end(never, False, False, 0)
    outer.pack_start(footer, False, False, 0)

    win.show_all()
    # Focus would otherwise land on a button far down the page and scroll to it.
    close.grab_focus()
    scroll.get_vadjustment().set_value(0)
    GLib.idle_add(lambda: scroll.get_vadjustment().set_value(0) or False)
    arg = {a.split("=")[0]: a.split("=")[-1] for a in sys.argv[1:] if "=" in a}
    if "--scroll" in arg:
        def do_scroll():
            adj = scroll.get_vadjustment()
            adj.set_value(float(arg["--scroll"]) * (adj.get_upper() - adj.get_page_size()))
        GLib.timeout_add(400, lambda: do_scroll() or False)
    if "--hover" in arg:
        GLib.timeout_add(600, lambda: panel.hover(panel.strip_x[arg["--hover"]][0][0] + 1) or False)
    Gtk.main()


if __name__ == "__main__":
    main()
