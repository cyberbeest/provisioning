#!/usr/bin/env python3
"""Whitelisted Folders.

One global list of extra folders that every sandboxed (firejail) app --
browser, messengers, wallets -- is allowed to see, on top of its own data
plus Downloads and Pictures.

How it works: firejail profiles all `include globals.local`, which firejail
looks up in ~/.config/firejail/ before /etc/firejail/. This tool owns one
marked block inside that user-level file (the jailed apps themselves can't
reach it -- their $HOME is private) and keeps the list itself in
~/.config/cyberbeest/shared-folders.conf. Anything the user adds to
globals.local outside the marked block is left alone.

Downloads and Pictures are ordinary entries too, stored as firejail's own
${DOWNLOADS} / ${PICTURES} macros rather than as paths: firejail resolves
them from the user's XDG settings at every app start, so a changed system
language or a renamed/moved XDG folder needs no rewriting of anything here.
(Seeded, so
nothing changes for existing users). They used to be hard-coded in the
per-app profiles; now, if one is removed, the block adds an
`ignore whitelist ${DOWNLOADS}` / `${PICTURES}` line to cancel the stock
profiles' own whitelisting. (Our per-app .local files are read *before*
globals.local, so they carry no Downloads/Pictures lines any more.)

Why the guardrails: a bad line in globals.local makes *every* jailed app
fail to start, and a shared folder is only worth anything if it can't hand
over keys or app data. So a folder is checked with realpath (a symlink
picked in the file chooser resolves to its real target first), hidden
folders and $HOME itself are refused, and the final line is dry-run through
firejail before it is saved. A symlink *inside* a shared folder that points
elsewhere is harmless -- the target isn't mounted in the jail, so it simply
doesn't resolve there.
"""

import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from i18n import t  # noqa: E402

HOME = os.path.realpath(os.path.expanduser("~"))
USER = os.path.basename(HOME)
CONF_PATH = os.path.join(HOME, ".config", "cyberbeest", "shared-folders.conf")
GLOBALS_LOCAL = os.path.join(HOME, ".config", "firejail", "globals.local")
BEGIN = "# BEGIN cyberbeest shared folders (managed by Whitelisted Folders -- do not edit)"
END = "# END cyberbeest shared folders"

# Outside $HOME, only removable-media / mount locations make sense.
EXTERNAL_ROOTS = ("/media", "/mnt", "/run/media")


class RefusedFolder(Exception):
    """The chosen folder can't be shared; str(e) is a user-facing reason."""


def check_folder(path):
    """Return the resolved path if it may be shared, else raise RefusedFolder."""
    if "\n" in path or "${" in path:
        raise RefusedFolder(t("sharedfolders.err_chars"))
    rp = os.path.realpath(path)
    if not os.path.isdir(rp):
        raise RefusedFolder(t("sharedfolders.err_not_dir"))
    if rp == HOME or HOME.startswith(rp.rstrip(os.sep) + os.sep) or rp == "/":
        raise RefusedFolder(t("sharedfolders.err_home"))
    if rp.startswith(HOME + os.sep):
        first = rp[len(HOME) + 1:].split(os.sep)[0]
        if first.startswith("."):
            raise RefusedFolder(t("sharedfolders.err_hidden"))
        return rp
    if any(rp.startswith(r + os.sep) for r in EXTERNAL_ROOTS):
        return rp
    raise RefusedFolder(t("sharedfolders.err_location"))


