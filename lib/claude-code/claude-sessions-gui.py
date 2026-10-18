#!/usr/bin/env python3
"""Live list of all Claude Code sessions, newest change first, with each one's last message.

Reads ~/.claude/projects/*/*.jsonl (read-only) and refreshes every 2 seconds.
Double-click a row to jump to its terminal window, or resume it in a new terminal.
A session whose terminal window was closed is stopped and resumed automatically.
Right-click for more (copy session id).
"""
import glob
import json
import os
import signal
import subprocess
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

PROJECTS = os.path.expanduser("~/.claude/projects")
TAIL_BYTES = 512 * 1024
SESSIONS = os.path.expanduser("~/.claude/sessions")
REFRESH_MS = 2000
GROUP_HEADINGS = ["", "Not today", "Not this week"]  # recent group gets no heading

_scan_lock = threading.Lock()
_cache = {}  # path -> (mtime, size, info)
_titles = {}  # path -> title
_counts = {}  # path -> [bytes consumed, message count]
_starts = {}  # path -> start directory
_started = {}  # path -> ISO timestamp of first message
CACHE_FILE = os.path.expanduser("~/.cache/claude-sessions-gui/cache.json")


def load_cache():
    try:
        with open(CACHE_FILE) as f:
            d = json.load(f)
        for path, v in d["files"].items():
            _cache[path] = (tuple(v["key"]), v["info"])
            _titles[path] = v["title"]
            _counts[path] = tuple(v["count"])
            _starts[path] = v["start"]
            if v["started"]:
                _started[path] = v["started"]
    except (OSError, ValueError, KeyError, TypeError):
        _cache.clear()
        _titles.clear()
        _counts.clear()
        _starts.clear()
        _started.clear()


def save_cache():
    files = {p: {"key": list(k), "info": info, "title": _titles.get(p, ""),
                 "count": list(_counts.get(p, (0, 0))), "start": _starts.get(p, ""),
                 "started": _started.get(p, "")}
             for p, (k, info) in list(_cache.items())}
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"files": files}, f)
        os.replace(tmp, CACHE_FILE)
    except OSError:
        pass


