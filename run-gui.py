#!/usr/bin/env python3
"""GUI front-end for the NN-*.sh provisioning scripts.

It lists every NN-*.sh script in a sidebar (with a status:
pending/done/running/failed, "done" meaning its .log is newer than the
script itself), and runs each one directly as its
own `sudo -A bash NN-*.sh` subprocess, streaming its output into the shared
log view on the right and updating that script's sidebar status as it goes.

"Run all" / "Run changed only" walk the whole list; double-clicking a single
row in the sidebar runs just that script (handy for debugging one step),
regardless of whether it's already marked done. The sidebar also supports
native multi-select (plain click, ctrl+click to toggle, shift+click for a
range) for picking an arbitrary subset to run via "Run selected" -- handy
for e.g. re-running a few specific steps without doing the whole sequence.
Only one run -- whole sequence, selected subset, or single script -- can be
active at a time.

Each script keeps its own log text (self.logs, keyed by script name, plus a
"" bucket for messages not tied to any one script, like the zenity-install
step). Single-clicking a row just selects it and shows its stored log --
GtkListBox activates rows on a single click by default, which used to mean
single-clicking accidentally started a run; activate-on-single-click is
explicitly disabled so double-click is required for that, freeing up
single-click to be a safe, non-disruptive "view this script's log" action,
including while a run is active elsewhere. Selecting the row that's
currently running resumes live-following it (self.follow_live); selecting
any other row shows a frozen snapshot without interrupting or hiding the
active run, which keeps updating that script's stored log in the
background regardless of what's currently displayed. This log-viewing
behavior only kicks in when exactly one row ends up selected (a plain
click): ctrl/shift-click selections of more than one row, built up for
"Run selected", leave whatever log was last shown alone rather than trying
to guess which of several scripts to display.

No batch-level xfce4-panel reload here:
the only two scripts that touch panel config, 11-xfce-panel-plugins.sh and
12-xfce-panel-layout.sh, already reload the panel themselves.

Scripts in NEEDS_TERMINAL (currently just 00-locale-keyboard-timezone.sh)
use whiptail, which needs a real controlling terminal to draw its menus --
piping its stdout/stderr into our log view like every other script breaks
that. Those are instead opened in an xterm window (still elevated via the
same graphical sudo prompt) and we block until it closes, rather than
streaming their output into the shared log pane. Deliberately xterm, not
xfce4-terminal: xfce4-terminal is a D-Bus single-instance app, so a new
invocation can silently hand its command off to an already-running
xfce4-terminal (e.g. the one run-gui.py itself was launched from) and exit
immediately -- no window appears and we stop "blocking" before the command
even starts. xterm has no such client/server model, so it can't do that.

xterm also doesn't reliably propagate the wrapped command's own exit status
as its own -- it exits 0 on normal termination regardless of how the command
inside it fared -- so _run_in_terminal captures the real exit code to a temp
file from inside the shell instead of trusting xterm's proc.returncode.

Requires zenity (for the graphical sudo prompt). On a brand new machine that
hasn't run any NN-*.sh script yet, zenity may not be installed at all (it's
only otherwise pulled in as a side effect of 04-software-launch-warning.sh)
-- checked for at startup and installed automatically if missing, via an
explicit xterm window (same technique as _run_in_terminal below) rather than
prompting on whatever terminal happened to launch this tool: since
beestify.sh's autostart flow launches this from inside an
`xfce4-terminal --hold` window that sits behind the GTK window once this
tool takes over, a plain background sudo prompt there would be invisible to
whoever's just looking at the GTK app.

Only prompts for the sudo password once per run of run-gui.py, not once per
script: the first sudo call uses zenity-askpass.sh as normal, but run-gui.py
runs that same helper directly itself first (see _get_sudo_password) to grab
the typed password into memory, then points every later sudo -A call at
cached-askpass.sh instead, which just echoes that cached password back
rather than popping a fresh dialog. (Relying on sudo's own timestamp/ticket
cache instead wasn't reliable here -- each script subprocess runs in its own
new session via start_new_session=True below, and tty_tickets-style caching
keys off exactly that kind of session/tty identity, so it kept re-prompting
every script instead of reusing the earlier authentication.) If a cached
password turns out to be stale (e.g. the user changed it mid-run), the
resulting sudo failure clears it so the next attempt re-prompts.

Every script subprocess gets stdin=DEVNULL and start_new_session=True: without
those, a script inherits run-gui.py's own stdin/process group -- i.e. the
terminal it was launched from, if any -- and a subprocess still alive when
the window is closed can be left holding that terminal's controlling tty,
making it look frozen even though it's really just an orphaned background
process waiting to read from a tty nothing will ever type into again.

Dev tool only (not shipped to end users), so unlike lib/*.py it doesn't use
lib/i18n.py.

Things-to-do pane: a handful of scripts can't fully finish themselves --
either because a step is genuinely a human choice (18-desktop-background.sh
deliberately doesn't auto-select a wallpaper, see its own comments for why)
or because the change only takes effect after a logout/reboot
(00-locale-keyboard-timezone.sh, and more generally most config scripts per
their own "log out/in or reboot to pick this up" comments). Rather than
these getting mentioned once in a scrolling log and then forgotten, any
script can emit a line matching `MANUAL_TODO: <text>` on stdout and it gets
pulled into a persistent "Things to do" pane above the log view, keyed by
script name so a later re-run of the same script replaces rather than
duplicates its entry. For NEEDS_TERMINAL scripts, whose output isn't
streamed into the log view live, the log file is re-read for MANUAL_TODO
lines after the terminal window closes instead.

Separately, finishing a full "Run all" / "Run changed only" batch (not a
single-script debug run via double-click) adds its own "reboot to fully
apply everything" entry to the same pane with a one-click Reboot Now button
-- consolidating the various per-script "needs a reboot" comments into a
single action at the end of provisioning instead of the user having to
reboot after every script or hunt through the log for whether one is
needed.
"""
import glob
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zoneinfo

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

DIR = os.path.dirname(os.path.realpath(__file__))
ASKPASS = os.path.join(DIR, "lib", "zenity-askpass.sh")
CACHED_ASKPASS = os.path.join(DIR, "lib", "cached-askpass.sh")

NEEDS_TERMINAL = {"00-locale-keyboard-timezone.sh", "00a-touchpad-tap-global.sh"}

# Scripts driven by the upfront "Provisioning profile" dialog (see
# ProvisioningProfileDialog) instead of their own whiptail prompts. Once the
# dialog has been answered, both scripts run piped like every other step --
# they only need NEEDS_TERMINAL's xterm/whiptail treatment when no profile
# has been collected (e.g. run standalone via menu.sh, or the dialog was
# cancelled).
PROFILE_SCRIPTS = {"00-locale-keyboard-timezone.sh", "00a-touchpad-tap-global.sh"}

