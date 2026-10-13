package main

import (
	"github.com/jezek/xgb"
	"github.com/jezek/xgb/randr"
	"github.com/jezek/xgb/xproto"
)

// The panel lives at the bottom of the primary monitor. mon* is that monitor's rectangle
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
	m := r.Monitors[0]
	for _, x := range r.Monitors {
		if x.Primary {
			m = x
			break
		}
	}
	monX, monY, monW, monH = int(m.X), int(m.Y), int(m.Width), int(m.Height)
}

func initRandr(c *xgb.Conn, root xproto.Window) {
	if randr.Init(c) == nil {
		haveRandr = true
		randr.SelectInput(c, root, randr.NotifyMaskScreenChange)
	}
}

// monitorBottom is the screen y of the panel's top edge.
func panelTopY() int { return monY + monH - panelH }
