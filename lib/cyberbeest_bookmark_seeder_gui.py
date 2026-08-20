#!/usr/bin/env python3
"""Cyberbeest Bookmark Seeder.

A tiny built-in text editor (new/open/save/save as, live-parsed preview
table) for a text file of grouped addresses --

    Tor: abcdef.onion, abcd.xyz
    i2p: abcd.i2p
    News: some-site.example

-- and files them as Firefox bookmarks, one subfolder per category under a
top-level "Cyberbeest Seed" folder. "Tor:" entries go into the Tor Browser
profile, "i2p:" entries into the dedicated i2p Firefox profile (see
setup_i2p_extras.py), and everything else into the normal default Firefox
profile -- these are the three browsers actually installed on a Cyberbeest.

Written as a self-contained Gtk.Box page (SeederPage) so it can later be
dropped into a unified Cyberbeest Settings dialog as a tab, rather than
staying its own top-level window forever.

Bookmarks are written directly into each profile's places.sqlite rather
than through Firefox itself, so the browser holding that file must be
closed first -- this tool closes it automatically (killing only the
process(es) that actually have that specific places.sqlite open, via
lsof, not every Firefox-like process on the system) and takes a timestamped
backup of the file before writing.
"""

import base64
import configparser
import glob
import os
import subprocess
import time
from collections import OrderedDict
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

HOME = os.path.expanduser("~")
FIREFOX_DIR = os.path.join(HOME, ".mozilla", "firefox")
I2P_PROFILE_NAME = "i2p-profile"  # must match setup_i2p_extras.py's PROFILE_DIR
TORBROWSER_GLOB = os.path.join(
    HOME, ".local", "share", "torbrowser", "tbb", "*", "tor-browser",
    "Browser", "TorBrowser", "Data", "Browser", "profile.default", "places.sqlite",
)

SEED_ROOT_TITLE = "Cyberbeest Seed"


# --- category classification -------------------------------------------

def target_for_category(category):
    c = category.strip().lower()
    if c in ("tor", "onion"):
        return "tor"
    if c in ("i2p", "eepsite", "eepsites"):
        return "i2p"
    return "web"


TARGET_LABELS = {"tor": "Tor Browser", "i2p": "i2p Firefox", "web": "default Firefox"}


def looks_like_host(item):
    return " " not in item and "@" not in item and "." in item


def normalize_url(item, target):
    if "://" in item:
        return item
    if not looks_like_host(item):
        return None
    scheme = "http" if target in ("tor", "i2p") else "https"
    return f"{scheme}://{item}"


def parse_seed_file(text):
    groups = OrderedDict()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        category, rest = line.split(":", 1)
        items = [i.strip() for i in rest.split(",") if i.strip()]
        if items:
            groups.setdefault(category.strip(), []).extend(items)
    return groups


def build_plan(groups):
    """Returns (rows, by_target) where rows is a flat list of
    (category, item, target, url_or_None) for the preview table, and
    by_target maps target -> {category: [(url, title), ...]} for entries
    that resolved to a usable URL."""
    rows = []
    by_target = {}
    for category, items in groups.items():
        target = target_for_category(category)
        for item in items:
            url = normalize_url(item, target)
            rows.append((category, item, target, url))
            if url is not None:
                by_target.setdefault(target, OrderedDict()).setdefault(category, []).append((url, item))
    return rows, by_target


# --- profile resolution ---------------------------------------------------

def resolve_default_places():
    installs_ini = os.path.join(FIREFOX_DIR, "installs.ini")
    profiles_ini = os.path.join(FIREFOX_DIR, "profiles.ini")
    profile_path_name = None

    if os.path.exists(installs_ini):
        cfg = configparser.ConfigParser()
        cfg.read(installs_ini)
        for section in cfg.sections():
            if cfg.has_option(section, "Default"):
                profile_path_name = cfg.get(section, "Default")
                break

    if profile_path_name is None and os.path.exists(profiles_ini):
        cfg = configparser.ConfigParser()
        cfg.read(profiles_ini)
        for section in cfg.sections():
            if cfg.has_option(section, "Default") and cfg.get(section, "Default") == "1":
                profile_path_name = cfg.get(section, "Path", fallback=None)
                break

    if profile_path_name is None:
        return None
    places = os.path.join(FIREFOX_DIR, profile_path_name, "places.sqlite")
    return places if os.path.exists(places) else None