# Where the collected profile answers are handed to 00-/00a-. A plain file
# rather than environment variables: sudo's default env_reset policy strips
# arbitrary env vars from the escalated command (only SUDO_ASKPASS and
# friends survive, since those are consumed by sudo itself before the
# reset), but a file in this directory is trivially readable by root once
# the script is running as root anyway. Not sensitive data (locale/keyboard/
# timezone/touchpad choices), so no special permissions needed; removed on
# exit purely for tidiness, see RunGuiWindow.on_destroy.
PROFILE_FILE = os.path.join(DIR, ".provisioning-profile.env")

# code|Display name|default language (en/de)|en locale|de locale|keyboard layout|default IANA timezone
# Keep in sync with 00-locale-keyboard-timezone.sh's own COUNTRIES array --
# that script's interactive whiptail path (used when no profile was
# collected) is the source of truth this mirrors.
PROFILE_COUNTRIES = [
    ("DE", "Germany", "de", "en_US.UTF-8", "de_DE.UTF-8", "de", "Europe/Berlin"),
    ("AT", "Austria", "de", "en_US.UTF-8", "de_AT.UTF-8", "at", "Europe/Vienna"),
    ("CH", "Switzerland", "de", "en_US.UTF-8", "de_CH.UTF-8", "ch", "Europe/Zurich"),
    ("US", "United States", "en", "en_US.UTF-8", "de_DE.UTF-8", "us", "America/New_York"),
    ("GB", "United Kingdom", "en", "en_GB.UTF-8", "de_DE.UTF-8", "gb", "Europe/London"),
    ("IE", "Ireland", "en", "en_IE.UTF-8", "de_DE.UTF-8", "gb", "Europe/Dublin"),
    ("CA", "Canada", "en", "en_CA.UTF-8", "de_DE.UTF-8", "us", "America/Toronto"),
    ("AU", "Australia", "en", "en_AU.UTF-8", "de_DE.UTF-8", "us", "Australia/Sydney"),
    ("NZ", "New Zealand", "en", "en_NZ.UTF-8", "de_DE.UTF-8", "us", "Pacific/Auckland"),
    ("XE", "Other (default: English UI)", "en", "en_US.UTF-8", "de_DE.UTF-8", "us", "UTC"),
    ("XD", "Other (default: German UI)", "de", "en_US.UTF-8", "de_DE.UTF-8", "de", "UTC"),
]

XKB_BASE_LST = "/usr/share/X11/xkb/rules/base.lst"

# Small fallback used only if XKB_BASE_LST is missing (shouldn't happen --
# x11-xkb-utils is installed by 00-locale-keyboard-timezone.sh itself, and
# this dialog isn't shown before that point). Codes match the country
# defaults in PROFILE_COUNTRIES above.
FALLBACK_KEYBOARDS = [
    ("de", "German"),
    ("at", "German (Austria)"),
    ("ch", "German (Switzerland)"),
    ("us", "English (US)"),
    ("gb", "English (UK)"),
]


def load_keyboard_layouts():
    # Full xkb layout list (~100 entries, not just the 5 Cyberbeest markets)
    # -- the installer should be able to pick any keyboard layout even for a
    # UI language Cyberbeest doesn't ship a translation catalog for yet.
    # base.lst's "! layout" section is one "<code>  <description>" pair per
    # line; sorted by description so the searchable combo below reads
    # naturally when typing a country/language name.
    try:
        layouts = []
        in_section = False
        with open(XKB_BASE_LST) as f:
            for line in f:
                if line.startswith("! layout"):
                    in_section = True
                    continue
                if line.startswith("!"):
                    in_section = False
                    continue
                if in_section and line.strip():
                    code, _, name = line.strip().partition(" ")
                    layouts.append((code, name.strip()))
        if layouts:
            return sorted(layouts, key=lambda row: row[1])
    except OSError:
        pass
    return FALLBACK_KEYBOARDS

# Scripts whose effects are hard to walk back (or actively dangerous to run
# on a machine you're still debugging over SSH) get a confirmation dialog
# right before they run, even inside a "Run all"/"Run changed only" batch.
NEEDS_CONFIRMATION = {
    "99-remove-openssh-server.sh": (
        "This permanently removes the SSH server and wipes every user's "
        "authorized_keys, cutting off remote SSH access to this machine.\n\n"
        "Continue?"
    ),
}

# Must match cyberbeest-bootstrap.sh's own AUTOSTART_FILE -- that's the
# fresh-install autostart entry that relaunches beestify.sh (and so this
# GUI) on every login until provisioning is complete. Deleting it directly
# is exactly what cyberbeest-bootstrap.sh itself does on a clean finish;
# see the "Disable auto-provisioning on login" button below for doing that
# manually, on purpose, before every script has run.
AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/cyberbeest-provisioning.desktop")

MANUAL_TODO_RE = re.compile(r"^MANUAL_TODO:\s*(.+?)\s*$", re.MULTILINE)
REBOOT_TODO_KEY = "__reboot__"

STATUS_STYLE = {
    "pending": ("pending", "#8a8a8a"),
    "running": ("running...", "#2b78e4"),
    "done": ("done", "#2a9d3f"),
    "failed": ("failed", "#d43f3f"),
    "skipped": ("skipped", "#8a8a8a"),
}

