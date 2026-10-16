// wattage-panel: battery power draw and remaining time, as a gopanel helper. Port of
// lib/xfce-panel-plugins/wattage-panel.c (same label, tooltip, tick-window averaging,
// persisted ticks and history.csv). Sends text only; the panel renders it.
package main

import (
	"bufio"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"gopanel/proto"
)

const (
	batPath         = "/sys/class/power_supply/BAT0"
	sampleEvery     = 3 * time.Second
	logEvery        = 5 * time.Minute
	resumeMaxGapSec = 30 * 60
	debugRingSize   = 10
)

type status int

const (
	discharging status = iota
	charging
	other
)

func parseStatus(s string) status {
	switch s {
	case "Discharging":
		return discharging
	case "Charging":
		return charging
	}
	return other
}

func logName(s status) string {
	switch s {
	case discharging:
		return "battery"
	case charging:
		return "charging"
	}
	return "ac"
}

type point struct {
	t int64
	e float64 // energy_now, uWh
}

var avgWindows = []struct {
	label string
	secs  int64
}{{"10 min", 600}, {"30 min", 1800}, {"1 h", 3600}, {"2 h", 7200}}

type watt struct {
	ticks         []point // seed + validated, monotonically decreasing energy readings
	batteryStart  int64
	lastValid     float64
	haveLastValid bool
	debug         []point
	debugRaw      bool

	haveLast   bool
	lastStatus status
	lastWatts  float64
	lastCap    float64
	lastEnergy float64
	screenOff  bool
	persist    bool // false while the xfce plugin runs and owns the state files
}

func readFloat(path string) (float64, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	v, err := strconv.ParseFloat(strings.TrimSpace(string(b)), 64)
	return v, err == nil
}