def resolve_i2p_places():
    places = os.path.join(FIREFOX_DIR, I2P_PROFILE_NAME, "places.sqlite")
    return places if os.path.exists(places) else None


def resolve_tor_places():
    matches = glob.glob(TORBROWSER_GLOB)
    return matches[0] if matches else None


RESOLVERS = {"web": resolve_default_places, "i2p": resolve_i2p_places, "tor": resolve_tor_places}

# Coalesces reparsing into one pass after a burst of keystrokes, same
# debounce idea as cyberbeest_panel_color_gui.py's RESTART_DEBOUNCE_MS.
REPARSE_DEBOUNCE_MS = 250


# --- closing the browser that owns a given places.sqlite -----------------

def close_owning_processes(places_path, log):
    try:
        out = subprocess.run(["lsof", "-t", places_path], capture_output=True, text=True)
    except FileNotFoundError:
        log(f"  lsof not available, cannot confirm {places_path} is free -- proceeding anyway.")
        return
    pids = [p for p in out.stdout.split() if p.strip().isdigit()]
    if not pids:
        return
    log(f"  Closing browser holding {places_path} ({len(pids)} process(es))...")
    subprocess.run(["kill"] + pids)
    for _ in range(20):
        time.sleep(0.5)
        out = subprocess.run(["lsof", "-t", places_path], capture_output=True, text=True)
        if not out.stdout.split():
            return
    subprocess.run(["kill", "-9"] + pids)
    time.sleep(0.5)


# --- places.sqlite writing -------------------------------------------------

def gen_guid():
    return base64.urlsafe_b64encode(os.urandom(9)).decode("ascii")[:12]


def rev_host(host):
    return host[::-1] + "."


def now_us():
    return int(time.time() * 1_000_000)


def find_or_create_folder(cur, parent_id, title):
    cur.execute("SELECT id FROM moz_bookmarks WHERE parent=? AND type=2 AND title=?", (parent_id, title))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM moz_bookmarks WHERE parent=?", (parent_id,))
    pos = cur.fetchone()[0]
    ts = now_us()
    cur.execute(
        "INSERT INTO moz_bookmarks (type, fk, parent, position, title, dateAdded, lastModified, guid, syncChangeCounter) "
        "VALUES (2, NULL, ?, ?, ?, ?, ?, ?, 1)",
        (parent_id, pos, title, ts, ts, gen_guid()),
    )
    return cur.lastrowid


def add_bookmark(cur, parent_id, url, title):
    host = urlsplit(url).hostname or ""
    cur.execute("SELECT id FROM moz_places WHERE url=?", (url,))
    row = cur.fetchone()
    if row:
        place_id = row[0]
    else:
        cur.execute(
            "INSERT INTO moz_places (url, title, rev_host, hidden, typed, frecency, guid, url_hash) "
            "VALUES (?, ?, ?, 0, 0, -1, ?, 0)",
            (url, title, rev_host(host), gen_guid()),
        )
        place_id = cur.lastrowid

    cur.execute("SELECT id FROM moz_bookmarks WHERE parent=? AND fk=?", (parent_id, place_id))
    if cur.fetchone():
        return False

    cur.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM moz_bookmarks WHERE parent=?", (parent_id,))
    pos = cur.fetchone()[0]
    ts = now_us()
    cur.execute(
        "INSERT INTO moz_bookmarks (type, fk, parent, position, title, dateAdded, lastModified, guid, syncChangeCounter) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, 1)",
        (place_id, parent_id, pos, title, ts, ts, gen_guid()),
    )
    return True


