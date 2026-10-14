package main

import (
	"log"
	"strings"
	"time"

	"github.com/jezek/xgb/xproto"
)

// XEmbed system tray (the legacy tray protocol Qt/GTK2 apps such as Telegram and
// nm-applet still use). We own the _NET_SYSTEM_TRAY_S0 selection when nobody else
// does (the xfce4-panel systray plugin does while it runs), announce it with a
// MANAGER message so running apps dock again, and reparent each icon window into
// the panel window. Everything runs on the main goroutine, driven by X events and a
// 0.5 s tick that tries to take over a free selection.

const (
	xtGap  = 4
	xtEdge = 3
)

type xtray struct {
	it     *item
	mgr    xproto.Window
	owned  bool
	yield  bool // another panel is about to start: leave the selection alone
	icons  []xproto.Window
	hidden map[xproto.Window]bool // docked, but the app also has a StatusNotifier icon: shown once, not twice
}

var (
	xt       = &xtray{}
	panelWin xproto.Window
	reflow   func() // relayout + redraw, set by main
)

func newXTrayItem() *item {
	it := newItem("xtray")
	xt.it = it
	it.w = xt.width()
	return it
}

func (x *xtray) visibleIcons() []xproto.Window {
	var out []xproto.Window
	for _, w := range x.icons {
		if !x.hidden[w] {
			out = append(out, w)
		}
	}
	return out
}

func (x *xtray) width() int {
	n := len(x.visibleIcons())
	if n == 0 {
		return 0
	}
	return n*(iconSize+xtGap) - xtGap + 2*xtEdge
}

// tryAcquire takes the tray selection if it is free.
func (x *xtray) tryAcquire() {
	if x.owned || x.it == nil || x.yield {
		return
	}
	sel := A("_NET_SYSTEM_TRAY_S0")
	r, err := xproto.GetSelectionOwner(xc, sel).Reply()
	if err != nil || r.Owner != 0 {
		return
	}
	if x.mgr == 0 {
		id, _ := xproto.NewWindowId(xc)
		scr := xproto.Setup(xc).DefaultScreen(xc)
		xproto.CreateWindow(xc, 0, id, xroot, -10, -10, 1, 1, 0, xproto.WindowClassInputOnly, scr.RootVisual,
			xproto.CwEventMask, []uint32{xproto.EventMaskPropertyChange})
		xproto.ChangeProperty(xc, xproto.PropModeReplace, id, A("_NET_SYSTEM_TRAY_ORIENTATION"),
			xproto.AtomCardinal, 32, 1, u32(0)) // horizontal
		x.mgr = id
	}
	xproto.SetSelectionOwner(xc, x.mgr, sel, xproto.TimeCurrentTime)
	if o, err := xproto.GetSelectionOwner(xc, sel).Reply(); err != nil || o.Owner != x.mgr {
		return
	}
	x.owned = true
	ev := xproto.ClientMessageEvent{Format: 32, Window: xroot, Type: A("MANAGER"),
		Data: xproto.ClientMessageDataUnionData32New([]uint32{uint32(xproto.TimeCurrentTime), uint32(sel), uint32(x.mgr), 0, 0})}
	xproto.SendEvent(xc, false, xroot, xproto.EventMaskStructureNotify, string(ev.Bytes()))
	log.Println("xembed: owning the system tray selection")
}

// yieldTray gives up the selection for good (until restart) so a starting xfce4-panel
// can take it: its systray plugin does not retry.
func (x *xtray) yieldTray() {
	x.yield = true
	if x.owned {
		xproto.SetSelectionOwner(xc, 0, A("_NET_SYSTEM_TRAY_S0"), xproto.TimeCurrentTime)
		x.release()
	}
}

// release gives the icons back to the root window (the new owner announces itself
// with MANAGER and apps dock again).
func (x *xtray) release() {
	x.owned = false
	for _, w := range x.icons {
		xproto.UnmapWindow(xc, w)
		xproto.ReparentWindow(xc, w, xroot, 0, 0)
	}
	x.icons = nil
	x.sync()
}

func (x *xtray) sync() {
	if x.it != nil {
		x.it.w = x.width()
	}
	if reflow != nil {
		reflow()
	}
}

func (x *xtray) has(w xproto.Window) bool {
	for _, i := range x.icons {
		if i == w {
			return true
		}
	}
	return false
}

