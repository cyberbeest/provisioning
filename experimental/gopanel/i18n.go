package main

import (
	"os"
	"regexp"
	"strings"
	"time"
)

// Minimal German translation, switched on by the system locale (/etc/default/locale, like
// lib/i18n.py -- $LANG is not trusted, it is often stripped in autostarted processes).
// Strings missing from the table stay English.

var german = detectGerman()

func detectGerman() bool {
	if v := os.Getenv("GOPANEL_LANG"); v != "" { // testing override
		return strings.HasPrefix(v, "de")
	}
	lang := os.Getenv("LANG")
	if b, err := os.ReadFile("/etc/default/locale"); err == nil {
		if m := regexp.MustCompile(`(?m)^LANG="?([^"\n]*)"?\s*$`).FindSubmatch(b); m != nil && len(m[1]) > 0 {
			lang = string(m[1])
		}
	}
	return strings.HasPrefix(lang, "de")
}

var deStrings = map[string]string{
	"Start XFCE panel":              "XFCE-Leiste starten",
	"Stop XFCE panel":               "XFCE-Leiste beenden",
	"Restart this panel":            "Diese Leiste neu starten",
	"Remove from panel":             "Aus der Leiste entfernen",
	"Remove \"%s\" from the panel?": "„%s“ aus der Leiste entfernen?",
	"Remove":                        "Entfernen",
	"Cancel":                        "Abbrechen",
	"Quit this panel":               "Diese Leiste beenden",
	"Minimize":                      "Minimieren",
	"Restore":                       "Wiederherstellen",
	"Maximize":                      "Maximieren",
	"Unmaximize":                    "Maximierung aufheben",
	"Close":                         "Schließen",
	"Volume":                        "Lautstärke",
	"Volume muted":                  "Lautstärke stumm",
	"Starting %s…":                  "%s wird gestartet …",
	"Mute":                          "Stumm",
	"Properties…":                   "Eigenschaften…",
	"Microphone":                    "Mikrofon",
	"Audio Mixer…":                  "Audio-Mixer…",
	"Battery":                       "Akku",
	"Charging":                      "Wird geladen",
	"Fully charged":                 "Voll geladen",
	"Discharging":                   "Wird entladen",
	"remaining":                     "verbleibend",
	"Computer":                      "Computer",
	"Display brightness":            "Bildschirmhelligkeit",
	"Power Manager Settings…":       "Energieverwaltung…",
	"Extended power options…":       "Erweiterte Energieoptionen…",
	"Applications":                  "Anwendungen",
	"Recently Used":                 "Zuletzt benutzt",
	"Favorites":                     "Favoriten",
	"All Applications":              "Alle Anwendungen",
	"No favorites yet":              "Noch keine Favoriten",
	"Add to Favorites":              "Zu Favoriten hinzufügen",
	"Remove from Favorites":         "Aus Favoriten entfernen",
	"Add to Desktop":                "Auf die Arbeitsfläche legen",
}

// tr translates a UI string; unknown strings pass through.
func tr(s string) string {
	if german {
		if t, ok := deStrings[s]; ok {
			return t
		}
	}
	return s
}

var (
	deMonths = []string{"Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"}
	deDays   = []string{"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"}
)

// monthTitle is "October 2026" / "Oktober 2026".
func monthTitle(t time.Time) string {
	if german {
		return deMonths[t.Month()-1] + t.Format(" 2006")
	}
	return t.Format("January 2006")
}

// weekdayShort is the two-letter column header.
func weekdayShort(d time.Weekday) string {
	if german {
		return deDays[d][:2]
	}
	return d.String()[:2]
}

// longDate is the clock tooltip: "Monday, 2 January 2006" / "Montag, 2. Januar 2006".
func longDate(t time.Time) string {
	if german {
		return deDays[t.Weekday()] + ", " + t.Format("2.") + " " + deMonths[t.Month()-1] + t.Format(" 2006")
	}
	return t.Format("Monday, 2 January 2006")
}

// propsLabel is the plugin menu entry: "Kitt Scanner Properties…" / "Eigenschaften von Kitt Scanner…".
func propsLabel(title string) string {
	if title == "" {
		return tr("Properties…")
	}
	if german {
		return "Eigenschaften von " + title + "…"
	}
	return title + " Properties…"
}
