# Provisioning scripts

This directory holds the scripts used to build the end-user image from a stock
install, as an alternative to cloning this dev machine and purging personal data.

## Pattern

Each script:
- Is named `NN-short-description.sh` (numbered = run order).
- Is idempotent — safe to re-run on a machine that already has it applied.
- Logs its own output to `NN-short-description.log` in this directory.
- Expects to be run as root itself (`sudo bash NN-*.sh`) — it does not use the
  RUNME/`claude-sudo-helper.sh` convention from the dev machine's `CLAUDE.md`.
  That convention exists for Claude to request sudo without holding it; during
  an actual install there's a human at the keyboard who can just type their
  password.

`lib/` holds the underlying scripts each `NN-*.sh` step wraps (installers,
helper scripts, the messenger catalog builder). They're not meant to be run
directly except for one-off debugging of a single step.

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

## What's NOT provisioned here

Per-user setup that only makes sense on the end-user's own device — e.g.
pairing this laptop to *their* phone over Bluetooth — is a manual step for
them to do via the Blueman GUI (Whisker menu → Bluetooth Manager), not
something to bake into the image.
