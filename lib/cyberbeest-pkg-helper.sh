#!/bin/bash
# Root-side helper for Cyberbeest Packages (cyberbeest_package_manager_gui.py).
# The dev-machine copy is invoked via pkexec from a fixed path (see
# com.cyberbeest.package-manager.policy in this same directory); this copy
# is called directly as root during provisioning (install-secure-messengers.sh
# calls it for setup-repo; 50-i2pd-default.sh calls it for
# setup-i2pd-toggle), so no pkexec/fixed-path requirement applies here.
#
# Usage:
#   cyberbeest-pkg-helper.sh setup-repo <signal|element|mullvad|protonvpn>
#   cyberbeest-pkg-helper.sh install <pkg>...
#   cyberbeest-pkg-helper.sh remove <pkg>...
#   cyberbeest-pkg-helper.sh install-deb-url <url>   (for vendors with no apt
#                                             repo at all, e.g. Viber: just a
#                                             stable "always latest" .deb URL;
#                                             dpkg -i --skip-same-version, so
#                                             re-running is a safe no-op)
#   cyberbeest-pkg-helper.sh setup-viber-updater     (installs the daily
#                                             systemd timer that re-runs the
#                                             install-deb-url check, since
#                                             Viber has no repo to piggyback
#                                             updates on)
#   cyberbeest-pkg-helper.sh setup-i2pd-toggle       (scoped NOPASSWD sudoers
#                                             rule + disables i2pd boot
#                                             autostart, for the on-demand
#                                             start/stop toggle -- see
#                                             lib/setup_i2p_extras.py for the
#                                             unprivileged half)
#   cyberbeest-pkg-helper.sh teardown-i2pd-toggle    (removes that sudoers
#                                             rule, run when I2P is unchecked)
#   cyberbeest-pkg-helper.sh batch          (reads one step per line on stdin,
#                                             e.g. "install telegram-desktop";
#                                             lets a whole queue run under a
#                                             single pkexec authentication)

set -euo pipefail

LOG="$(cd "$(dirname "$0")" && pwd)/cyberbeest_pkg_helper.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >>"$LOG"; }

export DEBIAN_FRONTEND=noninteractive

ensure_repo_deps() {
    # curl/gnupg aren't guaranteed present on a stock Debian install; wget is
    # more commonly there by default, but install it too for consistency.
    local missing=()
    for pkg in curl gnupg wget; do
        dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        log "Installing missing deps for repo setup: ${missing[*]}"
        apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed while installing deps"; return 1; }
        apt-get -o DPkg::Lock::Timeout=60 install -y "${missing[@]}" >>"$LOG" 2>&1 || { log "apt-get install failed: ${missing[*]}"; return 1; }
    fi
}

do_setup_repo() {
    ensure_repo_deps || return 1
    case "$1" in
    signal)
        if [ ! -f /etc/apt/sources.list.d/signal-desktop.sources ]; then
            log "Setting up Signal apt repository"
            curl -fsSL https://updates.signal.org/desktop/apt/keys.asc | gpg --yes --dearmor -o /usr/share/keyrings/signal-desktop-keyring.gpg \
                || { log "Signal keyring fetch failed"; return 1; }
            curl -fsSL -o /etc/apt/sources.list.d/signal-desktop.sources https://updates.signal.org/static/desktop/apt/signal-desktop.sources \
                || { log "Signal sources fetch failed"; return 1; }
            apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Signal repo"; return 1; }
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
            apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Element repo"; return 1; }
            log "Element apt repository set up"
        else
            log "Element apt repository already present, skipping"
        fi
        ;;
    mullvad)
        if [ ! -f /etc/apt/sources.list.d/mullvad.list ]; then
            log "Setting up Mullvad apt repository"
            curl -fsSL -o /usr/share/keyrings/mullvad-keyring.asc https://repository.mullvad.net/deb/mullvad-keyring.asc \
                || { log "Mullvad keyring fetch failed"; return 1; }
            echo "deb [signed-by=/usr/share/keyrings/mullvad-keyring.asc arch=$(dpkg --print-architecture)] https://repository.mullvad.net/deb/stable stable main" >/etc/apt/sources.list.d/mullvad.list \
                || { log "Mullvad sources write failed"; return 1; }
            apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Mullvad repo"; return 1; }
            log "Mullvad apt repository set up"
        else
            log "Mullvad apt repository already present, skipping"
        fi
        ;;
    protonvpn)
        if [ ! -f /etc/apt/sources.list.d/protonvpn.list ]; then
            log "Setting up Proton VPN apt repository"
            curl -fsSL -o /usr/share/keyrings/protonvpn-keyring.asc https://repo.protonvpn.com/debian/public_key.asc \
                || { log "Proton VPN keyring fetch failed"; return 1; }
            echo "deb [signed-by=/usr/share/keyrings/protonvpn-keyring.asc] https://repo.protonvpn.com/debian stable main" >/etc/apt/sources.list.d/protonvpn.list \
                || { log "Proton VPN sources write failed"; return 1; }
            apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed after adding Proton VPN repo"; return 1; }
            log "Proton VPN apt repository set up"
        else
            log "Proton VPN apt repository already present, skipping"
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
    apt-get -o DPkg::Lock::Timeout=60 update >>"$LOG" 2>&1 || { log "apt-get update failed"; return 1; }
    apt-get -o DPkg::Lock::Timeout=60 install -y "$@" >>"$LOG" 2>&1 || { log "apt-get install failed: $*"; return 1; }
    log "Install finished: $*"
}

