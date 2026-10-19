#!/usr/bin/env python3
"""Cyberbeest Image Favorites: grid of the images starred in the viewer.

Runs as its own process so it stays open when the viewer windows close. The
favorites database and image loading come from cyberbeest_image_viewer.py,
which sits next to this script.
"""

import hashlib
import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cyberbeest_image_viewer as civ

VIEWER_SCRIPT = civ.__file__


GALLERY_THUMB = 160


def _cached_thumbnail(path):
    """Pixbuf from the freedesktop thumbnail cache (the one Files fills), or
    None when there is no up-to-date entry."""
    digest = hashlib.md5(Gio.File.new_for_path(path).get_uri().encode()).hexdigest()
    try:
        mtime = str(int(os.stat(path).st_mtime))
    except OSError:
        return None
    for size in ("large", "normal"):
        thumb = os.path.expanduser(f"~/.cache/thumbnails/{size}/{digest}.png")
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(thumb)
        except GLib.Error:
            continue
        if pixbuf.get_option("tEXt::Thumb::MTime") == mtime:
            return pixbuf
    return None


def _generated_thumbnail(path):
    # The jail can't write ~/.cache, so these live only as long as the window.
    frames, _size = civ.load_frames(path)
    img = frames[0][0]
    scale = min(GALLERY_THUMB / img.width, GALLERY_THUMB / img.height, 1.0)
    w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    if (w, h) != img.size:
        img = civ.resize_gamma_correct(img, w, h)
    return civ.pil_to_pixbuf(img)


SORT_FILE = os.path.join(civ.CONFIG_DIR, "image-favorites-sort")
VIEW_FILE = os.path.join(civ.CONFIG_DIR, "image-favorites-view")

# key -> (label, sort key over (path, added)); everything but the date
# sorts ascending, the date newest first.
SORT_MODES = {
    "date": ("Date added", lambda e: -e[1]),
    "folder": ("Folder", lambda e: (os.path.dirname(e[0]).casefold(), os.path.basename(e[0]).casefold())),
    "name": ("Name", lambda e: (os.path.basename(e[0]).casefold(), os.path.dirname(e[0]).casefold())),
    "type": ("Type", lambda e: (os.path.splitext(e[0])[1].casefold(), os.path.basename(e[0]).casefold())),
}


def _saved_sort():
    try:
        with open(SORT_FILE) as f:
            key = f.read().strip()
    except OSError:
        return "date"
    return key if key in SORT_MODES else "date"


def _saved_view():
    try:
        with open(VIEW_FILE) as f:
            return "list" if f.read().strip() == "list" else "thumbnails"
    except OSError:
        return "thumbnails"


LIST_THUMB = 40


