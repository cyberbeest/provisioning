#!/usr/bin/env python3
"""Flips on qBittorrent's I2P support after it's installed via the
Cyberbeest Package Manager's opt-in "qBittorrent" row.

Split out from setup_i2p_extras.py (2026-08-27) when i2pd moved from an
opt-in package-manager row to a default install (see 50-i2pd-default.sh)
-- qBittorrent remains opt-in on its own, so it needs its own small
post-install step instead of sharing i2pd's. i2pd is expected to already
be on the system (it's default now), so this just needs qBittorrent's own
config edited; it doesn't touch i2pd at all.

Runs unprivileged, as the user. Idempotent: safe to re-run.
"""

import os

QBT_CONF = os.path.join(os.path.expanduser("~"), ".config", "qBittorrent", "qBittorrent.conf")


def main():
    key = r"Session\I2P\Enabled"
    line = f"{key}=true\n"
    os.makedirs(os.path.dirname(QBT_CONF), exist_ok=True)

    if not os.path.exists(QBT_CONF):
        with open(QBT_CONF, "w", encoding="utf-8") as f:
            f.write("[BitTorrent]\n" + line)
        return

    with open(QBT_CONF, encoding="utf-8") as f:
        lines = f.readlines()

    for i, existing_line in enumerate(lines):
        if existing_line.strip() == f"{key}=true":
            return
        if existing_line.startswith(f"{key}="):
            lines[i] = line
            with open(QBT_CONF, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return

    if "[BitTorrent]\n" in lines:
        idx = lines.index("[BitTorrent]\n") + 1
        lines.insert(idx, line)
    else:
        lines.append("\n[BitTorrent]\n")
        lines.append(line)
    with open(QBT_CONF, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    main()