do_remove() {
    log "Removing: $*"
    apt-get -o DPkg::Lock::Timeout=60 remove -y "$@" >>"$LOG" 2>&1 || { log "apt-get remove failed: $*"; return 1; }
    log "Remove finished: $*"
}

do_install_deb_url() {
    # No checksum/signature check here: this exists for vendors (Viber) that
    # ship an "always latest" .deb with no stable published checksum and no
    # apt repo to piggyback GPG verification on, so HTTPS-from-the-vendor's-
    # own-CDN is the actual ceiling, not a corner we cut. If a vendor with a
    # pinnable checksum or signature is added here later, verify it.
    local url="$1" deb
    deb="$(mktemp /tmp/cyberbeest-deb-XXXXXX.deb)"
    log "Downloading $url"
    curl -fsSL -o "$deb" "$url" || { log "Download failed: $url"; rm -f "$deb"; return 1; }
    if ! dpkg -i --skip-same-version "$deb" >>"$LOG" 2>&1; then
        log "dpkg -i failed, retrying after apt-get install -f"
        apt-get -o DPkg::Lock::Timeout=60 install -f -y >>"$LOG" 2>&1 || { log "apt-get install -f failed"; rm -f "$deb"; return 1; }
        dpkg -i --skip-same-version "$deb" >>"$LOG" 2>&1 || { log "dpkg -i failed after dependency fix: $url"; rm -f "$deb"; return 1; }
    fi
    rm -f "$deb"
    log "Installed from $url"
}

do_setup_i2pd_toggle() {
    log "Setting up i2pd on-demand toggle (sudoers rule + disabling boot autostart)"
    local sudoers_file=/etc/sudoers.d/i2pd-toggle
    local tmp
    tmp="$(mktemp)"
    cat > "$tmp" <<'EOF'
# Allow cyberbeest to start/stop/query the i2pd service without a password.
# Scoped to exactly these three invocations -- no wildcard/general systemctl
# access. Written by cyberbeest-pkg-helper.sh (setup-i2pd-toggle).
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl start i2pd
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl stop i2pd
cyberbeest ALL=(root) NOPASSWD: /usr/bin/systemctl is-active i2pd
EOF
    if visudo -c -f "$tmp" >>"$LOG" 2>&1; then
        install -m 0440 -o root -g root "$tmp" "$sudoers_file"
        log "Installed $sudoers_file"
    else
        log "visudo syntax check FAILED for i2pd-toggle sudoers rule"
        rm -f "$tmp"
        return 1
    fi
    rm -f "$tmp"

    # i2pd.service is disabled from boot-autostart on purpose -- it's only
    # started via the Whisker launcher / login-restore script from here on,
    # so it's installed by default but never actually running unless the
    # user starts it.
    systemctl disable i2pd >>"$LOG" 2>&1 || log "systemctl disable i2pd failed (non-fatal, may already be disabled)"
    log "i2pd toggle set up"
}

do_teardown_i2pd_toggle() {
    log "Removing i2pd toggle sudoers rule"
    rm -f /etc/sudoers.d/i2pd-toggle
}

do_setup_viber_updater() {
    log "Installing Viber daily update-check timer"
    cat > /usr/local/sbin/viber-update-check.sh <<'EOF'
#!/bin/bash
# Viber has no apt repo, just a stable "always latest" download URL.
# dpkg -i --skip-same-version makes this a no-op when already current.
set -uo pipefail
# Same no-checksum tradeoff as do_install_deb_url above: Viber's URL always
# serves "latest" with nothing stable to check it against, so HTTPS from
# Viber's own CDN is what we're trusting.
DEB=/tmp/viber-latest.deb
curl -fsSL -o "$DEB" "https://download.cdn.viber.com/cdn/desktop/Linux/viber.deb" || exit 1
dpkg -i --skip-same-version "$DEB"
rm -f "$DEB"
EOF
    chmod 755 /usr/local/sbin/viber-update-check.sh

    cat > /etc/systemd/system/viber-update-check.service <<'EOF'
[Unit]
Description=Check for and install Viber updates (no apt repo upstream)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/viber-update-check.sh
EOF

    cat > /etc/systemd/system/viber-update-check.timer <<'EOF'
[Unit]
Description=Run Viber update check daily

[Timer]
OnBootSec=10min
OnUnitActiveSec=1d
AccuracySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload >>"$LOG" 2>&1
    systemctl enable --now viber-update-check.timer >>"$LOG" 2>&1 || { log "enabling viber-update-check.timer failed"; return 1; }
    log "Viber update timer installed and enabled"
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
    setup-i2pd-toggle)
        do_setup_i2pd_toggle
        ;;
    teardown-i2pd-toggle)
        do_teardown_i2pd_toggle
        ;;
    remove)
        shift
        do_remove "$@"
        ;;
    install-deb-url)
        shift
        do_install_deb_url "$@"
        ;;
    setup-viber-updater)
        do_setup_viber_updater
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
