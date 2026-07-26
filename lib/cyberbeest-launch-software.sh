#!/bin/bash
# Shown before every launch of GNOME Software (the "Software" app), because
# its Explore/search now covers the whole Debian archive, not just the
# Cyberbeest-approved list (see cyberbeest_package_manager_gui.py). Installed
# as an override for org.gnome.Software's .desktop Exec= and D-Bus service,
# by install-software-warning.sh.

set -euo pipefail

# i18n.sh only resolves lib/i18n/ relative to its own location, so this
# script's install step (install-software-warning.sh) has to deploy i18n.sh
# and lib/i18n/ next to it too -- see there.
. "$(cd "$(dirname "$0")" && pwd)/i18n.sh"

if zenity --question \
    --title="$(t launch_software.dialog_title)" \
    --text="$(t launch_software.message)" \
    --ok-label="$(t launch_software.continue)" \
    --cancel-label="$(t launch_software.cancel)" \
    --width=420; then
    exec /usr/bin/gnome-software "$@"
fi
exit 0