func readString(path string) string {
	b, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func stateDir() string {
	d := os.Getenv("XDG_STATE_HOME")
	if d == "" {
		home, _ := os.UserHomeDir()
		d = filepath.Join(home, ".local/state")
	}
	d = filepath.Join(d, "wattage-panel")
	os.MkdirAll(d, 0o755)
	return filepath.Join(d)
}

func (w *watt) ticksFileReset(t int64, e float64) {
	if !w.persist {
		return
	}
	os.WriteFile(filepath.Join(stateDir(), "ticks.csv"), []byte(fmt.Sprintf("%d,%.0f\n", t, e)), 0o644)
}

func (w *watt) ticksFileAppend(t int64, e float64) {
	if !w.persist {
		return
	}
	f, err := os.OpenFile(filepath.Join(stateDir(), "ticks.csv"), os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0o644)
	if err != nil {
		return
	}
	fmt.Fprintf(f, "%d,%.0f\n", t, e)
	f.Close()
}

func (w *watt) resetTicks(now int64, e float64) {
	w.ticks = []point{{now, e}}
	w.batteryStart = now
	w.lastValid = e
	w.haveLastValid = true
	w.ticksFileReset(now, e)
}

// historyShowsACSince: history.csv has a non-battery row after since.
func historyShowsACSince(since int64) bool {
	f, err := os.Open(filepath.Join(stateDir(), "history.csv"))
	if err != nil {
		return false
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Scan() // header
	for sc.Scan() {
		p := strings.Split(sc.Text(), ",")
		if len(p) < 2 {
			continue
		}
		if ts, err := strconv.ParseInt(p[0], 10, 64); err == nil && ts > since && p[1] != "battery" {
			return true
		}
	}
	return false
}

// tryResume continues a persisted discharge session after a restart, if it is
// recent, the battery hasn't gained charge, and no AC time was logged since.
func (w *watt) tryResume(now int64, e float64) bool {
	f, err := os.Open(filepath.Join(stateDir(), "ticks.csv"))
	if err != nil {
		return false
	}
	defer f.Close()
	var loaded []point
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		p := strings.Split(sc.Text(), ",")
		if len(p) != 2 {
			continue
		}
		t, e1 := strconv.ParseInt(p[0], 10, 64)
		en, e2 := strconv.ParseFloat(p[1], 64)
		if e1 == nil && e2 == nil {
			loaded = append(loaded, point{t, en})
		}
	}
	if len(loaded) < 1 {
		return false
	}
	last := loaded[len(loaded)-1]
	if now-last.t > resumeMaxGapSec || e > last.e || historyShowsACSince(last.t) {
		return false
	}
	w.ticks = loaded
	w.batteryStart = loaded[0].t
	w.lastValid = last.e
	w.haveLastValid = true
	if e < last.e { // battery kept draining while we weren't running
		w.ticks = append(w.ticks, point{now, e})
		w.lastValid = e
		w.ticksFileAppend(now, e)
	}
	return true
}

// windowAverage: average watts between the first and last real tick inside the
// trailing window. ticks[0] is a seed, not an observed EC update, so it never counts.
func (w *watt) windowAverage(now, window int64) (watts float64, n int, ok bool) {
	if len(w.ticks) < 3 {
		return
	}
	cutoff := now - window
	end := len(w.ticks) - 1
	if w.ticks[end].t < cutoff {
		return
	}
	start := end
	for start > 1 && w.ticks[start-1].t >= cutoff {
		start--
	}
	if start >= end {
		return
	}
	span := w.ticks[end].t - w.ticks[start].t
	diff := w.ticks[start].e - w.ticks[end].e
	if span <= 0 || diff <= 0 {
		return
	}
	return (diff / 1e6) / (float64(span) / 3600), end - start + 1, true
}

func plural(n int) string {
	if n == 1 {
		return "tick"
	}
	return "ticks"
}

// update samples the battery and returns the panel label and tooltip.
func (w *watt) update() (label, tip string) {
	st := parseStatus(readString(batPath + "/status"))
	statusStr := readString(batPath + "/status")
	powerUw, _ := readFloat(batPath + "/power_now")
	energy, _ := readFloat(batPath + "/energy_now")
	capacity, _ := readFloat(batPath + "/capacity")
	now := time.Now().Unix()

	w.debug = append(w.debug, point{now, energy})
	if len(w.debug) > debugRingSize {
		w.debug = w.debug[1:]
	}

	if st == discharging {
		if !w.haveLastValid || w.lastStatus != discharging {
			// Only resume a persisted session on true process startup; a live
			// AC/charging -> Discharging transition is unambiguously a fresh one.
			if resumed := !w.haveLast && w.persist && w.tryResume(now, energy); !resumed {
				w.resetTicks(now, energy)
			}
		} else if energy < w.lastValid {
			w.ticks = append(w.ticks, point{now, energy})
			w.lastValid = energy
			w.ticksFileAppend(now, energy)
		}
		// energy == lastValid: no new tick yet. energy > lastValid: EC readback
		// glitch (bounces up a ~0.29Wh step and back within seconds): dropped.
	} else {
		w.haveLastValid = false // reseed next time we go on battery
	}

	// Prefer the machine's own power_now; some boards never populate it (flat 0), so
	// fall back to the 10-minute tick average.
	watts := powerUw / 1e6
	isAvg := false
	if watts <= 0 && st == discharging {
		if aw, _, ok := w.windowAverage(now, avgWindows[0].secs); ok {
			watts, isAvg = aw, true
		}
	}

	switch st {
	case discharging:
		if watts > 0 {
			hours := energy / (watts * 1e6)
			h := int(hours)
			label = fmt.Sprintf("%.1fW -%d:%02d", watts, h, int((hours-float64(h))*60))
		} else {
			label = fmt.Sprintf("%.1fW", watts)
		}
	case charging:
		label = fmt.Sprintf("%.1fW chg", watts)
	default:
		label = "AC"
	}

	var b strings.Builder
	if isAvg {
		fmt.Fprintf(&b, "Battery: %.0f%% (%s)\nPower: %.1f W (10 min average)", capacity, statusStr, watts)
	} else {
		fmt.Fprintf(&b, "Battery: %.0f%% (%s)\nPower: %.1f W (instant, as reported)", capacity, statusStr, watts)
	}
	if st == discharging {
		el := now - w.batteryStart
		fmt.Fprintf(&b, "\n\nAverages since on battery (%d:%02d:%02d):", el/3600, el/60%60, el%60)
		for _, win := range avgWindows {
			if aw, n, ok := w.windowAverage(now, win.secs); ok {
				fmt.Fprintf(&b, "\n  %-6s: %.1f W  (%d %s)", win.label, aw, n, plural(n))
			} else {
				fmt.Fprintf(&b, "\n  %-6s: not enough data yet", win.label)
			}
		}
		if aw, n, ok := w.windowAverage(now, el+1); ok {
			fmt.Fprintf(&b, "\n  %-6s: %.1f W  (%d %s)", "all", aw, n, plural(n))
		} else {
			fmt.Fprintf(&b, "\n  %-6s: not enough data yet", "all")
		}
	}
	if w.debugRaw {
		b.WriteString("\n\nLast raw energy_now readings:")
		for _, p := range w.debug {
			fmt.Fprintf(&b, "\n%s  %.0f uWh", time.Unix(p.t, 0).Format("15:04:05"), p.e)
		}
	}

	w.lastStatus, w.lastWatts, w.lastCap, w.lastEnergy, w.haveLast = st, watts, capacity, energy, true
	return label, b.String()
}

// appendLog adds one history.csv row (hour-granularity graphs, offline analysis).
func (w *watt) appendLog() {
	if !w.haveLast || !w.persist {
		return
	}
	path := filepath.Join(stateDir(), "history.csv")
	_, err := os.Stat(path)
	fresh := err != nil
	f, err := os.OpenFile(path, os.O_APPEND|os.O_WRONLY|os.O_CREATE, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	if fresh {
		f.WriteString("timestamp,status,watts,battery_pct,screen,energy_now_uwh\n")
	}
	screen := "on"
	if w.screenOff {
		screen = "off"
	}
	fmt.Fprintf(f, "%d,%s,%.2f,%.0f,%s,%.0f\n", time.Now().Unix(), logName(w.lastStatus), w.lastWatts, w.lastCap, screen, w.lastEnergy)
}

// xfcePluginRunning: the original C plugin still owns ticks.csv/history.csv.
func xfcePluginRunning() bool {
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		if n := e.Name(); n[0] >= '0' && n[0] <= '9' {
			if b, err := os.ReadFile("/proc/" + n + "/cmdline"); err == nil && strings.Contains(string(b), "libwattage-panel.so") {
				return true
			}
		}
	}
	return false
}

func debugRawFromRC() bool {
	home, _ := os.UserHomeDir()
	m, _ := filepath.Glob(filepath.Join(home, ".config/xfce4/panel/wattage-panel-*.rc"))
	for _, p := range m {
		if b, err := os.ReadFile(p); err == nil && strings.Contains(string(b), "DebugRaw=true") {
			return true
		}
	}
	return false
}

func run(c *proto.Client) {
	w := &watt{debugRaw: debugRawFromRC()}
	w.persist = !xfcePluginRunning()
	if _, err := os.Stat(batPath); err != nil {
		c.SetLabel("") // no battery: hidden slot
		for range c.Events {
		}
		return
	}
	push := func() bool {
		label, tip := w.update()
		return c.SetLabel(label) == nil && c.SetTooltip(tip) == nil
	}
	if !push() {
		return
	}
	w.appendLog()
	sampleT := time.NewTicker(sampleEvery)
	defer sampleT.Stop()
	logT := time.NewTicker(logEvery)
	defer logT.Stop()
	for {
		select {
		case ev, ok := <-c.Events:
			if !ok {
				return
			}
			switch ev {
			case "pause":
				w.screenOff = true
			case "resume":
				w.screenOff = false
				if !push() { // catch the label up at once
					return
				}
			}
		case <-sampleT.C:
			if w.screenOff { // locked or display off: nobody sees the label
				continue
			}
			if !push() {
				return
			}
		case <-logT.C:
			w.persist = !xfcePluginRunning()
			if w.screenOff {
				w.update() // fresh reading (and tick) for the log row; nothing to send
			}
			w.appendLog()
		}
	}
}

func main() {
	for {
		if !proto.ParentAlive() {
			return
		}
		c, err := proto.Dial("wattage-panel", func(int) int { return 0 })
		if err != nil {
			time.Sleep(time.Second)
			continue
		}
		log.Println("connected")
		run(c)
		c.Close()
		time.Sleep(time.Second)
	}
}