# Wall-clock durations captured from a real end-to-end provisioning run
# (2026-08-31, derived from the "=== <date> : ..." timestamp on each
# script's first log line vs. the next script's), shown next to "pending"
# rows as a rough per-script estimate. Actual time on a given machine varies
# mainly with network speed (apt/pip installs) and whether packages are
# already cached -- treat these as ballpark, not a guarantee. A script not
# in this dict (e.g. one added since) just shows "pending" with no estimate.
SCRIPT_DURATION_ESTIMATES = {
    "00-locale-keyboard-timezone.sh": 37,
    "00a-touchpad-tap-global.sh": 0,
    "01-bluetooth-tethering.sh": 26,
    "02-gnome-software-store.sh": 14,
    "03-secure-messengers.sh": 176,
    "04-software-launch-warning.sh": 0,
    "05-unattended-upgrades-security.sh": 87,
    "06-vendor-origins-unattended-upgrades.sh": 52,
    "07-security-update-timer.sh": 114,
    "08-xdg-user-dirs.sh": 2,
    "09-cyberbeest-logout-dialog.sh": 2,
    "10-browser-sandbox.sh": 23,
    "11-xfce-panel-plugins.sh": 99,
    "12-xfce-panel-layout.sh": 7,
    "13-lock-shutdown-watcher.sh": 16,
    "14-user-avatar.sh": 0,
    "15-grub-plymouth-theme.sh": 67,
    "16-power-lock-config.sh": 5,
    "17-login-lock-screen.sh": 0,
    "18-desktop-background.sh": 0,
    "19-low-battery-shutdown.sh": 1,
    "20-shutdown-sound.sh": 0,
    "21-default-password-nag.sh": 9,
    "22-i2p-package-manager.sh": 2,
    "23-vlc-media-player.sh": 22,
    "24-avif-mime-default.sh": 0,
    "25-cyberbeest-panel-color.sh": 2,
    "26-lid-close-policy.sh": 3,
    "27-desktop-hotlinks.sh": 7,
    "29-wireguard-vpn-toggle.sh": 5,
    "30-lockscreen-shutdown-button.sh": 99,
    "31-disable-sleep-states.sh": 1,
    "32-minor-apt-packages.sh": 109,
    "33-rename-thunar-to-files.sh": 11,
    "35-boot-chime.sh": 3,
    "36-crypto-wallets.sh": 47,
    "37-encrypted-dns.sh": 20,
    "38-jail-messengers.sh": 2,
    "39-feather-tor-ondemand.sh": 2,
    "40-jail-wallets-viber.sh": 2,
    "41-bookmark-seeder.sh": 3,
    "42-security-watch.sh": 17,
    "43-intrusion-watch.sh": 3,
    "44-wipe-app-data.sh": 2,
    "45-hide-redundant-terminals.sh": 1,
    "46-cyberbeest-keyboard-shortcuts.sh": 0,
    "47-set-max-volume.sh": 0,
    "48-whisker-menu-categories.sh": 0,
    "49-whisker-category-cleanup.sh": 1,
    "50-i2pd-default.sh": 281,
}


def list_scripts():
    # [0-9][0-9][a-z]?-*.sh: the optional trailing letter lets a script slot
    # in right after an existing NN- step (e.g. 00a- runs between 00- and
    # 01-) without renumbering everything after it. '-' (0x2D) sorts before
    # any letter, so "00-..." still sorts before "00a-..." before "01-...".
    return sorted(
        os.path.basename(p)
        for pattern in ("[0-9][0-9]-*.sh", "[0-9][0-9][a-z]-*.sh")
        for p in glob.glob(os.path.join(DIR, pattern))
    )


def log_path_for(script):
    return os.path.join(DIR, script[:-3] + ".log")


def script_is_done(script):
    log = log_path_for(script)
    script_path = os.path.join(DIR, script)
    return os.path.exists(log) and os.path.getmtime(log) > os.path.getmtime(script_path)


def format_duration(seconds):
    seconds = round(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds}s"


class ScriptRow(Gtk.ListBoxRow):
    def __init__(self, script):
        super().__init__()
        self.script = script

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_border_width(4)
        self.add(box)

        name_label = Gtk.Label(label=script, xalign=0)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(name_label, True, True, 0)

        self.status_label = Gtk.Label(label="", xalign=1)
        box.pack_start(self.status_label, False, False, 0)

        if script_is_done(script):
            self.set_status("done")
        else:
            self.set_status("pending", estimate=SCRIPT_DURATION_ESTIMATES.get(script))

    def set_status(self, state, duration=None, estimate=None):
        text, color = STATUS_STYLE[state]
        if duration is not None:
            text = f"{text} ({format_duration(duration)})"
        elif estimate:
            text = f"{text} (~{format_duration(estimate)})"
        self.status_label.set_markup(f'<span foreground="{color}">{GLib.markup_escape_text(text)}</span>')


