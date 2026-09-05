#!/usr/bin/env python3
"""Cyberbeest Wipe App Data.

Lets the user pick one or more known apps and erase all of that app's
local data (config, cache, chat history, wallet files, browsing data --
whatever the app's firejail sandbox whitelists as its own, since that's
exactly the app's data footprint). Reads the path table from
app-data-paths.conf (installed alongside this script).

Only apps with data to wipe or that are currently installed are listed --
an app the user never installed doesn't show up just because it's in the
path table, but leftover data from a non-purge `apt remove` still does.

Why plain delete is enough here, no multi-pass "secure" overwrite: this
machine's disk is fully LUKS-encrypted, so a deleted file's leftover
blocks are just ciphertext without the key -- shred-style overwriting is
both unnecessary and actually unreliable on ext4+SSD anyway (journaling
can retain copies; wear-leveling means the physical cells overwritten
usually aren't the ones that held the old data). Reclaiming the freed
blocks at the SSD-controller level is handled by the system's existing
weekly fstrim.timer, not by this tool.

Every entry but i2pd is a plain user-owned path under $HOME, deleted
directly with no privilege escalation. i2pd's data lives under
/var/lib/i2pd (a system service account), so that one entry stops the
service, deletes as root via pkexec, and restarts it -- pkexec rather
than the dev machine's RUNME/sudo-helper flow, since this tool ships to
end-user machines that don't have that helper running.
"""

import glob
import os
import shlex
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

CONF_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "app-data-paths.conf")

HOME = os.path.realpath(os.path.expanduser("~"))


def _is_safe_target(p):
    """Refuse anything that isn't clearly inside $HOME or the i2pd state
    dir -- a static-config typo (a bare path, an unresolved glob, a stray
    "/") should never turn into an `rm -rf` of something huge."""
    rp = os.path.realpath(p)
    if rp in ("/", HOME):
        return False
    if rp.startswith(HOME + os.sep):
        return True
    if rp.startswith("/var/lib/i2pd" + os.sep) or rp == "/var/lib/i2pd":
        return True
    return False


