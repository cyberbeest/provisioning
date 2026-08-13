/*
 * process-alias: shared lookup table mapping raw /proc comm strings (as
 * read by kitt-scanner's top-CPU list and mem-liquid's top-RAM list, both
 * truncated to 15 chars by the kernel) to human-readable names. Anything
 * not listed here is shown under its own name unchanged.
 */
#ifndef PROCESS_ALIAS_H
#define PROCESS_ALIAS_H

#include <string.h>

typedef struct {
    const char *comm;
    const char *alias;
} ProcessAlias;

static const ProcessAlias PROCESS_ALIASES[] = {
    /* XFCE desktop/session */
    { "Xorg",             "window drawing" }, /* not "windowing": Xorg does the drawing, xfwm4 the managing */
    { "xfwm4",            "window manager" },
    { "xfce4-panel",      "panel" },
    { "xfce4-session",    "session manager" },
    { "xfsettingsd",      "settings daemon" },
    { "xfconfd",          "settings store" },
    { "xfdesktop",        "desktop" },
    { "xfce4-notifyd",    "notifications" },
    { "xfce4-power-man",  "power management" },
    { "xfce4-screensav",  "screen lock" },
    { "xfce4-terminal",   "terminal" },
    { "Thunar",           "file manager" },
    { "wrapper-2.0",      "panel plugin" },
    { "lightdm",          "login screen" },

    /* System/hardware daemons */
    { "dbus-daemon",      "messaging bus" },
    { "NetworkManager",   "networking" },
    { "wpa_supplicant",   "wifi auth" },
    { "ModemManager",     "mobile modem" },
    { "pulseaudio",       "audio" },
    { "rtkit-daemon",     "audio scheduler" },
    { "avahi-daemon",     "network discovery" },
    { "upowerd",          "power/battery" },
    { "udisksd",          "disk manager" },
    { "polkitd",          "permissions" },
    { "polkit-mate-aut",  "permission prompt" },
    { "systemd-udevd",    "device manager" },
    { "systemd-logind",   "login manager" },
    { "systemd-journal",  "logging" },
    { "systemd-timesyn",  "clock sync" },
    { "watchdogd",        "hardware watchdog" },
    { "unattended-upgr",  "auto-updates" },

    /* Kernel housekeeping */
    { "kswapd0",          "memory reclaim" },
    { "oom_reaper",       "memory cleanup" },

    /* Apps / tray icons */
    { "telegram-deskto",  "Telegram" },
    { "tor",              "Tor network" },
    { "sshd",             "remote access (SSH)" },
    { "ssh-agent",        "SSH keys" },
    { "nm-applet",        "network icon" },
    { "blueman-applet",   "bluetooth icon" },
    { "blueman-tray",     "bluetooth icon" },
    { "obexd",            "bluetooth file transfer" },
    { "mpris-proxy",      "media controls" },
    { "switcheroo-cont",  "GPU switching" },
    { "xdg-desktop-por",  "app sandbox" },
    { "xdg-permission-",  "app sandbox" },
    { "xdg-document-po",  "app sandbox" },
};

#define PROCESS_ALIASES_COUNT (sizeof(PROCESS_ALIASES) / sizeof(PROCESS_ALIASES[0]))

/* Kernel worker threads carry a driver/queue name after "kworker/...-", so
 * these are matched by substring rather than exact comm, e.g.
 * "kworker/u13:0-rtw_tx_wq" or "kworker/1:2-i915-unordered". */
typedef struct {
    const char *substr;
    const char *alias;
} ProcessAliasSubstr;

static const ProcessAliasSubstr PROCESS_ALIAS_SUBSTRINGS[] = {
    { "rtw",     "wifi (driver)" },
    { "i915",    "graphics (driver)" },
    { "hci0",    "bluetooth (driver)" },
    { "ext4",    "disk filesystem" },
    { "sdhci",   "SD card reader" },
    { "kcryptd", "disk encryption" },
};

#define PROCESS_ALIAS_SUBSTRINGS_COUNT \
    (sizeof(PROCESS_ALIAS_SUBSTRINGS) / sizeof(PROCESS_ALIAS_SUBSTRINGS[0]))

/* Returns a human-readable name for a raw /proc comm string, or comm itself
 * unchanged if nothing in the table matches. */
static inline const char *
process_alias(const char *comm)
{
    for (size_t i = 0; i < PROCESS_ALIASES_COUNT; i++)
        if (strcmp(comm, PROCESS_ALIASES[i].comm) == 0)
            return PROCESS_ALIASES[i].alias;

    for (size_t i = 0; i < PROCESS_ALIAS_SUBSTRINGS_COUNT; i++)
        if (strstr(comm, PROCESS_ALIAS_SUBSTRINGS[i].substr))
            return PROCESS_ALIAS_SUBSTRINGS[i].alias;

    return comm;
}

#endif