func (x *xtray) dock(w xproto.Window) {
	if x.has(w) || x.it == nil {
		return
	}
	if _, err := xproto.GetWindowAttributes(xc, w).Reply(); err != nil {
		return
	}
	noticeIcon()
	mapped := true
	if r := getProp(w, "_XEMBED_INFO", 2); r != nil && len(r.Value) >= 8 {
		mapped = r.Value[4]&1 != 0
	}
	xproto.ChangeWindowAttributes(xc, w, xproto.CwEventMask, []uint32{xproto.EventMaskStructureNotify | xproto.EventMaskPropertyChange})
	xproto.ChangeSaveSet(xc, xproto.SetModeInsert, w) // survive our exit
	xproto.ConfigureWindow(xc, w, xproto.ConfigWindowWidth|xproto.ConfigWindowHeight, []uint32{uint32(iconSize), uint32(iconSize)})
	xproto.ReparentWindow(xc, w, panelWin, 0, 0)
	ev := xproto.ClientMessageEvent{Format: 32, Window: w, Type: A("_XEMBED"),
		Data: xproto.ClientMessageDataUnionData32New([]uint32{uint32(xproto.TimeCurrentTime), 0, 0, uint32(panelWin), 0})} // EMBEDDED_NOTIFY
	xproto.SendEvent(xc, false, w, 0, string(ev.Bytes()))
	if mapped {
		xproto.MapWindow(xc, w)
	}
	x.icons = append(x.icons, w)
	x.sync()
}

func (x *xtray) remove(w xproto.Window) {
	for i, c := range x.icons {
		if c == w {
			delete(x.hidden, w)
			x.icons = append(x.icons[:i], x.icons[i+1:]...)
			x.sync()
			return
		}
	}
}

// place moves the docked windows to follow the item after a layout pass; hidden ones wait
// unmapped off-screen.
func (x *xtray) place() {
	if x.it == nil {
		return
	}
	y := (panelH - iconSize) / 2
	i := 0
	for _, w := range x.icons {
		if x.hidden[w] {
			xproto.ConfigureWindow(xc, w, xproto.ConfigWindowX|xproto.ConfigWindowY, []uint32{0xffffff38, 0xffffff38}) // -200,-200
			continue
		}
		xproto.ConfigureWindow(xc, w, xproto.ConfigWindowX|xproto.ConfigWindowY|xproto.ConfigWindowWidth|xproto.ConfigWindowHeight,
			[]uint32{uint32(x.it.x + xtEdge + i*(iconSize+xtGap)), uint32(y), uint32(iconSize), uint32(iconSize)})
		i++
	}
}

// windowIDs returns the lowercase name and class strings of a window.
func windowIDs(w xproto.Window) []string {
	var out []string
	for _, p := range []string{"_NET_WM_NAME", "WM_NAME", "WM_CLASS"} {
		if r := getProp(w, p, 256); r != nil {
			for _, s := range strings.Split(string(r.Value), "\x00") {
				if s != "" {
					out = append(out, strings.ToLower(s))
				}
			}
		}
	}
	return out
}

// refreshHidden hides docked icons whose application also shows a StatusNotifier icon
// (blueman registers both; the XEmbed one stays blank). Called from the tick.
func (x *xtray) refreshHidden() {
	if len(x.icons) == 0 || sniTray == nil {
		return
	}
	ids := sniTray.ids()
	changed := false
	for _, w := range x.icons {
		hide := false
		for _, s := range windowIDs(w) {
			for _, id := range ids {
				if len(id) >= 4 && (s == id || strings.HasPrefix(s, id)) {
					hide = true
				}
			}
		}
		if hide != x.hidden[w] {
			if x.hidden == nil {
				x.hidden = map[xproto.Window]bool{}
			}
			x.hidden[w] = hide
			if hide {
				xproto.UnmapWindow(xc, w)
			} else {
				xproto.MapWindow(xc, w)
			}
			changed = true
		}
	}
	if changed {
		x.sync()
	}
}

// handle consumes tray-related X events; true if the event was ours.
func (x *xtray) handle(ev interface{}) bool {
	switch e := ev.(type) {
	case xproto.ClientMessageEvent:
		if x.mgr != 0 && e.Window == x.mgr && e.Type == A("_NET_SYSTEM_TRAY_OPCODE") {
			d := e.Data.Data32
			if len(d) >= 3 && d[1] == 0 { // SYSTEM_TRAY_REQUEST_DOCK
				x.dock(xproto.Window(d[2]))
			}
			return true
		}
	case xproto.SelectionClearEvent:
		if e.Owner == x.mgr && x.mgr != 0 {
			x.release()
			return true
		}
	case xproto.DestroyNotifyEvent:
		if x.has(e.Window) {
			x.remove(e.Window)
			return true
		}
	case xproto.ReparentNotifyEvent:
		if x.has(e.Window) && e.Parent != panelWin {
			x.remove(e.Window)
			return true
		}
	}
	return false
}

func xtrayTick() <-chan time.Time { return time.NewTicker(500 * time.Millisecond).C }

// parkIcons hides the docked icons before we exit or exec: the save-set would otherwise hand
// them back to the root window *mapped*, and they would show up as tiny stray windows (in
// the middle of the screen) until the next panel docks them again.
func (x *xtray) parkIcons() {
	for _, w := range x.icons {
		xproto.UnmapWindow(xc, w)
		xproto.ReparentWindow(xc, w, xroot, -200, -200)
	}
	x.icons = nil
	xproto.GetInputFocus(xc).Reply() // round trip: make sure the requests went out before exec
}
