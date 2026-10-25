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
import subprocess
import sys

RUN_DIR = f"/run/user/{os.getuid()}"
CACHE_PATH = f"{RUN_DIR}/cyberbeest-connections-names.json"
NOTIFIED_PATH = f"{RUN_DIR}/cyberbeest-connections-notified.json"
SPARKLE_PATH = f"{RUN_DIR}/cyberbeest-connections-sparkle"
SETTINGS_PATH = os.path.expanduser("~/.config/cyberbeest/connections/settings.json")

from i18n import t  # noqa: E402


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
    """Returns {app: [(ip, port, incoming), ...]}.

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
            app = m.group(1)
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
                    app = f"{name} ({t('connections.sandboxed')})" if mark_sandboxed else name
                elif mark_sandboxed or not u:
                    app = t("connections.unknown")
                else:
                    app = f"uid {u.group(1)}"  # the panel script words this itself
            else:
                app = f"{uid_name(u.group(1))} ({t('connections.system_service')})"
        apps.setdefault(app, []).append((rip, rport, lport in listening))
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
        for _rip, _rport, is_in in conns:
            print(f"{'in' if is_in else 'out'} {app}")


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
    fresh = []
    for app, conns in read_connections(mark_sandboxed=False, scan=False).items():
        if app == unknown or app.startswith("uid ") or app.endswith(service):
            continue
        seen = {"lan" if is_lan(rip) else "wan" for rip, _p, _i in conns}
        known = set(notified.get(app, []))
        if seen <= known:
            continue
        known |= seen
        notified[app] = sorted(known)
        scope = "both" if len(known) == 2 else known.pop()
        fresh.append((app, scope))
    if not fresh:
        return
    with open(NOTIFIED_PATH, "w", encoding="utf-8") as f:
        json.dump(notified, f)
    with open(SPARKLE_PATH, "w"):
        pass
    lines = [t(f"connections.notify_{scope}").format(app=friendly_name(app))
             for app, scope in sorted(fresh, key=lambda x: x[1] == "lan")]
    if len(lines) > 5:
        lines = lines[:5] + [t("connections.notify_more").format(n=len(lines) - 5)]
    subprocess.run(
        ["notify-send", "-a", "Cyberbeest", "-i", "network-transmit-receive",
         "-t", "7000", t("connections.notify_title"), "\n".join(lines)],
        check=False,
    )


if __name__ == "__main__":
    if "--notify" in sys.argv:
        notify_new_apps()
    else:
        print_summary()
