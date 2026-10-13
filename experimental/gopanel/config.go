package main

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// helperNames maps xfce panel plugin types to the helper binaries that replace them.
var helperNames = map[string]string{
	"kitt-scanner":    "kitt",
	"mem-liquid":      "mem-liquid",
	"io-scanner":      "io-scanner",
	"network-scanner": "network-scanner",
	"wattage-panel":   "wattage-panel",
	"cpuload-color":   "cpuload-color",
}

// notYet lists xfce plugins gopanel does not replace (yet).
var notYet = map[string]string{
	"whiskermenu": "menu button (next session)",
	"tasklist":    "taskbar (next session)",
}

func atoi(vals []string, def int) int {
	if len(vals) == 1 {
		if n, err := strconv.Atoi(vals[0]); err == nil {
			return n
		}
	}
	return def
}

// iniFile reads a flat key=value rc file (xfce plugin settings, genmon-N.rc).
func iniFile(path string) map[string]string {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	m := map[string]string{}
	for _, ln := range strings.Split(string(b), "\n") {
		if k, v, ok := strings.Cut(strings.TrimSpace(ln), "="); ok {
			m[k] = v
		}
	}
	return m
}

// buildItems mirrors the xfce4-panel plugin list (panel-1, in order) as gopanel items.
func buildItems(cfg map[string][]string) []*item {
	home, _ := os.UserHomeDir()
	var items []*item
	for _, id := range cfg["/panels/panel-1/plugin-ids"] {
		t := ""
		if v := cfg["/plugins/plugin-"+id]; len(v) > 0 {
			t = v[0]
		}
		switch {
		case t == "launcher":
			for _, file := range cfg["/plugins/plugin-"+id+"/items"] {
				path := filepath.Join(home, ".config/xfce4/panel/launcher-"+id, file)
				if _, err := os.Stat(path); err != nil {
					path = filepath.Join("/usr/share/applications", file)
				}
				if it := newLauncherItem(path); it != nil {
					items = append(items, it)
				}
			}
		case t == "separator":
			it := newItem("separator")
			if v := cfg["/plugins/plugin-"+id+"/expand"]; len(v) == 1 && v[0] == "true" {
				it.expand = true
			} else {
				it.w = 8
			}
			items = append(items, it)
		case t == "systray":
			items = append(items, newTrayItem())
		case t == "power-manager-plugin":
			items = append(items, newPowerItem())
		case t == "pulseaudio":
			items = append(items, newVolumeItem())
		case t == "clock":
			items = append(items, newClockItem())
		case t == "genmon":
			rc := iniFile(filepath.Join(home, ".config/xfce4/panel/genmon-"+id+".rc"))
			if rc["Command"] != "" {
				period, _ := strconv.Atoi(rc["UpdatePeriod"])
				items = append(items, newGenmonItem(rc["Command"], period))
			}
		case helperNames[t] != "":
			it := newItem("helper")
			it.name = helperNames[t]
			items = append(items, it)
		case t == "":
		default:
			why := notYet[t]
			if why == "" {
				why = "not implemented yet"
			}
			log.Printf("plugin-%s (%s): skipped, %s", id, t, why)
		}
	}
	return items
}

func newLauncherItem(path string) *item {
	l, icon := parseDesktop(path)
	if l == nil {
		log.Println("skipping", path)
		return nil
	}
	it := newItem("launcher")
	it.w = panelH
	it.img = loadIcon(icon)
	it.hl = true
	it.tip = l.name
	if l.comment != "" && l.comment != l.name {
		it.tip += "\n" + l.comment
	}
	it.click = func(x, y, btn int) {
		if btn == 1 {
			run(l.command())
		}
	}
	return it
}
