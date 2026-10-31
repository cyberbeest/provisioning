#!/usr/bin/env python3
"""Remembers which host name an IP address was looked up under, so the network
connections window can show "api.example.com" instead of a bare address.

Runs as a small service (cyberbeest-dns-watch.service, opt-in in Settings) with
only the right to capture packets. It reads the answers that apps get from the
local DNS proxy (dnscrypt-proxy, UDP port 53 on the loopback interface) and
keeps IP -> name in memory only: the most recent MAX_ENTRIES addresses, each for
at most MAX_AGE seconds. Nothing is written to disk.

Other programs ask over a Unix socket, one address per line, and get the name
back (or an empty line). There is no command that lists the cache, and a
request is refused unless the peer is one of our own viewer scripts, runs as
the allowed user and is not inside a sandbox (its own pid namespace or a
seccomp filter, as Firejail sets up), so a sandboxed app cannot learn which
hosts the rest of the system talked to.
"""
import ipaddress
import os
import select
import socket
import struct
import sys
import time
from collections import OrderedDict

SOCK_PATH = "/run/cyberbeest-dns-watch/sock"
MAX_ENTRIES = 2000
MAX_AGE = 3600
MAX_LINES_PER_CONN = 1000
GLOBAL_PER_MINUTE = 5000
VIEWERS = ("connections-window.py", "connections_lookup.py", "connections-genmon.sh")

cache = OrderedDict()  # ip string -> (name, time)


def remember(ip, name):
    cache[ip] = (name, time.time())
    cache.move_to_end(ip)
    while len(cache) > MAX_ENTRIES:
        cache.popitem(last=False)


def lookup(ip):
    try:
        ip = str(ipaddress.ip_address(ip.strip().split("%")[0]))
    except ValueError:
        return ""
    hit = cache.get(ip)
    if not hit:
        return ""
    if time.time() - hit[1] > MAX_AGE:
        del cache[ip]
        return ""
    return hit[0]


# --- DNS parsing -----------------------------------------------------------

def read_name(msg, off):
    """Returns (name, offset after it in the record), following compression."""
    labels, end, jumps = [], None, 0
    while True:
        if off >= len(msg):
            raise ValueError("truncated")
        n = msg[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            if off + 1 >= len(msg):
                raise ValueError("truncated")
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | msg[off + 1]
            jumps += 1
            if jumps > 20:
                raise ValueError("loop")
            continue
        off += 1
        labels.append(msg[off:off + n].decode("ascii", "replace"))
        off += n
    return ".".join(labels).lower(), (end if end is not None else off)


def parse_response(msg):
    """[(ip, asked name)] for the A/AAAA records of a DNS response."""
    if len(msg) < 12:
        return []
    flags, qd, an = struct.unpack_from(">2xHHH", msg, 0)
    if not flags & 0x8000 or flags & 0xF or not an:  # not a response / error
        return []
    off, asked = 12, None
    try:
        for _ in range(qd):
            name, off = read_name(msg, off)
            off += 4
            asked = asked or name
        out = []
        for _ in range(an):
            _name, off = read_name(msg, off)
            rtype, _cls, _ttl, rdlen = struct.unpack_from(">HHIH", msg, off)
            off += 10
            if rtype == 1 and rdlen == 4:
                out.append((str(ipaddress.IPv4Address(msg[off:off + 4])), asked))
            elif rtype == 28 and rdlen == 16:
                out.append((str(ipaddress.IPv6Address(msg[off:off + 16])), asked))
            off += rdlen
        return out
    except (ValueError, struct.error):
        return []


def dns_payload(frame):
    """UDP payload of an Ethernet frame the capture filter let through."""
    if len(frame) < 14:
        return b""
    et = struct.unpack_from(">H", frame, 12)[0]
    if et == 0x0800:
        ihl = (frame[14] & 0xF) * 4
        return frame[14 + ihl + 8:]
    if et == 0x86DD:
        return frame[14 + 40 + 8:]
    return b""


# --- capture ---------------------------------------------------------------

def bpf_udp_src53():
    """Classic BPF: IPv4/IPv6 UDP packets with source port 53, unfragmented."""
    def i(code, jt, jf, k):
        return struct.pack("HBBI", code, jt, jf, k)
    prog = [
        i(0x28, 0, 0, 12),          # 0  ldh [12]            ethertype
        i(0x15, 0, 7, 0x0800),      # 1  jeq ipv4 else ->9
        i(0x30, 0, 0, 23),          # 2  ldb [23]            protocol
        i(0x15, 0, 11, 17),         # 3  udp else drop
        i(0x28, 0, 0, 20),          # 4  ldh [20]            flags/fragment
        i(0x45, 9, 0, 0x1FFF),      # 5  fragment -> drop
        i(0xB1, 0, 0, 14),          # 6  ldx 4*([14]&0xf)
        i(0x48, 0, 0, 14),          # 7  ldh [x+14]          source port
        i(0x15, 5, 6, 53),          # 8  53 -> accept
        i(0x15, 0, 5, 0x86DD),      # 9  ipv6 else drop
        i(0x30, 0, 0, 20),          # 10 ldb [20]            next header
        i(0x15, 0, 3, 17),          # 11 udp else drop
        i(0x28, 0, 0, 54),          # 12 ldh [54]            source port
        i(0x15, 0, 1, 53),          # 13 53 -> accept
        i(0x06, 0, 0, 262144),      # 14 accept
        i(0x06, 0, 0, 0),           # 15 drop
    ]
    return b"".join(prog), len(prog)


def open_capture():
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))  # ETH_P_ALL
    s.bind(("lo", 0))
    import ctypes
    code, n = bpf_udp_src53()
    buf = ctypes.create_string_buffer(code, len(code))
    fprog = struct.pack("HL", n, ctypes.addressof(buf))
    s.setsockopt(socket.SOL_SOCKET, 26, fprog)  # SO_ATTACH_FILTER (not in the socket module))
    return s


