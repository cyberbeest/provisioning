#!/bin/bash
# Root-side helper for Cyberbeest Packages (cyberbeest_package_manager_gui.py).
# The dev-machine copy is invoked via pkexec from a fixed path (see
# com.cyberbeest.package-manager.policy in this same directory); this copy
# is called directly as root during provisioning (build_messenger_catalog.py
# calls it for setup-repo), so no pkexec/fixed-path requirement applies here.
#
# Usage:
#   cyberbeest-pkg-helper.sh setup-repo <signal|element>
#   cyberbeest-pkg-helper.sh install <pkg>...
#   cyberbeest-pkg-helper.sh remove <pkg>...
#   cyberbeest-pkg-helper.sh batch          (reads one step per line on stdin,
#                                             e.g. "install telegram-desktop";
#                                             lets a whole queue run under a
#                                             single pkexec authentication)

set -euo pipefail

LOG="$(cd "$(dirname "$0")" && pwd)/cyberbeest_pkg_helper.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$LOG"; }

export DEBIAN_FRONTEND=noninteractive

do_setup_repo() {
    case "$1" in
    signal)
        if [ ! -f /etc/apt/sources.list.d/signal-desktop.sources ]; then
            log "Setting up Signal apt repository"
            curl -fsSL https://updates.signal.org/desktop/apt/keys.asc | gpg --dearmor -o /usr/share/keyrings/signal-desktop-keyring.gpg \
                || { log "Signal keyring fetch failed"; return 1; }
            curl -fsSL -o /etc/apt/sources.list.d/signal-desktop.sources https://updates.signal.org/static/desktop/apt/signal-desktop.sources \
                || { log "Signal sources fetch failed"; return 1; }
            apt-get update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Signal repo"; return 1; }
            log "Signal apt repository set up"
        else
            log "Signal apt repository already present, skipping"
        fi
        ;;
    element)
        if [ ! -f /etc/apt/sources.list.d/element-io.list ]; then
            log "Setting up Element apt repository"
            wget -qO /usr/share/keyrings/element-io-archive-keyring.gpg https://packages.element.io/debian/element-io-archive-keyring.gpg \
                || { log "Element keyring fetch failed"; return 1; }
            echo "deb [signed-by=/usr/share/keyrings/element-io-archive-keyring.gpg] https://packages.element.io/debian/ default main" >/etc/apt/sources.list.d/element-io.list \
                || { log "Element sources write failed"; return 1; }
            apt-get update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Element repo"; return 1; }
            log "Element apt repository set up"
        else
            log "Element apt repository already present, skipping"
        fi
        ;;
    *)
        log "Unknown repo: $1"
        return 1
        ;;
    esac
}

do_install() {
    log "Installing: $*"
    apt-get update >>"$LOG" 2>&1 || { log "apt-get update failed"; return 1; }
    apt-get install -y "$@" >>"$LOG" 2>&1 || { log "apt-get install failed: $*"; return 1; }
    log "Install finished: $*"
}

do_remove() {
    log "Removing: $*"
    apt-get remove -y "$@" >>"$LOG" 2>&1 || { log "apt-get remove failed: $*"; return 1; }
    log "Remove finished: $*"
}

run_step() {
    case "$1" in
    setup-repo)
        shift
        do_setup_repo "$@"
        ;;
    install)
        shift
        do_install "$@"
        ;;
    remove)
        shift
        do_remove "$@"
        ;;
    *)
        log "Unknown action: $1"
        return 1
        ;;
    esac
}

action="${1:-}"
shift || true

if [ "$action" = "batch" ]; then
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # shellcheck disable=SC2086
        if ! run_step $line; then
            log "FAILED: $line"
            echo "Failed while running: $line" >&2
            exit 1
        fi
    done
else
    if ! run_step "$action" "$@"; then
        log "FAILED: $action $*"
        echo "Failed while running: $action $*" >&2
        exit 1
    fi
fi
