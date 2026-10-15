// Package procinfo: process helpers shared by the Kitt (top CPU) and mem-liquid
// (top RAM) helpers. The alias table is generated from lib/xfce-panel-plugins/process-alias.h.
package procinfo

import "strings"

var aliases = map[string]string{
	"Xorg":            "window drawing",
	"xfwm4":           "window manager",
	"xfce4-panel":     "panel",
	"xfce4-session":   "session manager",
	"xfsettingsd":     "settings daemon",
	"xfconfd":         "settings store",
	"xfdesktop":       "desktop",
	"xfce4-notifyd":   "notifications",
	"xfce4-power-man": "power management",
	"xfce4-screensav": "screen lock",
	"xfce4-terminal":  "terminal",
	"Thunar":          "file manager",
	"wrapper-2.0":     "panel plugin",
	"lightdm":         "login screen",
	"dbus-daemon":     "messaging bus",
	"NetworkManager":  "networking",
	"wpa_supplicant":  "wifi auth",
	"ModemManager":    "mobile modem",
	"pulseaudio":      "audio",
	"rtkit-daemon":    "audio scheduler",
	"avahi-daemon":    "network discovery",
	"upowerd":         "power/battery",
	"udisksd":         "disk manager",
	"polkitd":         "permissions",
	"polkit-mate-aut": "permission prompt",
	"systemd-udevd":   "device manager",
	"systemd-logind":  "login manager",
	"systemd-journal": "logging",
	"systemd-timesyn": "clock sync",
	"watchdogd":       "hardware watchdog",
	"unattended-upgr": "auto-updates",
	"kswapd0":         "memory reclaim",
	"oom_reaper":      "memory cleanup",
	"telegram-deskto": "Telegram",
	"tor":             "Tor network",
	"butler":          "Butler",
	"sshd":            "remote access (SSH)",
	"ssh-agent":       "SSH keys",
	"nm-applet":       "network icon",
	"blueman-applet":  "bluetooth icon",
	"blueman-tray":    "bluetooth icon",
	"obexd":           "bluetooth file transfer",
	"mpris-proxy":     "media controls",
	"switcheroo-cont": "GPU switching",
	"xdg-desktop-por": "app sandbox",
	"xdg-permission-": "app sandbox",
	"xdg-document-po": "app sandbox",
}

var substrAliases = []struct{ sub, alias string }{
	{"rtw", "wifi (driver)"},
	{"i915", "graphics (driver)"},
	{"hci0", "bluetooth (driver)"},
	{"ext4", "disk filesystem"},
	{"sdhci", "SD card reader"},
	{"kcryptd", "disk encryption"},
}

// Alias returns a human-readable name for a raw /proc comm string, or comm unchanged.
func Alias(comm string) string {
	if a, ok := aliases[comm]; ok {
		return a
	}
	for _, s := range substrAliases {
		if strings.Contains(comm, s.sub) {
			return s.alias
		}
	}
	return comm
}
