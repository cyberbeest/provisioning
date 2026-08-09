# Provisioning scripts

This directory holds the scripts used to build the end-user image from a stock
install.

## License

Licensed under the [PolyForm Shield License 1.0.0](LICENSE) — free to read,
run, and use for self-provisioning your own machine, but not to build a
competing product or service on top of.

## Pattern

Each script:
- Is named `NN-short-description.sh` (numbered = run order).
- Is idempotent — safe to re-run on a machine that already has it applied.
- Logs its own output to `NN-short-description.log` in this directory.
- Expects to be run as root itself (`sudo bash NN-*.sh`), since there's a
  human at the keyboard during an install who can just type their password.

`lib/` holds the underlying scripts each `NN-*.sh` step wraps (installers,
helper scripts, the secure-messengers installer). They're not meant to be run
directly except for one-off debugging of a single step.

Scripts `08` onward assume a single desktop account named `cyberbeest` (same
assumption the rest of this image makes) — they install into `$SUDO_USER`'s
home if run via `sudo bash NN-*.sh` as that user, falling back to `cyberbeest`
otherwise.

## Running the full set

- `./menu.sh` — the recommended entry point for a fresh install. Shows a
  checklist of all `NN-*.sh` scripts (all selected by default) so you can
  deselect ones that don't apply to this machine (e.g. Bluetooth tethering on
  a VM), then runs the selected ones in order via `sudo`, stopping if one
  fails since later scripts may depend on it.
- `./run-all.sh` — non-interactive, runs every `NN-*.sh` script unconditionally
  in order. Useful for scripted/repeat test runs where you always want the
  full set (each script still needs to be run as root, so invoke this with
  `sudo ./run-all.sh` or add `sudo` per-script if you edit it to do so).
- `./run-changed.sh` — like `run-all.sh`, but skips any script whose `.log` is
  newer than the script itself (i.e. it already ran since it was last
  edited). Handy while iterating on one or two scripts instead of re-running
  the full set each time; not needed for a normal install. Since it compares
  file mtimes, a fresh `git clone` makes everything look changed again.
- `./run-gui.py` — graphical alternative to the above (dev tool, not part of
  the shipped image), running each `NN-*.sh` script directly rather than
  wrapping `run-all.sh`/`run-changed.sh`: a sidebar lists every script with
  its pending/running/done/failed status, and a shared log pane on the right
  streams whichever one is currently running. "Run all" / "Run changed only"
  walk the whole list; double-clicking a script in the sidebar runs just that
  one, regardless of its status. Each script is elevated individually via a
  graphical sudo prompt (zenity), which `sudo` normally only asks for once
  every few scripts thanks to credential caching. "Stop after current
  script" doesn't kill anything mid-script -- it lets the running one finish,
  then skips the rest.

## Getting this directory onto a fresh install

This repo is public on GitHub, so on a freshly installed Debian machine
(online, per the standard first-boot flow):

```
sudo apt install git
git clone https://github.com/cyberbeest/provisioning.git
cd provisioning
./menu.sh
```

Or, via the `beestify.sh` bootstrap script (installs git, clones this repo,
and runs `./menu.sh` for you). This tracks the `stable` branch -- only
fast-forwarded to a `main` commit once it's been validated end-to-end on a
fresh install, unlike `main` itself where every fix lands immediately:

```
curl -fsSL https://cyberbeest.com/beestify.sh | bash
```

`beestify-bleeding.sh` is the same thing but tracks `main` directly (cloned
into `~/provisioning-bleeding` instead, so both can coexist) -- for testing
the latest fixes before they're promoted to `stable`:

```
curl -fsSL https://cyberbeest.com/beestify-bleeding.sh | bash
```

## Default-password nag (21-default-password-nag.sh)

Installs the change-password GUI and a login-time nag that checks whether
the LUKS master password and/or the cyberbeest login (short) password still
match whatever they were initially set to, prompting a change if so. It only
has anything to check against `/etc/cyberbeest/initial-passwords.conf`, a
root-only local file that is **never** part of this repo — create it by hand
right after actually setting the password:

```
sudo cyberbeest-record-initial-password master '<the value you just set it to>' weak
sudo cyberbeest-record-initial-password short '<the value you just set it to>' weak
```

## Cyberbeest Package Manager (22-i2p-package-manager.sh)

Installs the Cyberbeest Package Manager GUI, a Whisker-menu app for
opt-in installs that are more involved than a plain `apt install`.
Currently one entry: I2P (i2pd) + qBittorrent, which also sets up a
dedicated, Alpenglow-themed Firefox profile proxied through i2pd for
eepsite browsing and enables qBittorrent's I2P/SAM support -- none of
which is installed or enabled by default, only when checked in the app.

For a shipped unit, generate a real per-device passphrase instead (e.g. via
the change-password GUI's own "Generate" button), put it on a sticker, and
record it tagged `secure` rather than `weak` — that's what lets the nag
offer "keep it" instead of forcing a change. A self-installer who sets their
own password during the Debian install never runs this, so nothing gets
recorded and the nag never appears.

## Menu key remap (part of 00-locale-keyboard-timezone.sh)

When German is picked as the keyboard layout, an extra whiptail confirmation
offers to remap the (otherwise unused) Menu/context-menu key to act as the
German ISO "<>|" key -- plain = `<`, Shift = `>`, AltGr = `|`. This is opt-in
and defaults to "no" because it's only correct on canonical Cyberbeest
hardware: an ANSI-body (104-key) keyboard with German stickers/keymap
applied, which physically lacks the ISO key between left Shift and Y that a
real German keyboard has there. Accepting it on a real ISO/German keyboard,
or different hardware, would remap Menu for no reason. Installed as
`~/.local/bin/cyberbeest-menu-key-remap.sh` plus an autostart entry, so it
reapplies (via `xmodmap`) on every Xfce login.

## Secure messengers (03-secure-messengers.sh)

Installs the always-on set directly (not just made discoverable in GNOME
Software): Signal, Element (Matrix), Telegram, and Tor Browser
(`torbrowser-launcher`). Reasoning per app is in
`lib/install-secure-messengers.sh`; short version: these are the mainstream,
non-redundant options, one per protocol where it matters (skips qTox, Gajim,
Nheko, Dino as too niche/redundant for a general-audience machine). Proton
Mail has no native Linux app at all (Snap-only, itself just wrapping their
web app), so it's installed as a plain browser-bookmark launcher instead of
a package.

Everything else is opt-in, installed on demand by clicking an "Install" link
on a cyberbeest.com info page (or any trusted local page) rather than
shipped by default. That's implemented as a `cyberbeest-install:<app-id>`
URI scheme, e.g. `cyberbeest-install:viber` — the browser hands the link to
`cyberbeest-web-install-handler.sh` (registered via
`cyberbeest-web-install-handler.desktop` and
`/etc/xdg/mimeapps.list`), which shows a confirmation dialog (zenity) and,
if accepted, installs via `pkexec` + `cyberbeest-pkg-helper.sh` (its own
polkit action, `com.cyberbeest.web-install.policy`, distinct from the
dev-machine-only Cyberbeest Package Manager GUI's policy). The handler only
recognizes a hardcoded allowlist of app ids — a link can never run arbitrary
commands, at most name one of the apps in that list. Viber is the first
(and so far only) optional app: it has no apt repo, just a stable "always
latest" download URL, so accepting its install also sets up a daily
`systemd` timer (`viber-update-check.timer`) re-checking that URL, since a
one-time install would otherwise silently go stale with no security
updates. All of this is deployed to `/usr/local/lib/cyberbeest/` so it's
independent of wherever this repo happens to be checked out.

## Calculator (32-calculator.sh)

Installs `gnome-calculator`, since whisker menu has no calculator app by
default. Picked over the lighter `galculator` because it shows up in the
menu simply as "Calculator" — less confusing for normal users than a
branded app name.

## What's NOT provisioned here

Per-user setup that only makes sense on the end-user's own device — e.g.
pairing this laptop to *their* phone over Bluetooth — is a manual step for
them to do via the Blueman GUI (Whisker menu → Bluetooth Manager), not
something to bake into the image.
