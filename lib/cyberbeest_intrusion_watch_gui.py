#!/usr/bin/env python3
"""Cyberbeest Intrusion Watch.

Manually launched (or auto-refreshing) poll-mode scanner: runs a handful of
cheap, local checks and shows OK / WARN / ALERT / N-A per check. No daemon,
no realtime notifications -- click "Scan Now" or turn on auto-scan.

Checks:
  - SSH failed logins        (journalctl -u ssh, since last scan)
  - sudo auth failures       (journalctl -t sudo, since last scan)
  - LightDM failed logins    (journalctl -u lightdm, since last scan)
  - USB device insertions    (journalctl -k, since last scan; informational)
  - DNS NXDOMAIN spike       (dnscrypt-proxy nx.log/query.log, since last scan)
  - Unexpected listening ports (ss -tln/-uln, diff against an accepted baseline)
  - Unexpected persistence entries (autostart/cron/systemd-enabled, diff
    against an accepted baseline)

The three journalctl-based checks need the 'adm' group (read access to the
system journal) -- if the running user isn't in it, those checks show as
N/A with a pointer to setup-intrusion-watch-adm-group.sh instead of silently
reporting "0 failures" while actually blind.

The two baseline-diff checks (ports, persistence) need to be seeded once via
their "Accept as baseline" button before they can flag anything new.
"""

import datetime
import json
import os
import re
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

STATE_DIR = os.path.expanduser("~/.config/cyberbeest/intrusion-watch")
STATE_PATH = os.path.join(STATE_DIR, "state.json")
DNS_LOG_DIR = "/var/log/dnscrypt-proxy"

STATUS_ICON = {"ok": "✅", "warn": "⚠️", "alert": "\U0001F6A8", "na": "➖"}
STATUS_LABEL = {"ok": "OK", "warn": "WARN", "alert": "ALERT", "na": "N/A"}


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def in_adm_group():
    import grp

    try:
        return any(grp.getgrgid(g).gr_name == "adm" for g in os.getgroups())
    except (KeyError, OSError):
        return False


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def journal_lines_since(since_iso, unit=None, syslog_id=None):
    cmd = ["journalctl", "--no-pager", "-q", f"--since={since_iso}"]
    if unit:
        cmd += ["-u", unit]
    if syslog_id:
        cmd += ["-t", syslog_id]
    out = run(cmd)
    return [l for l in out.splitlines() if l.strip()]


class Check:
    """Result of one scan check."""

    def __init__(self, key, name, status, summary, details=None, diff_key=None):
        self.key = key
        self.name = name
        self.status = status
        self.summary = summary
        self.details = details or []
        self.diff_key = diff_key  # state key to update when "Accept as baseline" is used


ADM_NOTE = "Needs the 'adm' group for journal read access -- log out and back in (it's normally granted at install time)."


def check_ssh(since_iso, since_dt):
    unit_exists = run(["systemctl", "list-unit-files", "ssh.service"]).strip()
    if "ssh.service" not in unit_exists:
        return Check("ssh", "SSH failed logins", "na", "sshd not installed")
    if not in_adm_group():
        return Check("ssh", "SSH failed logins", "na", ADM_NOTE)
    lines = journal_lines_since(since_iso, unit="ssh")
    hits = [l for l in lines if re.search(r"Failed password|Invalid user|Connection closed by (invalid|authenticating) user", l)]
    if not hits:
        return Check("ssh", "SSH failed logins", "ok", f"0 failed attempts since {since_dt}")
    status = "alert" if len(hits) >= 10 else "warn"
    return Check("ssh", "SSH failed logins", status, f"{len(hits)} failed attempt(s) since {since_dt}", hits[-50:])


