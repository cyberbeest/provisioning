#!/usr/bin/env python3
"""IP-to-country lookup for the network icon's flags (opt-in).

The table is built weekly on our server from the public registry statistics
(cyberbeest-vserver/geo/build-geo.py) and downloaded only while the option is
on. Lookups are local; no IP address ever leaves the machine.

    geo.py --update [--force]   fetch the table if the option is on (--force: regardless)
    geo.py --remove             delete the table
    geo.py IP...                print the country of each address
"""
import gzip
import hashlib
import ipaddress
import json
import os
import struct
import sys
import urllib.request

BASE_URL = "https://downloads.cyberbeest.com/geo/geo-country.bin.gz"
DATA_DIR = os.path.expanduser("~/.local/share/cyberbeest")
TABLE = os.path.join(DATA_DIR, "geo-country.bin")
SETTINGS = os.path.expanduser("~/.config/cyberbeest/connections/settings.json")
MAGIC = b"CBGEO1\0\0"
HEADER = 16


def flags_enabled():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return bool(json.load(f).get("flags", False))
    except (OSError, ValueError):
        return False


def flag_emoji(cc):
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in cc)


class Geo:
    def __init__(self, path=TABLE):
        with open(path, "rb") as f:
            self.data = f.read()
        if self.data[:8] != MAGIC:
            raise ValueError("not a geo table")
        self.n4, self.n6 = struct.unpack_from("<II", self.data, 8)
        self.off6 = HEADER + self.n4 * 6

    def _search(self, base, n, stride, fmt, key):
        lo, hi, hit = 0, n, None
        while lo < hi:
            mid = (lo + hi) // 2
            if struct.unpack_from(fmt, self.data, base + mid * stride)[0] <= key:
                hit, lo = mid, mid + 1
            else:
                hi = mid
        if hit is None:
            return None
        cc = self.data[base + hit * stride + stride - 2: base + hit * stride + stride]
        return cc.decode() if cc != b"\0\0" else None

    def country(self, ip):
        """Two-letter country code, or None (unknown, private, unassigned)."""
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return None
        addr = getattr(addr, "ipv4_mapped", None) or addr
        if addr.version == 4:
            return self._search(HEADER, self.n4, 6, "<I", int(addr))
        return self._search(self.off6, self.n6, 10, "<Q", int(addr) >> 64)


def load():
    """The table if the option is on and a table is installed, else None."""
    if not flags_enabled():
        return None
    try:
        return Geo()
    except (OSError, ValueError, struct.error):
        return None


def _fetch(url, limit):
    req = urllib.request.Request(url, headers={"User-Agent": "cyberbeest-geo/1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("download too large")
    return data


def update(force=False):
    if not force and not flags_enabled():
        return "off"
    sha_path = TABLE + ".sha256"
    want = _fetch(BASE_URL + ".sha256", 200).decode().strip()
    if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
        raise ValueError("bad checksum file")
    try:
        have = open(sha_path).read().strip()
    except OSError:
        have = ""
    if have == want and os.path.exists(TABLE):
        return "current"
    blob = gzip.decompress(_fetch(BASE_URL, 5_000_000))
    if hashlib.sha256(blob).hexdigest() != want or blob[:8] != MAGIC:
        raise ValueError("checksum mismatch")
    try:
        old = os.path.getsize(TABLE)
    except OSError:
        old = 0
    if len(blob) < old // 2 or len(blob) < 500_000:
        raise ValueError("new table implausibly small")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TABLE + ".tmp", "wb") as f:
        f.write(blob)
    os.replace(TABLE + ".tmp", TABLE)
    with open(sha_path, "w") as f:
        f.write(want + "\n")
    return "updated"


def remove():
    for p in (TABLE, TABLE + ".sha256"):
        try:
            os.remove(p)
        except OSError:
            pass


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--update" in args:
        try:
            print(update("--force" in args))
        except (OSError, ValueError) as e:
            print(f"failed: {e}")
            sys.exit(1)
    elif "--remove" in args:
        remove()
    else:
        g = Geo()
        for ip in args:
            print(ip, g.country(ip))
