package main

import "testing"

func TestSortTray(t *testing.T) {
	mk := func(id, title string) *trayIcon { return &trayIcon{id: id, title: title} }
	names := func(icons []*trayIcon) string {
		s := ""
		for _, ic := range icons {
			s += ic.id + " "
		}
		return s
	}
	icons := []*trayIcon{mk("qt", "Dictate"), mk("blueman", "Bluetooth"), mk("nm", "Network"), mk("x", "Mic")}
	sortTray(icons, []string{"*", "dictate"})
	if got := names(icons); got != "blueman nm x qt " {
		t.Errorf("star first: %q", got)
	}
	icons = []*trayIcon{mk("qt", "Dictate"), mk("blueman", "Bluetooth"), mk("nm", "Network")}
	sortTray(icons, []string{"network", "dictate"}) // no "*": unlisted last
	if got := names(icons); got != "nm qt blueman " {
		t.Errorf("no star: %q", got)
	}
}
