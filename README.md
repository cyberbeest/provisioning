# Provisioning scripts

This directory holds the scripts used to build the end-user image from a stock
install.

## Pattern

Each script:
- Is named `NN-short-description.sh` (numbered = run order).
- Is idempotent — safe to re-run on a machine that already has it applied.
- Logs its own output to `NN-short-description.log` in this directory.
- Expects to be run as root itself (`sudo bash NN-*.sh`), since there's a
  human at the keyboard during an install who can just type their password.

`lib/` holds the underlying scripts each `NN-*.sh` step wraps (installers,
helper scripts, the messenger catalog builder). They're not meant to be run
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
and runs `./menu.sh` for you):

```
curl -fsSL https://cyberbeest.com/beestify.sh | bash
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

For a shipped unit, generate a real per-device passphrase instead (e.g. via
the change-password GUI's own "Generate" button), put it on a sticker, and
record it tagged `secure` rather than `weak` — that's what lets the nag
offer "keep it" instead of forcing a change. A self-installer who sets their
own password during the Debian install never runs this, so nothing gets
recorded and the nag never appears.

## What's NOT provisioned here

Per-user setup that only makes sense on the end-user's own device — e.g.
pairing this laptop to *their* phone over Bluetooth — is a manual step for
them to do via the Blueman GUI (Whisker menu → Bluetooth Manager), not
something to bake into the image.