def check_sudo(since_iso, since_dt):
    if not in_adm_group():
        return Check("sudo", "sudo auth failures", "na", ADM_NOTE)
    lines = journal_lines_since(since_iso, syslog_id="sudo")
    hits = [l for l in lines if "authentication failure" in l or "incorrect password" in l]
    if not hits:
        return Check("sudo", "sudo auth failures", "ok", f"0 failures since {since_dt}")
    status = "alert" if len(hits) >= 5 else "warn"
    return Check("sudo", "sudo auth failures", status, f"{len(hits)} failure(s) since {since_dt}", hits[-50:])


def check_lightdm(since_iso, since_dt):
    unit_exists = run(["systemctl", "list-unit-files", "lightdm.service"]).strip()
    if "lightdm.service" not in unit_exists:
        return Check("lightdm", "Login screen failed logins", "na", "lightdm not installed")
    if not in_adm_group():
        return Check("lightdm", "Login screen failed logins", "na", ADM_NOTE)
    lines = journal_lines_since(since_iso, unit="lightdm")
    hits = [l for l in lines if re.search(r"pam_unix.*authentication failure|auth could not identify password", l)]
    if not hits:
        return Check("lightdm", "Login screen failed logins", "ok", f"0 failed logins since {since_dt}")
    status = "alert" if len(hits) >= 5 else "warn"
    return Check("lightdm", "Login screen failed logins", status, f"{len(hits)} failed login(s) since {since_dt}", hits[-50:])


def check_usb(since_iso, since_dt):
    if not in_adm_group():
        return Check("usb", "USB device insertions", "na", ADM_NOTE)
    lines = journal_lines_since(since_iso, unit=None)
    hits = [l for l in lines if re.search(r"New USB device found|usb \d.*: new .*device", l)]
    if not hits:
        return Check("usb", "USB device insertions", "ok", f"0 new devices since {since_dt}")
    return Check("usb", "USB device insertions", "warn", f"{len(hits)} device event(s) since {since_dt} -- informational, verify these were expected", hits[-50:])


def _tail_since_offset(path, offset):
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], 0
    if offset > size:
        offset = 0  # log rotated/truncated
    with open(path, "rt", errors="replace") as f:
        f.seek(offset)
        lines = [l for l in f.read().splitlines() if l.strip()]
    return lines, size


def check_dns(state, since_dt):
    nx_path = os.path.join(DNS_LOG_DIR, "nx.log")
    q_path = os.path.join(DNS_LOG_DIR, "query.log")
    if not os.path.exists(nx_path) or not os.path.exists(q_path):
        return Check("dns", "DNS NXDOMAIN spike", "na", "dnscrypt-proxy query/nx logging not enabled")
    offsets = state.setdefault("dns_offsets", {})
    nx_lines, nx_size = _tail_since_offset(nx_path, offsets.get("nx", 0))
    q_lines, q_size = _tail_since_offset(q_path, offsets.get("query", 0))
    offsets["nx"] = nx_size
    offsets["query"] = q_size
    if offsets.get("nx", 0) == 0 and not nx_lines:
        pass  # first run, nothing to compare yet
    total = len(q_lines)
    nx_count = len(nx_lines)
    if total == 0 and nx_count == 0:
        return Check("dns", "DNS NXDOMAIN spike", "ok", f"No DNS activity since {since_dt}")
    ratio = (nx_count / total) if total else 1.0
    if nx_count >= 60 or (total >= 20 and ratio > 0.5):
        status = "alert"
    elif nx_count >= 20 or (total >= 20 and ratio > 0.25):
        status = "warn"
    else:
        status = "ok"
    summary = f"{nx_count} NXDOMAIN / {total} queries since {since_dt}"
    return Check("dns", "DNS NXDOMAIN spike", status, summary, nx_lines[-50:])


def _listening_ports():
    ports = set()
    for cmd in (["ss", "-tlnH"], ["ss", "-ulnH"]):
        for line in run(cmd).splitlines():
            parts = line.split()
            if len(parts) >= 4:
                proto = "tcp" if cmd[1] == "-tlnH" else "udp"
                ports.add(f"{proto} {parts[3]}")
    return ports


