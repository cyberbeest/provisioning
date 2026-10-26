#!/usr/bin/env python3
"""Reads established TCP connections and names their apps.

Shared by the connections window and the panel tooltip (run directly it prints
"in|out <app>" per connection). ss cannot name processes inside firejail
sandboxes, so those are found by joining each sandbox and matching socket
inodes. That scan costs about a second, so its result is cached per socket
inode and the scan only runs for a socket not seen before, and only when the
caller allows it (the window always does; the panel tooltip when hovered or once a minute,
by setting CONNECTIONS_SCAN). An unidentified sandboxed socket is printed as
"uid <n>" in that mode.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys

RUN_DIR = f"/run/user/{os.getuid()}"
CACHE_PATH = f"{RUN_DIR}/cyberbeest-connections-names.json"
NOTIFIED_PATH = f"{RUN_DIR}/cyberbeest-connections-notified.json"
SPARKLE_PATH = f"{RUN_DIR}/cyberbeest-connections-sparkle"
SETTINGS_PATH = os.path.expanduser("~/.config/cyberbeest/connections/settings.json")

from i18n import t  # noqa: E402


_display = {}


def display_name(proc):
    """Name to show for a process: from connections-names.txt (SSH, Firefox,
    ...), else the process name itself."""
    if not _display:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "connections-names.txt"), encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2 and not line.startswith("#"):
                        _display[parts[0]] = parts[1]
        except OSError:
            pass
        _display.setdefault("", "")
    return _display.get(proc, proc)


def split_endpoint(ep):
    host, _, port = ep.rpartition(":")
    return host.strip("[]"), port


def is_loopback(ip):
    return ip.startswith("127.") or ip == "::1"


def uid_name(uid):
    try:
        import pwd
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return f"uid {uid}"


def listening_ports(env):
    out = subprocess.run(
        ["ss", "-tlnH"], capture_output=True, text=True, env=env,
    ).stdout
    return {split_endpoint(l.split()[3])[1] for l in out.splitlines() if len(l.split()) >= 4}


SANDBOX_SH = r"""
for d in /proc/[0-9]*/fdinfo/*; do
    p=${d%%/fdinfo/*}
    [ -S "$p/fd/${d##*/}" ] || continue
    while read k v; do
        [ "$k" = "ino:" ] && { read c < "$p/comm"; echo "$v $c"; }
    done < "$d"
