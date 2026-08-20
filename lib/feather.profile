# Custom firejail profile for Feather (Monero wallet).
#
# No stock community profile exists for Feather. Same reasoning as
# lib/sparrow.profile: Feather also links libusb/hidapi for hardware
# wallet support (Ledger), so `private-dev` and `nogroups` are
# deliberately omitted to avoid silently breaking USB access. Feather's
# own Tor usage (see feather-wrapper.sh, provisioning/39-feather-tor-ondemand.sh)
# talks to the system tor daemon on 127.0.0.1:9050, which stays reachable
# since this profile doesn't put the process in its own net namespace.
noblacklist ${HOME}/.config/feather

include disable-common.inc
include disable-devel.inc
include disable-exec.inc
include disable-programs.inc

mkdir ${HOME}/.config/feather
whitelist ${HOME}/.config/feather
whitelist ${HOME}/Downloads
include whitelist-common.inc
include whitelist-var-common.inc

caps.drop all
ipc-namespace
netfilter
no3d
nodvd
nonewprivs
noroot
notv
protocol unix,inet,inet6
seccomp

disable-mnt
private-cache
private-tmp
