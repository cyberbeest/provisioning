# Custom firejail profile for Sparrow (Bitcoin wallet).
#
# No stock community profile exists for Sparrow, so this is hand-built,
# modeled on firejail's stock electrum.profile but deliberately WITHOUT
# `private-dev` and `nogroups`: Sparrow talks to hardware wallets
# (Trezor/Ledger/BitBox/Jade/KeepKey) over libusb (libusb4java +
# libhidapi-libusb.so are bundled in its runtime), and
#   - `private-dev` builds a minimal /dev that does not include
#     /dev/bus/usb by default, which would silently break USB access, and
#   - the udev rules for several of these devices grant access via the
#     `plugdev` group, which `nogroups` would strip from the sandboxed
#     process even though the cyberbeest user is a plugdev member.
# Everything else follows the same policy as the other jailed apps: only
# Sparrow's own data dir plus Downloads is visible, caps are dropped, and
# shells/interpreters/common escape vectors are disabled.
noblacklist ${HOME}/.sparrow

include disable-common.inc
include disable-devel.inc
include disable-exec.inc
include disable-programs.inc

mkdir ${HOME}/.sparrow
whitelist ${HOME}/.sparrow
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
