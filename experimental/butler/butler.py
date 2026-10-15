#!/usr/bin/env python3
"""Butler (working title): type or dictate a simple command, pick from the best matches.

Typing      ranks the commands live (after a short pause), best match first
Enter       run the shown command; commands marked confirm ask once more
Up/Down     pick another of the top three
Esc         close

`butler.py "make the display brighter"` starts with the text already ranked (for Dictate later).
Matching is a small multilingual sentence-embedding model (butler/matcher.py), no text generation.
Every confirmed choice is logged to ~/.local/state/butler/log.jsonl (local only) for tuning.
"""
import json
import os
import sys
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from butler import loader, slots, runner  # noqa: E402

LOG = os.path.expanduser("~/.local/state/butler/log.jsonl")
LIVE_DELAY_MS = 120   # pause after the last keystroke before ranking
MIN_CHARS = 3
LOW = 0.5   # below this the best match is probably not what was meant
LANG = "de" if os.environ.get("LC_ALL", os.environ.get("LANG", "")).startswith("de") else "en"

T = {
    "loading": {"en": "Loading the matcher…", "de": "Lade den Abgleich…"},
    "hint_input": {"en": "Type or dictate a command   ·   Esc: close", "de": "Befehl tippen oder diktieren   ·   Esc: schließen"},
    "hint_result": {"en": "Enter: run   ·   ↑↓: other candidates   ·   Esc: close", "de": "Enter: ausführen   ·   ↑↓: andere Vorschläge   ·   Esc: schließen"},
    "hint_pick": {"en": "↑↓: choose a command   ·   or rephrase   ·   Esc: close", "de": "↑↓: Befehl wählen   ·   oder anders formulieren   ·   Esc: schließen"},
    "hint_ask": {"en": "Type a number, Enter: run   ·   Esc: back", "de": "Zahl eingeben, Enter: ausführen   ·   Esc: zurück"},
    "hint_confirm": {"en": "Enter: yes, do it   ·   Esc: cancel", "de": "Enter: ja, ausführen   ·   Esc: abbrechen"},
    "unsure": {"en": "Not sure I understood. Closest matches:", "de": "Nicht sicher, ob ich das verstanden habe. Ähnlichste Befehle:"},
    "ask_generic": {"en": "How much (percent)?", "de": "Wie viel (Prozent)?"},
    "need_value": {"en": "needs a value", "de": "braucht einen Wert"},
    "will_ask": {"en": "Butler will ask for the value", "de": "Butler fragt nach dem Wert"},
    "failed": {"en": "That did not work", "de": "Das hat nicht geklappt"},
    "all_cmds": {"en": "All commands", "de": "Alle Befehle"},
    "hint_list": {"en": "Click a command to try it   ·   Esc: back", "de": "Befehl anklicken zum Ausprobieren   ·   Esc: zurück"},
    "no_catalog": {"en": "Catalog problem: ", "de": "Problem im Katalog: "},
}


def tr(key):
    return T[key][LANG]


def log_entry(entry):
    if os.environ.get("BUTLER_DRY"):
        return
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


CSS = b"""
window { background: #1e2127; }
#prompt, #prompt text { background: #2a2f38; color: #e6e9ef; font-size: 17px; }
#prompt { border-radius: 10px; padding: 12px; }
#title { color: #e6e9ef; font-size: 22px; font-weight: bold; }
#hint, #reason { color: #8b93a3; font-size: 13px; }
#pick { color: #7fd1a0; font-size: 20px; font-weight: bold; }
#pick.low { color: #d1b27f; }
#alt { color: #aab2c0; font-size: 15px; }
#alt.sel { color: #7fd1a0; font-weight: bold; }
#link { color: #7fb4ff; font-size: 13px; padding: 0; border: none; background: none; box-shadow: none; }
#link:hover { color: #a9ceff; }
#cat { color: #8b93a3; font-size: 12px; font-weight: bold; margin-top: 8px; }
#cmd { color: #e6e9ef; font-size: 15px; padding: 3px 6px; border-radius: 6px; }
#cmd:hover { background: #2a2f38; color: #7fd1a0; }
"""