class App:
    def __init__(self, app_id, name, paths, proc_pattern, dpkg_package=""):
        self.id = app_id
        self.name = name
        self.paths = paths  # list of raw path strings (may include ~ and globs)
        self.proc_pattern = proc_pattern
        self.dpkg_package = dpkg_package

    def is_installed(self):
        """Whether the app package is currently installed (not just
        removed-with-leftover-data). Used to decide whether to list the
        app at all when it has no data yet -- see load_apps()/filtering
        in WipeAppDataWindow. No package configured = never considered
        "installed" by this check; such an app still shows up in the list
        if it has data."""
        if not self.dpkg_package:
            return False
        r = subprocess.run(
            ["dpkg-query", "-W", "-f=${Status}", self.dpkg_package],
            capture_output=True, text=True,
        )
        return r.returncode == 0 and "install ok installed" in r.stdout

    def resolved_paths(self):
        """Expand ~ and globs to actual existing paths on disk."""
        out = []
        for raw in self.paths:
            if raw.startswith("~") or os.path.isabs(raw):
                expanded = os.path.expanduser(raw)
            else:
                expanded = os.path.join(os.path.expanduser("~"), raw)
            if any(ch in expanded for ch in "*?["):
                out.extend(glob.glob(expanded))
            elif os.path.exists(expanded):
                out.append(expanded)
        return out

    def is_running(self):
        if self.id == "i2pd":
            r = subprocess.run(["systemctl", "is-active", "i2pd"], capture_output=True, text=True)
            return r.stdout.strip() == "active"
        if not self.proc_pattern:
            return False
        r = subprocess.run(["pgrep", "-f", self.proc_pattern], capture_output=True)
        return r.returncode == 0

    def close(self, timeout=8):
        """Best-effort: ask a running instance to quit, then force-kill if
        it's still around after `timeout` seconds. i2pd is handled inside
        plan_commands()'s own pkexec script (systemctl stop), not here."""
        if self.id == "i2pd" or not self.proc_pattern or not self.is_running():
            return True
        subprocess.run(["pkill", "-TERM", "-f", self.proc_pattern])
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.is_running():
                return True
            time.sleep(0.3)
        subprocess.run(["pkill", "-KILL", "-f", self.proc_pattern])
        time.sleep(0.5)
        return not self.is_running()

    def size_locked(self):
        """True if this app's real size can't be determined as the
        current user -- i.e. its data lives under a root/service-account
        path this user isn't in the group for (i2pd's /var/lib/i2pd:
        most of its state files are 750/640 owned by the i2pd user/group,
        not readable by a normal desktop user). size_bytes() would report
        0 for these regardless of actual size, which is indistinguishable
        from genuinely empty -- callers should show that distinction
        rather than mislabeling it "empty"."""
        return self.id == "i2pd"

    def size_bytes(self):
        total = 0
        for p in self.resolved_paths():
            r = subprocess.run(["du", "-sb", p], capture_output=True, text=True)
            if r.returncode == 0:
                try:
                    total += int(r.stdout.split()[0])
                except (ValueError, IndexError):
                    pass
        return total


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def load_apps():
    apps = []
    with open(CONF_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            while len(parts) < 5:
                parts.append("")
            app_id, name, paths_raw, proc_pattern, dpkg_package = parts[:5]
            paths = paths_raw.split() if paths_raw else []
            apps.append(App(app_id, name, paths, proc_pattern, dpkg_package))
    return apps


def load_listable_apps():
    """Apps worth showing at all: ones with data to wipe, or ones
    currently installed (even with no data yet) -- so a fresh install
    still shows up, and leftover data from a non-purge `apt remove`
    remains wipeable, but an app never installed on this machine doesn't
    clutter the list."""
    return [app for app in load_apps() if app.size_bytes() > 0 or app.is_installed()]


I2PD_SCRIPT = (
    "systemctl stop i2pd || true; "
    "rm -rf /var/lib/i2pd/*.dat /var/lib/i2pd/*.crt /var/lib/i2pd/netDb "
    "/var/lib/i2pd/peerProfiles /var/lib/i2pd/addressbook /var/lib/i2pd/destinations; "
    "systemctl start i2pd || true"
)


def plan_commands(app):
    """The exact argv command(s) wipe_app() will run for this app, right
    now, given what's actually on disk. This is shown to the user verbatim
    in the confirmation dialog -- display and execution must never diverge,
    so wipe_app() below executes exactly this list and nothing else."""
    if app.id == "i2pd":
        if not os.path.isdir("/var/lib/i2pd"):
            return []
        return [["pkexec", "bash", "-c", I2PD_SCRIPT]]
    cmds = []
    for p in app.resolved_paths():
        if not _is_safe_target(p):
            raise ValueError(f"refusing unsafe target outside $HOME: {p}")
        cmds.append(["rm", "-rf", "--", p])
    return cmds


def format_commands(cmds):
    return "\n".join(shlex.join(c) for c in cmds)


def wipe_app(app):
    """Close the app if running, then execute plan_commands(app) verbatim.
    Returns (ok, message)."""
    if not app.close():
        return False, "Could not close the running app -- not wiped, try again after closing it manually"

    try:
        cmds = plan_commands(app)
    except ValueError as e:
        return False, str(e)

    if not cmds:
        return True, "No data present"

    errors = []
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"{shlex.join(cmd)}: {r.stderr.strip() or r.stdout.strip()}")
    if errors:
        return False, "; ".join(errors)
    if app.id == "i2pd":
        return True, "Wiped (router identity, netDb, and known destinations reset)"
    return True, f"Wiped ({len(cmds)} path(s))"