def _text_of(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _read_tail(path, size):
    with open(path, "rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # drop partial line
        return f.read().decode("utf-8", "replace").splitlines()


def _find_title(path):
    """Latest /rename title if any, else the latest auto-generated one."""
    custom = ai = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"custom-title"' in line or '"ai-title"' in line:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") == "custom-title":
                        custom = d.get("customTitle") or custom
                    elif d.get("type") == "ai-title":
                        ai = d.get("aiTitle") or ai
    except OSError:
        return _titles.get(path, "")
    _titles[path] = custom or ai
    return _titles[path]


def _start_cwd(path):
    """Directory the session was started in (first cwd in the file)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"cwd"' in line:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("cwd"):
                        _started[path] = d.get("timestamp", "")
                        return d["cwd"]
    except OSError:
        pass
    return ""


def _folder_name(path):
    """Readable name from the encoded projects folder, e.g. -home-me-claude -> claude."""
    enc = os.path.basename(os.path.dirname(path))
    home = os.path.expanduser("~").replace("/", "-")
    if enc == home:
        return "~"
    if enc.startswith(home + "-"):
        return enc[len(home) + 1:]
    return enc


def _count_messages(path, size):
    """Incrementally count real messages (typed prompts + assistant text)."""
    off, n = _counts.get(path, (0, 0))
    if size < off:
        off, n = 0, 0
    if size > off:
        with open(path, "rb") as f:
            f.seek(off)
            data = f.read(size - off)
        end = data.rfind(b"\n") + 1
        for line in data[:end].decode("utf-8", "replace").splitlines():
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("isSidechain") or d.get("isMeta"):
                continue
            if d.get("type") in ("user", "assistant") and _text_of(d.get("message", {})).strip():
                n += 1
        off += end
    _counts[path] = (off, n)
    return n


def running_info():
    """sessionId -> registry record for live Claude Code processes."""
    out = {}
    for p in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            with open(p) as f:
                d = json.load(f)
            os.kill(d["pid"], 0)
        except (OSError, ValueError, KeyError):
            continue
        out[d["sessionId"]] = d
    return out


def running_status():
    """sessionId -> 'busy'/'idle' for live Claude Code processes."""
    out = {}
    for p in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            with open(p) as f:
                d = json.load(f)
            os.kill(d["pid"], 0)
        except (OSError, ValueError, KeyError):
            continue
        out[d["sessionId"]] = d.get("status", "running")
    return out


def parse(path, mtime, size):
    lines = _read_tail(path, size)
    role = text = cwd = ""
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not cwd and d.get("cwd"):
            cwd = d["cwd"]
        if text or d.get("isSidechain") or d.get("isMeta"):
            if cwd and text:
                break
            continue
        if d.get("type") in ("user", "assistant"):
            t = _text_of(d.get("message", {})).strip()
            if t and not t.startswith("<"):
                role, text = d["type"], t
    title = _find_title(path)
    if path not in _starts:
        _starts[path] = _start_cwd(path)
    cwd = _starts[path] or cwd
    return {
        "id": os.path.basename(path)[:-6],
        "project": os.path.basename(cwd) or _folder_name(path),
        "cwd": cwd,
        "title": title,
        "role": role,
        "text": " ".join(text.split()),
        "mtime": mtime,
        "started": _started.get(path, ""),
        "count": _count_messages(path, size),
    }


def scan(progress=None):
    with _scan_lock:
        return _scan(progress)


def _scan(progress):
    rows = []
    dirty = False
    paths = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    for gone in set(_cache) - set(paths):
        del _cache[gone]
        dirty = True
    for i, path in enumerate(paths):
        if progress:
            progress(i, len(paths))
        try:
            st = os.stat(path)
        except OSError:
            continue
        key = (st.st_mtime, st.st_size)
        hit = _cache.get(path)
        if hit and hit[0] == key:
            rows.append(hit[1])
            continue
        try:
            info = parse(path, st.st_mtime, st.st_size)
        except OSError:
            continue
        _cache[path] = (key, info)
        dirty = True
        rows.append(info)
    if dirty:
        save_cache()
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def parent_pid(pid, comm):
    """Nearest ancestor process named comm (0 if none)."""
    while pid > 1:
        try:
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            with open(f"/proc/{ppid}/comm") as f:
                if f.read().strip() == comm:
                    return ppid
        except (OSError, ValueError, IndexError):
            return 0
        pid = ppid
    return 0


def _window_names(tpid):
    """{window id: title} for the visible windows of a terminal process."""
    names = {}
    if not tpid:
        return names
    out = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(tpid)],
                         capture_output=True, text=True).stdout.split()
    for w in out:
        names[w] = subprocess.run(["xdotool", "getwindowname", w],
                                  capture_output=True, text=True).stdout.strip()
    return names


def has_terminal(rec):
    """True if the session runs on a pty inside an xfce4-terminal window."""
    try:
        tty = os.readlink(f"/proc/{rec['pid']}/fd/0")
    except OSError:
        return False
    return tty.startswith("/dev/pts/") and parent_pid(rec["pid"], "xfce4-terminal") != 0


# other places a live session may legitimately sit, which this tool can't manage
OTHER_HOSTS = ("sshd", "tmux: server", "tmux", "screen", "SCREEN", "gnome-terminal-",
               "konsole", "xterm", "alacritty", "kitty", "tilix")


def terminal_gone(rec):
    """True for an interactive session whose xfce4-terminal window was closed.

    Background sessions and sessions hosted by ssh/tmux/another terminal app
    are not orphans, so they are left alone.
    """
    if rec.get("kind", "interactive") != "interactive" or has_terminal(rec):
        return False
    return not any(parent_pid(rec["pid"], c) for c in OTHER_HOSTS)


def stop_process(rec, grace=5.0):
    """SIGTERM, then SIGKILL after grace seconds. True once the process is gone."""
    pid = rec["pid"]
    try:  # guard against pid reuse since the registry was read
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"claude" not in f.read():
                return False
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    for sig, wait in ((None, grace), (signal.SIGKILL, 2.0)):
        if sig:
            try:
                os.kill(pid, sig)
            except OSError:
                return True
        end = time.time() + wait
        while time.time() < end:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.1)
    return False


def activate_terminal(rec):
    """Raise the terminal window running a live session.

    Windows of one terminal process share a PID and often a title, so the
    session's tty briefly gets a unique window title (output only, no input),
    the window is found by that title, then its previous title is restored.
    """
    try:
        tty = os.readlink(f"/proc/{rec['pid']}/fd/0")
    except OSError:
        return "session process is gone"
    if not tty.startswith("/dev/pts/"):
        return f"session is not on a terminal ({tty})"
    marker = f"cc-session-{rec['sessionId'][:8]}"
    before = _window_names(parent_pid(rec["pid"], "xfce4-terminal"))
    win = ""
    try:
        with open(tty, "w") as t:
            t.write(f"\033]0;{marker}\007")
            t.flush()
            for _ in range(10):
                time.sleep(0.1)
                out = subprocess.run(["xdotool", "search", "--name", marker],
                                     capture_output=True, text=True).stdout.split()
                if out:
                    win = out[0]
                    break
            if win:
                subprocess.run(["xdotool", "windowactivate", win], capture_output=True)
                # xfce4-terminal prepends its own "Terminal - " to the title
                prev = before.get(win, "")
                if prev.startswith("Terminal - "):
                    prev = prev[len("Terminal - "):]
                t.write(f"\033]0;{prev or 'Claude Code'}\007")
                t.flush()
                return f"activated terminal of {rec['sessionId'][:8]}"
    except OSError as e:
        return f"could not reach the terminal: {e}"
    # marker ignored: static-title terminal (started with --title). Only
    # unambiguous when the terminal process has a single window.
    if len(before) == 1:
        w = next(iter(before))
        subprocess.run(["xdotool", "windowactivate", w], capture_output=True)
        return f"activated terminal of {rec['sessionId'][:8]}"
    if before:
        return (f"{len(before)} terminal windows share a fixed title; cannot tell which "
                "one holds this session (windows opened with --title ignore title changes)")
    return "terminal window not found (different terminal app?)"


def ago(secs):
    secs = int(max(0, secs))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


class Win(Gtk.Window):
    def __init__(self):
        super().__init__(title="Claude Sessions")
        try:
            self.set_icon_from_file(os.path.expanduser(
                "~/.local/share/icons/hicolor/256x256/apps/claude-sessions.png"))
        except GLib.Error:
            pass
        self.set_default_size(1000, 600)
        # cols: age, project, title, who, last message, id, tooltip
        self.store = Gtk.ListStore(str, str, str, str, str, str, str, int, str)
        self.ids = []
        self.opening = {}  # session id -> time until which repeat opens are ignored
        self.sort_col = 0  # column index in the store; 0 = Changed
        self.sort_desc = True
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_tooltip_column(6)
        self.view.get_selection().set_select_function(
            lambda _sel, model, path, _cur: bool(model[path][5]))
        self.view.connect("row-activated", self.on_activate)
        self.view.connect("button-press-event", self.on_press)
        self.specs = specs = [("Changed", 0, 150), ("State", 1, 70), ("Title", 2, 260),
                 ("Msgs", 8, 50), ("By", 3, 60), ("Last message", 4, 0)]
        for name, i, w in specs:
            r = Gtk.CellRendererText()
            if i == 4:
                r.set_property("ellipsize", Pango.EllipsizeMode.END)
            col = Gtk.TreeViewColumn(name, r, text=i, weight=7)
            if w:
                col.set_min_width(w)
            else:
                col.set_expand(True)
            col.set_resizable(True)
            col.set_clickable(True)
            col.connect("clicked", self.on_header, i)
            self.view.append_column(col)
        sw = Gtk.ScrolledWindow()
        sw.add(self.view)
        self.status = Gtk.Label(xalign=0)
        self.bar = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER)
        self.bar.set_text("Reading sessions…")
        self.loading = True
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=8)
        btn = Gtk.Button()
        plus = Gtk.Label()
        plus.set_markup('<span size="xx-large" weight="bold">+</span>')
        btn.add(plus)
        btn.set_tooltip_text("New session")
        btn.connect("clicked", lambda _b: self.new_session())
        bar.pack_start(btn, False, False, 6)
        self.search = Gtk.SearchEntry(placeholder_text="Search sessions")
        self.search.set_width_chars(28)
        self.search.connect("search-changed", lambda _e: self.refresh())
        bar.pack_start(self.status, True, True, 0)
        bar.pack_start(self.bar, True, True, 0)
        bar.pack_end(self.search, False, False, 6)
        box.pack_start(bar, False, False, 4)
        box.pack_start(sw, True, True, 0)
        self.add(box)
        self.view.get_columns()[0].set_sort_indicator(True)
        self.view.set_search_column(2)
        threading.Thread(target=self.first_scan, daemon=True).start()
        GLib.timeout_add(REFRESH_MS, self.refresh)

    def first_scan(self):
        """Fill the cache off the main thread so the window opens at once."""
        def progress(i, n):
            GLib.idle_add(self.bar.set_fraction, i / max(n, 1))
            GLib.idle_add(self.bar.set_text, f"Reading sessions… {i} / {n}")
        load_cache()
        scan(progress)
        GLib.idle_add(self.finish_loading)

    def finish_loading(self):
        self.loading = False
        self.bar.hide()
        self.refresh()

    def refresh(self):
        if self.loading:
            return True
        rows = scan()
        now = time.time()
        sel = None
        model, it = self.view.get_selection().get_selected()
        if it:
            sel = model[it][5]
        # duplicate titles get a stable (n/total) suffix, oldest session first
        groups = {}
        for r in rows:
            if r["title"]:
                groups.setdefault(r["title"], []).append(r)
        for g in groups.values():
            g.sort(key=lambda r: (r["started"], r["id"]))
            for i, r in enumerate(g, 1):
                r["label"] = f"{r['title']} ({i}/{len(g)})" if len(g) > 1 else r["title"]
        total = len(rows)
        q = self.search.get_text().strip().lower()
        if q:
            rows = [r for r in rows if all(
                w in " ".join((r.get("label", r["title"]), r["text"], r["cwd"], r["id"])).lower()
                for w in q.split())]
        info = running_info()
        live = {sid: d.get("status", "running") for sid, d in info.items()}
        keys = {
            0: lambda r: r["mtime"],
            1: lambda r: {"busy": 2, "idle": 1}.get(live.get(r["id"]), 0),
            2: lambda r: r.get("label", r["title"]).lower(),
            3: lambda r: r["role"],
            4: lambda r: r["text"].lower(),
            8: lambda r: r["count"],
        }
        rows.sort(key=lambda r: r["mtime"], reverse=True)  # tie-break: newest first
        if self.sort_col != 0 or not self.sort_desc:
            rows.sort(key=keys[self.sort_col], reverse=self.sort_desc)
        items = rows
        if self.sort_col == 0:  # age headings only make sense when sorted by change
            items, last = [], None
            for r in rows:
                g = 0 if now - r["mtime"] < 86400 else 1 if now - r["mtime"] < 7 * 86400 else 2
                if g != last and (g or last is not None):  # blank spacer when oldest-first
                    items.append({"heading": GROUP_HEADINGS[g]})
                    last = g
                items.append(r)
        ids = [r.get("id") or "#" + r["heading"] for r in items]
        if ids != self.ids:
            self.store.clear()
            for r in items:
                self.store.append(["", "", "", "", "", r.get("id", ""), "", 400, ""])
            self.ids = ids
        n_active = 0
        for row, r in zip(self.store, items):
            if "heading" in r:
                row[0], row[7] = r["heading"], 700
                continue
            st = live.get(r["id"], "")
            active = st == "busy"
            n_active += active
            row[0] = ago(now - r["mtime"])
            if st and has_terminal(info[r["id"]]):
                st += " / visible"
            row[1] = ("● " if active else "") + st
            row[8] = str(r["count"])
            row[2] = r.get("label", r["title"])
            row[3] = {"user": "you", "assistant": "Claude"}.get(r["role"], "")
            row[4] = r["text"][:300]
            row[6] = GLib.markup_escape_text(
                f"{r['cwd']}\n{r['id']}\n\n{r['text'][:1200]}")
            row[7] = 700 if active else 400
            if r["id"] == sel:
                self.view.get_selection().select_iter(row.iter)
        self.status.set_text(
            f"  {len(rows)}{f' of {total}' if q else ''} sessions  ·  {len(live)} running  ·  {n_active} busy"
            "  ·  double-click opens the session  ·  right-click for more")
        return True

    def on_header(self, col, i):
        if i == self.sort_col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = i, i in (0, 1, 8)  # numbers/state: high first
        for c, (_, j, _) in zip(self.view.get_columns(), self.specs):
            c.set_sort_indicator(j == self.sort_col)
            c.set_sort_order(Gtk.SortType.DESCENDING if self.sort_desc else Gtk.SortType.ASCENDING)
        self.refresh()

    def on_activate(self, view, path, col):
        if not self.store[path][5]:
            return
        self.open_session(self.store[path][5])

    def on_press(self, view, ev):
        if ev.button != 3:
            return False
        hit = view.get_path_at_pos(int(ev.x), int(ev.y))
        if not hit:
            return False
        view.get_selection().select_path(hit[0])
        sid = self.store[hit[0]][5]
        if not sid:
            return True
        menu = Gtk.Menu()
        for label, fn in (("Open / activate terminal", self.open_session),
                          ("Copy session id", self.copy_id)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _w, f=fn: f(sid))
            menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(ev)
        return True

    def copy_id(self, sid):
        Gtk.Clipboard.get(Gdk_CLIPBOARD).set_text(sid, -1)
        self.status.set_text(f"  copied {sid}")

    def open_session(self, sid):
        # a launch takes a while to show up as running; ignore repeats meanwhile
        if time.time() < self.opening.get(sid, 0):
            return
        self.opening[sid] = time.time() + 15
        rec = running_info().get(sid)
        if rec and rec.get("kind") == "bg":
            self.launch(rec.get("cwd") or os.path.expanduser("~"),
                        f"claude attach {rec.get('jobId') or sid}")
            self.status.set_text(f"  attaching to background session {sid[:8]} in a new terminal")
            return
        if rec and terminal_gone(rec):
            self.status.set_text(f"  {sid[:8]} still runs but its terminal window is gone; "
                                 "stopping it and resuming in a new terminal...")
            threading.Thread(target=self.recover, args=(sid, rec), daemon=True).start()
            return
        if rec:
            self.status.set_text("  " + activate_terminal(rec))
            return
        self.resume(sid)

    def resume(self, sid):
        info = next((r for r in scan() if r["id"] == sid), None)
        cwd = info["cwd"] if info and os.path.isdir(info["cwd"]) else os.path.expanduser("~")
        self.launch(cwd, f"claude --resume {sid}")
        self.status.set_text(f"  resuming {sid[:8]} in a new terminal ({cwd})")

    def recover(self, sid, rec):
        """Stop the orphaned process, then resume the session in a fresh terminal."""
        if stop_process(rec):
            GLib.idle_add(self.resume, sid)
        else:
            GLib.idle_add(self.status.set_text,
                          f"  could not stop orphaned process {rec['pid']} of {sid[:8]}")

    def new_session(self):
        cwd = os.path.expanduser("~/claude")
        self.launch(cwd, "claude")
        self.status.set_text(f"  started a new session in {cwd}")

    @staticmethod
    def launch(cwd, cmd):
        # interactive bash so PATH matches a normal terminal; no --title, so the
        # terminal follows the title Claude Code sets (needed by activate_terminal)
        subprocess.Popen(["xfce4-terminal", "--icon=claude-code", "--working-directory", cwd,
                          "-e", f"bash -ic '{cmd}'"], start_new_session=True)


from gi.repository import Gdk
Gdk_CLIPBOARD = Gdk.SELECTION_CLIPBOARD

class App(Gtk.Application):
    """Single instance: launching again raises the open window."""

    def __init__(self):
        super().__init__(application_id="local.cyberbeest.ClaudeSessions")
        self.win = None

    def do_activate(self):
        if not self.win:
            self.win = Win()
            self.add_window(self.win)
        self.win.show_all()
        self.win.present()
        self.win.search.grab_focus()


if __name__ == "__main__":
    App().run()
