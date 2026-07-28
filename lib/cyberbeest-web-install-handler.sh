#!/bin/bash
# Handles cyberbeest-install:<app-id> links -- the "Install" button on a
# cyberbeest.com messenger info page opens a link like
# cyberbeest-install:viber, the browser hands it to this script (registered
# as the x-scheme-handler/cyberbeest-install app), and this script confirms
# with the user then installs it.
#
# Only apps in the hardcoded APP_* case below can ever be installed this
# way -- the URI's app id is never passed to a shell or pkexec as a raw
# string, so a malicious/spoofed link can at most name one of these apps,
# never run arbitrary commands. Add a new optional app by adding a case here
# (and, if it fits the model, listing it on a cyberbeest.com info page).
#
# Registered via cyberbeest-web-install-handler.desktop; installed as part
# of provisioning (install-secure-messengers.sh) and mirrored on the dev
# machine directly.
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
HELPER="$DIR/cyberbeest-pkg-helper.sh"
. "$DIR/i18n.sh"

uri="${1:-}"
app_id="${uri#cyberbeest-install:}"
app_id="${app_id%%[/?]*}"

app_name=""
steps=()
case "$app_id" in
viber)
    app_name="Viber"
    steps=("install-deb-url https://download.cdn.viber.com/cdn/desktop/Linux/viber.deb" "setup-viber-updater")
    ;;
*)
    zenity --error \
        --title="$(t web_install.unknown_app_title)" \
        --text="$(t web_install.unknown_app_message)" \
        --width=360
    exit 1
    ;;
esac

confirm_msg="$(t web_install.confirm_message)"
confirm_msg="${confirm_msg//APPNAME/$app_name}"
install_label="$(t web_install.install_label)"
install_label="${install_label//APPNAME/$app_name}"

if ! zenity --question \
    --title="$(t web_install.confirm_title)" \
    --text="$confirm_msg" \
    --ok-label="$install_label" \
    --cancel-label="$(t web_install.cancel_label)" \
    --width=420; then
    exit 0
fi

if printf '%s\n' "${steps[@]}" | pkexec "$HELPER" batch; then
    success_msg="$(t web_install.success_message)"
    zenity --info --title="$(t web_install.success_title)" --text="${success_msg//APPNAME/$app_name}" --width=360
else
    failure_msg="$(t web_install.failure_message)"
    zenity --error --title="$(t web_install.failure_title)" --text="${failure_msg//APPNAME/$app_name}" --width=360
fi
