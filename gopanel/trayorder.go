package main

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Tray order hints: ~/.config/gopanel/order.conf lists tray icons in the order they
// should appear, one per line. A line matches an icon when it is a case-insensitive
// substring of the icon's Id, Title or tooltip. "*" stands for every icon not listed,
// placed where the "*" is (no "*" line: unlisted icons go after the listed ones).
// Icons with the same rank keep their registration order.
//
// The default puts Dictate at the end of the tray, so it sits right next to the volume
// item that follows the tray in the panel.

var trayOrder = loadTrayOrder()

func loadTrayOrder() []string {
	def := []string{"*", "dictate"}
	dir, err := os.UserConfigDir()
	if err != nil {
		return def
	}
	b, err := os.ReadFile(filepath.Join(dir, "gopanel", "order.conf"))
	if err != nil {
		return def
	}
	var out []string
	for _, l := range strings.Split(string(b), "\n") {
		if l = strings.ToLower(strings.TrimSpace(l)); l != "" && !strings.HasPrefix(l, "#") {
			out = append(out, l)
		}
	}
	return out
}

// trayRank is the icon's position in the hint list; unlisted icons rank at the "*".
func trayRank(ic *trayIcon, hints []string) int {
	star := len(hints)
	for i, h := range hints {
		if h == "*" {
			star = i
			break
		}
	}
	hay := strings.ToLower(ic.id + "\x00" + ic.title + "\x00" + ic.tip)
	for i, h := range hints {
		if h != "*" && strings.Contains(hay, h) {
			return i
		}
	}
	return star
}

// sortTray orders icons by the hint list, keeping registration order within a rank.
func sortTray(icons []*trayIcon, hints []string) {
	rank := make(map[*trayIcon]int, len(icons))
	for _, ic := range icons {
		rank[ic] = trayRank(ic, hints)
	}
	sort.SliceStable(icons, func(i, j int) bool { return rank[icons[i]] < rank[icons[j]] })
}
