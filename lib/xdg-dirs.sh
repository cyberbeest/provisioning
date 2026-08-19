#!/bin/bash
# Shared helper for resolving a target user's real (locale-translated) XDG
# user directories -- e.g. ~/Bilder rather than a hardcoded ~/Pictures under
# German. Source this, then call `xdg_dir NAME`, where NAME is one of
# DESKTOP, DOWNLOAD, TEMPLATES, PUBLICSHARE, DOCUMENTS, MUSIC, PICTURES,
# VIDEOS (see `xdg-user-dir --help`).
#
# Must run as root/sudo with TARGET_USER already set, same convention every
# caller already uses -- resolution has to happen in the target user's own
# environment since it reads their ~/.config/user-dirs.dirs, not root's.
#
# Depends on: 08-xdg-user-dirs.sh having already run (installs the
# xdg-user-dirs package, which this needs, and makes sure user-dirs.dirs
# reflects the real, locale-translated directory names before any of this
# repo's other scripts touch a user folder).
xdg_dir() {
	su - "$TARGET_USER" -c "xdg-user-dir $1"
}