done
"""


def sandbox_sockets(env):
    """{socket inode: app name} for firejail sandboxes. Firejail hides its
    processes from ss, but inside the sandbox they are visible."""
    out = subprocess.run(
        ["firejail", "--list"], capture_output=True, text=True, env=env,
    ).stdout
    owners = {}
    for line in out.splitlines():
        pid = line.split(":")[0]
        if not pid.isdigit():
            continue
        try:
            res = subprocess.run(
                ["firejail", f"--join={pid}", "sh", "-c", SANDBOX_SH],
                capture_output=True, text=True, env=env, timeout=5,
            ).stdout
        except subprocess.TimeoutExpired:
            continue
        for l in res.splitlines():
            ino, _, name = l.partition(" ")
            if name:
                owners[ino] = name
    return owners


def read_connections(mark_sandboxed=True, scan=True):
    """Returns {app: [(ip, port, incoming, local port), ...]}.

    A connection is incoming when its local port is one a local socket is
    listening on.
    """
    env = dict(os.environ, LC_ALL="C")
    listening = listening_ports(env)
    out = subprocess.run(
        ["ss", "-tnpeH", "state", "established"],
        capture_output=True, text=True, env=env,
    ).stdout
    apps = {}
    cache = load_cache()
    seen = set(re.findall(r"ino:(\d+)", out))
    scanned = False
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 4:
            continue
        lip, lport = split_endpoint(cols[2])
        rip, rport = split_endpoint(cols[3])
        if is_loopback(lip) or is_loopback(rip):
            continue
        m = re.search(r'\(\("([^"]+)"', line)
        if m:
            app = display_name(m.group(1))
        else:
            u = re.search(r"uid:(\d+)", line)
            if not u or int(u.group(1)) >= 1000:
                ino = re.search(r"ino:(\d+)", line)
                name = cache.get(ino.group(1)) if ino else None
                if ino and name is None and scan and not scanned:
                    scanned = True
                    cache.update(sandbox_sockets(env))
                    name = cache.get(ino.group(1))
                if name:
                    name = display_name(name)
                    app = f"{name} ({t('connections.sandboxed')})" if mark_sandboxed else name
                elif mark_sandboxed or not u:
                    app = t("connections.unknown")
                else:
                    app = f"uid {u.group(1)}"  # the panel script words this itself
            else:
                app = f"{uid_name(u.group(1))} ({t('connections.system_service')})"
        apps.setdefault(app, []).append((rip, rport, lport in listening, lport))
    if scan or scanned:
        save_cache({k: v for k, v in cache.items() if k in seen})
    return apps


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def print_summary():
    """One "in|out <app>" line per connection, for the panel tooltip."""
    scan = bool(os.environ.get("CONNECTIONS_SCAN"))
    for app, conns in read_connections(mark_sandboxed=False, scan=scan).items():
        for _rip, _rport, is_in, _lport in conns:
            print(f"{'in' if is_in else 'out'} {app}")


DNS_WATCH_SOCK = "/run/cyberbeest-dns-watch/sock"


def dns_names_enabled():
    return bool(read_settings().get("dnsnames", False))


def dns_names(ips):
    """{ip: name the address was looked up under}, from cyberbeest-dns-watch.
    Empty when the option is off or the service is not running."""
    if not ips or not dns_names_enabled():
        return {}
    out = {}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(DNS_WATCH_SOCK)
        buf = b""
        for ip in sorted(set(ips)):
            s.sendall(ip.encode() + b"\n")
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    return out
                buf += chunk
            line, _, buf = buf.partition(b"\n")
            if line:
                out[ip] = line.decode("ascii", "replace")
    except OSError:
        pass
    finally:
        s.close()
    return out


def flags_for(conns, geo):
    """Flag emoji for an app's connections, most connections first: the
    country's flag, 🏠 for the local network, 🌐 for an unknown country."""
    from geo import flag_emoji
    counts = {}
    for rip, _port, _in, _lport in conns:
        if is_lan(rip):
            key = "🏠"
        else:
            cc = geo.country(rip)
            key = flag_emoji(cc) if cc else "🌐"
        counts[key] = counts.get(key, 0) + 1
    return "".join(k for k, _n in sorted(counts.items(), key=lambda kv: -kv[1]))


_names = {}


def country_name(cc):
    """Country name in the user's language (iso-codes), or the code itself."""
    if not _names:
        import gettext
        import i18n
        try:
            with open("/usr/share/iso-codes/json/iso_3166-1.json", encoding="utf-8") as f:
                en = {c["alpha_2"]: c.get("common_name") or c["name"]
                      for c in json.load(f)["3166-1"]}
        except (OSError, ValueError, KeyError):
            en = {}
        tr = gettext.translation("iso_3166-1", "/usr/share/locale",
                                 languages=[i18n._LOCALE], fallback=True)
        _names.update({k: tr.gettext(v) for k, v in en.items()})
    return _names.get(cc, cc)


def country_names(conns, geo):
    """Names of the countries behind the connections, most connections first."""
    counts = {}
    for rip, _port, _in, _lport in conns:
        cc = geo.country(rip)
        if cc:
            counts[cc] = counts.get(cc, 0) + 1
    return [country_name(cc) for cc, _n in sorted(counts.items(), key=lambda kv: -kv[1])]


def print_rows(geo):
    """"<count> in|out <app>\t<flags>" per app and direction, for the panel
    tooltip when flags are on."""
    scan = bool(os.environ.get("CONNECTIONS_SCAN"))
    rows = []
    for app, conns in read_connections(mark_sandboxed=False, scan=scan).items():
        for is_in in (True, False):
            sub = [c for c in conns if c[2] == is_in]
            if sub:
                rows.append((len(sub), f"{'in' if is_in else 'out'} {app}", flags_for(sub, geo)))
    for n, rest, flags in sorted(rows, key=lambda r: -r[0]):
        print(f"{n} {rest}\t{flags}")


def is_lan(ip):
    """True for private, link-local and similar non-routable addresses."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    addr = getattr(addr, "ipv4_mapped", None) or addr
    return addr.is_private or addr.is_link_local


def friendly_name(comm):
    """Name from the app's .desktop entry, matched on the executable (comm is
    cut to 15 characters); falls back to the process name."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        matches = []
        for info in Gio.AppInfo.get_all():
            exe = os.path.basename((info.get_executable() or "").strip())
            if exe and (exe == comm or (len(comm) >= 15 and exe.startswith(comm))):
                matches.append(info)
        # Only the entry named after the program counts (not a web-app
        # launcher that merely runs it).
        prefix = comm.split("-")[0].lower()
        for info in matches:
            if (info.get_id() or "").lower().startswith(prefix):
                return info.get_name()
    except (ImportError, ValueError):
        pass
    return comm[:1].upper() + comm[1:]