def check_ports(state):
    current = _listening_ports()
    baseline = state.get("baseline_ports")
    if baseline is None:
        return Check("ports", "Unexpected listening ports", "na",
                      "No baseline yet -- review the list below, then Accept as baseline",
                      sorted(current), diff_key="baseline_ports")
    new = sorted(current - set(baseline))
    gone = sorted(set(baseline) - current)
    if not new:
        summary = "No new listening ports" + (f" ({len(gone)} closed since baseline)" if gone else "")
        return Check("ports", "Unexpected listening ports", "ok", summary)
    details = [f"+ {p}" for p in new] + [f"- {p}" for p in gone]
    return Check("ports", "Unexpected listening ports", "warn",
                 f"{len(new)} new listening port(s) since baseline", details, diff_key="baseline_ports")


def _persistence_set():
    entries = set()
    for path in (os.path.expanduser("~/.config/autostart"), "/etc/xdg/autostart"):
        try:
            for f in os.listdir(path):
                if f.endswith(".desktop"):
                    entries.add(f"autostart:{f}")
        except OSError:
            pass
    for line in run(["crontab", "-l"]).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(f"cron-user:{line}")
    for line in run(["systemctl", "list-unit-files", "--state=enabled", "--no-legend", "--no-pager"]).splitlines():
        parts = line.split()
        if parts:
            entries.add(f"systemd-enabled:{parts[0]}")
    return entries


def check_persistence(state):
    current = _persistence_set()
    baseline = state.get("baseline_persistence")
    if baseline is None:
        return Check("persistence", "Unexpected autostart/cron/systemd entries", "na",
                      "No baseline yet -- review the list below, then Accept as baseline",
                      sorted(current), diff_key="baseline_persistence")
    new = sorted(current - set(baseline))
    gone = sorted(set(baseline) - current)
    if not new:
        summary = "No new persistence entries" + (f" ({len(gone)} removed since baseline)" if gone else "")
        return Check("persistence", "Unexpected autostart/cron/systemd entries", "ok", summary)
    details = [f"+ {p}" for p in new] + [f"- {p}" for p in gone]
    return Check("persistence", "Unexpected autostart/cron/systemd entries", "warn",
                 f"{len(new)} new entry/entries since baseline", details, diff_key="baseline_persistence")


CHECK_FNS_LOG_BASED = [check_ssh, check_sudo, check_lightdm, check_usb]


