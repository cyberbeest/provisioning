package main

import (
	"github.com/jezek/xgb"
	"github.com/jezek/xgb/randr"
	"github.com/jezek/xgb/xproto"
)

// The panel lives at the bottom of one monitor (see pickMonitor). mon* is that monitor's rectangle
// in root coordinates; anchors passed around (item x positions) are panel-relative and get
// offset by monX where a screen position is needed.
var (
	monX, monY, monW, monH int
	rootH                  int
	haveRandr              bool
)

// queryMonitor refreshes mon* (and rootH) from RandR, falling back to the whole root window.
func queryMonitor(c *xgb.Conn, scr *xproto.ScreenInfo) {
	rootH = int(scr.HeightInPixels)
	if g, err := xproto.GetGeometry(c, xproto.Drawable(scr.Root)).Reply(); err == nil {
		rootH = int(g.Height)
		monX, monY, monW, monH = 0, 0, int(g.Width), int(g.Height)
	} else {
		monX, monY, monW, monH = 0, 0, int(scr.WidthInPixels), int(scr.HeightInPixels)
	}
	if !haveRandr {
		return
	}
	r, err := randr.GetMonitors(c, scr.Root, true).Reply()
	if err != nil || len(r.Monitors) == 0 {
		return
	}
	allMons = allMons[:0]
	for _, x := range r.Monitors {
		name := ""
		if n, err := xproto.GetAtomName(c, x.Name).Reply(); err == nil {
			name = n.Name
		}
		allMons = append(allMons, monRect{name, int(x.X), int(x.Y), int(x.Width), int(x.Height)})
	}
	m := pickMonitor(c, r.Monitors)
	monX, monY, monW, monH = int(m.X), int(m.Y), int(m.Width), int(m.Height)
}

// panelOutput is the xfce4-panel setting /panels/panel-1/output-name ("" or "Automatic" = pick).
var panelOutput string

// pickMonitor chooses where the panel lives: the output named in the panel config if it is
// connected, else the primary monitor, else the leftmost one (then the topmost).
func pickMonitor(c *xgb.Conn, ms []randr.MonitorInfo) randr.MonitorInfo {
	if panelOutput != "" && panelOutput != "Automatic" {
		for _, m := range ms {
			if r, err := xproto.GetAtomName(c, m.Name).Reply(); err == nil && r.Name == panelOutput {
				return m
			}
		}
	}
	best := ms[0]
	for _, m := range ms {
		if m.Primary {
			return m
		}
		if m.X < best.X || (m.X == best.X && m.Y < best.Y) {
			best = m
		}
	}
	return best
}

func initRandr(c *xgb.Conn, root xproto.Window) {
	if randr.Init(c) == nil {
		haveRandr = true
		// output/crtc changes too: `xrandr --primary` and hotplugging change the monitor list
		// without a screen-size change
		randr.SelectInput(c, root, randr.NotifyMaskScreenChange|randr.NotifyMaskOutputChange|randr.NotifyMaskCrtcChange)
	}
}

// monitorBottom is the screen y of the panel's top edge.
func panelTopY() int { return monY + monH - panelH }

func firstOf(v []string) string {
	if len(v) > 0 {
		return v[0]
	}
	return ""
}
