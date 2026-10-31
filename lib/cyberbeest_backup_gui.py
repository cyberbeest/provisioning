#!/usr/bin/env python3
"""Cyberbeest Backup: graphical full-disk backup and restore.

Both run as root through pkexec + cyberbeest-backup-helper.sh /
cyberbeest-restore-helper.sh (installed by 73-cyberbeest-backup.sh). The
backup is locked with the computer's master password. The helpers speak the
@@STAGE@@/@@PROGRESS@@/@@WARN@@/@@ERROR@@/@@DONE@@ line protocol documented in
cyberbeest-backup-common.sh; this window only renders it.
"""
import json
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from i18n import t  # noqa: E402

LIBDIR = "/usr/local/lib/cyberbeest"
BACKUP_HELPER = f"{LIBDIR}/cyberbeest-backup-helper.sh"
RESTORE_HELPER = f"{LIBDIR}/cyberbeest-restore-helper.sh"
EXTRACT_HELPER = f"{LIBDIR}/cyberbeest-extract-helper.sh"
STAGES = {
    "backup": ["check", "container", "boot", "image", "verify", "finish"],
    "restore": ["check", "partition", "boot", "encryption", "system", "finish"],
    "extract": ["check", "unpack", "mount"],
}


def fmt_gb(n):
    return f"{int(n) / 1e9:.0f} GB"


def list_disks():
    """Whole disks as (path, label), excluding the one holding the running system."""
    try:
        out = subprocess.run(
            ["lsblk", "-J", "-b", "-o", "PATH,TYPE,SIZE,MODEL,TRAN,RM,MOUNTPOINTS"],
            capture_output=True, text=True, timeout=10).stdout
        devs = json.loads(out)["blockdevices"]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return []
    disks = []
    for d in devs:
        if d.get("type") != "disk":
            continue
        def mounts(n):
            m = [x for x in (n.get("mountpoints") or []) if x]
            for c in n.get("children") or []:
                m += mounts(c)
            return m
        if "/" in mounts(d):
            continue
        kind = t("backup.disk_external") if (d.get("tran") == "usb" or d.get("rm")) else t("backup.disk_internal")
        model = (d.get("model") or "").strip()
        disks.append((d["path"], f"{model} {fmt_gb(d['size'])} – {kind} ({d['path']})".strip()))
    return disks


class BackupWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("backup.title"))
        self.set_default_size(720, 640)
        self.set_border_width(12)
        self.proc = None
        self.mode = None
        self.stage_labels = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(root)

        self.notebook = Gtk.Notebook()
        root.pack_start(self.notebook, False, False, 0)
        self.notebook.append_page(self._backup_page(), Gtk.Label(label=t("backup.tab_backup")))
        self.notebook.append_page(self._restore_page(), Gtk.Label(label=t("backup.tab_restore")))
        self.notebook.append_page(self._extract_page(), Gtk.Label(label=t("backup.tab_extract")))

        self.stage_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        root.pack_start(self.stage_row, False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_text(t("backup.idle"))
        root.pack_start(self.progress, False, False, 0)
        self.status = Gtk.Label(xalign=0, wrap=True)
        root.pack_start(self.status, False, False, 0)

        self.ready_box = Gtk.Box(spacing=8)
        self.open_btn = Gtk.Button(label=t("backup.open_files"))
        self.open_btn.connect("clicked", self.on_open_files)
        self.finish_btn = Gtk.Button(label=t("backup.finish"))
        self.finish_btn.connect("clicked", self.on_finish)
        self.ready_box.pack_start(self.open_btn, False, False, 0)
        self.ready_box.pack_start(self.finish_btn, False, False, 0)
        root.pack_start(self.ready_box, False, False, 0)
        self.view_mount = None

        sw = Gtk.ScrolledWindow()
        sw.set_vexpand(True)
        self.log = Gtk.TextView(editable=False, monospace=True)
        self.log.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sw.add(self.log)
        root.pack_start(sw, True, True, 0)

        self.cancel_btn = Gtk.Button(label=t("backup.cancel"))
        self.cancel_btn.set_sensitive(False)
        self.cancel_btn.connect("clicked", self.on_cancel)
        root.pack_start(self.cancel_btn, False, False, 0)
        self.connect("delete-event", self.on_delete)

    # ---------------------------------------------------------------- pages
    def _label(self, text, markup=False):
        l = Gtk.Label(xalign=0, wrap=True)
        (l.set_markup if markup else l.set_text)(text)
        return l

    def _pw_entry(self):
        e = Gtk.Entry(visibility=False, activates_default=False)
        return e

    def _backup_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        box.pack_start(self._label(t("backup.backup_intro")), False, False, 0)
        box.pack_start(self._label(t("backup.dest_folder")), False, False, 0)
        self.dest_chooser = Gtk.FileChooserButton(title=t("backup.dest_folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        media = f"/media/{os.environ.get('USER', 'cyberbeest')}"
        try:
            first = sorted(os.listdir(media))[0]
            self.dest_chooser.set_current_folder(os.path.join(media, first))
        except (OSError, IndexError):
            pass
        box.pack_start(self.dest_chooser, False, False, 0)
        box.pack_start(self._label(t("backup.master_password")), False, False, 0)
        self.backup_pw = self._pw_entry()
        box.pack_start(self.backup_pw, False, False, 0)
        box.pack_start(self._label(t("backup.master_note")), False, False, 0)
        if self._on_battery():
            box.pack_start(self._label(t("backup.battery_warning")), False, False, 0)
        self.backup_btn = Gtk.Button(label=t("backup.start_backup"))
        self.backup_btn.connect("clicked", self.on_backup)
        box.pack_start(self.backup_btn, False, False, 0)
        return box

    def _restore_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        box.pack_start(self._label(t("backup.restore_intro")), False, False, 0)
        if self._on_installed_system():
            box.pack_start(self._label(t("backup.restore_installed_hint")), False, False, 0)
        box.pack_start(self._label(t("backup.source_folder")), False, False, 0)
        self.src_chooser = Gtk.FileChooserButton(title=t("backup.source_folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        box.pack_start(self.src_chooser, False, False, 0)
        box.pack_start(self._label(t("backup.target_disk")), False, False, 0)
        row = Gtk.Box(spacing=6)
        self.disk_combo = Gtk.ComboBoxText()
        row.pack_start(self.disk_combo, True, True, 0)
        refresh = Gtk.Button(label=t("backup.refresh"))
        refresh.connect("clicked", lambda *_: self.fill_disks())
        row.pack_start(refresh, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(self._label(t("backup.master_password_restore")), False, False, 0)
        self.restore_pw = self._pw_entry()
        box.pack_start(self.restore_pw, False, False, 0)
        self.restore_btn = Gtk.Button(label=t("backup.start_restore"))
        self.restore_btn.connect("clicked", self.on_restore)
        box.pack_start(self.restore_btn, False, False, 0)
        self.fill_disks()
        return box

    def _extract_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        box.pack_start(self._label(t("backup.extract_intro")), False, False, 0)
        box.pack_start(self._label(t("backup.source_folder")), False, False, 0)
        self.ex_src = Gtk.FileChooserButton(title=t("backup.source_folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        box.pack_start(self.ex_src, False, False, 0)
        box.pack_start(self._label(t("backup.scratch_folder")), False, False, 0)
        self.ex_scratch = Gtk.FileChooserButton(title=t("backup.scratch_folder"), action=Gtk.FileChooserAction.SELECT_FOLDER)
        media = f"/media/{os.environ.get('USER', 'cyberbeest')}"
        try:
            self.ex_scratch.set_current_folder(os.path.join(media, sorted(os.listdir(media))[0]))
        except (OSError, IndexError):
            pass
        box.pack_start(self.ex_scratch, False, False, 0)
        box.pack_start(self._label(t("backup.master_password_restore")), False, False, 0)
        self.ex_pw = self._pw_entry()
        box.pack_start(self.ex_pw, False, False, 0)
        self.extract_btn = Gtk.Button(label=t("backup.start_extract"))
        self.extract_btn.connect("clicked", self.on_extract)
        box.pack_start(self.extract_btn, False, False, 0)
        return box

    def fill_disks(self):
        self.disk_combo.remove_all()
        self.disks = list_disks()
        for path, label in self.disks:
            self.disk_combo.append(path, label)
        if self.disks:
            self.disk_combo.set_active(0)

    @staticmethod
    def _on_battery():
        try:
            for n in os.listdir("/sys/class/power_supply"):
                if n.startswith(("AC", "ADP")):
                    with open(f"/sys/class/power_supply/{n}/online") as f:
                        return f.read().strip() == "0"
        except OSError:
            pass
        return False

    @staticmethod
    def _on_installed_system():
        try:
            with open("/proc/cmdline") as f:
                return "boot=live" not in f.read()
        except OSError:
            return True

    # -------------------------------------------------------------- running
    def set_busy(self, busy):
        for w in (self.backup_btn, self.restore_btn, self.extract_btn, self.notebook):
            w.set_sensitive(not busy)
        self.cancel_btn.set_sensitive(busy)

    def append_log(self, text):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        self.log.scroll_to_mark(buf.get_insert(), 0, False, 0, 0)

    def build_stage_row(self, mode):
        for c in self.stage_row.get_children():
            self.stage_row.remove(c)
        self.stage_labels = []
        for key in STAGES[mode]:
            l = Gtk.Label()
            l.set_markup(f'<span foreground="#8a8a8a">{GLib.markup_escape_text(t("backup.stage_" + key))}</span>')
            self.stage_row.pack_start(l, True, True, 0)
            self.stage_labels.append((key, l))
        self.stage_row.show_all()

    def run_helper(self, mode, helper, args, password):
        self.mode = mode
        self.result = None
        self.view_mount = None
        self.ready_box.hide()
        self.finish_btn.set_sensitive(True)
        self.build_stage_row(mode)
        self.log.get_buffer().set_text("")
        self.status.set_text("")
        self.progress.set_fraction(0)
        self.progress.set_text(t("backup.starting"))
        self.set_busy(True)
        try:
            self.proc = subprocess.Popen(["pkexec", helper] + args, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            self.proc.stdin.write(password + "\n")
            self.proc.stdin.flush()
        except OSError as e:
            self.finish(1, str(e))
            return
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        for line in self.proc.stdout:
            GLib.idle_add(self.on_line, line.rstrip("\n"))
        rc = self.proc.wait()
        GLib.idle_add(self.finish, rc, None)

    def on_line(self, line):
        if line.startswith("@@STAGE@@ "):
            _, idx, total, key = line.split(" ", 3)
            self.mark_stage(key)
            self.progress.set_fraction(0)
            self.progress.set_text(t("backup.stage_" + key))
        elif line.startswith("@@PROGRESS@@ "):
            try:
                pct = float(line.split(" ", 1)[1])
                self.progress.set_fraction(pct / 100)
                self.progress.set_text(f"{pct:.0f} %")
            except ValueError:
                pass
        elif line.startswith("@@WARN@@ "):
            code, _, detail = line[9:].partition(" ")
            self.append_log(self.message(code, detail, warn=True))
        elif line.startswith("@@ERROR@@ "):
            code, _, detail = line[10:].partition(" ")
            self.result = ("error", self.message(code, detail))
        elif line.startswith("@@READY@@ "):
            self.view_mount = line[10:]
            self.progress.set_fraction(1)
            self.progress.set_text(t("backup.finished"))
            self.status.set_text(t("backup.extract_ready"))
            self.ready_box.show_all()
            self.cancel_btn.set_sensitive(False)
        elif line.startswith("@@DONE@@ "):
            self.result = ("done", line[9:])
        else:
            self.append_log(line)
        return False

    def mark_stage(self, current):
        seen = True
        for key, l in self.stage_labels:
            if key == current:
                color, seen = "#2b78e4", False
            else:
                color = "#2a9d3f" if seen else "#8a8a8a"
            l.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(t("backup.stage_" + key))}</span>')

    def message(self, code, detail, warn=False):
        text = t(("backup.warn." if warn else "backup.err.") + code)
        if text.startswith("backup."):
            text = code
        return f"{text} ({detail})" if detail and not detail.startswith("(") else text

    def finish(self, rc, err):
        self.set_busy(False)
        self.proc = None
        self.ready_box.hide()
        if self.mode == "extract" and self.view_mount and not (self.result and self.result[0] == "error"):
            self.view_mount = None
            self.progress.set_text(t("backup.idle"))
            self.status.set_text("")
            return False
        if self.result and self.result[0] == "done" and rc == 0:
            self.progress.set_fraction(1)
            self.progress.set_text(t("backup.finished"))
            key = "backup.done_backup" if self.mode == "backup" else "backup.done_restore"
            self.status.set_markup(f'<span foreground="#2a9d3f">{GLib.markup_escape_text(t(key))}</span>\n{GLib.markup_escape_text(self.result[1])}')
        else:
            msg = (self.result[1] if self.result else None) or err or t("backup.err.generic")
            self.progress.set_text(t("backup.failed"))
            self.status.set_markup(f'<span foreground="#c62828">{GLib.markup_escape_text(msg)}</span>')
        return False

    # ------------------------------------------------------------- handlers
    def on_backup(self, _btn):
        dest = self.dest_chooser.get_filename()
        pw = self.backup_pw.get_text()
        if not dest or not pw:
            self.status.set_text(t("backup.need_folder_and_password"))
            return
        self.run_helper("backup", BACKUP_HELPER, [dest], pw)
        self.backup_pw.set_text("")

    def on_restore(self, _btn):
        src = self.src_chooser.get_filename()
        disk = self.disk_combo.get_active_id()
        pw = self.restore_pw.get_text()
        if not src or not disk or not pw:
            self.status.set_text(t("backup.need_restore_fields"))
            return
        label = self.disk_combo.get_active_text()
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE, text=t("backup.confirm_title"))
        dlg.format_secondary_text(t("backup.confirm_body").replace("{disk}", label or disk))
        box = dlg.get_content_area()
        entry = Gtk.Entry(placeholder_text=t("backup.confirm_word"))
        box.pack_start(entry, False, False, 6)
        dlg.add_button(t("backup.cancel"), Gtk.ResponseType.CANCEL)
        ok = dlg.add_button(t("backup.start_restore"), Gtk.ResponseType.OK)
        ok.set_sensitive(False)
        entry.connect("changed", lambda e: ok.set_sensitive(e.get_text().strip().upper() == t("backup.confirm_word").upper()))
        dlg.show_all()
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        self.run_helper("restore", RESTORE_HELPER, [src, disk], pw)
        self.restore_pw.set_text("")

    def on_extract(self, _btn):
        src = self.ex_src.get_filename()
        scratch = self.ex_scratch.get_filename()
        pw = self.ex_pw.get_text()
        if not src or not scratch or not pw:
            self.status.set_text(t("backup.need_extract_fields"))
            return
        self.run_helper("extract", EXTRACT_HELPER, [src, scratch], pw)
        self.ex_pw.set_text("")

    def on_open_files(self, _btn):
        if self.view_mount:
            subprocess.Popen(["xdg-open", self.view_mount])

    def on_finish(self, _btn):
        self.finish_btn.set_sensitive(False)
        try:
            self.proc.stdin.write("close\n")
            self.proc.stdin.flush()
        except (OSError, AttributeError):
            pass

    def on_cancel(self, _btn):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write("cancel\n")
                self.proc.stdin.flush()
            except OSError:
                pass
            self.status.set_text(t("backup.cancelling"))

    def on_delete(self, *_):
        if self.proc and self.proc.poll() is None and not self.view_mount:
            dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                    buttons=Gtk.ButtonsType.YES_NO, text=t("backup.close_while_running"))
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.YES:
                return True
        return False  # closing the window closes the helper's stdin, which stops it


def main():
    win = BackupWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    win.ready_box.hide()
    Gtk.main()


if __name__ == "__main__":
    main()