def seed_into_profile(places_path, category_to_urls):
    import shutil
    import sqlite3

    backup = f"{places_path}.bak-{int(time.time())}"
    shutil.copy2(places_path, backup)

    con = sqlite3.connect(places_path)
    try:
        cur = con.cursor()
        cur.execute("SELECT id FROM moz_bookmarks WHERE guid='menu________'")
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Bookmarks Menu root not found -- unexpected places.sqlite schema")
        menu_id = row[0]
        seed_root = find_or_create_folder(cur, menu_id, SEED_ROOT_TITLE)

        added = 0
        for category, urls in category_to_urls.items():
            folder_id = find_or_create_folder(cur, seed_root, category)
            for url, title in urls:
                if add_bookmark(cur, folder_id, url, title):
                    added += 1
        con.commit()
    finally:
        con.close()
    return added, backup


# --- GUI --------------------------------------------------------------------

class SeederPage(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.set_border_width(16)
        self.groups = OrderedDict()
        self.rows = []
        self.by_target = {}
        self.current_path = None
        self._reparse_timeout = None

        heading = Gtk.Label(xalign=0)
        heading.set_markup("<b>Seed bookmarks</b>")
        self.pack_start(heading, False, False, 0)

        info = Gtk.Label(
            wrap=True, max_width_chars=60, xalign=0,
            label='"Category: item, item" lines, one category per line. "Tor:" '
                  'entries go to the Tor Browser bookmarks, "i2p:" entries to '
                  'the i2p Firefox profile, everything else to the default '
                  'Firefox profile.',
        )
        self.pack_start(info, False, False, 0)

        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(file_row, False, False, 0)
        for label, handler in (
            ("New", self.on_new), ("Open...", self.on_open),
            ("Save", self.on_save), ("Save As...", self.on_save_as),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", handler)
            file_row.pack_start(button, False, False, 0)
        self.filename_label = Gtk.Label(label="(new file)", xalign=0, ellipsize=3)
        self.filename_label.get_style_context().add_class("dim-label")
        file_row.pack_start(self.filename_label, True, True, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(360)
        self.pack_start(paned, True, True, 0)

        self.buffer = Gtk.TextBuffer()
        self.buffer.connect("changed", self.on_text_changed)
        editor = Gtk.TextView(buffer=self.buffer)
        editor.set_monospace(True)
        editor.set_top_margin(4)
        editor.set_left_margin(6)
        editor_scroller = Gtk.ScrolledWindow()
        editor_scroller.set_size_request(340, 260)
        editor_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        editor_scroller.add(editor)
        paned.pack1(editor_scroller, resize=True, shrink=False)

        self.store = Gtk.ListStore(str, str, str, str)  # category, item, browser, status
        tree = Gtk.TreeView(model=self.store)
        for i, name in enumerate(("Category", "Item", "Browser", "Status")):
            tree.append_column(Gtk.TreeViewColumn(name, Gtk.CellRendererText(), text=i))
        table_scroller = Gtk.ScrolledWindow()
        table_scroller.set_size_request(340, 260)
        table_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        table_scroller.add(tree)
        paned.pack2(table_scroller, resize=True, shrink=False)

        seed_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pack_start(seed_row, False, False, 0)
        self.seed_button = Gtk.Button(label="Seed bookmarks")
        self.seed_button.set_sensitive(False)
        self.seed_button.connect("clicked", self.on_seed)
        seed_row.pack_start(self.seed_button, False, False, 0)
        self.warn_label = Gtk.Label(
            label="Closes any open Firefox / Tor Browser windows to write bookmarks.",
            xalign=0,
        )
        self.warn_label.get_style_context().add_class("dim-label")
        seed_row.pack_start(self.warn_label, False, False, 0)

        self.log_buffer = Gtk.TextBuffer()
        log_view = Gtk.TextView(buffer=self.log_buffer)
        log_view.set_editable(False)
        log_view.set_monospace(True)
        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_size_request(560, 120)
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroller.add(log_view)
        self.pack_start(log_scroller, False, False, 0)

        self._reparse()

    def log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + "\n")

    def _update_title(self):
        name = os.path.basename(self.current_path) if self.current_path else "(new file)"
        self.filename_label.set_text(name)
        toplevel = self.get_toplevel()
        if isinstance(toplevel, Gtk.Window):
            toplevel.set_title(f"Cyberbeest Bookmark Seeder -- {name}")

    def _confirm_discard(self):
        if not self.buffer.get_modified():
            return True
        dialog = Gtk.MessageDialog(
            transient_for=self.get_toplevel(), modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Discard unsaved changes?",
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Discard", Gtk.ResponseType.OK)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def on_new(self, _button):
        if not self._confirm_discard():
            return
        self.buffer.set_text("")
        self.buffer.set_modified(False)
        self.current_path = None
        self._update_title()

    def on_open(self, _button):
        if not self._confirm_discard():
            return
        dialog = Gtk.FileChooserDialog(
            title="Open seed file", transient_for=self.get_toplevel(), action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError as exc:
                self.log(f"Could not read {path}: {exc}")
                dialog.destroy()
                return
            self.buffer.set_text(text)
            self.buffer.set_modified(False)
            self.current_path = path
            self._update_title()
            self.log(f"Opened {path}")
        dialog.destroy()

    def on_save(self, _button):
        if self.current_path is None:
            self.on_save_as(_button)
            return
        self._write_to(self.current_path)

    def on_save_as(self, _button):
        dialog = Gtk.FileChooserDialog(
            title="Save seed file", transient_for=self.get_toplevel(), action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        if self.current_path:
            dialog.set_filename(self.current_path)
        if dialog.run() == Gtk.ResponseType.OK:
            self._write_to(dialog.get_filename())
        dialog.destroy()

    def _write_to(self, path):
        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as exc:
            self.log(f"Could not save {path}: {exc}")
            return
        self.buffer.set_modified(False)
        self.current_path = path
        self._update_title()
        self.log(f"Saved {path}")

    def on_text_changed(self, _buffer):
        if self._reparse_timeout is not None:
            GLib.source_remove(self._reparse_timeout)
        self._reparse_timeout = GLib.timeout_add(REPARSE_DEBOUNCE_MS, self._reparse)

    def _reparse(self):
        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), True)
        self.groups = parse_seed_file(text)
        self.rows, self.by_target = build_plan(self.groups)

        self.store.clear()
        for category, item, target, url in self.rows:
            status = "OK" if url else "skipped (not a URL)"
            self.store.append([category, item, TARGET_LABELS[target], status])

        self.seed_button.set_sensitive(bool(self.by_target))
        self._reparse_timeout = None
        return False

    def on_seed(self, _button):
        self.seed_button.set_sensitive(False)
        GLib.idle_add(self._do_seed)

    def _do_seed(self):
        for target, category_to_urls in self.by_target.items():
            label = TARGET_LABELS[target]
            places_path = RESOLVERS[target]()
            if places_path is None:
                self.log(f"{label}: could not find its bookmarks database, skipped.")
                continue
            self.log(f"{label}: closing browser if open...")
            close_owning_processes(places_path, self.log)
            try:
                added, backup = seed_into_profile(places_path, category_to_urls)
            except Exception as exc:  # noqa: BLE001 -- surface any failure in the log rather than crashing the GUI
                self.log(f"{label}: FAILED -- {exc}")
                continue
            self.log(f"{label}: added {added} new bookmark(s) under '{SEED_ROOT_TITLE}'. Backup: {backup}")
        self.log("Done.")
        self.seed_button.set_sensitive(True)
        return False


class SeederWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Bookmark Seeder")
        self.set_default_size(760, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)
        self.add(SeederPage())


def main():
    win = SeederWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
