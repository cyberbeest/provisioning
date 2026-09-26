#!/usr/bin/env python3
"""GUI front-end for the NN-*.sh provisioning scripts.

It lists every NN-*.sh script in a sidebar (with a status:
pending/done/running/failed, "done" meaning its .log is newer than both
the script itself and every lib/ file the script's body references --
see script_lib_dependencies()), and runs each one directly as its
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
"" bucket for messages not tied to any one script). Single-clicking a row
just selects it and shows its stored log --
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

The graphical sudo prompt is cyberbeest-askpass.py, a small dedicated GTK3
dialog -- not zenity: this Debian's zenity (4.1.90, the GTK4 rewrite) either
ignores custom prompt text on a --password dialog entirely, or via --forms
(which does respect custom text) never wires Enter to the default button at
all, confirmed both ways by hand. Since none of run-gui.py's own dialogs use
zenity either (they're plain Gtk.MessageDialog), this tool has no zenity
dependency at all.

Only prompts for the sudo password once per run of run-gui.py, not once per
script: the first sudo call uses cyberbeest-askpass.py as normal, but
run-gui.py runs that same helper directly itself first (see
_get_sudo_password) to grab the typed password into memory, then points
every later sudo -A call at cached-askpass.sh instead, which just echoes
that cached password back rather than popping a fresh dialog. (Relying on
sudo's own timestamp/ticket cache instead wasn't reliable here -- each
script subprocess runs in its own new session via start_new_session=True
below, and tty_tickets-style caching keys off exactly that kind of
session/tty identity, so it kept re-prompting every script instead of
reusing the earlier authentication.) If a cached password turns out to be
stale (e.g. the user changed it mid-run), the resulting sudo failure clears
it so the next attempt re-prompts.

Every script subprocess gets stdin=DEVNULL and start_new_session=True: without
those, a script inherits run-gui.py's own stdin/process group -- i.e. the
terminal it was launched from, if any -- and a subprocess still alive when
the window is closed can be left holding that terminal's controlling tty,
making it look frozen even though it's really just an orphaned background
process waiting to read from a tty nothing will ever type into again.

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
import hashlib
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
import threading
import time
import zoneinfo

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

DIR = os.path.dirname(os.path.realpath(__file__))
ASKPASS = os.path.join(DIR, "lib", "cyberbeest-askpass.py")
CACHED_ASKPASS = os.path.join(DIR, "lib", "cached-askpass.sh")

# lib/i18n.py only resolves `from i18n import t` if lib/ is on sys.path --
# unlike the installed Python GUI scripts (see lib/i18n.py's own docstring),
# this one runs straight out of the repo checkout rather than being copied
# next to i18n.py, so that has to be added explicitly here.
sys.path.insert(0, os.path.join(DIR, "lib"))
from i18n import t

NEEDS_TERMINAL = {"00-locale-keyboard-timezone.sh", "00a-touchpad-tap-global.sh"}

# Scripts skipped by "Select scripts for VM install" (more-actions menu):
# hardware that doesn't exist in a VM guest (touchpad/bluetooth/battery/
# lid/sleep-states), the auto-lock/screensaver family (a VM guest doesn't
# need its own lock screen), background daemons with nothing to watch or
# warm up in a VM (boot/shutdown chimes, fail2ban with no sshd exposed --
# see 99-remove-openssh-server.sh), and encrypted DNS -- assumes the VM
# stays on libvirt's default NAT network, whose dnsmasq forwards guest DNS
# queries to the host's own resolver, riding through the host's
# dnscrypt-proxy transparently with nothing needed guest-side. Everything
# else, including the apps (messengers/wallets/
# browser sandbox/VPN/i2pd toggles), stays selected -- the point of this
# profile is "all our apps, none of the automatic background stuff that
# assumes real hardware or its own network path."
VM_INSTALL_EXCLUDE = {
    "00a-touchpad-tap-global.sh",
    "01-bluetooth-tethering.sh",
    "13-lock-shutdown-watcher.sh",
    "16-power-lock-config.sh",
    "17-login-lock-screen.sh",
    "19-low-battery-shutdown.sh",
    "20-shutdown-sound.sh",
    "37-encrypted-dns.sh",
    "26-lid-close-policy.sh",
    "30-lockscreen-shutdown-button.sh",
    "31-disable-sleep-states.sh",
    "35-boot-chime.sh",
    "51-fail2ban.sh",
}

# Scripts driven by the upfront "Provisioning profile" dialog (see
# ProvisioningProfileDialog) instead of their own whiptail prompts. Once the
# dialog has been answered, both scripts run piped like every other step --
# they only need NEEDS_TERMINAL's xterm/whiptail treatment when no profile
# has been collected (e.g. run standalone via menu.sh, or the dialog was
# cancelled).
PROFILE_SCRIPTS = {"00-locale-keyboard-timezone.sh", "00a-touchpad-tap-global.sh"}

# 56- only needs the profile while its VM is out of date: the dialog's
# "Update the VM" row (see vm_update_status) is its only question.
VM_SCRIPT = "56-cyberbeest-sandbox-vm-kvm.sh"
VM_LIB = os.path.join(DIR, "lib", "download-and-create-sandbox-vm-kvm.sh")
VM_NAME = "Cyberbeest-VM"
VM_DIR = os.path.expanduser("~/.local/share/cyberbeest-vms")
# Same margin as the lib script's own space check.
VM_SPACE_MARGIN = 1024 ** 3

# Where the collected profile answers are handed to 00-/00a-. A plain file
# rather than environment variables: sudo's default env_reset policy strips
# arbitrary env vars from the escalated command (only SUDO_ASKPASS and
# friends survive, since those are consumed by sudo itself before the
# reset), but a file in this directory is trivially readable by root once
# the script is running as root anyway. Not sensitive data (locale/keyboard/
# timezone/touchpad choices), so no special permissions needed; removed on
# exit purely for tidiness, see RunGuiWindow.on_destroy.
PROFILE_FILE = os.path.join(DIR, ".provisioning-profile.env")

# Unlike PROFILE_FILE above (deliberately wiped on exit -- it only exists to
# pass this run's answers to the shell scripts), this is where the answers
# themselves are remembered *across* separate run-gui.py launches, so
# reopening the profile dialog later (a re-run after fixing something, a
# second pass on the same machine) starts pre-filled with what was actually
# picked last time instead of resetting to hardcoded defaults (country=US,
# etc.). Still asked for confirmation each session (see _ensure_profile) --
# this only changes the starting values, never skips the dialog outright.
PERSISTED_PROFILE_FILE = os.path.expanduser("~/.config/cyberbeest/run-gui-profile.json")


def load_persisted_profile():
    try:
        with open(PERSISTED_PROFILE_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_persisted_profile(answers):
    try:
        os.makedirs(os.path.dirname(PERSISTED_PROFILE_FILE), exist_ok=True)
        with open(PERSISTED_PROFILE_FILE, "w") as f:
            json.dump(answers, f)
    except OSError:
        pass

# code|Display name|default language (en/de)|en locale|de locale|keyboard layout|default IANA timezone
# Keep in sync with 00-locale-keyboard-timezone.sh's own COUNTRIES array --
# that script's interactive whiptail path (used when no profile was
# collected) is the source of truth this mirrors.
def _allocated_bytes(path):
    try:
        return os.stat(path).st_blocks * 512
    except OSError:
        return 0


def vm_update_status():
    """None unless the sandbox VM exists and was built from an older image
    than the one pinned in VM_LIB. Otherwise the disk-space figures the
    profile dialog shows next to its "Update the VM" checkbox -- the same
    arithmetic the lib script checks before touching anything: the old VM
    stays as the backup, so only a previous backup is freed."""
    try:
        with open(VM_LIB, encoding="utf-8") as f:
            pins = dict(re.findall(r'^(IMAGE_\w+)="([^"]*)"$', f.read(), re.MULTILINE))
        pinned = pins["IMAGE_SHA256"]
        # The download itself becomes the VM's disk.
        download_bytes = new_bytes = int(pins["IMAGE_BYTES"])
    except (OSError, KeyError, ValueError):
        return None
    try:
        names = subprocess.run(
            ["virsh", "--connect", "qemu:///session", "list", "--all", "--name"],
            capture_output=True, text=True, timeout=10,
        ).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if VM_NAME not in names:
        return None
    try:
        with open(os.path.join(VM_DIR, VM_NAME + ".image-sha256")) as f:
            if f.read().strip() == pinned:
                return None
    except OSError:
        pass  # set up before stamping existed: an older image
    st = os.statvfs(VM_DIR)
    free = st.f_bavail * st.f_frsize
    backup = _allocated_bytes(os.path.join(VM_DIR, VM_NAME + "-backup.qcow2"))
    return {
        "free": free,
        "current": _allocated_bytes(os.path.join(VM_DIR, VM_NAME + ".qcow2")),
        "previous_backup": backup,
        "download": download_bytes,
        "needed": new_bytes,
        "fits": free + backup >= new_bytes + VM_SPACE_MARGIN,
    }


def format_gb(n):
    return f"{n / 1e9:.1f} GB"


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
    "99-remove-openssh-server.sh": t("run_gui.confirm_remove_openssh"),
}


def openssh_removal_has_work():
    # Mirrors 99-remove-openssh-server.sh's own idempotency checks -- if
    # none of these are true, the script is a guaranteed no-op, so the
    # "this will cut off SSH access" confirmation dialog would just be
    # noise (and actively misleading, warning about a disconnect that
    # isn't going to happen).
    for pkg in ("openssh-server", "fail2ban"):
        if subprocess.run(
            ["dpkg", "-s", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0:
            return True
    homes = {"/root"}
    try:
        homes.update(u.pw_dir for u in pwd.getpwall() if 1000 <= u.pw_uid < 60000)
    except OSError:
        pass
    for home in homes:
        for name in ("authorized_keys", "authorized_keys2"):
            if os.path.exists(os.path.join(home, ".ssh", name)):
                return True
    return False


# Optional per-script predicate: if present and it returns False, the
# script's NEEDS_CONFIRMATION dialog is skipped entirely (straight to
# running it) instead of asking about an action that would be a no-op.
CONFIRMATION_SKIP_IF_NOOP = {
    "99-remove-openssh-server.sh": openssh_removal_has_work,
}

# Must match cyberbeest-bootstrap.sh's own AUTOSTART_FILE -- that's the
# fresh-install autostart entry that relaunches beestify.sh (and so this
# GUI) on every login until provisioning is complete. Deleting it directly
# is exactly what cyberbeest-bootstrap.sh itself does on a clean finish;
# see the "Disable auto-provisioning on login" button below for doing that
# manually, on purpose, before every script has run.
AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/cyberbeest-provisioning.desktop")

MANUAL_TODO_RE = re.compile(r"^MANUAL_TODO:\s*(.+?)\s*$", re.MULTILINE)

# apt errors from a package server being briefly unavailable or mid-sync
# (e.g. Signal's repo publishing a new index while we download it). Every
# script runs `apt-get update`, which covers *all* configured repos, so a
# hiccup on one third-party server fails whichever script happens to run
# at that moment. Such a failure gets retried after a wait instead of
# ending the run.
APT_TRANSIENT_RE = re.compile(
    r"^E: (Failed to fetch|Some index files failed to download|Unable to fetch some archives)"
    r"|Hash Sum mismatch|Mirror sync in progress",
    re.MULTILINE,
)
APT_RETRY_DELAYS_S = (60, 120, 240)
REBOOT_TODO_KEY = "__reboot__"
# One "send a report" todo per failed script, removed again once it succeeds.
REPORT_TODO_PREFIX = "__report__:"

STATUS_STYLE = {
    "pending": (t("run_gui.state_pending"), "#8a8a8a"),
    "running": (t("run_gui.state_running"), "#2b78e4"),
    "done": (t("run_gui.state_done"), "#2a9d3f"),
    "failed": (t("run_gui.state_failed"), "#d43f3f"),
    "skipped": (t("run_gui.state_skipped"), "#8a8a8a"),
}

# Wall-clock durations, derived from the "=== <date> : ..." timestamp on
# each script's first log line vs. the next script's, shown next to
# "pending" rows as a rough per-script estimate. This is a running max
# across real end-to-end provisioning runs (started 2026-08-31, last
# refreshed from a run on 2026-09-26) -- a run's own value only replaces
# an entry when it's bigger. Actual time on a given machine varies mainly
# with network speed (apt/pip installs) and whether packages are already
# cached -- treat these as ballpark, not a guarantee. A script not in this
# dict (e.g. one added since) just shows "pending" with no estimate.
SCRIPT_DURATION_ESTIMATES = {
    "00-locale-keyboard-timezone.sh": 88,
    "00a-touchpad-tap-global.sh": 0,
    "01-bluetooth-tethering.sh": 26,
    "02-gnome-software-store.sh": 14,
    "03-secure-messengers.sh": 176,
    "04-software-launch-warning.sh": 0,
    "05-unattended-upgrades-security.sh": 87,
    "06-vendor-origins-unattended-upgrades.sh": 52,
    "07-security-update-timer.sh": 114,
    "08-xdg-user-dirs.sh": 5,
    "09-cyberbeest-logout-dialog.sh": 6,
    "10-browser-sandbox.sh": 23,
    "11-xfce-panel-plugins.sh": 99,
    "11a-clipboard-status.sh": 19,
    "12-xfce-panel-layout.sh": 20,
    "13-lock-shutdown-watcher.sh": 16,
    "13a-lock-warning-watcher.sh": 6,
    "14-user-avatar.sh": 0,
    "15-grub-plymouth-theme.sh": 69,
    "16-power-lock-config.sh": 8,
    "17-login-lock-screen.sh": 0,
    "18-desktop-background.sh": 1,
    "19-low-battery-shutdown.sh": 1,
    "20-shutdown-sound.sh": 1,
    "21-default-password-nag.sh": 9,
    "22-i2p-package-manager.sh": 6,
    "23-vlc-media-player.sh": 22,
    "24-avif-mime-default.sh": 1,
    "25-cyberbeest-panel-color.sh": 5,
    "26-lid-close-policy.sh": 7,
    "27-desktop-hotlinks.sh": 8,
    "28-single-workspace.sh": 1,
    "29-wireguard-vpn-toggle.sh": 6,
    "30-lockscreen-shutdown-button.sh": 104,
    "31-disable-sleep-states.sh": 4,
    "32-minor-apt-packages.sh": 109,
    "33-rename-thunar-to-files.sh": 11,
    "35-boot-chime.sh": 8,
    "36-crypto-wallets.sh": 47,
    "37-encrypted-dns.sh": 20,
    "38-jail-messengers.sh": 4,
    "39-feather-tor-ondemand.sh": 4,
    "40-jail-wallets-viber.sh": 6,
    "41-bookmark-seeder.sh": 5,
    "42-security-watch.sh": 17,
    "43-intrusion-watch.sh": 5,
    "44-wipe-app-data.sh": 5,
    "45-hide-redundant-terminals.sh": 1,
    "46-cyberbeest-keyboard-shortcuts.sh": 0,
    "47-set-max-volume.sh": 0,
    "48-whisker-menu-categories.sh": 1,
    "49-whisker-category-cleanup.sh": 2,
    "50-i2pd-default.sh": 281,
    "51-fail2ban.sh": 4,
    "52-cyberbeest-update.sh": 0,
    "53a-qemu-kvm-virt-manager.sh": 142,
    "54-lock-screen-curtain.sh": 7,
    "55-powerbtn-double-press.sh": 19,
    "56-cyberbeest-sandbox-vm-kvm.sh": 741,
    "58-cyberbeest-image-viewer.sh": 36,
    "59-cyberbeest-scanner.sh": 144,
    "60-xfce-panel-watchdog.sh": 1,
    "91-sandbox-vm.sh": 0,
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


def script_lib_dependencies(script):
    # Best-effort static scan for lib/ paths a script's body references
    # (including glob patterns like "lib/i18n/strings.*.sh"), so editing a
    # shared lib/ file marks every script that installs it as pending
    # without each of them needing a manual "bump this file" comment (the
    # old approach -- see 52-cyberbeest-update.sh's history).
    deps = set()
    try:
        with open(os.path.join(DIR, script), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return deps
    for match in re.finditer(r'lib/[^\s"\'`)]+', text):
        full = os.path.join(DIR, match.group(0).rstrip(".,;:"))
        if "*" in full or "?" in full:
            deps.update(glob.glob(full))
        elif os.path.exists(full):
            deps.add(full)
    return deps


# The shared i18n catalogs hold every tool's strings, so treating them
# like any other lib/ dependency re-ran every script that installs them on
# any string edit anywhere. Instead, a script only goes pending when a
# string in one of the key groups (the "clipboard." in
# "clipboard.show_image") its own files use actually changed: a fingerprint
# of those strings is recorded on each successful run and compared.
I18N_CATALOG_RE = re.compile(r"/lib/i18n/strings[._][a-z]+\.(py|sh)$")
_catalog_cache = {}


def load_catalog(path):
    """{key: value} of one catalog file, cached by mtime."""
    mtime = os.path.getmtime(path)
    cached = _catalog_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    entries = {}
    if path.endswith(".py"):
        ns = {}
        with open(path, encoding="utf-8") as f:
            exec(f.read(), ns)
        entries = dict(ns.get("STRINGS", {}))
    else:
        out = subprocess.run(
            ["bash", "-c",
             'declare -gA STRINGS_EN=() STRINGS_L10N=(); . "$1"; '
             'for n in STRINGS_EN STRINGS_L10N; do declare -n a=$n; '
             'for k in "${!a[@]}"; do printf "%s\\0%s\\0" "$k" "${a[$k]}"; done; '
             'unset -n a; done', "_", path],
            capture_output=True, text=True, timeout=10,
        ).stdout.split("\0")
        entries = dict(zip(out[0::2], out[1::2]))
    _catalog_cache[path] = (mtime, entries)
    return entries


def i18n_fingerprint(script, catalogs, other_deps):
    """Hash of the catalog strings in the key groups this script's own
    files mention, or None if none are found (then any catalog change
    counts, as before)."""
    catalog_data = {os.path.basename(c): load_catalog(c) for c in sorted(catalogs)}
    prefixes = {k.split(".", 1)[0] for entries in catalog_data.values() for k in entries if "." in k}
    used = set()
    for path in [os.path.join(DIR, script)] + sorted(other_deps):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        used.update(m.group(1) for m in re.finditer(r"(?<![\w/.-])([a-z0-9_]+)\.[a-z0-9_{]", text) if m.group(1) in prefixes)
    if not used:
        return None
    digest = hashlib.sha256()
    for name, entries in catalog_data.items():
        for key in sorted(k for k in entries if k.split(".", 1)[0] in used):
            digest.update(f"{name}\0{key}\0{entries[key]}\0".encode())
    return digest.hexdigest()


def i18n_hash_file_for(script):
    return os.path.join(DIR, script[:-3] + ".i18n-hash")


def split_lib_dependencies(script):
    deps = script_lib_dependencies(script)
    catalogs = {d for d in deps if I18N_CATALOG_RE.search(d)}
    return catalogs, deps - catalogs


def record_i18n_fingerprint(script):
    catalogs, others = split_lib_dependencies(script)
    if not catalogs:
        return
    fingerprint = i18n_fingerprint(script, catalogs, others)
    try:
        if fingerprint is None:
            os.remove(i18n_hash_file_for(script))
        else:
            with open(i18n_hash_file_for(script), "w") as f:
                f.write(fingerprint + "\n")
    except OSError:
        pass


def failed_marker_for(script):
    return os.path.join(DIR, script[:-3] + ".failed")


def mark_script_result(script, succeeded):
    # A failed run still writes its log, which on its own would make the
    # log newer than the script and count it as done -- the marker keeps
    # it pending until a run actually succeeds.
    marker = failed_marker_for(script)
    try:
        if succeeded:
            if os.path.exists(marker):
                os.remove(marker)
            record_i18n_fingerprint(script)
        else:
            open(marker, "w").close()
    except OSError:
        pass


def script_is_done(script):
    log = log_path_for(script)
    if not os.path.exists(log) or os.path.exists(failed_marker_for(script)):
        return False
    log_mtime = os.path.getmtime(log)
    script_path = os.path.join(DIR, script)
    if log_mtime <= os.path.getmtime(script_path):
        return False
    catalogs, others = split_lib_dependencies(script)
    if not all(log_mtime > os.path.getmtime(dep) for dep in others):
        return False
    hash_file = i18n_hash_file_for(script)
    if all(log_mtime > os.path.getmtime(c) for c in catalogs):
        # Done under the plain mtime rule. A run from before fingerprints
        # existed (or one outside this GUI) left none -- record it now, as
        # the installed strings match the current catalogs.
        if catalogs and not os.path.exists(hash_file):
            record_i18n_fingerprint(script)
        return True
    try:
        with open(hash_file) as f:
            stored = f.read().strip()
    except OSError:
        return False
    return stored == i18n_fingerprint(script, catalogs, others)


def repo_version_string():
    """<track><commit-date YYYY-MMDD>-<short-hash>[ + N pending][ + M
    changed] for this checkout -- what Cyberbeest Update and this window
    show instead of a hand-maintained version number, since git already
    tracks exactly this. <track> is "beta"/"stable" (mapped from the raw
    git branch, main/stable, the same way cyberbeest-update.sh's own
    $TRACK is) -- deliberately not run through i18n, since this string is
    meant to be a stable identifier (e.g. to quote in a bug report), not
    localized UI text. "pending" is exactly what the runner's own "Run
    changed only" button counts: every script script_is_done() calls not
    done, whether it's never been run at all or was run before but is now
    stale -- the per-row status list doesn't distinguish those either, so
    neither does this. "changed" is the number of tracked files this
    checkout has modified locally against its own HEAD (git status
    --porcelain, ignored/untracked files excluded) -- 0 on a normal
    end-user machine; cyberbeest-update.sh's own LOCAL_EDITS check uses
    the same git status call for the same reason. No separator between
    the track and the date: both are unambiguous either way (the track
    label isn't digits-first) and it's one less thing pushing the string
    past a glance-able length.
    """
    try:
        branch = subprocess.run(
            ["git", "-C", DIR, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        commit_date = subprocess.run(
            ["git", "-C", DIR, "log", "-1", "--format=%cd", "--date=format:%Y-%m%d"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        short_hash = subprocess.run(
            ["git", "-C", DIR, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None

    track = "stable" if branch == "stable" else "beta"
    version = f"{track}{commit_date}-{short_hash}"

    pending = sum(1 for s in list_scripts() if not script_is_done(s))
    if pending:
        version += f" + {pending} pending"

    # Best-effort: a failure (e.g. not actually a git checkout) just leaves
    # this part out rather than breaking the whole version string.
    try:
        local_edits = subprocess.run(
            ["git", "-C", DIR, "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, check=True,
        ).stdout
        changed = sum(1 for line in local_edits.splitlines() if line.strip())
    except (subprocess.CalledProcessError, OSError):
        changed = 0
    if changed:
        version += f" + {changed} changed"
    return version


def locale_dependent_scripts():
    # Mirrors 00-locale-keyboard-timezone.sh's own `grep -lZ
    # '^# LOCALE_DEPENDENT:'` -- used to tell whether its "Run changed" TODO
    # is already satisfied by the rest of the current batch.
    result = set()
    for script in list_scripts():
        try:
            with open(os.path.join(DIR, script), encoding="utf-8") as f:
                if any(line.startswith("# LOCALE_DEPENDENT:") for line in f):
                    result.add(script)
        except OSError:
            pass
    return result


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

    # Custom response ids for the two non-Cancel buttons -- Gtk.ResponseType
    # only has generic ids like OK/APPLY, and this dialog needs to tell
    # "just save" apart from "save and start the run that's pending",
    # which are genuinely different actions with different buttons.
    RESPONSE_SAVE = 1
    RESPONSE_START = 2

    def __init__(self, parent, previous=None, pending_count=None):
        super().__init__(title=t("run_gui.profile_dialog_title"), transient_for=parent, modal=True)
        self.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        self.add_button(t("run_gui.profile_save"), self.RESPONSE_SAVE)
        # Only offered when a run is actually pending (opened via
        # _ensure_profile, not the standalone "Profile..." button) -- saves
        # and immediately proceeds with it, rather than the button always
        # existing but being a no-op/confusing when nothing is queued.
        if pending_count is not None:
            start_label = (
                t("run_gui.profile_start_one_script") if pending_count == 1
                else t("run_gui.profile_start_n_scripts").format(count=pending_count)
            )
            start_button = self.add_button(start_label, self.RESPONSE_START)
            start_button.get_style_context().add_class("suggested-action")
            self.set_default_response(self.RESPONSE_START)
        else:
            self.set_default_response(self.RESPONSE_SAVE)
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
        add_row(t("run_gui.profile_country_label"), self.country_combo)

        self.lang_en = Gtk.RadioButton.new_with_label_from_widget(None, t("run_gui.profile_lang_english"))
        self.lang_de = Gtk.RadioButton.new_with_label_from_widget(self.lang_en, t("run_gui.profile_lang_german"))
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lang_box.pack_start(self.lang_en, False, False, 0)
        lang_box.pack_start(self.lang_de, False, False, 0)
        add_row(t("run_gui.profile_ui_language_label"), lang_box)

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
        add_row(t("run_gui.profile_keyboard_label"), self.keyboard_combo)

        self.menu_key_remap = Gtk.CheckButton(
            label=t("run_gui.profile_menu_key_remap")
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
        add_row(t("run_gui.profile_timezone_label"), self.tz_combo)

        self.touchpad_tuning = Gtk.CheckButton(
            label=t("run_gui.profile_touchpad_checkbox")
        )
        self.touchpad_tuning.set_active(prev.get("PROVISIONING_TOUCHPAD_TUNING", "yes") != "no")
        add_row(t("run_gui.profile_touchpad_label"), self.touchpad_tuning)

        # VM image download (56-cyberbeest-sandbox-vm-kvm.sh): the
        # hypervisor itself (53a-qemu-kvm-virt-manager.sh, KVM -- the only one
        # provisioning ships, VirtualBox was dropped entirely 2026-09-19)
        # always installs regardless of this choice. This checkbox only
        # controls the multi-GB KVM VM disk-image download.
        self.vm_image = Gtk.CheckButton(label=t("run_gui.profile_vm_image_checkbox"))
        self.vm_image.set_active(prev.get("PROVISIONING_VM_IMAGE", "yes") != "no")
        add_row(t("run_gui.profile_vm_image_label"), self.vm_image)

        # Only shown while the existing VM is on an older image. Always
        # starts unticked, even if it was ticked last time: it's a big
        # download and a VM that suddenly looks different can confuse.
        self.vm_update = None
        status = vm_update_status()
        if status:
            self.vm_update = Gtk.CheckButton(label=t("run_gui.profile_vm_update_checkbox"))
            space_text = t("run_gui.profile_vm_update_space").format(
                free=format_gb(status["free"]),
                current=format_gb(status["current"]),
                needed=format_gb(status["needed"]),
            )
            if status["previous_backup"]:
                space_text += "\n" + t("run_gui.profile_vm_update_previous_backup").format(
                    size=format_gb(status["previous_backup"]))
            if not status["fits"]:
                space_text += "\n" + t("run_gui.profile_vm_update_no_space")
                self.vm_update.set_sensitive(False)
            space_label = Gtk.Label(label=space_text, xalign=0)
            space_label.set_line_wrap(True)
            space_label.get_style_context().add_class("dim-label")
            info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.BUTTON)
            info_icon.set_tooltip_text(t("run_gui.profile_vm_update_tooltip").format(
                download=format_gb(status["download"])))
            checkbox_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            checkbox_row.pack_start(self.vm_update, False, False, 0)
            checkbox_row.pack_start(info_icon, False, False, 0)
            vm_update_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            vm_update_box.pack_start(checkbox_row, False, False, 0)
            vm_update_box.pack_start(space_label, False, False, 0)
            add_row(t("run_gui.profile_vm_update_label"), vm_update_box)

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
        """Runs the dialog; returns (answers, start_requested).
        answers is None if cancelled (start_requested then always False).
        start_requested is True only for RESPONSE_START -- RESPONSE_SAVE
        saves the same answers dict but the caller shouldn't proceed with
        whatever run (if any) prompted the dialog."""
        response = self.run()
        if response not in (self.RESPONSE_SAVE, self.RESPONSE_START):
            self.destroy()
            return None, False

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
            "PROVISIONING_VM_IMAGE": "yes" if self.vm_image.get_active() else "no",
            "PROVISIONING_VM_UPDATE": "yes" if self.vm_update and self.vm_update.get_active() else "no",
        }
        self.destroy()
        return answers, response == self.RESPONSE_START


class RunGuiWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=t("run_gui.window_title"))
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
        # Last-actually-picked answers, loaded from disk -- used only to
        # pre-fill the dialog's starting values (see _edit_profile), not a
        # substitute for self.profile_env itself.
        self.saved_profile_defaults = load_persisted_profile()
        self.current_run_is_batch = False
        self.batch_scripts = set()
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

        # Two rows: run/setup actions on top, stop/abort controls below --
        # keeping every button in one row got cramped once Profile and
        # Select all joined Run changed/Run all/Run selected/the more-
        # actions dropdown.
        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.pack_start(button_box, False, False, 0)

        button_row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.pack_start(button_row1, False, False, 0)

        self.run_changed_button = Gtk.Button(label=t("run_gui.button_run_changed"))
        self.run_changed_button.connect("clicked", lambda _b: self.start_sequence(changed_only=True))
        button_row1.pack_start(self.run_changed_button, False, False, 0)

        self.run_all_button = Gtk.Button(label=t("run_gui.button_run_all"))
        self.run_all_button.connect("clicked", lambda _b: self.start_sequence(changed_only=False))
        button_row1.pack_start(self.run_all_button, False, False, 0)

        self.run_selected_button = Gtk.Button(label=t("run_gui.button_run_selected"))
        self.run_selected_button.connect("clicked", lambda _b: self.start_selected())
        button_row1.pack_start(self.run_selected_button, False, False, 0)

        # Opens the same dialog as the old "Provisioning profile..." menu
        # item (now folded into this button instead -- no point keeping
        # both) without starting anything, so settings can be reviewed or
        # changed ahead of time, not just right before a "Run all"/"Run
        # changed only" via _ensure_profile.
        self.profile_button = Gtk.Button(label=t("run_gui.button_profile"))
        self.profile_button.connect("clicked", lambda _b: self._edit_profile())
        button_row1.pack_start(self.profile_button, False, False, 0)

        # A small drop-down (just the triangle, no label) rather than another
        # full-size button -- this is a rare, one-off action, not something
        # that deserves the same visual weight as Run all/Run selected/Stop.
        self.more_menu_button = Gtk.MenuButton()
        self.more_menu_button.set_image(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON))
        self.more_menu_button.set_tooltip_text(t("run_gui.more_actions_tooltip"))
        more_menu = Gtk.Menu()
        self.disable_autostart_item = Gtk.MenuItem(label=t("run_gui.menu_disable_autostart"))
        self.disable_autostart_item.set_sensitive(os.path.exists(AUTOSTART_FILE))
        self.disable_autostart_item.connect("activate", self.on_disable_autostart)
        more_menu.append(self.disable_autostart_item)
        self.select_vm_scripts_item = Gtk.MenuItem(label=t("run_gui.menu_select_vm_scripts"))
        self.select_vm_scripts_item.connect("activate", lambda _mi: self._select_vm_scripts())
        more_menu.append(self.select_vm_scripts_item)
        self.switch_to_update_item = Gtk.MenuItem(label=t("run_gui.menu_switch_to_update"))
        self.switch_to_update_item.connect("activate", self.on_switch_to_update)
        more_menu.append(self.switch_to_update_item)
        more_menu.show_all()
        self.more_menu_button.set_popup(more_menu)
        button_row1.pack_start(self.more_menu_button, False, False, 0)

        self.total_time_label = Gtk.Label(label=t("run_gui.total_time").format(duration=format_duration(0)), xalign=1)
        button_row1.pack_end(self.total_time_label, False, False, 0)

        button_row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.pack_start(button_row2, False, False, 0)

        # This checkout's git-derived version string (branch/commit-date/
        # hash, plus pending/changed counts) -- see repo_version_string().
        # Small and dim, right-aligned on the second button row: worth
        # having on screen (e.g. to quote in a bug report) without
        # competing for attention with anything actually actionable.
        version = repo_version_string()
        if version:
            self.version_label = Gtk.Label(xalign=1)
            self.version_label.set_markup(f"<small>{GLib.markup_escape_text(version)}</small>")
            self.version_label.get_style_context().add_class("dim-label")
            button_row2.pack_end(self.version_label, False, False, 0)

        # Directly under the more-actions dropdown above -- selecting
        # everything is prep for "Run selected", same family as that
        # dropdown's own one-off actions, just common enough to deserve a
        # full button instead of being buried in the menu.
        self.select_all_button = Gtk.Button(label=t("run_gui.button_select_all"))
        self.select_all_button.connect("clicked", lambda _b: self.listbox.select_all())
        button_row2.pack_start(self.select_all_button, False, False, 0)

        self.stop_button = Gtk.Button(label=t("run_gui.button_stop"))
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self.on_stop)
        button_row2.pack_start(self.stop_button, False, False, 0)

        # Separate from Stop above: that one waits for the current script to
        # finish on its own, which is fine for a normal script but not for
        # one that's mid-way through a multi-gigabyte download (see
        # 55-cyberbeest-sandbox-vm.sh). This kills only network-fetch
        # processes (curl/wget) among the running script's descendants,
        # rather than the whole root-owned process tree -- the script's own
        # set -euo pipefail then fails and exits cleanly on its own once the
        # download dies, instead of risking an abrupt kill mid-apt-install
        # or mid-file-write in some other script.
        self.abort_download_button = Gtk.Button(label=t("run_gui.button_abort_download"))
        self.abort_download_button.set_sensitive(False)
        self.abort_download_button.connect("clicked", self.on_abort_download)
        button_row2.pack_start(self.abort_download_button, False, False, 0)

        self.status_label = Gtk.Label(label=t("run_gui.status_idle"), xalign=0)
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
        # Themes default this to just a few px tall -- bump it so it's
        # actually easy to see progress on at a glance.
        progress_css = Gtk.CssProvider()
        progress_css.load_from_data(b"progressbar > trough { min-height: 12px; } progressbar > trough > progress { min-height: 12px; }")
        self.progress_bar.get_style_context().add_provider(progress_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root.pack_start(self.progress_bar, False, False, 0)

        self.todo_frame = Gtk.Frame(label=t("run_gui.todo_frame_title"))
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

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        paned.pack1(sidebar, False, False)

        # Filters the list by file name. Typing anywhere in the window
        # lands here (see on_window_key_press), Escape clears it.
        self.filter_entry = Gtk.SearchEntry()
        self.filter_entry.set_placeholder_text(t("run_gui.filter_placeholder"))
        self.filter_entry.connect("search-changed", self.on_filter_changed)
        self.filter_entry.connect("stop-search", lambda e: e.set_text(""))
        sidebar.pack_start(self.filter_entry, False, False, 0)
        self.connect("key-press-event", self.on_window_key_press)

        self.sidebar_scroller = Gtk.ScrolledWindow()
        self.sidebar_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sidebar_scroller.set_size_request(280, -1)
        sidebar.pack_start(self.sidebar_scroller, True, True, 0)

        self.listbox = Gtk.ListBox()
        # MULTIPLE (not SINGLE) so plain click / ctrl+click / shift+click
        # range-select all work natively, feeding "Run selected" below.
        self.listbox.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        # Explicitly False: GtkListBox defaults to activating (i.e. running)
        # a row on a single click, which is not what we want here.
        self.listbox.set_activate_on_single_click(False)
        self.listbox.connect("row-activated", self.on_row_activated)
        self.listbox.connect("selected-rows-changed", self.on_selection_changed)
        self.listbox.set_filter_func(self._row_matches_filter)
        self.sidebar_scroller.add(self.listbox)

        for script in list_scripts():
            row = ScriptRow(script)
            self.rows[script] = row
            self.listbox.add(row)
        self._update_run_changed_label()
        self._update_run_selected_sensitivity()

        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        paned.pack2(log_box, True, False)

        log_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        log_box.pack_start(log_header, False, False, 0)

        # Sensitive only once a script is actually being viewed (see
        # show_log) -- disabled at startup, when nothing is selected yet.
        self.view_source_button = Gtk.Button(label=t("run_gui.button_view_source"))
        self.view_source_button.set_sensitive(False)
        self.view_source_button.connect("clicked", lambda _b: self._view_source())
        log_header.pack_end(self.view_source_button, False, False, 0)

        log_scroller = Gtk.ScrolledWindow()
        log_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_box.pack_start(log_scroller, True, True, 0)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_buffer = self.log_view.get_buffer()
        log_scroller.add(self.log_view)

        self.show_all()

    # -- script list filter --------------------------------------------------

    def _row_matches_filter(self, row):
        words = self.filter_entry.get_text().lower().split()
        return all(word in row.script.lower() for word in words)

    def on_filter_changed(self, _entry):
        self.listbox.invalidate_filter()
        # A selected row the filter hides would still be run by "Run
        # selected" without being visible -- drop it from the selection.
        for row in self.listbox.get_selected_rows():
            if not self._row_matches_filter(row):
                self.listbox.unselect_row(row)

    def on_window_key_press(self, _window, event):
        if event.keyval == Gdk.KEY_Escape and self.filter_entry.get_text():
            self.filter_entry.set_text("")
            return True
        if isinstance(self.get_focus(), Gtk.Editable):
            return False
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK):
            return False
        char = chr(Gdk.keyval_to_unicode(event.keyval) or 0)
        if not char.isprintable() or char in ("\0", " "):
            return False
        self.filter_entry.grab_focus_without_selecting()
        return self.filter_entry.event(event)

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
            dismiss_button = Gtk.Button(label=t("run_gui.dismiss_button"))
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
            return (t("run_gui.action_open_desktop_settings"), self._open_desktop_settings)
        if script == "21-default-password-nag.sh":
            return (t("run_gui.action_open_password_settings"), self._open_password_settings)
        return None

    def _open_desktop_settings(self, _button):
        subprocess.Popen(["xfdesktop-settings"])

    def _open_password_settings(self, _button):
        subprocess.Popen([os.path.expanduser("~/.local/bin/cyberbeest-change-password")])

    def _open_report(self, script, status):
        # Separate process: the report window shows the scrubbed log and
        # sends nothing until its owner clicks Send.
        subprocess.Popen([sys.executable, os.path.join(DIR, "lib", "cyberbeest-send-report.py"), script, str(status)])

    def _do_reboot(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=t("run_gui.reboot_confirm_title"),
        )
        dialog.format_secondary_text(t("run_gui.reboot_confirm_secondary"))
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
                text = t("run_gui.log_hasnt_run_this_session").format(script=script) + on_disk
            else:
                text = t("run_gui.log_hasnt_run_yet").format(script=script)
        self.log_buffer.set_text(text)
        self.view_source_button.set_sensitive(bool(script))

    def _view_source(self):
        script = self.displayed_script
        if not script:
            return
        try:
            with open(os.path.join(DIR, script)) as f:
                source = f.read()
        except OSError as e:
            source = str(e)

        dialog = Gtk.Dialog(
            title=t("run_gui.view_source_title").format(script=script),
            transient_for=self,
            modal=True,
        )
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_size(700, 600)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        dialog.get_content_area().pack_start(scroller, True, True, 0)

        source_view = Gtk.TextView()
        source_view.set_editable(False)
        source_view.set_cursor_visible(False)
        source_view.set_monospace(True)
        source_view.get_buffer().set_text(source)
        scroller.add(source_view)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_selection_changed(self, _listbox):
        # Only treat this as "view this script's log" when exactly one row
        # ends up selected (a plain click, or ctrl/shift-click narrowing a
        # multi-selection back down to one) -- a multi-row selection being
        # built up for "Run selected" shouldn't fight over which one log to
        # show, so it's left alone in that case.
        self._update_run_selected_sensitivity()
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

    def set_row_status(self, script, state, duration=None, estimate=None):
        self.rows[script].set_status(state, duration, estimate)
        # A script just flipped done/pending -- the "Run changed only" count
        # is stale the moment any row's status changes, not just at the end
        # of a batch.
        self._update_run_changed_label()

    def _update_run_changed_label(self):
        changed_count = sum(1 for s in list_scripts() if not script_is_done(s))
        self.run_changed_button.set_label(
            t("run_gui.button_run_changed_count").format(count=changed_count)
        )
        self.run_changed_button.set_sensitive(not self.busy and changed_count > 0)

    def _update_run_selected_sensitivity(self):
        has_selection = bool(self.listbox.get_selected_rows())
        self.run_selected_button.set_sensitive(not self.busy and has_selection)

    def _add_session_runtime(self, seconds):
        self.session_total_seconds += seconds
        self.total_time_label.set_text(t("run_gui.total_time").format(duration=format_duration(self.session_total_seconds)))

    # -- starting runs --------------------------------------------------

    def _set_controls_busy(self, busy):
        self.busy = busy
        self._update_run_changed_label()
        self._update_run_selected_sensitivity()
        self.run_all_button.set_sensitive(not busy)
        self.stop_button.set_sensitive(busy)
        self.abort_download_button.set_sensitive(busy)
        # Closing mid-run would leave the root process running unattended.
        self.switch_to_update_item.set_sensitive(not busy)
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
            t("run_gui.total_time").format(duration=format_duration(self.session_total_seconds + elapsed_current))
        )
        if self.currently_running_script:
            self.status_label.set_text(
                t("run_gui.status_running_script_elapsed").format(
                    script=self.currently_running_script, elapsed=format_duration(elapsed_current)
                )
            )
        return GLib.SOURCE_CONTINUE

    def start_sequence(self, changed_only):
        if self.busy:
            return
        scripts = list_scripts()
        if changed_only:
            scripts = [s for s in scripts if not script_is_done(s)]
            if not scripts:
                self.status_label.set_text(t("run_gui.status_nothing_to_run"))
                return
        self._start_run(
            scripts,
            label=t("run_gui.button_run_changed") if changed_only else t("run_gui.button_run_all"),
            batch=True,
        )

    def start_selected(self):
        if self.busy:
            return
        selected = {row.script for row in self.listbox.get_selected_rows()}
        scripts = [s for s in list_scripts() if s in selected]
        if not scripts:
            self.status_label.set_text(t("run_gui.status_nothing_selected"))
            return
        self.listbox.unselect_all()
        # Treated as a batch run (reboot suggestion included) since, like
        # "Run all"/"Run changed only" and unlike a single-script debug
        # double-click, this is an explicit "get these steps applied" run
        # that can span multiple scripts.
        self._start_run(scripts, label=t("run_gui.button_run_selected"), batch=True)

    def _select_vm_scripts(self):
        # Just sets up the sidebar selection -- doesn't run anything itself.
        # The user reviews the selection (and can ctrl/shift-click to adjust
        # it further, e.g. re-adding 37-encrypted-dns.sh if this particular
        # VM should run its own dnscrypt-proxy rather than riding on the
        # host's) and then clicks "Run selected" same as any other manual
        # selection.
        if self.busy:
            return
        self.listbox.unselect_all()
        for script, row in self.rows.items():
            if script not in VM_INSTALL_EXCLUDE:
                self.listbox.select_row(row)
        self.status_label.set_text(
            t("run_gui.status_vm_scripts_selected").format(
                count=len(self.listbox.get_selected_rows())
            )
        )

    def on_row_activated(self, _listbox, row):
        if self.busy:
            return
        # Not a batch run: a single-script debug run via double-click
        # shouldn't nag for a reboot the way finishing all of provisioning
        # does.
        self._start_run([row.script], label=t("run_gui.label_run_single").format(script=row.script), batch=False)

    def _edit_profile(self, pending_scripts=None):
        # pending_scripts is None for the standalone "Profile..." button
        # (nothing is about to run -- only Cancel/Save are offered), or the
        # actual script list when _ensure_profile calls this right before a
        # run starts (adds a "Start N scripts" button alongside Save).
        # Returns whether the run (if any) should actually proceed --
        # RESPONSE_SAVE saves but says no, same as Cancel from the caller's
        # point of view, just with the answers persisted either way.
        dialog = ProvisioningProfileDialog(
            self,
            previous=self.profile_env or self.saved_profile_defaults,
            pending_count=len(pending_scripts) if pending_scripts else None,
        )
        answers, start_requested = dialog.collect()
        if answers is not None:
            self.profile_env = answers
            save_persisted_profile(answers)
            with open(PROFILE_FILE, "w") as f:
                for key, value in answers.items():
                    f.write(f"{key}={value}\n")
        return start_requested

    def _ensure_profile(self, scripts):
        # Only bother the user with the profile dialog if this run actually
        # touches one of the scripts it covers, and only once per run-gui.py
        # session -- "Profile..." covers revisiting/editing it later.
        # Returns False if the run should be aborted -- Cancel, or Save
        # without Start (settings saved for next time, but this particular
        # run doesn't proceed) -- True only for an actual Start click.
        if self.profile_env is not None:
            return True
        if not (set(scripts) & PROFILE_SCRIPTS) and not (
            VM_SCRIPT in scripts and vm_update_status()
        ):
            return True
        return self._edit_profile(pending_scripts=scripts)

    def _start_run(self, scripts, label, batch):
        if not self._ensure_profile(scripts):
            return
        self.current_run_is_batch = batch
        self.batch_scripts = set(scripts)
        self.stop_requested = False
        self.follow_live = True
        self.logs[""] = ""
        if self.displayed_script == "":
            self.log_buffer.set_text("")
        self.status_label.set_text(t("run_gui.status_starting").format(label=label))
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
                text=t("run_gui.confirm_run_title").format(script=script),
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
        output = []
        for line in proc.stdout:
            output.append(line)
            GLib.idle_add(self.append_log, script, line)
        status = proc.wait()
        self.proc = None
        self.last_piped_output = "".join(output)
        return status

    def _wait_unless_stopped(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.stop_requested:
                return False
            time.sleep(1)
        return True

    def _run_in_terminal(self, script):
        GLib.idle_add(
            self.append_log,
            script,
            t("run_gui.log_opening_terminal").format(script=script),
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
                GLib.idle_add(self.append_log, "", t("run_gui.log_stop_requested").format(count=len(remaining)))
                break

            script = remaining.pop(0)

            confirm_message = NEEDS_CONFIRMATION.get(script)
            has_work_check = CONFIRMATION_SKIP_IF_NOOP.get(script)
            if has_work_check is not None and not has_work_check():
                confirm_message = None
            if confirm_message and not self._confirm(script, confirm_message):
                GLib.idle_add(self.append_log, script, t("run_gui.log_skipped").format(script=script))
                GLib.idle_add(self.set_row_status, script, "skipped")
                GLib.idle_add(self._bump_progress)
                continue

            self.currently_running_script = script
            GLib.idle_add(self._begin_script_display, script)
            GLib.idle_add(self.set_row_status, script, "running", None, SCRIPT_DURATION_ESTIMATES.get(script))
            GLib.idle_add(self.status_label.set_text, t("run_gui.status_running_script").format(script=script))

            start_time = time.monotonic()
            self.current_script_start = start_time
            # A profile-driven script has no whiptail prompts left to draw,
            # so it no longer needs the xterm/TTY treatment -- runs piped
            # like everything else.
            profile_driven = self.profile_env is not None and script in PROFILE_SCRIPTS
            if script in NEEDS_TERMINAL and not profile_driven:
                status = self._run_in_terminal(script)
            else:
                GLib.idle_add(self.append_log, script, t("run_gui.log_running_marker").format(script=script))
                status = self._run_piped(script)
                # Scripts are idempotent, so re-running the whole script
                # after a transient package-server error is safe.
                for attempt, delay in enumerate(APT_RETRY_DELAYS_S, 1):
                    if status == 0 or not APT_TRANSIENT_RE.search(self.last_piped_output):
                        break
                    GLib.idle_add(
                        self.append_log, script,
                        t("run_gui.log_apt_retry").format(
                            script=script, seconds=delay, attempt=attempt, total=len(APT_RETRY_DELAYS_S)
                        ),
                    )
                    if not self._wait_unless_stopped(delay):
                        break
                    GLib.idle_add(self.append_log, script, t("run_gui.log_running_marker").format(script=script))
                    status = self._run_piped(script)
            # For a NEEDS_TERMINAL script this includes however long the
            # xterm sat open waiting for someone to work through its
            # whiptail menus, not just the script's own work -- expected,
            # since that's genuinely how long this step took this run.
            duration = time.monotonic() - start_time
            self.current_script_start = None
            GLib.idle_add(self._add_session_runtime, duration)
            GLib.idle_add(self._bump_progress)

            mark_script_result(script, status == 0)
            if status == 0:
                GLib.idle_add(
                    self.append_log, script,
                    t("run_gui.log_done_marker").format(script=script, duration=format_duration(duration)),
                )
                GLib.idle_add(self.set_row_status, script, "done", duration)
                GLib.idle_add(self._dismiss_todo, REPORT_TODO_PREFIX + script)
            else:
                failed_script = script
                # Could be a stale/wrong cached password as easily as the
                # script's own failure -- either way, cheaper to re-prompt
                # next run than to keep feeding sudo something that doesn't
                # work.
                self.sudo_password = None
                GLib.idle_add(
                    self.append_log, script,
                    t("run_gui.log_failed_marker").format(
                        script=script, duration=format_duration(duration), status=status
                    ),
                )
                GLib.idle_add(self.set_row_status, script, "failed", duration)
                GLib.idle_add(
                    self._add_todo,
                    REPORT_TODO_PREFIX + script,
                    t("run_gui.todo_report_text").format(script=script),
                    (t("run_gui.todo_report_action"),
                     lambda _b, s=script, st=status: self._open_report(s, st)),
                )
                if remaining:
                    GLib.idle_add(
                        self.append_log,
                        script,
                        t("run_gui.log_stopping_dependency"),
                    )
                break

        self.currently_running_script = None
        GLib.idle_add(self._on_finished, stopped, failed_script)

    def _on_finished(self, stopped, failed_script):
        self._set_controls_busy(False)
        if stopped:
            self.status_label.set_text(t("run_gui.status_stopped"))
        elif failed_script:
            self.status_label.set_text(t("run_gui.status_failed").format(script=failed_script))
        else:
            self.status_label.set_text(t("run_gui.status_finished"))
            if self.current_run_is_batch:
                # Supersedes any per-script "reboot (or log out/in) for X to
                # apply" todo (00-locale-keyboard-timezone.sh,
                # 00a-touchpad-tap-global.sh, 46-cyberbeest-keyboard-shortcuts.sh,
                # ...) with one aggregate suggestion -- but only if at least
                # one of those actually fired. Without this check, a batch
                # run whose scripts don't need a reboot at all (e.g.
                # cyberbeest-update reinstalling just one always-live-effect
                # script) would still nag for one, just because it went
                # through the same "Run changed only"/"Run all"/"Run
                # selected" machinery a real multi-step provisioning run
                # does.
                had_reboot_todo = False
                for key, (text, _action) in list(self.todos.items()):
                    if text.startswith("Reboot (or log out/in)"):
                        self.todos.pop(key, None)
                        had_reboot_todo = True
                if had_reboot_todo:
                    self._add_todo(
                        REBOOT_TODO_KEY,
                        t("run_gui.todo_reboot_text"),
                        action=(t("run_gui.todo_reboot_action"), self._do_reboot),
                    )
                # 00-locale-keyboard-timezone.sh always asks for a follow-up
                # "Run changed" to re-apply GRUB/LUKS/lock-screen text to the
                # scripts it just invalidated -- but if this same batch
                # already reached those scripts afterward (true for any "Run
                # all", and for "Run changed"/"Run selected" runs that happen
                # to include them), they're already re-applied and the
                # follow-up would be a no-op. Drop it in that case instead of
                # leaving a stale nag.
                locale_todo_key = "00-locale-keyboard-timezone.sh"
                if locale_todo_key in self.todos and locale_dependent_scripts() <= self.batch_scripts:
                    self._dismiss_todo(locale_todo_key)

    def on_disable_autostart(self, _menuitem):
        pending = [s for s in list_scripts() if not script_is_done(s)]
        message = t("run_gui.disable_autostart_message")
        if pending:
            message += t("run_gui.disable_autostart_pending_note").format(
                count=len(pending),
                list="\n".join(f"  • {s}" for s in pending),
            )
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=t("run_gui.disable_autostart_confirm_title"),
        )
        dialog.format_secondary_text(message)
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.YES:
            return
        try:
            os.remove(AUTOSTART_FILE)
        except OSError as e:
            self.status_label.set_text(
                t("run_gui.status_disable_autostart_failed").format(path=AUTOSTART_FILE, error=e)
            )
            return
        self.disable_autostart_item.set_sensitive(False)
        self.status_label.set_text(t("run_gui.status_autostart_disabled"))

    NETWORK_FETCH_COMMANDS = {"curl", "wget"}

    def _find_descendant_pids(self, root_pid):
        # Build the whole system's pid->(ppid, comm) map from /proc in one
        # pass, then walk down from root_pid -- cheaper than repeatedly
        # shelling out to pgrep/ps, and doesn't depend on either being
        # installed.
        children = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat") as f:
                    stat_line = f.read()
                # "pid (comm) state ppid ...": comm can itself contain
                # spaces/parens, so split on the *last* ')' rather than the
                # first, then take the fields after it.
                rparen = stat_line.rindex(")")
                comm = stat_line[stat_line.index("(") + 1 : rparen]
                ppid = int(stat_line[rparen + 2 :].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            children.setdefault(ppid, []).append((int(entry), comm))

        found = []
        stack = [root_pid]
        while stack:
            for pid, comm in children.get(stack.pop(), []):
                found.append((pid, comm))
                stack.append(pid)
        return found

    def on_abort_download(self, _button):
        if self.proc is None or self.proc.poll() is not None:
            return
        targets = [
            pid for pid, comm in self._find_descendant_pids(self.proc.pid)
            if comm in self.NETWORK_FETCH_COMMANDS
        ]
        if not targets:
            self.status_label.set_text(t("run_gui.status_abort_download_none"))
            return
        subprocess.run(
            ["sudo", "-A", "-p", "", "kill", "-TERM", *(str(p) for p in targets)],
            env=self._sudo_env(),
        )
        self.status_label.set_text(t("run_gui.status_abort_download_killed"))

    def on_switch_to_update(self, _item):
        # Cyberbeest Update pulls the latest commits and then reopens this
        # window itself, so this one just gets out of the way.
        installed = os.path.expanduser("~/.local/bin/cyberbeest-update.sh")
        updater = installed if os.path.exists(installed) else os.path.join(DIR, "lib", "cyberbeest-update.sh")
        subprocess.Popen([updater], start_new_session=True)
        self.destroy()

    def on_stop(self, _button):
        if not self.busy:
            return
        self.stop_requested = True
        self.stop_button.set_sensitive(False)
        self.status_label.set_text(t("run_gui.status_stop_requested"))

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
    # Used by cyberbeest-update.sh (bash) to get the exact same version
    # string this window shows, instead of reimplementing the pending/
    # changed logic in a second language -- see repo_version_string().
    if "--print-version" in sys.argv[1:]:
        version = repo_version_string()
        if version is None:
            sys.exit(1)
        print(version)
        return
    RunGuiWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