class Butler(Gtk.Window):
    def __init__(self, initial=""):
        super().__init__(title="Butler")
        self.set_icon_name("butler")
        self.set_default_size(620, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_resizable(False)
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.state = "input"          # input | result | ask | confirm | sent
        self.matcher, self.cmds, self.load_error = None, None, None
        self.ranked, self.idx, self.vals, self.sentence = [], 0, {}, ""
        self.touched = False   # arrow keys used on this result
        self.pending_rank = False
        self.live_timer = None
        threading.Thread(target=self._load, daemon=True).start()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(24)
        self.add(box)
        t = Gtk.Label(label="Butler", xalign=0)
        t.set_name("title")
        box.pack_start(t, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_name("prompt")
        self.entry.connect("key-press-event", self.on_key)
        self.entry.connect("changed", self.on_edit)
        self.entry.set_text(initial)
        box.pack_start(self.entry, False, False, 0)
        self.result = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.pack_start(self.result, False, False, 0)
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.pack_start(foot, False, False, 0)
        self.hint = Gtk.Label(xalign=0)
        self.hint.set_name("hint")
        foot.pack_start(self.hint, True, True, 0)
        self.link = Gtk.Button(label=tr("all_cmds"))
        self.link.set_name("link")
        self.link.set_relief(Gtk.ReliefStyle.NONE)
        self.link.set_can_focus(False)
        self.link.connect("clicked", lambda _b: self.show_list())
        foot.pack_end(self.link, False, False, 0)
        self.hint.set_text(tr("hint_input"))
        if initial:
            self.pending_rank = True

    # --- loading -----------------------------------------------------------
    def _load(self):
        try:
            cmds, errs = loader.load()
            if errs:
                raise RuntimeError("; ".join(errs[:2]))
            from butler.matcher import Matcher
            m = Matcher(cmds)
            GLib.idle_add(self._loaded, cmds, m, None)
        except Exception as e:  # noqa: BLE001 - shown in the window
            GLib.idle_add(self._loaded, None, None, str(e))

    def _loaded(self, cmds, m, err):
        self.cmds, self.matcher, self.load_error = cmds, m, err
        if err:
            self.label(tr("no_catalog") + err, "reason")
            self.show_all()
        elif self.pending_rank:
            self.pending_rank = False
            self.analyse()
        elif self.state in ("input", "result") and len(self.text()) >= MIN_CHARS:
            self.analyse()   # typed while the matcher was loading
        return False

    # --- helpers -----------------------------------------------------------
    def clear_result(self):
        for c in self.result.get_children():
            c.destroy()

    def label(self, text, name, sel=False, low=False):
        l = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=64)
        l.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if name == "alt":
            l.set_ellipsize(Pango.EllipsizeMode.END)
            l.set_line_wrap(False)
        l.set_name(name)
        ctx = l.get_style_context()
        if sel:
            ctx.add_class("sel")
        if low:
            ctx.add_class("low")
        self.result.pack_start(l, False, False, 0)
        return l

    def set_hint(self, key):
        self.hint.set_text(tr(key))

    def text(self):
        return self.entry.get_text().strip()

    def name_of(self, cmd, vals=None):
        """The whole command as one sentence, with the value filled in ("…" while it is still unknown)."""
        if vals is None:
            vals = self.slot_for(cmd, self.sentence)[0]
        kinds = {cmd["slot"]["kind"]} if "slot" in cmd else set()
        return cmd["sentence"][LANG].format_map({k: vals.get(k, "…") for k in kinds})

    def slot_for(self, cmd, text):
        """(vals dict, status) for the sentence; status ok|default|missing|-"""
        if "slot" not in cmd:
            return {}, "-"
        v, st = slots.extract(cmd["slot"], text)
        return ({cmd["slot"]["kind"]: v} if v is not None else {}), st

    def effect(self, cmd, vals, st):
        if st == "missing":
            return tr("need_value")
        reply = cmd["reply"][LANG].format(**vals)
        return reply

    def show_list(self):
        if not self.cmds:
            return
        if self.live_timer:
            GLib.source_remove(self.live_timer)
            self.live_timer = None
        self.state = "list"
        self.clear_result()
        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(320)
        sw.set_max_content_height(320)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sw.add(col)
        cat = None
        for c in self.cmds:
            if c["category"][LANG] != cat:
                cat = c["category"][LANG]
                h = Gtk.Label(label=cat.upper(), xalign=0)
                h.set_name("cat")
                col.pack_start(h, False, False, 0)
            eb = Gtk.EventBox()
            l = Gtk.Label(label=self.name_of(c, {}), xalign=0)
            l.set_name("cmd")
            eb.add(l)
            eb.connect("button-release-event", lambda _w, _e, c=c: self.pick_from_list(c))
            col.pack_start(eb, False, False, 0)
        self.result.pack_start(sw, False, False, 0)
        self.set_hint("hint_list")
        self.show_all()

    def pick_from_list(self, cmd):
        self.state = "input"
        self.clear_result()
        self.entry.set_text(self.name_of(cmd, {}).replace("…%", "").replace("…", "").strip())
        self.entry.grab_focus()
        self.entry.set_position(-1)
        self.flush_live()

    # --- keys --------------------------------------------------------------
    def on_key(self, _w, ev):
        k = ev.keyval
        enter = k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)
        if self.state == "list":
            if k == Gdk.KEY_Escape:
                self.state = "input"
                self.clear_result()
                self.set_hint("hint_input")
                self.on_edit(None)
            return k != Gdk.KEY_BackSpace and not (32 <= k < 127) and k != Gdk.KEY_Delete
        if k == Gdk.KEY_F1:
            self.show_list()
            return True
        if self.state in ("input", "result"):
            if k == Gdk.KEY_Escape:
                self.destroy()
                return True
            if enter:
                self.flush_live()   # rank right now if the pause has not elapsed yet
                if self.state == "result" and (self.ranked[0][1] >= LOW or self.touched):  # unsure: pick on purpose
                    self.confirm()
                return True
            if self.state == "result" and k in (Gdk.KEY_Down, Gdk.KEY_Tab):
                self.touched = True
                self.idx = (self.idx + 1) % len(self.ranked)
                self.render()
                return True
            if self.state == "result" and k == Gdk.KEY_Up:
                self.touched = True
                self.idx = (self.idx - 1) % len(self.ranked)
                self.render()
                return True
            return False
        elif self.state == "ask":
            if enter:
                self.answer_ask()
                return True
            if k == Gdk.KEY_Escape:
                self.back_to_input()
                return True
        elif self.state == "confirm":
            if enter:
                self.run_selected()
                return True
            if k == Gdk.KEY_Escape:
                self.state = "result"
                self.render()
                return True
            return True
        elif self.state == "sent":
            return True
        return False

    def on_edit(self, _e):
        """Every change re-ranks after a short pause. The ask and sent states use the entry for other things."""
        if self.state in ("ask", "sent"):
            return
        if self.state == "confirm":
            self.state = "input"
        if self.live_timer:
            GLib.source_remove(self.live_timer)
            self.live_timer = None
        if len(self.text()) < MIN_CHARS:
            self.state = "input"
            self.clear_result()
            self.set_hint("hint_input")
            return
        self.live_timer = GLib.timeout_add(LIVE_DELAY_MS, self._live)

    def _live(self):
        self.live_timer = None
        self.analyse()
        return False

    def flush_live(self):
        if self.live_timer:
            GLib.source_remove(self.live_timer)
            self.live_timer = None
            if len(self.text()) >= MIN_CHARS:
                self.analyse()

    def back_to_input(self):
        self.state = "input"
        self.clear_result()
        self.entry.set_text(self.sentence)   # re-ranks through on_edit
        self.entry.grab_focus()
        self.entry.set_position(-1)
        self.set_hint("hint_input")

    # --- ranking -----------------------------------------------------------
    def analyse(self):
        if self.matcher is None:
            if self.load_error:
                return
            self.pending_rank = True
            self.clear_result()
            self.label(tr("loading"), "reason")
            self.show_all()
            return
        self.sentence = self.text()
        self.ranked = self.matcher.match(self.sentence, 3)
        self.idx, self.touched = 0, False
        self.state = "result"
        self.render()

    def render(self):
        self.clear_result()
        text = self.sentence
        cmd, score = self.ranked[self.idx]
        low = self.ranked[0][1] < LOW
        if low:
            self.label(tr("unsure"), "reason")
        vals, st = self.slot_for(cmd, text)
        self.label(self.name_of(cmd, vals), "pick", low=low)
        note = tr("will_ask") if st == "missing" else cmd["category"][LANG]
        self.label(f"{note}   ·   {score:.2f}", "reason")
        self.label(" ", "reason")
        for i, (c, sc) in enumerate(self.ranked):
            self.label(("▸ " if i == self.idx else "   ") + f"{self.name_of(c)}    {sc:.2f}", "alt", i == self.idx)
        self.set_hint("hint_pick" if low and not self.touched else "hint_result")
        self.show_all()

    # --- running -----------------------------------------------------------
    def confirm(self):
        cmd, _ = self.ranked[self.idx]
        self.vals, st = self.slot_for(cmd, self.sentence)
        if st == "missing":
            self.state = "ask"
            self.clear_result()
            ask = cmd["slot"].get("ask", {}).get(LANG) or tr("ask_generic")
            self.label(self.name_of(cmd, {}), "pick")
            self.label(ask, "reason")
            self.entry.set_text("")
            self.entry.grab_focus()
            self.set_hint("hint_ask")
            self.show_all()
            return
        if cmd.get("confirm"):
            self.state = "confirm"
            self.clear_result()
            self.label(self.name_of(cmd, self.vals), "pick", low=True)
            self.set_hint("hint_confirm")
            self.show_all()
            return
        self.run_selected()

    def answer_ask(self):
        cmd, _ = self.ranked[self.idx]
        v, st = slots.extract(cmd["slot"], self.text())
        if st == "missing":
            return
        self.vals = {cmd["slot"]["kind"]: v}
        self.run_selected()

    def run_selected(self):
        cmd, score = self.ranked[self.idx]
        self.state = "sent"
        self.clear_result()
        try:
            argv, note, rc, _extras = runner.execute(cmd, self.vals, dry=False)
            ok = rc == 0
            msg = cmd["reply"][LANG].format(**self.vals) if ok else f"{tr('failed')} ({rc})"
        except Exception as e:  # noqa: BLE001 - shown to the user
            ok, msg = False, f"{tr('failed')}: {e}"
        log_entry({
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "text": self.sentence,
            "chosen": cmd["id"], "chosen_rank": self.idx, "score": round(score, 3),
            "ranked": [{"id": c["id"], "score": round(s, 3)} for c, s in self.ranked],
            "slots": self.vals, "ok": ok,
        })
        self.label(msg, "pick", low=not ok)
        self.hint.set_text("")
        self.show_all()
        GLib.timeout_add(900 if ok else 2500, self.destroy)


class App(Gtk.Application):
    def __init__(self, initial):
        super().__init__(application_id="local.cyberbeest.Butler")
        self.initial = initial

    def do_activate(self):
        wins = self.get_windows()
        if wins:
            wins[0].present()
            return
        w = Butler(self.initial)
        self.add_window(w)
        w.show_all()
        w.present()
        w.entry.grab_focus()
        w.entry.set_position(-1)


if __name__ == "__main__":
    sys.exit(App(" ".join(sys.argv[1:])).run([sys.argv[0]]))
