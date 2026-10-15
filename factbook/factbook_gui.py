#!/usr/bin/env python3
"""Factbook: every fact about Cyberbeest in one list, by topic, searchable (the facts Butler answers from).

Reads facts/*.json next to this file, or the directory given as the first argument.
Search box: Butler's matcher ranks the facts by meaning first, so "is my disk safe" finds the encryption facts
without sharing a word with them; facts that contain all the typed words (either language) follow after them.
Ctrl+F or / focuses the search, Esc clears it, then closes.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

HERE = Path(__file__).resolve().parent
LANG = "de" if os.environ.get("LC_ALL", os.environ.get("LC_MESSAGES", os.environ.get("LANG", ""))).startswith("de") else "en"
ASK_MIN = 0.35   # Butler's matcher: how similar a fact must be to be listed as an answer
ASK_K = 12
T = {
    "title": {"en": "Factbook", "de": "Faktenbuch"},
    "search": {"en": "Ask or search the facts", "de": "Fakten fragen oder durchsuchen"},
    "all": {"en": "All facts", "de": "Alle Fakten"},
    "none": {"en": "No fact matches.", "de": "Kein Fakt passt."},
    "count": {"en": "{n} of {total} facts", "de": "{n} von {total} Fakten"},
    "manual": {"en": "Manual section {s}", "de": "Handbuch, Abschnitt {s}"},
    "asking": {"en": "Butler is thinking…", "de": "Butler überlegt …"},
    "indexing": {"en": "Butler is updating its knowledge…", "de": "Butler aktualisiert sein Wissen …"},
}
CSS = b"""
.topic { font-weight: bold; font-size: 15px; padding: 14px 12px 4px 12px; }
.fact { padding: 8px 12px; }
.meta { opacity: 0.6; font-size: 12px; }
.side row { padding: 6px 10px; }
"""


def tr(key, **kw):
    return T[key][LANG].format(**kw)


def load(facts_dir):
    """[(topic, [fact dict, ...])] in file order; a broken file is skipped, not fatal."""
    topics = []
    for f in sorted(Path(facts_dir).glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            topics.append((d["topic"][LANG], [x for x in d["facts"] if x.get(LANG) and x.get("id")]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return topics


class Butler:
    """Butler's matcher as a child process (JSON lines, see butler_server.py), started on the first question."""

    def __init__(self, on_status=None):
        self.on_status = on_status   # called (main thread) with "indexing" or "ready"
        self.path = shutil.which("butler-server") or str(Path.home() / ".local/bin/butler-server")
        self.proc, self.seq, self.callbacks = None, 0, {}

    def available(self):
        return os.access(self.path, os.X_OK)

    def ask(self, text, callback):
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen([self.path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        self.seq += 1
        self.callbacks[self.seq] = callback
        # the server only reads once its model is loaded, so this line waits in the pipe until then
        self.proc.stdin.write(json.dumps({"op": "match", "seq": self.seq, "text": text, "k": ASK_K, "fact_min": ASK_MIN}) + "\n")
        self.proc.stdin.flush()

    def _read(self, proc):
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if self.on_status and ("indexing" in msg or msg.get("ready")):
                GLib.idle_add(self.on_status, "indexing" if "indexing" in msg else "ready")
            if "hits" in msg and msg.get("seq") in self.callbacks:
                GLib.idle_add(self.callbacks.pop(msg["seq"]), msg["hits"])

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write('{"op":"quit"}\n')
                self.proc.stdin.flush()
            except OSError:
                pass
            self.proc.terminate()


class Window(Gtk.Window):
    def __init__(self, topics):
        super().__init__(title=tr("title"))
        self.set_default_size(960, 660)
        self.set_icon_name("accessories-dictionary")
        self.total = sum(len(f) for _, f in topics)
        self.topic = None      # selected topic name, None = all
        self.asked = ""
        self.waiting = False   # a question is out and unanswered
        self.rank = []         # fact ids Butler matched to the current search, best first
        self.butler = Butler(self.on_status)
        self.status = ""
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(outer)
        # topics
        side_sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_width=250)
        self.side = Gtk.ListBox()
        self.side.get_style_context().add_class("side")
        self.side.connect("row-selected", self.on_topic)
        side_sw.add(self.side)
        side_sw.set_size_request(230, -1)
        outer.pack_start(side_sw, False, False, 0)
        outer.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        self.add_topic(None, tr("all"), self.total)
        for name, facts in topics:
            self.add_topic(name, name, len(facts))

        # search + facts
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.pack_start(box, True, True, 0)
        bar = Gtk.Box(spacing=8, margin=10)
        self.search = Gtk.SearchEntry(placeholder_text=tr("search"))
        self.search.connect("search-changed", self.on_text)
        self.search.connect("activate", self.ask_now)   # Enter: ask now, without waiting for the pause
        bar.pack_start(self.search, True, True, 0)
        self.timer = None
        box.pack_start(bar, False, False, 0)
        self.count = Gtk.Label(xalign=0, margin_start=12, margin_bottom=6)
        self.count.get_style_context().add_class("meta")
        box.pack_start(self.count, False, False, 0)

        sw = Gtk.ScrolledWindow()
        box.pack_start(sw, True, True, 0)
        self.empty = Gtk.Label(label=tr("none"), margin=24)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.set_header_func(self.header)
        self.list.set_filter_func(self.visible)
        self.list.set_sort_func(self.order)
        self.list.set_placeholder(self.empty)
        self.empty.show()
        sw.add(self.list)
        self.rows = {}
        for n, (topic, facts) in enumerate(topics):
            for k, fact in enumerate(facts):
                row = self.row(topic, fact, n * 1000 + k)
                self.rows[fact["id"]] = row
                self.list.add(row)
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", lambda *_: self.butler.stop())
        self.set_meta(False)
        self.side.select_row(self.side.get_row_at_index(0))

    def add_topic(self, key, label, n):
        row = Gtk.ListBoxRow()
        row.key = key
        box = Gtk.Box(spacing=6)
        box.pack_start(Gtk.Label(label=label, xalign=0, wrap=True, max_width_chars=26), True, True, 0)
        cnt = Gtk.Label(label=str(n))
        cnt.get_style_context().add_class("meta")
        box.pack_end(cnt, False, False, 0)
        row.add(box)
        self.side.add(row)

    def row(self, topic, fact, pos):
        row = Gtk.ListBoxRow(activatable=False)
        row.topic, row.pos, row.fid, row.manual = topic, pos, fact["id"], fact.get("manual")
        row.text = " ".join(fact.get(l, "") for l in ("en", "de")).lower()   # both languages are searchable
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("fact")
        lab = Gtk.Label(label=fact[LANG], xalign=0, wrap=True, selectable=True)
        lab.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.pack_start(lab, False, False, 0)
        row.meta_label = Gtk.Label(xalign=0)   # filled by set_meta(): manual section, plus the topic in Butler's ranking
        row.meta_label.get_style_context().add_class("meta")
        box.pack_start(row.meta_label, False, False, 0)
        row.add(box)
        return row

    # --- what is shown -------------------------------------------------------
    def query(self):
        return self.search.get_text().strip()

    def order(self, a, b):
        """Butler's matches in his order, then the text matches (and, with no search, every fact) in file order."""
        ra = self.rank.index(a.fid) if a.fid in self.rank else len(self.rank)
        rb = self.rank.index(b.fid) if b.fid in self.rank else len(self.rank)
        return (ra - rb) or (a.pos - b.pos)

    def header(self, row, before):
        if not self.query() and (before is None or before.topic != row.topic):
            lab = Gtk.Label(label=row.topic, xalign=0)
            lab.get_style_context().add_class("topic")
            row.set_header(lab)
        else:
            row.set_header(None)

    def visible(self, row):
        if self.topic is not None and row.topic != self.topic:
            return False
        q = self.query().lower()
        if not q or row.fid in self.rank:
            return True
        return all(w in row.text for w in q.split())

    def refilter(self):
        self.list.invalidate_filter()
        self.list.invalidate_sort()
        self.list.invalidate_headers()
        self.set_meta(bool(self.query()))
        n = sum(1 for r in self.list.get_children() if self.visible(r))
        self.count.set_text(tr("count", n=n, total=self.total))

    def on_topic(self, _box, row):
        if row is None:
            return
        self.topic = row.key
        self.refilter()

    def on_text(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
        if len(self.query()) < 3:
            self.rank = []
        else:   # the text matches show at once; Butler's come in front when he has answered
            self.timer = GLib.timeout_add(400, self.ask)
        self.refilter()

    def set_meta(self, with_topic):
        for r in self.rows.values():
            parts = [r.topic] if with_topic else []
            if r.manual:
                parts.append(tr("manual", s=r.manual))
            r.meta_label.set_text("  ·  ".join(parts))

    # --- Butler --------------------------------------------------------------
    def on_status(self, what):
        self.status = what
        if self.waiting:
            self.count.set_text(tr("indexing") if what == "indexing" else tr("asking"))
        return False

    def ask_now(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
        self.ask()

    def ask(self):
        self.timer = None
        text = self.query()
        if len(text) < 3 or not self.butler.available():
            return False
        self.asked = text
        self.waiting = True
        self.count.set_text(tr("indexing") if self.status == "indexing" else tr("asking"))
        try:
            self.butler.ask(text, self.on_answer)
        except OSError:
            self.butler.path = ""   # not usable: text matches only
        return False

    def on_answer(self, hits):
        self.waiting = False
        if self.asked != self.query():
            return False   # typed on meanwhile
        self.rank = []
        for h in hits:
            if h.get("kind") == "fact" and h["id"][5:] in self.rows:
                self.rank.append(h["id"][5:])
        self.refilter()
        return False

    def on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            if self.search.get_text():
                self.search.set_text("")
            else:
                self.destroy()
            return True
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if (ctrl and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F)) or (ev.keyval == Gdk.KEY_slash and not self.search.has_focus()):
            self.search.grab_focus()
            return True
        return False


def main():
    topics = load(sys.argv[1] if len(sys.argv) > 1 else HERE / "facts")
    win = Window(topics)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    win.search.grab_focus()
    Gtk.main()


if __name__ == "__main__":
    main()
