package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
)

// itemsReq: the control socket asks the main goroutine (the only one allowed to read
// items) for a snapshot of the panel layout; used by the welcome screen to point at icons.
var itemsReq = make(chan chan string, 4)

type itemInfo struct {
	Kind  string `json:"kind"`
	Name  string `json:"name,omitempty"`
	Rc    string `json:"rc,omitempty"`    // e.g. "genmon-19": which plugin this is
	Title string `json:"title,omitempty"` // language-independent plugin name ("Vpn genmon")
	Tip   string `json:"tip,omitempty"`
	X     int    `json:"x"`
	W     int    `json:"w"`
	Group string `json:"group,omitempty"` // "tray": one icon of the status-notifier tray
}

// itemsSnapshot is one JSON line: panel rectangle on the screen plus every visible item
// (tray icons listed individually). Read-only and harmless.
func itemsSnapshot(items []*item) string {
	var out []itemInfo
	for _, it := range items {
		if it.w <= 0 || it.kind == "separator" {
			continue
		}
		rc := strings.TrimSuffix(filepath.Base(it.rc), ".rc")
		if it.kind == "tray" && sniTray != nil {
			sniTray.mu.Lock()
			for i, ic := range sniTray.visible() {
				out = append(out, itemInfo{Kind: "tray", Name: ic.id, Tip: ic.tip, Group: "tray",
					X: it.x + trayEdge + i*(iconSize+trayGap), W: iconSize})
			}
			sniTray.mu.Unlock()
			continue
		}
		out = append(out, itemInfo{Kind: it.kind, Name: it.name, Rc: rc, Title: it.title, Tip: it.tip, X: it.x, W: it.w})
	}
	b, _ := json.Marshal(map[string]any{"x": monX, "y": panelTopY(), "w": monW, "h": panelH, "items": out})
	return string(b)
}
