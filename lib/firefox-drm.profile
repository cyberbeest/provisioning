# Custom firejail profile: includes the stock firefox-esr profile chain and
# then re-states one exception after it, so ours is the last (winning)
# directive -- firejail's seccomp line replaces rather than merges, and
# firefox-common.profile (pulled in via firefox-esr.profile -> firefox.profile)
# sets `seccomp !chroot` internally.
#
# Without this, the Widevine CDM's own internal sandbox setup
# (MOZ_SANDBOX_USE_CHROOT=1: it builds a user+mount namespace and does a
# bind-mount + chroot() inside it) fails partway through -- firejail's
# default seccomp blacklist blocks `mount` unconditionally, and blocks
# `chroot` except where a profile unblocks it, and that block applies even
# inside the CDM's own namespace. Firefox doesn't handle that failure
# cleanly and the GMP process segfaults instead of erroring out.
#
# Everything else in the stock profile chain -- network isolation, home
# directory whitelisting, caps.drop all, noroot, etc. -- is untouched; this
# only widens two syscalls needed for DRM playback to work at all.
include firefox-esr.profile
seccomp !chroot,!mount