class FavoritesWindow(Gtk.Window):
    """Grid of favorite images; activating one opens it in a new viewer
    process."""

    def __init__(self):
        super().__init__(title="Favorite images")
        self.connect("destroy", lambda _w: Gtk.main_quit())
        self.set_default_size(720, 520)
        # path, name (no extension), thumbnail, folder, type, date added, small thumbnail,
        # caption, grid label (caption, else name)
        self.store = Gtk.ListStore(str, str, GdkPixbuf.Pixbuf, str, str, str, GdkPixbuf.Pixbuf, str, str)
        self.view = Gtk.IconView(model=self.store, item_width=GALLERY_THUMB + 16)
        self.view.set_pixbuf_column(2)
        self.view.set_text_column(8)
        self.view.set_tooltip_column(0)
        self.view.connect("item-activated", self.on_activated)
        grid_scroller = Gtk.ScrolledWindow()
        grid_scroller.add(self.view)

        self.list_view = Gtk.TreeView(model=self.store)
        self.list_view.set_tooltip_column(0)
        self.list_view.connect("row-activated", self.on_row_activated)
        self.list_view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererPixbuf(), pixbuf=6))
        self.sort_columns = {}
        for key, title, column in (("folder", "Folder", 3), ("name", "Name", 1), ("caption", "Caption", 7), ("type", "Type", 4), ("date", "Date added", 5)):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(ellipsize=3), text=column)
            col.set_resizable(True)
            col.set_min_width(150 if key in ("folder", "name") else 80 if key == "type" else 140)
            col.set_expand(key in ("folder", "name"))
            col.set_clickable(key in SORT_MODES)
            if key in SORT_MODES:
                col.connect("clicked", lambda _c, k=key: self.sort_combo.set_active_id(k))
            self.list_view.append_column(col)
            self.sort_columns[key] = col
        list_scroller = Gtk.ScrolledWindow()
        list_scroller.add(self.list_view)

        self.stack = Gtk.Stack()
        self.stack.add_named(grid_scroller, "thumbnails")
        self.stack.add_named(list_scroller, "list")
        self.missing = Gtk.Label(label="No favorites yet. Press F or ★ to add one.")
        self.sort_key = _saved_sort()
        self.sort_combo = Gtk.ComboBoxText()
        for key, (label, _fn) in SORT_MODES.items():
            self.sort_combo.append(key, label)
        self.sort_combo.set_active_id(self.sort_key)
        self.sort_combo.set_can_focus(False)
        self.sort_combo.connect("changed", self.on_sort_changed)
        self.view_buttons = {}
        view_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        view_box.get_style_context().add_class("linked")
        for key, icon, tip in (("thumbnails", "view-grid-symbolic", "Thumbnails"), ("list", "view-list-symbolic", "List")):
            button = Gtk.ToggleButton(image=Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), tooltip_text=tip)
            button.set_can_focus(False)
            button.connect("toggled", lambda b, k=key: self.on_view_toggled(b, k))
            view_box.pack_start(button, False, False, 0)
            self.view_buttons[key] = button
        self.view_name = _saved_view()
        self.view_buttons[self.view_name].set_active(True)
        self.sort_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin=6)
        self.sort_bar.pack_start(view_box, False, False, 0)
        self.sort_bar.pack_start(Gtk.Label(label="Sort by", margin_start=12), False, False, 0)
        self.sort_bar.pack_start(self.sort_combo, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self.sort_bar, False, False, 0)
        box.pack_start(self.missing, True, True, 0)
        box.pack_start(self.stack, True, True, 0)
        self.add(box)
        self.connect("key-press-event", self.on_key_press)
        # Favorites toggled in a viewer window while this one is open.
        self.connect("focus-in-event", lambda _w, _e: self.refresh() and False)
        self.pending = []
        self.signature = None
        self.refresh()
        # Reload as soon as a viewer toggles a favorite. The directory is
        # watched, not the file, so a replaced database is still noticed.
        self._reload_timer = 0
        os.makedirs(civ.CONFIG_DIR, exist_ok=True)
        self.monitor = Gio.File.new_for_path(civ.CONFIG_DIR).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_db_changed)
        self.show_all()
        self.stack.set_visible_child_name(self.view_name)
        self._mark_sort_column()
        self._update_empty()

    def on_db_changed(self, _monitor, file, _other, event):
        if file.get_basename() != os.path.basename(civ.FAVORITES_DB):
            return
        if event not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            return
        # A commit can touch the file several times; reload once it settles.
        if self._reload_timer:
            GLib.source_remove(self._reload_timer)
        self._reload_timer = GLib.timeout_add(100, self._reload_now)

    def _reload_now(self):
        self._reload_timer = 0
        self.refresh()
        return False

    def on_view_toggled(self, button, view):
        if not button.get_active():
            # One of the two always stays pressed.
            if self.view_name == view:
                button.set_active(True)
            return
        self.view_name = view
        for key, other in self.view_buttons.items():
            if key != view:
                other.set_active(False)
        self.stack.set_visible_child_name(view)
        try:
            with open(VIEW_FILE, "w") as f:
                f.write(view)
        except OSError:
            pass

    def _mark_sort_column(self):
        for key, col in self.sort_columns.items():
            col.set_sort_indicator(key == self.sort_key)
            col.set_sort_order(Gtk.SortType.DESCENDING if key == "date" else Gtk.SortType.ASCENDING)

    def on_sort_changed(self, combo):
        self.sort_key = combo.get_active_id()
        self._mark_sort_column()
        try:
            with open(SORT_FILE, "w") as f:
                f.write(self.sort_key)
        except OSError:
            pass
        self.refresh()

    def _update_empty(self):
        empty = len(self.store) == 0 and not self.pending
        self.missing.set_visible(empty)
        self.sort_bar.set_visible(not empty)
        self.stack.set_visible(not empty)

    def refresh(self):
        entries = [e for e in civ.favorites_list() if os.path.exists(e[0])]
        entries.sort(key=SORT_MODES[self.sort_key][1])
        wanted = [e[0] for e in entries]
        self.added = {e[0]: e[1] for e in entries}
        self.captions = {e[0]: e[2] for e in entries}
        signature = [(e[0], e[2]) for e in entries]
        if signature == self.signature:
            return
        self.signature = signature
        # Rebuilding keeps the chosen order; the cached thumbnails are quick.
        self.store.clear()
        self.pending = wanted
        if wanted:
            GLib.idle_add(self._load_next)
        self._update_empty()

    def _load_next(self):
        if not self.pending:
            self._update_empty()
            return False
        path = self.pending.pop(0)
        try:
            pixbuf = _cached_thumbnail(path) or _generated_thumbnail(path)
        except Exception:
            pixbuf = None
        if pixbuf is not None:
            name, ext = os.path.splitext(os.path.basename(path))
            scale = LIST_THUMB / max(pixbuf.get_width(), pixbuf.get_height())
            small = pixbuf.scale_simple(max(1, round(pixbuf.get_width() * scale)),
                                        max(1, round(pixbuf.get_height() * scale)), GdkPixbuf.InterpType.BILINEAR)
            added = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.added.get(path, 0)))
            caption = self.captions.get(path, "")
            self.store.append([path, name, pixbuf, os.path.dirname(path), ext.lstrip(".").upper(), added, small,
                               caption, caption or name])
        self._update_empty()
        return True

    def on_row_activated(self, _view, tree_path, _column):
        self.on_activated(_view, tree_path)

    def on_activated(self, _view, tree_path):
        path = self.store[tree_path][0]
        # Inherits this process's sandbox, which is the viewer's own.
        subprocess.Popen([sys.executable, VIEWER_SCRIPT, path], start_new_session=True)

    def on_key_press(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False


def main():
    FavoritesWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