def dry_run(path):
    """True if firejail accepts the whitelist line for PATH. A path firejail
    rejects would otherwise be saved and then break every jailed app."""
    try:
        r = subprocess.run(
            ["firejail", "--noprofile", "--quiet", "--whitelist=" + path, "true"],
            capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _xdg_dir(kind, fallback):
    try:
        r = subprocess.run(["xdg-user-dir", kind], capture_output=True,
                           text=True, timeout=10)
        p = r.stdout.strip()
        if r.returncode == 0 and p:
            return os.path.realpath(p)
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(os.path.join(HOME, fallback))


# firejail macro -> the real folder it stands for (localized on e.g. German
# machines: ~/Bilder). These two start out shared.
def default_dirs():
    return {"${DOWNLOADS}": _xdg_dir("DOWNLOAD", "Downloads"),
            "${PICTURES}": _xdg_dir("PICTURES", "Pictures")}


def resolve(key):
    """The real folder an entry key stands for (a macro or a plain path)."""
    return default_dirs().get(key, key)


def key_for(path):
    """Entry key for a resolved PATH: the macro if it is a default folder."""
    for macro, real in default_dirs().items():
        if real == path:
            return macro
    return path


def default_entries():
    out = []
    for macro, real in default_dirs().items():
        try:
            check_folder(real)
        except RefusedFolder:
            continue
        out.append(macro)
    return out


def load_entries():
    """Entry keys (macro or absolute path) from the conf file; silently
    drops bad lines. Every share is read-write; an old "ro\tPATH"/"rw\tPATH"
    line is read as just PATH. No conf file at all means "never configured":
    the default shares."""
    if not os.path.exists(CONF_PATH):
        return default_entries()
    out = []
    try:
        with open(CONF_PATH) as f:
            for line in f:
                p = line.rstrip("\n").rpartition("\t")[2]
                if p and (p in default_dirs() or os.path.isabs(p)) and p not in out:
                    out.append(p)
    except OSError:
        pass
    return out


def _ancestors_in_home(p):
    """Folders strictly between $HOME and P, outermost first ([] outside $HOME)."""
    if not p.startswith(HOME + os.sep):
        return []
    parts = p[len(HOME) + 1:].split(os.sep)[:-1]
    return [os.path.join(HOME, *parts[:i + 1]) for i in range(len(parts))]


def render_block(entries):
    lines = [BEGIN]
    for p in entries:
        # noblacklist: stock profiles blacklist the XDG folders (Documents,
        # Videos, ...) and the blacklist wins over a plain whitelist -- and
        # a blacklisted *parent* blocks the child too, so every ancestor up
        # to $HOME is listed. The whitelist below still limits what's
        # visible to the shared folder itself.
        for anc in _ancestors_in_home(p):  # [] for the macro keys
            lines.append("noblacklist " + anc)
        lines.append("noblacklist " + p)
        lines.append("whitelist " + p)
    for macro in default_dirs():
        if macro not in entries:
            lines.append("ignore whitelist " + macro)
    lines.append(END)
    return "\n".join(lines) + "\n"


def _strip_block(text):
    out, skipping = [], False
    for line in text.splitlines():
        if line == BEGIN:
            skipping = True
        elif skipping and line == END:
            skipping = False
        elif not skipping:
            out.append(line)
    return out


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def save_entries(entries):
    """Persist ENTRIES and rewrite the managed block in globals.local."""
    _atomic_write(CONF_PATH, "".join(p + "\n" for p in entries))
    try:
        with open(GLOBALS_LOCAL) as f:
            rest = _strip_block(f.read())
    except OSError:
        rest = []
    while rest and not rest[-1].strip():
        rest.pop()
    text = "\n".join(rest) + ("\n" if rest else "")
    text += ("\n" if rest else "") + render_block(entries)
    _atomic_write(GLOBALS_LOCAL, text)


# Counting stops here so a huge tree (an external drive) can't spin forever;
# the row then shows e.g. "500,000+ files".
COUNT_CAP = 500_000


def _plural(n, noun, plus=""):
    """"1 folder", "2 folders", "500,000+ files" (translated forms)."""
    form = "one" if n == 1 and not plus else "many"
    return t("sharedfolders.%s_%s" % (noun, form)).format(n=f"{n:,}{plus}")


def count_tree(path, cancel, progress):
    """Walk PATH without following symlinks, calling progress(folders, files,
    done, capped) about 4x/s. PATH itself counts as one folder; a symlink
    counts as a file and isn't followed."""
    folders, files = 1, 0  # the shared folder itself counts
    last = 0.0
    for _root, dirs, names in os.walk(path, followlinks=False,
                                      onerror=lambda e: None):
        if cancel.is_set():
            return
        folders += len(dirs)
        files += len(names)
        if folders + files >= COUNT_CAP:
            progress(folders, files, True, True)
            return
        now = time.monotonic()
        if now - last > 0.25:
            last = now
            progress(folders, files, False, False)
    progress(folders, files, True, False)


# Jailed apps, as `firejail --list` reports them: (substring of the command
# line, label shown to the user, launcher that starts it jailed again, extra
# arguments for the relaunch after a restart).
BIN = os.path.join(HOME, "bin")
LOCAL_BIN = os.path.join(HOME, ".local", "bin")
JAILED_APPS = [
    ("/usr/bin/firefox-esr", "Firefox", os.path.join(BIN, "browser-sandbox.sh"), []),
    ("/usr/bin/google-chrome-stable", "Chrome", os.path.join(BIN, "chrome-sandbox.sh"),
     ["--restore-last-session"]),  # reopen the tabs it had
    ("/opt/Signal/signal-desktop", "Signal", os.path.join(BIN, "signal-sandbox.sh"), []),
    ("/opt/Element/element-desktop", "Element", os.path.join(BIN, "element-sandbox.sh"), []),
    ("/usr/bin/telegram-desktop", "Telegram", os.path.join(BIN, "telegram-sandbox.sh"), []),
    ("/opt/viber/Viber", "Viber", os.path.join(BIN, "viber-sandbox.sh"), []),
    ("/opt/sparrowwallet/bin/Sparrow", "Sparrow", os.path.join(BIN, "sparrow-sandbox.sh"), []),
    ("/usr/bin/feather", "Feather", os.path.join(LOCAL_BIN, "feather-wrapper.sh"), []),
]
QUIT_WAIT_S = 10   # how long an app gets to quit on its own before it is forced
SETTLE_S = 2       # pause before relaunch (Feather's wrapper stops Tor on exit)


def running_apps():
    """{label: (launcher, [firejail pids], relaunch args)} for the jailed apps
    running now."""
    try:
        out = subprocess.run(["firejail", "--list"], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        pid, _, rest = line.partition(":")
        if not pid.isdigit():
            continue
        for needle, label, launcher, args in JAILED_APPS:
            if needle in rest:
                found.setdefault(label, (launcher, [], args))[1].append(int(pid))
                break
    return found


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Notifier:
    """One desktop notification, updated in place for each step (the same
    `notify-send -p -r` pattern as lock-warning-watcher.sh)."""

    def __init__(self):
        self.nid = None

    def __call__(self, text):
        cmd = ["notify-send", "-p", "-u", "low", "-a", t("sharedfolders.window_title"),
               "-i", ICON_PATH, "-t", "4000"]
        if self.nid:
            cmd += ["-r", self.nid]
        cmd += [t("sharedfolders.window_title"), text]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
            if out.isdigit():
                self.nid = out
        except (OSError, subprocess.SubprocessError):
            pass  # notifications are a courtesy, never a reason to fail


def restart_apps(apps, notify=lambda text: None):
    """Quit each app politely (SIGTERM, so it can save its state), force it
    only after QUIT_WAIT_S, then start it again through its jailed launcher.
    NOTIFY(text) is called at every step. Blocking; run it in a thread.
    Returns the labels that were restarted."""
    import signal
    done = []
    for label, (launcher, pids, args) in apps.items():
        notify(t("sharedfolders.step_closing").format(app=label))
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + QUIT_WAIT_S
        while time.monotonic() < deadline and any(_alive(p) for p in pids):
            time.sleep(0.25)
        for pid in pids:
            if _alive(pid):
                subprocess.run(["firejail", "--shutdown=%d" % pid],
                               capture_output=True, timeout=15)
        time.sleep(SETTLE_S)
        if os.access(launcher, os.X_OK):
            notify(t("sharedfolders.step_starting").format(app=label))
            subprocess.Popen([launcher, *args], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            done.append(label)
    notify(t("sharedfolders.step_done").format(n=len(done)) if done
           else t("sharedfolders.step_none"))
    return done


import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib  # noqa: E402

# Must happen before Gtk is imported: GTK builds the window class from the
# program name at startup, and without this the window manager shows the
# script filename (alt+tab, taskbar grouping). The menu entry's
# StartupWMClass refers to this name.
GLib.set_prgname("whitelisted-folders")
GLib.set_application_name(t("sharedfolders.window_title"))

from gi.repository import GdkPixbuf, Gtk  # noqa: E402

ICON_PATH = os.path.join(HOME, ".local", "share", "cyberbeest", "icons", "Cyberbeest-black.png")

COL_PATH, COL_SUMMARY, COL_FOLDERS, COL_FILES, COL_KEY, COL_OK = range(6)


class SharedFoldersWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("sharedfolders.window_title"))
        self.set_default_size(640, 420)
        # Pre-scaled: the window system drops the 1024 px source image when
        # it's handed over as one big icon.
        try:
            self.set_icon_list([GdkPixbuf.Pixbuf.new_from_file_at_size(ICON_PATH, n, n)
                                for n in (16, 32, 48, 64, 128)])
        except GLib.Error:
            pass  # missing icon file: the window just gets no logo
        self.counters = {}  # path -> cancel Event of its running count
        self.entries = load_entries()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(10)
        self.add(root)

        intro = Gtk.Label(label=t("sharedfolders.intro"))
        intro.set_line_wrap(True)
        intro.set_xalign(0)
        root.pack_start(intro, False, False, 0)

        self.store = Gtk.ListStore(str, str, int, int, str, bool)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(True)

        col = Gtk.TreeViewColumn(t("sharedfolders.col_folder"), Gtk.CellRendererText(),
                                 text=COL_PATH, sensitive=COL_OK)
        col.set_expand(True)
        col.set_resizable(True)
        self.view.append_column(col)
        self.view.append_column(Gtk.TreeViewColumn(
            t("sharedfolders.col_contents"), Gtk.CellRendererText(),
            text=COL_SUMMARY, sensitive=COL_OK))

        scroll = Gtk.ScrolledWindow()
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self.view)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        add = Gtk.Button(label="+")
        add.set_tooltip_text(t("sharedfolders.add_tip"))
        add.set_size_request(36, 36)
        add.connect("clicked", self.on_add)
        remove = Gtk.Button(label="\u2212")
        remove.set_tooltip_text(t("sharedfolders.remove_tip"))
        remove.set_size_request(36, 36)
        remove.connect("clicked", self.on_remove)
        side.pack_start(add, False, False, 0)
        side.pack_start(remove, False, False, 0)

        listrow = Gtk.Box(spacing=6)
        listrow.pack_start(scroll, True, True, 0)
        listrow.pack_start(side, False, False, 0)
        root.pack_start(listrow, True, True, 0)

        self.status = Gtk.Label(label="", xalign=0)
        self.status.set_no_show_all(True)
        self._hide_status_timeout = None
        root.pack_start(self.status, False, False, 0)

        # Always available (changed folders only reach apps when they start
        # again); with nothing running, the button just says so.
        self.restart_row = Gtk.Box(spacing=8)
        note = Gtk.Label(label=t("sharedfolders.restart_note"))
        note.set_xalign(0)
        self.restart_row.pack_start(note, False, False, 0)
        self.restart_btn = Gtk.Button(label=t("sharedfolders.restart_btn"))
        self.restart_btn.connect("clicked", self.on_restart)
        self.restart_row.pack_start(self.restart_btn, False, False, 0)
        root.pack_start(self.restart_row, False, False, 0)
        GLib.timeout_add_seconds(5, self.refresh_presence_tick)

        for key in self.entries:
            self.store.append([resolve(key), t("sharedfolders.counting"), 0, 0, key, True])
        self.connect("destroy", self.on_destroy)
        self.connect("focus-in-event", lambda *_: self.recount_all())
        self.recount_all()

    # -- counting -----------------------------------------------------------
    def recount_all(self):
        for row in self.store:
            self.start_count(row[COL_PATH])
        return False

    def start_count(self, path):
        old = self.counters.pop(path, None)
        if old:
            old.set()
        # A folder that is gone (deleted, drive unplugged) stays in the list
        # as a greyed-out non-share -- firejail simply skips a whitelist line
        # for a missing path -- and counts again once it is back.
        if not os.path.isdir(path):
            self.mark_missing(path)
            return
        cancel = threading.Event()
        self.counters[path] = cancel

        def progress(folders, files, done, capped):
            GLib.idle_add(self.update_row, path, cancel, folders, files, done, capped)

        threading.Thread(target=count_tree, args=(path, cancel, progress), daemon=True).start()

    def mark_missing(self, path):
        for row in self.store:
            if row[COL_PATH] == path:
                row[COL_OK] = False
                row[COL_SUMMARY] = t("sharedfolders.missing")
                row[COL_FOLDERS] = row[COL_FILES] = 0

    def refresh_presence(self):
        """Flip rows between normal and 'not found' as folders come and go."""
        for row in self.store:
            exists = os.path.isdir(row[COL_PATH])
            if exists and not row[COL_OK]:
                row[COL_OK] = True
                row[COL_SUMMARY] = t("sharedfolders.counting")
                self.start_count(row[COL_PATH])
            elif not exists and row[COL_OK]:
                self.start_count(row[COL_PATH])  # cancels the count, marks missing

    def update_row(self, path, cancel, folders, files, done, capped):
        if cancel.is_set():
            return False
        for row in self.store:
            if row[COL_PATH] == path:
                row[COL_OK] = True
                plus = "+" if capped else ""
                text = t("sharedfolders.count").format(
                    folders=_plural(folders, "folder", plus),
                    files=_plural(files, "file", plus))
                row[COL_SUMMARY] = text if done else text + " \u2026"
                row[COL_FOLDERS], row[COL_FILES] = folders, files
                break
        return False

    # -- actions ------------------------------------------------------------
    def persist(self):
        self.entries = [r[COL_KEY] for r in self.store]
        save_entries(self.entries)

    def refresh_presence_tick(self):
        self.refresh_presence()
        return True  # keep the 5 s timer going

    def on_restart(self, _btn):
        apps = running_apps()
        if not apps:
            self.flash(t("sharedfolders.none_running"))
            return
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              text=t("sharedfolders.restart_q"))
        d.format_secondary_text(", ".join(apps) + "\n\n" + t("sharedfolders.restart_warn"))
        d.add_buttons(t("sharedfolders.cancel"), Gtk.ResponseType.CANCEL,
                      t("sharedfolders.restart_do"), Gtk.ResponseType.OK)
        resp = d.run()
        d.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        self.restart_btn.set_sensitive(False)

        def work():
            restart_apps(apps, Notifier())
            GLib.idle_add(self.restart_finished)

        threading.Thread(target=work, daemon=True).start()

    def restart_finished(self):
        self.restart_btn.set_sensitive(True)
        self.flash(t("sharedfolders.restarted"))
        return False

    def flash(self, text):
        """Green confirmation under the list, hidden again after 3 s (same
        pattern as the panel-color GUI)."""
        self.status.set_markup(f'<span foreground="#2a9d3f">{GLib.markup_escape_text(text)}</span>')
        self.status.set_no_show_all(False)
        self.status.show()
        if self._hide_status_timeout is not None:
            GLib.source_remove(self._hide_status_timeout)
        self._hide_status_timeout = GLib.timeout_add_seconds(3, self._hide_status)

    def _hide_status(self):
        self.status.hide()
        self._hide_status_timeout = None
        return False

    def error(self, text):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.OK, text=text)
        d.run()
        d.destroy()

    def on_add(self, _btn):
        chooser = Gtk.FileChooserDialog(
            title=t("sharedfolders.choose"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.add_buttons(t("sharedfolders.cancel"), Gtk.ResponseType.CANCEL,
                            t("sharedfolders.share"), Gtk.ResponseType.OK)
        chooser.set_current_folder(HOME)
        resp, picked = chooser.run(), chooser.get_filename()
        chooser.destroy()
        if resp != Gtk.ResponseType.OK or not picked:
            return
        try:
            path = check_folder(picked)
        except RefusedFolder as e:
            self.error(str(e))
            return
        if any(r[COL_PATH] == path for r in self.store):
            return
        if not dry_run(path):
            self.error(t("sharedfolders.err_firejail"))
            return
        # key_for: re-adding Downloads/Pictures stores the macro again, the
        # same as the seeded default.
        self.store.append([path, t("sharedfolders.counting"), 0, 0, key_for(path), True])
        self.persist()
        self.start_count(path)
        self.flash(t("sharedfolders.added"))

    def on_remove(self, _btn):
        model, it = self.view.get_selection().get_selected()
        if not it:
            return
        cancel = self.counters.pop(model[it][COL_PATH], None)
        if cancel:
            cancel.set()
        model.remove(it)
        self.persist()
        self.flash(t("sharedfolders.removed"))

    def on_destroy(self, *_):
        for c in self.counters.values():
            c.set()
        Gtk.main_quit()


if __name__ == "__main__":
    if "--seed" in sys.argv:
        # Headless, run by 44a-shared-folders.sh: write the default shares
        # (Downloads, Pictures) the first time only, so the per-app profiles
        # -- which no longer hard-code them -- keep sharing them.
        if not os.path.exists(CONF_PATH):
            save_entries(default_entries())
        sys.exit(0)
    win = SharedFoldersWindow()
    win.show_all()
    Gtk.main()