def notifications_enabled():
    return read_settings().get("notify", True)


def read_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def notify_new_apps():
    """Pops up one notification for apps that talk on the network for the first
    time this session, saying whether it reaches the Internet, the local
    network or both (announced again when an app first reaches the other one). Sockets of unnamed sandboxed apps and
    of system services are skipped."""
    if not notifications_enabled():
        return
    unknown = t("connections.unknown")
    service = f"({t('connections.system_service')})"
    try:
        with open(NOTIFIED_PATH, encoding="utf-8") as f:
            notified = json.load(f)
    except (OSError, ValueError):
        notified = {}
    try:
        from geo import load
        geo = load()
    except ImportError:
        geo = None
    fresh = []
    for app, conns in read_connections(mark_sandboxed=False, scan=False).items():
        if app == unknown or app.startswith("uid ") or app.endswith(service):
            continue
        seen = {"lan" if is_lan(rip) else "wan" for rip, _p, _i, _l in conns}
        known = set(notified.get(app, []))
        if seen <= known:
            continue
        known |= seen
        notified[app] = sorted(known)
        scope = "both" if len(known) == 2 else known.pop()
        wan = [c for c in conns if not is_lan(c[0])]
        fresh.append((app, scope, flags_for(wan, geo) if geo else "",
                      country_names(wan, geo) if geo else []))
    if not fresh:
        return
    with open(NOTIFIED_PATH, "w", encoding="utf-8") as f:
        json.dump(notified, f)
    with open(SPARKLE_PATH, "w"):
        pass
    lines = []
    for app, scope, flags, names in sorted(fresh, key=lambda x: x[1] == "lan"):
        if names:
            if scope != "wan":
                names = names + [t("connections.where_lan")]
            more = len(names) - 3
            if more > 0:
                names = names[:3] + [t("connections.where_more").format(n=more)]
            where = names[0] if len(names) == 1 else (
                ", ".join(names[:-1]) + t("connections.where_and") + names[-1])
            text = t("connections.notify_to").format(app=friendly_name(app), where=where)
        else:
            text = t(f"connections.notify_{scope}").format(app=friendly_name(app))
        lines.append((flags + " " + text).strip())
    if len(lines) > 5:
        lines = lines[:5] + [t("connections.notify_more").format(n=len(lines) - 5)]
    try:
        show_toast(t("connections.notify_title"), lines)
    except (ImportError, ValueError):
        subprocess.run(
            ["notify-send", "-a", "Cyberbeest", "-i", "network-transmit-receive",
             "-t", "7000", t("connections.notify_title"), "\n".join(lines)],
            check=False,
        )


def show_toast(title, lines, seconds=6):
    """Small popup in the bottom right corner of the work area (the desktop
    notification daemon has one global position and size, so this draws its
    own). Click to dismiss; blocks until it closes."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    win = Gtk.Window(type=Gtk.WindowType.POPUP)
    win.set_accept_focus(False)
    win.set_keep_above(True)
    win.set_skip_taskbar_hint(True)
    css = Gtk.CssProvider()
    css.load_from_data(b"window { background: #2b2b2b; border: 1px solid #b8925a; }"
                       b"label { color: #f0f0f0; font-size: 9pt; }"
                       b"label.title { color: #b8925a; font-weight: bold; }")
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, border_width=8)
    head = Gtk.Label(label="🌐 " + title, xalign=0)
    head.get_style_context().add_class("title")
    box.pack_start(head, False, False, 0)
    for line in lines:
        box.pack_start(Gtk.Label(label=line, xalign=0), False, False, 0)
    ev = Gtk.EventBox()
    ev.add(box)
    ev.connect("button-press-event", lambda *_: Gtk.main_quit())
    win.add(ev)
    win.show_all()
    area = Gdk.Display.get_default().get_primary_monitor().get_workarea()
    w, h = win.get_size()
    win.move(area.x + area.width - w - 12, area.y + area.height - h - 12)
    GLib.timeout_add_seconds(seconds, Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    if "--notify" in sys.argv:
        notify_new_apps()
    elif "--rows" in sys.argv:
        from geo import load
        print_rows(load())
    else:
        print_summary()