# --- clients ---------------------------------------------------------------

def peer_allowed(conn, allowed_uid):
    pid, uid, _gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != allowed_uid:
        return False
    try:
        with open(f"/proc/{pid}/status") as f:
            status = dict(l.split(":", 1) for l in f.read().splitlines() if ":" in l)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return False
    if len(status.get("NSpid", "").split()) > 1:   # inside a child pid namespace
        return False
    if status.get("Seccomp", "0").strip() != "0":  # sandbox filter
        return False
    return any(v in cmd for v in VIEWERS)


def serve(conn, allowed_uid, bucket):
    conn.settimeout(2)
    try:
        if not peer_allowed(conn, allowed_uid):
            return
        data = b""
        for _ in range(MAX_LINES_PER_CONN):
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
                if len(data) > 8192:
                    return
            line, _, data = data.partition(b"\n")
            now = time.time()
            if now - bucket[0] > 60:
                bucket[0], bucket[1] = now, 0
            bucket[1] += 1
            if bucket[1] > GLOBAL_PER_MINUTE:
                return
            conn.sendall(lookup(line.decode("ascii", "replace")).encode("ascii", "replace") + b"\n")
    except (OSError, socket.timeout):
        pass
    finally:
        conn.close()


def main():
    allowed_uid = int(os.environ["DNS_WATCH_UID"])
    cap = open_capture()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass
    srv.bind(SOCK_PATH)
    os.chmod(SOCK_PATH, 0o660)
    srv.listen(8)
    bucket = [time.time(), 0]
    while True:
        ready, _, _ = select.select([cap, srv], [], [], 60)
        if cap in ready:
            for _ in range(200):  # drain what is queued
                try:
                    frame = cap.recv(4096, socket.MSG_DONTWAIT)
                except BlockingIOError:
                    break
                for ip, name in parse_response(dns_payload(frame)):
                    if name:
                        remember(ip, name)
        if srv in ready:
            conn, _ = srv.accept()
            serve(conn, allowed_uid, bucket)


if __name__ == "__main__":
    main()
