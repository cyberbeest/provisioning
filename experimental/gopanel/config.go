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
var notYet = map[string]string{}

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
		case t == "whiskermenu":
			whiskerID = id
			items = append(items, newWhiskerButton(cfg, id))
		case t == "tasklist":
			items = append(items, newTaskbarItem())
		case t == "systray":
			items = append(items, newXTrayItem(), newTrayItem()) // XEmbed first: the SNI block (Dictate last, see trayorder.go) then meets the volume item
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
				g := newGenmonItem(rc["Command"], period)
				g.rc, g.ptype, g.title = filepath.Join(home, ".config/xfce4/panel/genmon-"+id+".rc"), "genmon", genmonTitle(rc["Command"])
				items = append(items, g)
			}
		case helperNames[t] != "":
			it := newItem("helper")
			it.name = helperNames[t]
			if p := filepath.Join(home, ".config/xfce4/panel/"+t+"-"+id+".rc"); fileExists(p) {
				it.rc, it.ptype, it.title = p, t, helperTitles[it.name]
			}
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
	items = launchersLeft(items)
	// a plain separator right after a stacked (right-aligned) label would only add a gap: drop it
	for i := 0; i+1 < len(items); i++ {
		if n := items[i+1]; items[i].kind == "helper" && isStacked(items[i].name) && n.kind == "separator" && !n.expand {
			n.w = 0
		}
	}
	return items
}

// launchersLeft puts the fixed launchers right after the menu button, before the expanding
// taskbar. Everything left of an expanding item keeps its x while the rest of the panel
// fills in, so the launchers do not jump around during startup.
func launchersLeft(items []*item) []*item {
	var head, launchers, rest []*item
	seenWhisker := false
	for _, it := range items {
		switch {
		case it.kind == "launcher":
			launchers = append(launchers, it)
		case !seenWhisker && it.kind == "whisker":
			seenWhisker = true
			head = append(head, it)
		case !seenWhisker:
			head = append(head, it)
		default:
			rest = append(rest, it)
		}
	}
	return append(append(head, launchers...), rest...)
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
			noticeStart(l.name)
		}
	}
	return it
}

// newWhiskerButton is the panel button that opens the application menu.
func newWhiskerButton(cfg map[string][]string, id string) *item {
	it := newItem("whisker")
	it.w = panelH
	it.hl = true
	it.tip = tr("Applications")
	if v := cfg["/plugins/plugin-"+id+"/button-icon"]; len(v) == 1 {
		it.img = loadIcon(v[0])
	} else {
		it.img = loadIcon("org.xfce.panel.applicationsmenu")
	}
	it.click = func(x, y, btn int) {
		if btn == 1 && toggleWhisker != nil {
			whiskerAnchor = it.x
			toggleWhisker()
		}
	}
	return it
}

var helperTitles = map[string]string{
	"kitt": "Kitt Scanner", "mem-liquid": "Memory Liquid", "io-scanner": "I/O Scanner",
	"network-scanner": "Network Scanner", "wattage-panel": "Wattage Panel",
}

// genmonTitle names a generic monitor after what it runs.
func genmonTitle(command string) string {
	if strings.Contains(command, "panel-status-genmon") {
		return "Autolock & Status"
	}
	base := filepath.Base(strings.Fields(command + " x")[0])
	base = strings.TrimSuffix(base, filepath.Ext(base))
	base = strings.NewReplacer("-", " ", "_", " ").Replace(base)
	if base == "" {
		return "Generic Monitor"
	}
	return strings.ToUpper(base[:1]) + base[1:]
}
