# Firejail profile for Cyberbeest Image Viewer (installed by 58-cyberbeest-image-viewer.sh).
# The viewer opens images from anywhere, so reads stay open. What it gets
# taken away is everything a decoder exploit would need afterwards: network,
# D-Bus, privileges, and write access to anything that survives a restart
# (dotfiles, autostart, the viewer's own script).

# Deliberately no `include globals.local`: that carries the Whitelisted Folders
# list, which would hide every other folder from the viewer.


# No network: the viewer never needs it, so nothing can be sent out.
net none
protocol unix
netfilter

caps.drop all
nonewprivs
# No `noroot`: it runs the jail in a user namespace that drops supplementary
# groups, so folders readable only through a group (e.g. a bind-mounted old
# home owned by another user) would be unreadable. caps.drop and nonewprivs
# already remove the privileges it would guard against.
seccomp
seccomp.block-secondary
memory-deny-write-execute

# Clipboard is X11 selections, so no session bus is needed.
dbus-user none
dbus-system none

nosound
notv
nodvd
nou2f
novideo
private-tmp
# 3D stays allowed: the gamma-correct downscale runs on the GPU.

# Home stays writable so images can be renamed wherever they are, but every
# top-level dotfile/dotdir is read-only: no autostart entries, no shell rc
# changes. The globs match every dot entry except exactly ".local".
# (Firejail rejects "!" and "^" in globs, hence the explicit ranges.)
read-only ${HOME}/.[a-km-zA-Z0-9_]*
read-only ${HOME}/.l[a-np-zA-Z0-9_.-]*
read-only ${HOME}/.lo[abd-zA-Z0-9_.-]*
read-only ${HOME}/.loc[b-zA-Z0-9_.-]*
read-only ${HOME}/.loca[a-km-zA-Z0-9_.-]*
read-only ${HOME}/.local?*
# The one thing the viewer writes itself (bar-collapsed flag).
read-write ${HOME}/.config/cyberbeest

# ~/.local is NOT remounted as a whole: Delete moves files into
# ~/.local/share/Trash, and a rename across a separate mount fails (EXDEV),
# so Trash must stay on the same mount as the images. Instead, lock every
# place under it that can make code run: the viewer's own script, Python
# modules, desktop-entry/MIME handlers, D-Bus services, systemd units.
read-only ${HOME}/.local/bin
read-only ${HOME}/.local/lib
read-only ${HOME}/.local/share/applications
read-only ${HOME}/.local/share/dbus-1
read-only ${HOME}/.local/share/systemd
read-only ${HOME}/.local/share/mime

# Secrets the viewer has no reason to read.
blacklist ${HOME}/.ssh
blacklist ${HOME}/.gnupg
blacklist ${HOME}/.password-store
blacklist ${HOME}/.mozilla
blacklist ${HOME}/.local/share/keyrings

# System paths stay read-only (the update replaces the script from outside
# the sandbox; the viewer only compares its mtime and re-execs itself).
read-only /usr
read-only /etc
read-only /var
