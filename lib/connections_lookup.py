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
import json
import os
import re
import subprocess
import sys

CACHE_PATH = f"/run/user/{os.getuid()}/cyberbeest-connections-names.json"

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


if __name__ == "__main__":
    print_summary()
