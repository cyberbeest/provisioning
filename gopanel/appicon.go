package main

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Windows without a _NET_WM_ICON (many GTK scripts) still get their app's icon: the
// window's WM_CLASS / _GTK_APPLICATION_ID is matched against the installed .desktop
// files by StartupWMClass, by the program the Exec line starts, and by the file name.

var (
	appIconMu    sync.Mutex
	appIconIdx   map[string]string // lower-case key -> Icon= value
	appIconBuilt time.Time
)

func desktopDirs() []string {
	home, _ := os.UserHomeDir()
	dirs := []string{filepath.Join(home, ".local/share/applications")}
	data := os.Getenv("XDG_DATA_DIRS")
	if data == "" {
		data = "/usr/local/share:/usr/share"
	}
	for _, d := range strings.Split(data, ":") {
		dirs = append(dirs, filepath.Join(d, "applications"))
	}
	return dirs
}

func buildAppIconIndex() map[string]string {
	idx := map[string]string{}
	set := func(k, icon string) {
		k = strings.ToLower(k)
		if k != "" {
			if _, ok := idx[k]; !ok { // earlier dirs (user) win
				idx[k] = icon
			}
		}
	}
	for _, d := range desktopDirs() {
		files, _ := filepath.Glob(filepath.Join(d, "*.desktop"))
		for _, p := range files {
			icon, wmClass, exec, ok := readDesktopIconKeys(p)
			if !ok || icon == "" {
				continue
			}
			set(wmClass, icon)
			set(strings.TrimSuffix(filepath.Base(p), ".desktop"), icon)
			fields := strings.Fields(exec)
			for len(fields) > 0 && (fields[0] == "env" || strings.Contains(fields[0], "=")) {
				fields = fields[1:]
			}
			if len(fields) > 0 {
				set(filepath.Base(fields[0]), icon)
			}
		}
	}
	return idx
}

func readDesktopIconKeys(path string) (icon, wmClass, exec string, ok bool) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	in := false
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		ln := strings.TrimSpace(sc.Text())
		if strings.HasPrefix(ln, "[") {
			in = ln == "[Desktop Entry]"
			continue
		}
		k, v, has := strings.Cut(ln, "=")
		if !in || !has {
			continue
		}
		switch k {
		case "Icon":
			icon = v
		case "StartupWMClass":
			wmClass = v
		case "Exec":
			exec = v
		case "NoDisplay", "Hidden":
			// still useful for matching; keep going
		}
	}
	return icon, wmClass, exec, true
}

// appIconFor returns the Icon= value of the .desktop file matching any of the keys.
func appIconFor(keys ...string) string {
	appIconMu.Lock()
	defer appIconMu.Unlock()
	lookup := func() string {
		for _, k := range keys {
			if ic := appIconIdx[strings.ToLower(k)]; ic != "" && k != "" {
				return ic
			}
		}
		return ""
	}
	if appIconIdx == nil {
		appIconIdx, appIconBuilt = buildAppIconIndex(), time.Now()
	}
	if ic := lookup(); ic != "" {
		return ic
	}
	if time.Since(appIconBuilt) > 30*time.Second { // new app installed since: look again
		appIconIdx, appIconBuilt = buildAppIconIndex(), time.Now()
		return lookup()
	}
	return ""
}
