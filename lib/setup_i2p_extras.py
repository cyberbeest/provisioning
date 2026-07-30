#!/usr/bin/env python3
"""Post-install setup for the I2P + qBittorrent package manager entry.

Runs unprivileged, as the user, after cyberbeest-pkg-helper.sh has already
apt-installed i2pd and qbittorrent. Handles everything that doesn't need
root: a dedicated Firefox profile for eepsites (proxied through i2pd,
Alpenglow theme so it's visually distinct from normal browsing), its
Whisker launcher, and flipping qBittorrent's I2P setting on.

Idempotent: safe to re-run (e.g. if the package manager row is
unchecked/rechecked, or this is run again after a manual tweak).
"""

import json
import os
import subprocess
import time

HOME = os.path.expanduser("~")
PROFILE_DIR = os.path.join(HOME, ".mozilla", "firefox", "i2p-profile")
PROFILES_INI = os.path.join(HOME, ".mozilla", "firefox", "profiles.ini")
DESKTOP_FILE = os.path.join(HOME, ".local", "share", "applications", "firefox-i2p.desktop")
QBT_CONF = os.path.join(HOME, ".config", "qBittorrent", "qBittorrent.conf")

USER_JS = """// I2P eepsite browsing profile — routes HTTP/HTTPS through i2pd's HTTP proxy
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", 4444);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", 4444);
user_pref("network.proxy.no_proxies_on", "localhost, 127.0.0.1");
user_pref("network.proxy.share_proxy_settings", false);
user_pref("extensions.activeThemeID", "firefox-alpenglow@mozilla.org");
"""

DESKTOP_ENTRY = """[Desktop Entry]
Name=Firefox (I2P)
Comment=Browse I2P eepsites via i2pd's HTTP proxy
Exec=firefox -no-remote -P i2p http://console.i2p
Terminal=false
Type=Application
Icon=firefox-esr
Categories=Network;WebBrowser;
StartupWMClass=firefox-esr
StartupNotify=true
"""


def log(msg):
    print(f"[setup_i2p_extras] {msg}")


def ensure_profile():
    if os.path.isdir(PROFILE_DIR):
        log("Firefox i2p profile already exists")
        return
    log("Creating Firefox i2p profile")
    subprocess.run(
        ["firefox", "-CreateProfile", f"i2p {PROFILE_DIR}"],
        capture_output=True, text=True, timeout=30,
    )
    if not os.path.isdir(PROFILE_DIR):
        raise RuntimeError("Firefox profile directory was not created")


def write_user_js():
    with open(os.path.join(PROFILE_DIR, "user.js"), "w", encoding="utf-8") as f:
        f.write(USER_JS)
    log("Wrote user.js proxy config")


def ensure_theme_active():
    ext_json = os.path.join(PROFILE_DIR, "extensions.json")
    if not os.path.exists(ext_json):
        log("First-run Firefox once (headless) to populate addon state")
        proc = subprocess.Popen(
            ["firefox", "-no-remote", "-P", "i2p", "-headless"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline and not os.path.exists(ext_json):
            time.sleep(1)
        subprocess.run(["pkill", "-f", "-P i2p -headless"], capture_output=True)
        proc.wait(timeout=15)
        if not os.path.exists(ext_json):
            raise RuntimeError("extensions.json never appeared after headless first-run")

    with open(ext_json, encoding="utf-8") as f:
        data = json.load(f)
    changed = False
    for addon in data.get("addons", []):
        if addon.get("id") == "default-theme@mozilla.org" and addon.get("active"):
            addon["active"] = False
            addon["userDisabled"] = True
            changed = True
        elif addon.get("id") == "firefox-alpenglow@mozilla.org" and not addon.get("active"):
            addon["active"] = True
            addon["userDisabled"] = False
            changed = True
    if changed:
        with open(ext_json, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # Force Firefox to re-derive startup state from extensions.json
        # instead of a stale cached addonStartup.json.lz4.
        cache = os.path.join(PROFILE_DIR, "addonStartup.json.lz4")
        if os.path.exists(cache):
            os.remove(cache)
        log("Activated Alpenglow theme")
    else:
        log("Alpenglow theme already active")


def ensure_desktop_entry():
    os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
    existing = None
    if os.path.exists(DESKTOP_FILE):
        with open(DESKTOP_FILE, encoding="utf-8") as f:
            existing = f.read()
    if existing != DESKTOP_ENTRY:
        with open(DESKTOP_FILE, "w", encoding="utf-8") as f:
            f.write(DESKTOP_ENTRY)
        os.chmod(DESKTOP_FILE, 0o755)
        subprocess.run(
            ["update-desktop-database", os.path.dirname(DESKTOP_FILE)],
            capture_output=True,
        )
        log("Installed Whisker launcher entry")
    else:
        log("Whisker launcher entry already up to date")


def ensure_qbittorrent_i2p_enabled():
    key = r"Session\I2P\Enabled"
    line = f"{key}=true\n"
    os.makedirs(os.path.dirname(QBT_CONF), exist_ok=True)

    if not os.path.exists(QBT_CONF):
        with open(QBT_CONF, "w", encoding="utf-8") as f:
            f.write("[BitTorrent]\n" + line)
        log("Created qBittorrent.conf with I2P enabled")
        return

    with open(QBT_CONF, encoding="utf-8") as f:
        lines = f.readlines()

    for i, existing_line in enumerate(lines):
        if existing_line.strip() == f"{key}=true":
            log("qBittorrent I2P support already enabled")
            return
        if existing_line.startswith(f"{key}="):
            lines[i] = line
            with open(QBT_CONF, "w", encoding="utf-8") as f:
                f.writelines(lines)
            log("Updated existing I2P setting to enabled")
            return

    if "[BitTorrent]\n" in lines:
        idx = lines.index("[BitTorrent]\n") + 1
        lines.insert(idx, line)
    else:
        lines.append("\n[BitTorrent]\n")
        lines.append(line)
    with open(QBT_CONF, "w", encoding="utf-8") as f:
        f.writelines(lines)
    log("Enabled I2P support in qBittorrent.conf")


def main():
    ensure_profile()
    write_user_js()
    ensure_theme_active()
    ensure_desktop_entry()
    ensure_qbittorrent_i2p_enabled()
    log("Done")


if __name__ == "__main__":
    main()