class WipeRow(Gtk.ListBoxRow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(4)

        self.check = Gtk.CheckButton()
        box.pack_start(self.check, False, False, 0)

        name = Gtk.Label(label=app.name)
        name.set_xalign(0)
        name.set_width_chars(16)
        box.pack_start(name, False, False, 0)

        size = app.size_bytes()
        locked = app.size_locked()
        if locked:
            self.size_label = Gtk.Label(label="root-locked")
            self.size_label.set_tooltip_text(
                "This app's data is owned by a system service account -- its "
                "real size can't be checked as your user, only wiped (which "
                "will prompt for the root password)."
            )
        else:
            self.size_label = Gtk.Label(label=human_size(size) if size else "empty")
        self.size_label.set_xalign(0)
        self.size_label.set_width_chars(10)
        box.pack_start(self.size_label, False, False, 0)

        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        box.pack_start(self.status_label, True, True, 0)

        if size == 0 and not locked:
            self.check.set_sensitive(False)
        elif app.is_running():
            self.status_label.set_markup('<span foreground="#a60">running -- will be closed automatically</span>')

        self.add(box)


class WipeAppDataWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Wipe App Data")
        self.set_default_size(520, 480)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_border_width(10)
        self.add(root)

        intro = Gtk.Label(
            label="Select apps to erase all local data for (chat history, wallet files, "
                  "browsing data, etc). Running apps are closed automatically first. "
                  "This cannot be undone.",
            wrap=True,
        )
        intro.set_xalign(0)
        root.pack_start(intro, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(self.listbox)
        root.pack_start(scroller, True, True, 0)

        self.rows = []
        for app in load_listable_apps():
            row = WipeRow(app)
            self.listbox.add(row)
            self.rows.append(row)
        self.listbox.show_all()

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _b: self.refresh())
        btn_box.pack_start(refresh_btn, False, False, 0)

        wipe_btn = Gtk.Button(label="Wipe Selected")
        wipe_btn.get_style_context().add_class("destructive-action")
        wipe_btn.connect("clicked", self._on_wipe_clicked)
        btn_box.pack_end(wipe_btn, False, False, 0)
        root.pack_start(btn_box, False, False, 0)

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self.rows = []
        for app in load_listable_apps():
            row = WipeRow(app)
            self.listbox.add(row)
            self.rows.append(row)
        self.listbox.show_all()

    def _confirm(self, selected):
        """Show exactly what's about to run -- the literal rm/pkexec
        commands, not just app names -- so nothing gets deleted on trust
        alone. Returns True iff the user clicked Wipe."""
        lines = []
        running_names = []
        for row in selected:
            if row.app.is_running():
                running_names.append(row.app.name)
            try:
                cmds = plan_commands(row.app)
            except ValueError as e:
                lines.append(f"# {row.app.name}: ERROR -- {e}")
                continue
            if not cmds:
                lines.append(f"# {row.app.name}: nothing to do")
                continue
            lines.append(f"# {row.app.name}")
            lines.extend(shlex.join(c) for c in cmds)
            lines.append("")

        dialog = Gtk.Dialog(title="Confirm wipe", transient_for=self, modal=True)
        dialog.set_default_size(560, 360)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        wipe_button = dialog.add_button("Wipe", Gtk.ResponseType.OK)
        wipe_button.get_style_context().add_class("destructive-action")

        content = dialog.get_content_area()
        content.set_border_width(10)
        content.set_spacing(6)

        header = Gtk.Label(label="These commands are about to run. This cannot be undone.", wrap=True)
        header.set_xalign(0)
        content.pack_start(header, False, False, 0)

        if running_names:
            note = Gtk.Label(
                label="Currently running, will be closed first: " + ", ".join(running_names),
                wrap=True,
            )
            note.set_xalign(0)
            note.get_style_context().add_class("dim-label")
            content.pack_start(note, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.get_buffer().set_text("\n".join(lines).strip())
        scroller.add(view)
        content.pack_start(scroller, True, True, 0)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _on_wipe_clicked(self, _btn):
        selected = [r for r in self.rows if r.check.get_active()]
        if not selected:
            return

        if not self._confirm(selected):
            return

        for row in selected:
            row.status_label.set_text("closing app if running, then wiping...")
            while Gtk.events_pending():
                Gtk.main_iteration()
            ok, message = wipe_app(row.app)
            if ok:
                row.status_label.set_markup(f'<span foreground="#080">{GLib.markup_escape_text(message)}</span>')
                row.check.set_active(False)
                row.check.set_sensitive(False)
                row.size_label.set_text("empty")
            else:
                row.status_label.set_markup(f'<span foreground="#c00">{GLib.markup_escape_text(message)}</span>')
            while Gtk.events_pending():
                Gtk.main_iteration()


def main():
    win = WipeAppDataWindow()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