class ProvisioningProfileDialog(Gtk.Dialog):
    """Collects every per-installer answer (country/language/keyboard/menu-key
    remap/timezone/touchpad tuning) in one place upfront, so
    00-locale-keyboard-timezone.sh and 00a-touchpad-tap-global.sh can run
    straight through without popping their own whiptail prompts mid-run.
    Named "Provisioning profile" (not just "settings") since a longer
    question list down the road is expected to turn this into a set of
    reusable named profiles rather than a one-off form -- see run-gui.py's
    PROFILE_SCRIPTS/PROFILE_COUNTRIES for the rest of this design's context.
    """

    def __init__(self, parent, previous=None):
        super().__init__(title="Provisioning profile", transient_for=parent, modal=True)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            "_Continue", Gtk.ResponseType.OK,
        )
        self.set_default_size(480, -1)
        self.answers = None

        box = self.get_content_area()
        box.set_border_width(12)
        box.set_spacing(10)

        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        box.pack_start(grid, False, False, 0)
        row = 0

        def add_row(label_text, widget):
            nonlocal row
            label = Gtk.Label(label=label_text, xalign=0)
            grid.attach(label, 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
            row += 1

        prev = previous or {}

        self.country_combo = Gtk.ComboBoxText()
        for code, name, *_rest in PROFILE_COUNTRIES:
            self.country_combo.append(code, name)
        # "changed" is wired up below, once every widget it touches
        # (keyboard/language/timezone) actually exists.
        add_row("Country:", self.country_combo)

        self.lang_en = Gtk.RadioButton.new_with_label_from_widget(None, "English")
        self.lang_de = Gtk.RadioButton.new_with_label_from_widget(self.lang_en, "Deutsch (German)")
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lang_box.pack_start(self.lang_en, False, False, 0)
        lang_box.pack_start(self.lang_de, False, False, 0)
        add_row("UI language:", lang_box)

        # Free-text combo (not a fixed radiolist like the old whiptail
        # dialog): the full ~100-entry xkb layout list, searchable by
        # country/language name, but also accepting any raw xkb layout code
        # typed directly -- a UI language Cyberbeest doesn't ship a
        # translation catalog for yet is still a real keyboard someone may
        # be typing on.
        self.keyboard_combo = Gtk.ComboBoxText.new_with_entry()
        keyboard_layouts = load_keyboard_layouts()
        self.keyboard_entry = self.keyboard_combo.get_child()
        kbd_store = Gtk.ListStore(str, str)
        for code, name in keyboard_layouts:
            label = f"{code} — {name}"
            kbd_store.append([code, label])
            # Also populate the combo's own dropdown (its arrow button opens
            # this list independently of the type-ahead completion below) --
            # without this it renders as an empty list.
            self.keyboard_combo.append(code, label)

        def kbd_combo_selected(combo):
            # The dropdown (unlike the completion popup's match-selected
            # below) has no hook to rewrite what lands in the entry, so a
            # row picked here would otherwise leave the full "code — name"
            # label in the entry instead of just the raw code.
            idx = combo.get_active()
            if idx >= 0:
                self.keyboard_entry.set_text(combo.get_active_id())
                self.keyboard_entry.set_position(-1)

        self.keyboard_combo.connect("changed", kbd_combo_selected)

        kbd_completion = Gtk.EntryCompletion()
        kbd_completion.set_model(kbd_store)
        kbd_completion.set_text_column(1)
        kbd_completion.set_popup_completion(True)

        def kbd_match_selected(_completion, model, treeiter):
            # set_text_column above drives what the popup *shows* ("de --
            # German"), but the entry (and so the final answer) should only
            # ever hold the raw layout code -- fill it in ourselves instead
            # of letting GTK insert the display text verbatim.
            self.keyboard_entry.set_text(model[treeiter][0])
            self.keyboard_entry.set_position(-1)
            return True

        kbd_completion.connect("match-selected", kbd_match_selected)
        self.keyboard_entry.set_completion(kbd_completion)
        self.keyboard_entry.connect("changed", self._on_keyboard_changed)
        add_row("Keyboard layout:", self.keyboard_combo)

        self.menu_key_remap = Gtk.CheckButton(
            label="Remap Menu key to </>/| (canonical Cyberbeest hardware only, German keyboard)"
        )
        self.menu_key_remap.set_active(prev.get("PROVISIONING_MENU_KEY_REMAP") == "yes")
        add_row("", self.menu_key_remap)

        self.tz_combo = Gtk.ComboBoxText.new_with_entry()
        for tz in sorted(zoneinfo.available_timezones()):
            self.tz_combo.append_text(tz)
        tz_entry = self.tz_combo.get_child()
        completion = Gtk.EntryCompletion()
        tz_store = Gtk.ListStore(str)
        for tz in sorted(zoneinfo.available_timezones()):
            tz_store.append([tz])
        completion.set_model(tz_store)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_popup_completion(True)
        tz_entry.set_completion(completion)
        add_row("Timezone:", self.tz_combo)

        self.touchpad_tuning = Gtk.CheckButton(
            label="Apply Cyberbeest touchpad tuning (tap-to-click everywhere, "
            "sensitivity/scrolling dialed in on reference hardware)"
        )
        self.touchpad_tuning.set_active(prev.get("PROVISIONING_TOUCHPAD_TUNING", "yes") != "no")
        add_row("Touchpad:", self.touchpad_tuning)

        # Now that every widget exists, wire up the country "changed" signal
        # and seed language/keyboard/timezone from the previous answers if
        # there were any, else derive them from the country default like the
        # whiptail flow does.
        self.country_combo.connect("changed", self._on_country_changed)
        self.country_combo.set_active_id(prev.get("PROVISIONING_COUNTRY", "US"))
        self._on_country_changed(self.country_combo, initial=True)
        if prev.get("PROVISIONING_LANG") == "de":
            self.lang_de.set_active(True)
        elif prev.get("PROVISIONING_LANG") == "en":
            self.lang_en.set_active(True)
        if prev.get("PROVISIONING_KEYBOARD"):
            self.keyboard_entry.set_text(prev["PROVISIONING_KEYBOARD"])
        if prev.get("PROVISIONING_TIMEZONE"):
            tz_entry.set_text(prev["PROVISIONING_TIMEZONE"])

        box.show_all()

    def _country_row(self, code):
        for row in PROFILE_COUNTRIES:
            if row[0] == code:
                return row
        return None

    def _on_country_changed(self, _combo, initial=False):
        row = self._country_row(self.country_combo.get_active_id())
        if not row:
            return
        _code, _name, default_lang, _en_loc, _de_loc, kbd_default, tz_default = row
        # Only push the country's defaults onto language/keyboard/timezone
        # the first time (dialog open, or a fresh country pick) -- doesn't
        # clobber an explicit override the user already made to those fields
        # on a later "changed" signal from something else.
        if initial or not self.keyboard_entry.get_text().strip():
            self.keyboard_entry.set_text(kbd_default)
        if initial:
            if default_lang == "de":
                self.lang_de.set_active(True)
            else:
                self.lang_en.set_active(True)
            self.tz_combo.get_child().set_text(tz_default)

    def _on_keyboard_changed(self, _entry):
        is_de = self.keyboard_entry.get_text().strip() == "de"
        self.menu_key_remap.set_sensitive(is_de)
        if not is_de:
            self.menu_key_remap.set_active(False)

    def collect(self):
        """Runs the dialog; returns an answers dict (see PROFILE_SCRIPTS'
        env-var contract with the two shell scripts) or None if cancelled."""
        response = self.run()
        if response != Gtk.ResponseType.OK:
            self.destroy()
            return None

        country_code = self.country_combo.get_active_id()
        row = self._country_row(country_code)
        lang_choice = "de" if self.lang_de.get_active() else "en"
        locale = (row[4] if lang_choice == "de" else row[3]) if row else "en_US.UTF-8"
        answers = {
            "PROVISIONING_PROFILE": "1",
            "PROVISIONING_COUNTRY": country_code or "",
            "PROVISIONING_LANG": lang_choice,
            "PROVISIONING_LOCALE": locale,
            "PROVISIONING_KEYBOARD": self.keyboard_entry.get_text().strip() or "us",
            "PROVISIONING_MENU_KEY_REMAP": "yes" if self.menu_key_remap.get_active() else "no",
            "PROVISIONING_TIMEZONE": self.tz_combo.get_child().get_text().strip() or "UTC",
            "PROVISIONING_TOUCHPAD_TUNING": "yes" if self.touchpad_tuning.get_active() else "no",
        }
        self.destroy()
        return answers


class RunGuiWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Provisioning Runner")
        self.set_default_size(920, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", self.on_destroy)

        self.proc = None
        self.busy = False
        self.stop_requested = False
        self.tick_source_id = None
        self.current_script_start = None
        self.rows = {}
        self.sudo_password = None
        self.logs = {"": ""}
        self.displayed_script = ""
        self.currently_running_script = None
        self.follow_live = True
        self.todos = {}
        # Answers dict from ProvisioningProfileDialog.collect(), or None if
        # it hasn't been shown yet (or was cancelled) -- see _ensure_profile.
        self.profile_env = None
        self.current_run_is_batch = False
        self.queue_total = 0
        self.queue_done = 0
        # Sum of individual script durations run in this session -- not
        # wall-clock time since the window opened (which would also count
        # idle time sitting on this screen doing nothing), and deliberately
        # not persisted across restarts of run-gui.py itself.
        self.session_total_seconds = 0.0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_border_width(12)
        self.add(root)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(button_box, False, False, 0)

        self.run_changed_button = Gtk.Button(label="Run changed only")
        self.run_changed_button.connect("clicked", lambda _b: self.start_sequence(changed_only=True))
        button_box.pack_start(self.run_changed_button, False, False, 0)

        self.run_all_button = Gtk.Button(label="Run all")
        self.run_all_button.connect("clicked", lambda _b: self.start_sequence(changed_only=False))
        button_box.pack_start(self.run_all_button, False, False, 0)

        self.run_selected_button = Gtk.Button(label="Run selected")
        self.run_selected_button.connect("clicked", lambda _b: self.start_selected())
        button_box.pack_start(self.run_selected_button, False, False, 0)

        self.stop_button = Gtk.Button(label="Stop after current script")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop)
        button_box.pack_start(self.stop_button, False, False, 0)

        # A small drop-down (just the triangle, no label) rather than another
        # full-size button -- this is a rare, one-off action, not something
        # that deserves the same visual weight as Run all/Run selected/Stop.
        self.more_menu_button = Gtk.MenuButton()
        self.more_menu_button.set_image(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON))
        self.more_menu_button.set_tooltip_text("More actions")
        more_menu = Gtk.Menu()
        self.disable_autostart_item = Gtk.MenuItem(label="Disable auto-provisioning on login")
        self.disable_autostart_item.set_sensitive(os.path.exists(AUTOSTART_FILE))
        self.disable_autostart_item.connect("activate", self.on_disable_autostart)
        more_menu.append(self.disable_autostart_item)
        self.edit_profile_item = Gtk.MenuItem(label="Provisioning profile...")
        self.edit_profile_item.connect("activate", lambda _mi: self._edit_profile())
        more_menu.append(self.edit_profile_item)
        more_menu.show_all()
        self.more_menu_button.set_popup(more_menu)
        button_box.pack_start(self.more_menu_button, False, False, 0)

        self.total_time_label = Gtk.Label(label="Total run time this session: 0s", xalign=1)
        button_box.pack_end(self.total_time_label, False, False, 0)

        self.status_label = Gtk.Label(label="Idle. Double-click a script below to run just that one.", xalign=0)
        status_css = Gtk.CssProvider()
        status_css.load_from_data(b"label { font-size: 200%; }")
        self.status_label.get_style_context().add_provider(status_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root.pack_start(self.status_label, False, False, 0)

        # Counts every script the worker attempts (success or failure) out of
        # the queue it was handed, not just successes -- a failed/skipped
        # script still "used up" its slot in the run. Reset to empty at
        # startup and refilled at the start of each run in _start_run().
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(True)
        root.pack_start(self.progress_bar, False, False, 0)

        self.todo_frame = Gtk.Frame(label="Things to do after the provisioning completed")
        # Hidden whenever self.todos is empty (start of day, or once every
        # entry has been dismissed) -- set_no_show_all so the later
        # self.show_all() doesn't force it visible regardless.
        self.todo_frame.set_no_show_all(True)
        self.todo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.todo_box.set_border_width(8)
        self.todo_frame.add(self.todo_box)
        root.pack_start(self.todo_frame, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(300)
        root.pack_start(paned, True, True, 0)

        self.sidebar_scroller = Gtk.ScrolledWindow()
        self.sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sidebar_scroller.set_size_request(280, -1)
        paned.pack1(self.sidebar_scroller, False, False)

        self.listbox = Gtk.ListBox()
        # MULTIPLE (not SINGLE) so plain click / ctrl+click / shift+click
        # range-select all work natively, feeding "Run selected" below.
        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        # Explicitly False: GtkListBox defaults to activating (i.e. running)
        # a row on a single click, which is not what we want here.
        self.listbox.set_activate_on_single_click(False)
        self.listbox.connect("row-activated", self.on_row_activated)
        self.listbox.connect("selected-rows-changed", self.on_selection_changed)
        self.sidebar_scroller.add(self.listbox)

        for script in list_scripts():
            row = ScriptRow(script)
            self.rows[script] = row
            self.listbox.add(row)

        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        paned.pack2(log_scroller, True, False)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        log_scroller.add(self.log_view)

        self.show_all()

        if shutil.which("zenity") is None:
            self._ensure_zenity()

    def _ensure_zenity(self):
        # On a brand new machine that hasn't run any NN-*.sh script yet,
        # zenity may not be installed (it's only pulled in as a side effect
        # of 04-software-launch-warning.sh) -- install it ourselves here
        # rather than making that a manual prerequisite, since it's tiny
        # (~35-40MB all in, mostly its GTK4/libadwaita deps that a GTK3-based
        # XFCE image wouldn't otherwise have). Plain `sudo` (not -A), since
        # zenity itself -- needed for the graphical askpass -- doesn't exist
        # yet, so this needs a real terminal to prompt on. Opened as its own
        # visible xterm window (not a background prompt on whatever terminal
        # happened to launch this tool) since that launching terminal may
        # not be what the user is actually looking at -- see class docstring.
        self.append_log("", "zenity not found -- opening a terminal window to install it (enter your sudo password there)...\n")
        self.status_label.set_text("Installing zenity -- see the terminal window...")
        self._set_controls_busy(True)
        threading.Thread(target=self._install_zenity_worker, daemon=True).start()

    def _install_zenity_worker(self):
        fd, exit_file = tempfile.mkstemp(prefix="run-gui-zenity-install-")
        os.close(fd)
        env = dict(os.environ, EXITFILE=exit_file)
        try:
            proc = subprocess.Popen(
                [
                    "xterm", "-T", "Install zenity", "-e", "bash", "-c",
                    'status=0; "$@" || status=$?; echo "$status" > "$EXITFILE"',
                    "_", "sudo", "apt-get", "-o", "DPkg::Lock::Timeout=60", "install", "-y", "zenity",
                ],
                env=env,
                start_new_session=True,
            )
            proc.wait()
            try:
                status = int(open(exit_file).read().strip())
            except (OSError, ValueError):
                status = 1
        finally:
            try:
                os.remove(exit_file)
            except OSError:
                pass
        GLib.idle_add(self._on_zenity_installed, status)

    def _on_zenity_installed(self, status):
        self._set_controls_busy(False)
        if status == 0 and shutil.which("zenity"):
            self.append_log("", "=== zenity installed ===\n")
            self.status_label.set_text("Idle. Double-click a script below to run just that one.")
        else:
            self.append_log(
                "",
                f"=== failed to install zenity (exit {status}) -- install it manually "
                "(sudo apt-get install zenity) and restart this tool ===\n",
            )
            self.status_label.set_text("zenity install failed -- see log above.")
            self.run_changed_button.set_sensitive(False)
            self.run_all_button.set_sensitive(False)
            self.listbox.set_sensitive(False)

    # -- log helpers --------------------------------------------------

    def append_log(self, script, text):
        self.logs[script] = self.logs.get(script, "") + text
        if self.displayed_script == script:
            current = self.log_buffer.get_text(
                self.log_buffer.get_start_iter(), self.log_buffer.get_end_iter(), False
            )
            if self.logs[script].startswith(current):
                # Common case: incremental insert at the end. Matters for
                # more than just efficiency -- GtkTextView treats a full
                # buffer replacement (set_text) as content changing out from
                # under it and resets/re-validates scroll position, which
                # was fighting the scroll-to-end below on any log with
                # enough lines to actually scroll (it kept snapping back
                # toward the top on every subsequent line).
                self.log_buffer.insert(self.log_buffer.get_end_iter(), text)
            else:
                # `current` isn't a prefix of the real log -- the buffer is
                # still showing show_log's synthetic "hasn't been run yet"
                # placeholder rather than actual output (e.g. right as a
                # script starts). Blindly inserting would leave that
                # placeholder line stuck at the top instead of being
                # replaced by real output, so do one full resync here; every
                # append after this one for this script takes the cheap
                # incremental path above instead.
                self.log_buffer.set_text(self.logs[script])
            # Deferred to the next idle cycle rather than called right here:
            # scroll_to_iter against a location from *this* insert/set_text
            # call measures against the TextView's pre-update layout (it
            # hasn't re-allocated for the new buffer contents yet), so the
            # scroll silently lands short of the end -- most visible on a
            # script with enough output to need scrolling at all.
            GLib.idle_add(self._scroll_log_to_end, script)
        for todo_text in MANUAL_TODO_RE.findall(text):
            self._add_todo(script, todo_text, action=self._todo_action_for(script))

    def _scroll_log_to_end(self, script):
        # By the time this idle callback runs, the user may have clicked to
        # a different row -- don't yank the view back to a script they're no
        # longer looking at.
        if self.displayed_script == script:
            end = self.log_buffer.get_end_iter()
            self.log_view.scroll_to_iter(end, 0.0, False, 0.0, 0.0)
        return GLib.SOURCE_REMOVE

    # -- things-to-do pane --------------------------------------------------

    def _add_todo(self, key, text, action=None):
        # Keyed by script (or REBOOT_TODO_KEY) so re-running a script
        # replaces its previous entry instead of piling up duplicates.
        self.todos[key] = (text, action)
        self._rebuild_todo_pane()

    def _dismiss_todo(self, key):
        self.todos.pop(key, None)
        self._rebuild_todo_pane()

    def _rebuild_todo_pane(self):
        for child in self.todo_box.get_children():
            self.todo_box.remove(child)
        for key, (text, action) in self.todos.items():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=text, xalign=0)
            label.set_line_wrap(True)
            row.pack_start(label, True, True, 0)
            if action is not None:
                action_label, callback = action
                action_button = Gtk.Button(label=action_label)
                action_button.connect("clicked", callback)
                # These are things to do only once provisioning has finished
                # (a reboot, opening desktop settings, ...) -- kept
                # unclickable while a run is still active so they can't be
                # triggered mid-run, e.g. rebooting out from under a script
                # that's still going.
                action_button.set_sensitive(not self.busy)
                row.pack_start(action_button, False, False, 0)
            dismiss_button = Gtk.Button(label="Dismiss")
            dismiss_button.connect("clicked", lambda _b, k=key: self._dismiss_todo(k))
            dismiss_button.set_sensitive(not self.busy)
            row.pack_start(dismiss_button, False, False, 0)
            self.todo_box.pack_start(row, False, False, 0)
        if self.todos:
            # set_no_show_all(True) above means show_all() would skip this
            # frame even when called directly on it -- show() + show_all()
            # on its (no-show-all-free) child box instead.
            self.todo_box.show_all()
            self.todo_frame.show()
        else:
            self.todo_frame.hide()

    def _update_todo_button_sensitivity(self):
        for row in self.todo_box.get_children():
            for child in row.get_children():
                if isinstance(child, Gtk.Button):
                    child.set_sensitive(not self.busy)

    def _todo_action_for(self, script):
        # MANUAL_TODO sources that have an obvious one-click shortcut to
        # offer alongside them right now.
        if script == "18-desktop-background.sh":
            return ("Open Desktop Settings", self._open_desktop_settings)
        if script == "21-default-password-nag.sh":
            return ("Open Passwords & Boot", self._open_password_settings)
        return None

    def _open_desktop_settings(self, _button):
        subprocess.Popen(["xfdesktop-settings"])

    def _open_password_settings(self, _button):
        subprocess.Popen([os.path.expanduser("~/.local/bin/cyberbeest-change-password")])

    def _do_reboot(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Reboot now?",
        )
        dialog.format_secondary_text("This will restart the machine immediately.")
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.YES:
            return
        self._dismiss_todo(REBOOT_TODO_KEY)
        subprocess.Popen(
            ["sudo", "-A", "-p", "", "reboot"],
            env=self._sudo_env(),
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    def show_log(self, script):
        self.displayed_script = script
        text = self.logs.get(script, "")
        if not text and script:
            # Nothing run yet *this session* -- fall back to whatever this
            # script logged last time it ran (e.g. from an earlier run-gui.py
            # session, or menu.sh), rather than just claiming there's nothing
            # to show.
            try:
                with open(log_path_for(script)) as f:
                    on_disk = f.read()
            except OSError:
                on_disk = ""
            if on_disk:
                text = f"-- {script} hasn't run in this session; showing its log from a previous run --\n\n{on_disk}"
            else:
                text = f"{script} hasn't been run yet. Double-click it to run.\n"
        self.log_buffer.set_text(text)

    def on_selection_changed(self, _listbox):
        # Only treat this as "view this script's log" when exactly one row
        # ends up selected (a plain click, or ctrl/shift-click narrowing a
        # multi-selection back down to one) -- a multi-row selection being
        # built up for "Run selected" shouldn't fight over which one log to
        # show, so it's left alone in that case.
        selected = self.listbox.get_selected_rows()
        if len(selected) != 1:
            return
        row = selected[0]
        self.show_log(row.script)
        self.follow_live = row.script == self.currently_running_script

    def _begin_script_display(self, script):
        # Fresh log for this run of the script -- doesn't touch any other
        # script's stored log, and doesn't disturb the view if the user has
        # manually navigated away to look at something else. Deliberately
        # doesn't touch listbox selection -- selection now doubles as the
        # "Run selected" picker, so auto-following the running script must
        # not silently add/remove it from whatever the user has selected.
        self.logs[script] = ""
        if self.follow_live:
            self.show_log(script)
            row = self.rows.get(script)
            if row is not None:
                self._scroll_sidebar_to(row)

    def _scroll_sidebar_to(self, row):
        # Keeps the running script visible as a batch run works through the
        # list, positioned about a quarter of the way down the sidebar
        # rather than flush with the top or bottom -- so a few scripts still
        # to come are already visible below it instead of only appearing
        # once they're about to run.
        alloc = row.get_allocation()
        if alloc.height <= 0:
            return
        adj = self.sidebar_scroller.get_vadjustment()
        page_size = adj.get_page_size()
        target = alloc.y - page_size * 0.25
        target = max(0.0, min(target, max(0.0, adj.get_upper() - page_size)))
        adj.set_value(target)

    def set_row_status(self, script, state, duration=None):
        self.rows[script].set_status(state, duration)

    def _add_session_runtime(self, seconds):
        self.session_total_seconds += seconds
        self.total_time_label.set_text(f"Total run time this session: {format_duration(self.session_total_seconds)}")

    # -- starting runs --------------------------------------------------

    def _set_controls_busy(self, busy):
        self.busy = busy
        self.run_changed_button.set_sensitive(not busy)
        self.run_all_button.set_sensitive(not busy)
        self.run_selected_button.set_sensitive(not busy)
        self.stop_button.set_sensitive(busy)
        # Existing todo entries' action/dismiss buttons are things-to-do-once
        # provisioning is done -- re-lock/unlock them for the busy state that
        # just changed, since _rebuild_todo_pane only sets sensitivity at the
        # moment a row is (re)built, not continuously.
        self._update_todo_button_sensitivity()
        # Deliberately NOT self.listbox.set_sensitive(not busy): the sidebar
        # stays clickable during a run so scripts' logs can be inspected
        # without interrupting it. on_row_activated's own busy check is what
        # stops a second run from starting concurrently.
        if busy:
            if self.tick_source_id is None:
                self.tick_source_id = GLib.timeout_add(1000, self._tick)
        elif self.tick_source_id is not None:
            GLib.source_remove(self.tick_source_id)
            self.tick_source_id = None

    def _tick(self):
        # Runs once a second while a run is active, so the current script's
        # elapsed time and the session total both visibly count up live
        # instead of only jumping when a script finishes.
        elapsed_current = time.monotonic() - self.current_script_start if self.current_script_start else 0.0
        self.total_time_label.set_text(
            f"Total run time this session: {format_duration(self.session_total_seconds + elapsed_current)}"
        )
        if self.currently_running_script:
            self.status_label.set_text(f"Running: {self.currently_running_script} ({format_duration(elapsed_current)})")
        return GLib.SOURCE_CONTINUE

    def start_sequence(self, changed_only):
        if self.busy:
            return
        scripts = list_scripts()
        if changed_only:
            scripts = [s for s in scripts if not script_is_done(s)]
            if not scripts:
                self.status_label.set_text("Nothing to run -- everything is already up to date.")
                return
        self._start_run(scripts, label="Run changed only" if changed_only else "Run all", batch=True)

    def start_selected(self):
        if self.busy:
            return
        selected = {row.script for row in self.listbox.get_selected_rows()}
        scripts = [s for s in list_scripts() if s in selected]
        if not scripts:
            self.status_label.set_text(
                "Nothing selected -- click (or ctrl/shift+click) one or more scripts below first."
            )
            return
        self.listbox.unselect_all()
        # Treated as a batch run (reboot suggestion included) since, like
        # "Run all"/"Run changed only" and unlike a single-script debug
        # double-click, this is an explicit "get these steps applied" run
        # that can span multiple scripts.
        self._start_run(scripts, label="Run selected", batch=True)

    def on_row_activated(self, _listbox, row):
        if self.busy:
            return
        # Not a batch run: a single-script debug run via double-click
        # shouldn't nag for a reboot the way finishing all of provisioning
        # does.
        self._start_run([row.script], label=f"Run {row.script}", batch=False)

    def _edit_profile(self):
        dialog = ProvisioningProfileDialog(self, previous=self.profile_env)
        answers = dialog.collect()
        if answers is not None:
            self.profile_env = answers
            with open(PROFILE_FILE, "w") as f:
                for key, value in answers.items():
                    f.write(f"{key}={value}\n")

    def _ensure_profile(self, scripts):
        # Only bother the user with the profile dialog if this run actually
        # touches one of the scripts it covers, and only once per run-gui.py
        # session -- "Provisioning profile..." in the more-actions menu
        # covers revisiting/editing it later.
        # Returns False if the run should be aborted (dialog was shown and
        # cancelled), True otherwise.
        if self.profile_env is not None:
            return True
        if not (set(scripts) & PROFILE_SCRIPTS):
            return True
        self._edit_profile()
        return self.profile_env is not None

    def _start_run(self, scripts, label, batch):
        if not self._ensure_profile(scripts):
            return
        self.current_run_is_batch = batch
        self.stop_requested = False
        self.follow_live = True
        self.logs[""] = ""
        if self.displayed_script == "":
            self.log_buffer.set_text("")
        self.status_label.set_text(f"{label}: starting (enter sudo password if prompted)...")
        self.queue_total = len(scripts)
        self.queue_done = 0
        self._update_progress()
        self._set_controls_busy(True)
        threading.Thread(target=self._worker, args=(scripts,), daemon=True).start()

    def _update_progress(self):
        if self.queue_total:
            self.progress_bar.set_fraction(self.queue_done / self.queue_total)
            self.progress_bar.set_text(f"{self.queue_done} / {self.queue_total}")
        else:
            self.progress_bar.set_fraction(0.0)
            self.progress_bar.set_text("")

    def _bump_progress(self):
        self.queue_done += 1
        self._update_progress()

    # -- running a single script --------------------------------------------------

    def _confirm(self, script, message):
        # Called from the worker thread; the dialog itself has to be built
        # and shown on the GTK main thread, so hand off via idle_add and
        # block this thread on an Event until the user answers.
        result = {}
        done = threading.Event()

        def show_dialog():
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.YES_NO,
                text=f"Run {script}?",
            )
            dialog.format_secondary_text(message)
            response = dialog.run()
            dialog.destroy()
            result["confirmed"] = response == Gtk.ResponseType.YES
            done.set()
            return False

        GLib.idle_add(show_dialog)
        done.wait()
        return result["confirmed"]

    def _get_sudo_password(self):
        if self.sudo_password is not None:
            return self.sudo_password
        result = subprocess.run([ASKPASS], stdout=subprocess.PIPE, text=True)
        password = result.stdout.rstrip("\n")
        if password:
            self.sudo_password = password
        return password or None

    def _sudo_env(self):
        env = dict(os.environ)
        password = self._get_sudo_password()
        if password:
            env["SUDO_ASKPASS"] = CACHED_ASKPASS
            env["CACHED_SUDO_PASSWORD"] = password
        else:
            # Nothing cached yet (or the dialog was cancelled) -- fall back to
            # a normal graphical prompt at the sudo level.
            env["SUDO_ASKPASS"] = ASKPASS
        return env

    def _run_piped(self, script):
        proc = subprocess.Popen(
            ["sudo", "-A", "-p", "", "bash", script],
            cwd=DIR,
            env=self._sudo_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.proc = proc
        for line in proc.stdout:
            GLib.idle_add(self.append_log, script, line)
        status = proc.wait()
        self.proc = None
        return status

    def _run_in_terminal(self, script):
        GLib.idle_add(
            self.append_log,
            script,
            f"=== opening {script} in a terminal window (needs an interactive TTY) -- "
            "complete it there ===\n",
        )
        # xterm doesn't reliably propagate the wrapped command's exit status as
        # its own (it exits 0 on normal termination regardless of how the
        # command inside fared), so its own proc.returncode can't be trusted --
        # capture the real exit code to a file from inside the shell instead.
        fd, exit_file = tempfile.mkstemp(prefix="run-gui-exit-")
        os.close(fd)
        env = self._sudo_env()
        env["EXITFILE"] = exit_file
        try:
            proc = subprocess.Popen(
                [
                    "xterm", "-T", script, "-e", "bash", "-c",
                    'status=0; "$@" || status=$?; echo "$status" > "$EXITFILE"',
                    "_", "sudo", "-A", "-p", "", "bash", script,
                ],
                cwd=DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.proc = proc
            proc.wait()
            self.proc = None
            # Output wasn't streamed into the log pane live (see class
            # docstring), so MANUAL_TODO lines weren't picked up by
            # append_log as they went by -- re-read the script's own log
            # file for them now that it's finished.
            try:
                log_text = open(log_path_for(script)).read()
            except OSError:
                log_text = ""
            for todo_text in MANUAL_TODO_RE.findall(log_text):
                GLib.idle_add(self._add_todo, script, todo_text, self._todo_action_for(script))
            try:
                return int(open(exit_file).read().strip())
            except (OSError, ValueError):
                return 1
        finally:
            try:
                os.remove(exit_file)
            except OSError:
                pass

    # -- worker thread --------------------------------------------------

    def _worker(self, scripts):
        stopped = False
        failed_script = None
        remaining = list(scripts)

        while remaining:
            if self.stop_requested:
                stopped = True
                GLib.idle_add(self.append_log, "", f"=== stop requested: skipping {len(remaining)} remaining script(s) ===\n")
                break

            script = remaining.pop(0)

            confirm_message = NEEDS_CONFIRMATION.get(script)
            if confirm_message and not self._confirm(script, confirm_message):
                GLib.idle_add(self.append_log, script, f"=== {script} skipped (not confirmed) ===\n")
                GLib.idle_add(self.set_row_status, script, "skipped")
                GLib.idle_add(self._bump_progress)
                continue

            self.currently_running_script = script
            GLib.idle_add(self._begin_script_display, script)
            GLib.idle_add(self.set_row_status, script, "running")
            GLib.idle_add(self.status_label.set_text, f"Running: {script}")

            start_time = time.monotonic()
            self.current_script_start = start_time
            # A profile-driven script has no whiptail prompts left to draw,
            # so it no longer needs the xterm/TTY treatment -- runs piped
            # like everything else.
            profile_driven = self.profile_env is not None and script in PROFILE_SCRIPTS
            if script in NEEDS_TERMINAL and not profile_driven:
                status = self._run_in_terminal(script)
            else:
                GLib.idle_add(self.append_log, script, f"=== running {script} ===\n")
                status = self._run_piped(script)
            # For a NEEDS_TERMINAL script this includes however long the
            # xterm sat open waiting for someone to work through its
            # whiptail menus, not just the script's own work -- expected,
            # since that's genuinely how long this step took this run.
            duration = time.monotonic() - start_time
            self.current_script_start = None
            GLib.idle_add(self._add_session_runtime, duration)
            GLib.idle_add(self._bump_progress)

            if status == 0:
                GLib.idle_add(self.append_log, script, f"=== {script} done ({format_duration(duration)}) ===\n")
                GLib.idle_add(self.set_row_status, script, "done", duration)
            else:
                failed_script = script
                # Could be a stale/wrong cached password as easily as the
                # script's own failure -- either way, cheaper to re-prompt
                # next run than to keep feeding sudo something that doesn't
                # work.
                self.sudo_password = None
                GLib.idle_add(self.append_log, script, f"=== {script} FAILED ({format_duration(duration)}, exit {status}) ===\n")
                GLib.idle_add(self.set_row_status, script, "failed", duration)
                if remaining:
                    GLib.idle_add(
                        self.append_log,
                        script,
                        "Stopping here since later scripts may depend on this one.\n",
                    )
                break

        self.currently_running_script = None
        GLib.idle_add(self._on_finished, stopped, failed_script)

    def _on_finished(self, stopped, failed_script):
        self._set_controls_busy(False)
        if stopped:
            self.status_label.set_text("Stopped after current script.")
        elif failed_script:
            self.status_label.set_text(f"Failed: {failed_script} -- see log above.")
        else:
            self.status_label.set_text("Finished successfully.")
            if self.current_run_is_batch:
                # Supersedes any per-script "reboot (or log out/in) for X to
                # apply" todo (00-locale-keyboard-timezone.sh,
                # 00a-touchpad-tap-global.sh, 46-cyberbeest-keyboard-shortcuts.sh,
                # ...) -- no point showing those once a full reboot covering
                # everything is already on offer.
                for key, (text, _action) in list(self.todos.items()):
                    if text.startswith("Reboot (or log out/in)"):
                        self.todos.pop(key, None)
                self._add_todo(
                    REBOOT_TODO_KEY,
                    "Reboot to fully apply everything from this run.",
                    action=("Reboot Now", self._do_reboot),
                )

    def on_disable_autostart(self, _menuitem):
        pending = [s for s in list_scripts() if not script_is_done(s)]
        message = (
            "This machine will no longer offer to run provisioning automatically "
            "at login."
        )
        if pending:
            message += (
                f"\n\n{len(pending)} script(s) haven't completed yet:\n"
                + "\n".join(f"  • {s}" for s in pending)
                + "\n\nYou can still run this tool by hand any time (beestify.sh)."
            )
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Disable auto-provisioning on login?",
        )
        dialog.format_secondary_text(message)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.YES:
            return
        try:
            os.remove(AUTOSTART_FILE)
        except OSError as e:
            self.status_label.set_text(f"Could not remove {AUTOSTART_FILE}: {e}")
            return
        self.disable_autostart_item.set_sensitive(False)
        self.status_label.set_text("Auto-provisioning on login disabled. Run beestify.sh by hand any time to pick up where you left off.")

    def on_stop(self, _button):
        if not self.busy:
            return
        self.stop_requested = True
        self.stop_button.set_sensitive(False)
        self.status_label.set_text("Stop requested -- finishing current script, then stopping...")

    def on_destroy(self, _window):
        if self.proc is not None and self.proc.poll() is None:
            self.append_log(self.currently_running_script or "", "\n[run-gui.py] window closed while a run was active -- ")
            self.append_log(self.currently_running_script or "", "leaving the root process running; check a terminal with `ps` if unsure.\n")
        try:
            os.remove(PROFILE_FILE)
        except OSError:
            pass
        Gtk.main_quit()


def main():
    RunGuiWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