def run_all_checks(state):
    now = datetime.datetime.now()
    last_scan = state.get("last_scan")
    since_dt = last_scan or "(24h ago)"
    since_iso = last_scan or (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    results = [fn(since_iso, since_dt) for fn in CHECK_FNS_LOG_BASED]
    results.append(check_dns(state, since_dt))
    results.append(check_ports(state))
    results.append(check_persistence(state))

    state["last_scan"] = now.strftime("%Y-%m-%d %H:%M:%S")
    return results


class IntrusionWatchWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Cyberbeest Intrusion Watch")
        self.set_default_size(760, 560)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("destroy", Gtk.main_quit)

        self.state = load_state()
        self._results_by_row = {}
        self._auto_timeout_id = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_border_width(8)
        self.add(root)

        if not in_adm_group():
            bar = Gtk.InfoBar()
            bar.set_message_type(Gtk.MessageType.WARNING)
            content = bar.get_content_area()
            content.add(Gtk.Label(
                label="Not in the 'adm' group -- SSH/sudo/LightDM/USB checks will show N/A. "
                      "See setup-intrusion-watch-adm-group.sh.",
                wrap=True,
            ))
            root.pack_start(bar, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        scan_btn = Gtk.Button(label="Scan Now")
        scan_btn.connect("clicked", lambda _b: self.scan())
        toolbar.pack_start(scan_btn, False, False, 0)

        auto_check = Gtk.CheckButton(label="Auto-scan every")
        auto_check.connect("toggled", self._on_auto_toggled)
        toolbar.pack_start(auto_check, False, False, 0)
        self.auto_check = auto_check

        interval_combo = Gtk.ComboBoxText()
        for label in ("5 min", "15 min", "30 min", "60 min"):
            interval_combo.append_text(label)
        interval_combo.set_active(1)
        toolbar.pack_start(interval_combo, False, False, 0)
        self.interval_combo = interval_combo

        self.status_label = Gtk.Label(label="Not scanned yet")
        self.status_label.set_xalign(1)
        toolbar.pack_start(self.status_label, True, True, 0)
        root.pack_start(toolbar, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        scroller.add(self.listbox)
        paned.pack1(scroller, resize=True, shrink=False)

        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        detail_box.set_border_width(4)
        detail_scroller = Gtk.ScrolledWindow()
        self.detail_view = Gtk.TextView()
        self.detail_view.set_editable(False)
        self.detail_view.set_monospace(True)
        self.detail_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        detail_scroller.add(self.detail_view)
        detail_box.pack_start(detail_scroller, True, True, 0)

        self.accept_btn = Gtk.Button(label="Accept as baseline")
        self.accept_btn.set_sensitive(False)
        self.accept_btn.connect("clicked", self._on_accept_baseline)
        detail_box.pack_start(self.accept_btn, False, False, 0)

        paned.pack2(detail_box, resize=True, shrink=False)
        paned.set_position(260)
        root.pack_start(paned, True, True, 0)

        self.show_all()
        self.scan()

    def _on_auto_toggled(self, btn):
        if self._auto_timeout_id is not None:
            GLib.source_remove(self._auto_timeout_id)
            self._auto_timeout_id = None
        if btn.get_active():
            minutes = int(self.interval_combo.get_active_text().split()[0])
            self._auto_timeout_id = GLib.timeout_add_seconds(minutes * 60, self._on_auto_tick)

    def _on_auto_tick(self):
        self.scan()
        return True  # keep repeating

    def scan(self):
        self.status_label.set_text("Scanning...")

        def worker():
            results = run_all_checks(self.state)
            save_state(self.state)
            GLib.idle_add(self._on_scanned, results)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scanned(self, results):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        self._results_by_row = {}

        worst = "ok"
        for res in results:
            if res.status == "alert":
                worst = "alert"
            elif res.status == "warn" and worst != "alert":
                worst = "warn"

            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(4)
            icon = Gtk.Label(label=STATUS_ICON[res.status])
            icon.set_width_chars(3)
            box.pack_start(icon, False, False, 0)
            name = Gtk.Label(label=res.name)
            name.set_xalign(0)
            name.set_width_chars(34)
            box.pack_start(name, False, False, 0)
            summary = Gtk.Label(label=res.summary)
            summary.set_xalign(0)
            summary.set_ellipsize(Pango.EllipsizeMode.END)
            summary.set_width_chars(1)
            box.pack_start(summary, True, True, 0)
            row.add(box)
            self.listbox.add(row)
            self._results_by_row[row] = res
        self.listbox.show_all()

        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.status_label.set_text(f"Last scan {now} -- overall: {STATUS_LABEL[worst]}")
        return False

    def _on_row_selected(self, _listbox, row):
        buf = self.detail_view.get_buffer()
        if row is None:
            buf.set_text("")
            self.accept_btn.set_sensitive(False)
            return
        res = self._results_by_row.get(row)
        if not res:
            return
        text = res.summary + "\n\n" + "\n".join(res.details) if res.details else res.summary
        buf.set_text(text)
        self.accept_btn.set_sensitive(res.diff_key is not None)
        self._selected_result = res

    def _on_accept_baseline(self, _btn):
        res = getattr(self, "_selected_result", None)
        if not res or not res.diff_key:
            return
        if res.key == "ports":
            self.state[res.diff_key] = sorted(_listening_ports())
        elif res.key == "persistence":
            self.state[res.diff_key] = sorted(_persistence_set())
        save_state(self.state)
        self.scan()


def main():
    win = IntrusionWatchWindow()
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
