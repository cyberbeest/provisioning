#!/bin/bash
# Shown before every launch of GNOME Software (the "Software" app), because
# its Explore/search now covers the whole Debian archive, not just the
# Cyberbeest-approved list (see cyberbeest_package_manager_gui.py). Installed
# as an override for org.gnome.Software's .desktop Exec= and D-Bus service,
# by install-software-warning.sh.

set -euo pipefail

MESSAGE="\"Software\" lets you browse and install any package from the Debian archive -- not just Cyberbeest-approved apps.

Installing something here is at your own risk. For a curated, pre-approved list instead, use the Cyberbeest Package Manager."

if zenity --question \
    --title="Cyberbeest Notice" \
    --text="$MESSAGE" \
    --ok-label="Continue to \"Software\"" \
    --cancel-label="Cancel" \
    --width=420; then
    exec /usr/bin/gnome-software "$@"
fi
exit 0
