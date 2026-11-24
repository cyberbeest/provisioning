package main

import (
	"github.com/jezek/xgb/xproto"
)

// A fullscreen window (a movie on the second monitor) should not have a panel over it, but
// the window manager restacks docks above it now and then (a click on the other desktop).
// So the panel window of a monitor with a fullscreen window on it is unmapped, and mapped
// again when the window is gone. The other monitors keep their panel.

var fsHidden = map[xproto.Window]bool{} // panel windows currently unmapped for a fullscreen window

// fullscreenRects returns the root rectangles of the visible fullscreen windows on the current desktop.
func fullscreenRects() []monRect {
	desk := uint32(0xffffffff)
	if d := propU32s(xroot, "_NET_CURRENT_DESKTOP", 1); len(d) == 1 {
		desk = d[0]
	}
	var out []monRect
	for _, id := range propU32s(xroot, "_NET_CLIENT_LIST", 512) {
		w := xproto.Window(id)
		fs, hidden := false, false
		for _, s := range propU32s(w, "_NET_WM_STATE", 32) {
			switch xproto.Atom(s) {
			case A("_NET_WM_STATE_FULLSCREEN"):
				fs = true
			case A("_NET_WM_STATE_HIDDEN"):
				hidden = true
			}
		}
		if !fs || hidden {
			continue
		}
		if d := propU32s(w, "_NET_WM_DESKTOP", 1); len(d) == 1 && d[0] != 0xffffffff && d[0] != desk {
			continue
		}
		g, err := xproto.GetGeometry(xc, xproto.Drawable(w)).Reply()
		if err != nil {
			continue
		}
		t, err := xproto.TranslateCoordinates(xc, w, xroot, 0, 0).Reply()
		if err != nil {
			continue
		}
		out = append(out, monRect{x: int(t.DstX), y: int(t.DstY), w: int(g.Width), h: int(g.Height)})
	}
	return out
}

// coversCenter reports whether any fullscreen rectangle holds the centre of the monitor.
func coversCenter(fs []monRect, x, y, w, h int) bool {
	cx, cy := x+w/2, y+h/2
	for _, r := range fs {
		if cx >= r.x && cx < r.x+r.w && cy >= r.y && cy < r.y+r.h {
			return true
		}
	}
	return false
}

// updateFullscreenPanels maps or unmaps the panel windows to match the fullscreen windows.
func updateFullscreenPanels() {
	fs := fullscreenRects()
	set := func(win xproto.Window, hide bool) {
		if hide == fsHidden[win] {
			return
		}
		if hide {
			xproto.UnmapWindow(xc, win)
			fsHidden[win] = true
		} else {
			xproto.MapWindow(xc, win)
			delete(fsHidden, win)
		}
	}
	set(panelWin, coversCenter(fs, monX, monY, monW, monH))
	live := map[xproto.Window]bool{panelWin: true}
	for _, r := range replicas {
		live[r.win] = true
		set(r.win, coversCenter(fs, r.mx, r.my, r.mw, r.mh))
	}
	for w := range fsHidden { // replicas rebuilt meanwhile
		if !live[w] {
			delete(fsHidden, w)
		}
	}
}

// fullscreenRelevant says whether a property change can alter which windows are fullscreen.
func fullscreenRelevant(e xproto.PropertyNotifyEvent) bool {
	switch e.Atom {
	case A("_NET_WM_STATE"), A("_NET_CLIENT_LIST"), A("_NET_CURRENT_DESKTOP"), A("_NET_WM_DESKTOP"):
		return true
	}
	return false
}
