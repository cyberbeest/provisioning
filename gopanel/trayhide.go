package main

import (
	"image"
	"image/color"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Hidden tray icons: ~/.config/gopanel/hidden-tray.conf lists the icons the user hid from
// their right-click menu ("Hide icon"), one key per line. The key is the lowercase
// StatusNotifier Id (the title when the item has none). While a hidden icon is running a
// "..." marker at the end of the tray lists them, and picking one shows it again.

func hideKey(ic *trayIcon) string {
	if ic.id != "" {
		return strings.ToLower(ic.id)
	}
	return strings.ToLower(ic.title)
}

func trayName(ic *trayIcon) string {
	for _, s := range []string{ic.title, ic.id} {
		if s != "" {
			return s
		}
	}
	if i := strings.Index(ic.tip, "\n"); i > 0 {
		return ic.tip[:i]
	}
	return ic.tip
}

func hiddenTrayPath() string {
	dir, err := os.UserConfigDir()
	if err != nil {
		return ""
	}
	return filepath.Join(dir, "gopanel", "hidden-tray.conf")
}

func loadHiddenTray() map[string]bool {
	m := map[string]bool{}
	p := hiddenTrayPath()
	if p == "" {
		return m
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return m
	}
	for _, l := range strings.Split(string(b), "\n") {
		if l = strings.ToLower(strings.TrimSpace(l)); l != "" && !strings.HasPrefix(l, "#") {
			m[l] = true
		}
	}
	return m
}

func saveHiddenTray(m map[string]bool) {
	p := hiddenTrayPath()
	if p == "" {
		return
	}
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	os.MkdirAll(filepath.Dir(p), 0o755)
	os.WriteFile(p, []byte("# tray icons hidden from the panel, one per line (remove a line to show it again)\n"+strings.Join(keys, "\n")+"\n"), 0o644)
}

// moreDots draws the "..." marker.
func moreDots(size int) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	c := color.RGBA{0x50, 0x50, 0x50, 0xff}
	r := size / 11
	if r < 1 {
		r = 1
	}
	cy := size / 2
	for i := 0; i < 3; i++ {
		cx := size/2 + (i-1)*(size/4)
		for y := -r; y <= r; y++ {
			for x := -r; x <= r; x++ {
				if x*x+y*y <= r*r+r/2 {
					img.SetRGBA(cx+x, cy+y, c)
				}
			}
		}
	}
	return img
}
