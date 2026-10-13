package main

import (
	"image"
	"strconv"
	"strings"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
)

// Where the panel lives is chosen in Cyberbeest Settings > Panel and kept in
// ~/.config/cyberbeest/panel.conf as MONITOR=auto | all | <output name>:
//
//	auto    the output named in the xfce4-panel config, else the primary monitor
//	<name>  that output (when it is connected, else as auto)
//	all     the panel on the primary monitor, replicated on every other monitor
//
// A replica has its own window, strut and layout (the taskbar and spacers use that monitor's
// width) and shows the same items. XEmbed tray icons are real windows and exist once, so the
// replicas leave that slot out. Events on a replica are handled by temporarily making the
// replica the "current panel" (monitor globals and item positions swapped), see withReplica.

type monRect struct {
	name       string
	x, y, w, h int
}

type replica struct {
	win            xproto.Window
	back           xproto.Pixmap
	mx, my, mw, mh int
	x, w           map[*item]int
	buf            []byte
}

var (
	replicas        []*replica
	panelMode       string // "" or "all"
	allMons         []monRect
	panelItems      []*item
	curHover        func() *item
	hoverPanel      *replica // the panel the hovered item is on (nil: the main panel)
	activeRep       *replica // the replica whose event is being handled, else nil
	swapped         bool     // inside withReplica: relayouts wait until the swap is undone
	pendingRelayout bool
	panelGCs        struct {
		c    *xgb.Conn
		scr  *xproto.ScreenInfo
		gc   xproto.Gcontext
		bgGC xproto.Gcontext
	}
)

// readMonitorChoice returns the MONITOR setting from panel.conf ("" when absent or auto).
func readMonitorChoice() string {
	if v := readPanelConf()["MONITOR"]; v != "auto" {
		return v
	}
	return ""
}

// applyMonitorChoice sets panelMode/panelOutput from panel.conf, falling back to the XFCE
// panel's own output-name; true if anything changed.
func applyMonitorChoice(cfg map[string][]string) bool {
	mode, out := "", firstOf(cfg["/panels/panel-1/output-name"])
	switch v := readMonitorChoice(); v {
	case "":
	case "all":
		mode = "all"
	default:
		out = v
	}
	changed := mode != panelMode || out != panelOutput
	panelMode, panelOutput = mode, out
	return changed
}

// monitorSig identifies the monitor setup the panels are laid out for.
func monitorSig() string {
	var b strings.Builder
	b.WriteString(panelMode)
	for _, m := range allMons {
		b.WriteString(";" + m.name)
		for _, v := range []int{m.x, m.y, m.w, m.h} {
			b.WriteString("," + strconv.Itoa(v))
		}
	}
	b.WriteString(";" + strconv.Itoa(monX) + "," + strconv.Itoa(monY) + "," + strconv.Itoa(rootH))
	return b.String()
}

// computeLayout assigns x and width to every item for a panel `width` px wide: fixed items
// keep their width, expanding ones share what is left (see relayout's notes in main.go).
func computeLayout(items []*item, width int, skipXEmbed bool) (xs, ws map[*item]int) {
	xs, ws = map[*item]int{}, map[*item]int{}
	fixed := 4 // 4px right margin
	var exp []*item
	for _, it := range items {
		if it.expand {
			exp = append(exp, it)
			continue
		}
		w := it.w
		if skipXEmbed && it.kind == "xtray" {
			w = 0
		}
		ws[it] = w
		fixed += w
	}
	// Free width goes first to expanding items that say how much they can use (the taskbar:
	// a full-width button per window), in panel order; fillers (the expanding separator) get
	// the rest. With no filler the users take everything, so the right side stays right.
	left := max(width-fixed, 0)
	var users, fillers []*item
	for _, it := range exp {
		if it.want != nil {
			users = append(users, it)
		} else {
			fillers = append(fillers, it)
		}
	}
	if len(fillers) == 0 && len(users) > 0 {
		for _, it := range users {
			ws[it] = left / len(users)
		}
	} else {
		for _, it := range users {
			w := min(it.want(), left)
			ws[it] = w
			left -= w
		}
		for _, it := range fillers {
			ws[it] = left / len(fillers)
		}
	}
	x := 0
	for _, it := range items {
		xs[it] = x
		x += ws[it]
	}
	return xs, ws
}

func layoutReplicas() {
	for _, r := range replicas {
		r.x, r.w = computeLayout(panelItems, r.mw, true)
	}
}

// composite fills buf (w x panelH, BGRX) with the panel or hover colour and the item image over it.
func composite(buf []byte, w int, img *image.RGBA, holdLeft bool, bg uint32) {
	br, bgn, bb := uint32(byte(bg>>16)), uint32(byte(bg>>8)), uint32(byte(bg))
	need := w * panelH * 4
	buf[0], buf[1], buf[2], buf[3] = byte(bb), byte(bgn), byte(br), 0
	for n := 4; n < need; n *= 2 { // fill with the background colour by doubling copies
		copy(buf[n:], buf[:n])
	}
	if img == nil {
		return
	}
	ib := img.Bounds()
	ox, oy := (w-ib.Dx())/2, (panelH-ib.Dy())/2
	if holdLeft {
		ox = 0 // icons fill the held slot from the left, so they do not slide as more dock
	}
	for y := 0; y < ib.Dy(); y++ {
		if oy+y < 0 || oy+y >= panelH {
			continue
		}
		for x := 0; x < ib.Dx(); x++ {
			if ox+x < 0 || ox+x >= w {
				continue
			}
			p := img.Pix[y*img.Stride+x*4:]
			o := ((oy+y)*w + ox + x) * 4
			inv := 255 - uint32(p[3])
			buf[o] = byte(uint32(p[2]) + bb*inv/255)
			buf[o+1] = byte(uint32(p[1]) + bgn*inv/255)
			buf[o+2] = byte(uint32(p[0]) + br*inv/255)
		}
	}
}

func (r *replica) drawItem(it *item, copyOut bool) {
	w, x := r.w[it], r.x[it]
	if w <= 0 {
		return
	}
	bg := curBg
	if curHover != nil && curHover() == it && it.hl && hoverPanel == r {
		bg = curHoverBg
	}
	img := it.img
	if it.imgAt != nil {
		img = it.imgAt(w, r)
	}
	need := w * panelH * 4
	if cap(r.buf) < need {
		r.buf = make([]byte, need)
	}
	buf := r.buf[:need]
	composite(buf, w, img, it.hold > 0, bg)
	g := panelGCs
	putBGRX(g.c, xproto.Drawable(r.back), g.gc, g.scr.RootDepth, x, 0, w, panelH, buf)
	if copyOut {
		xproto.CopyArea(g.c, xproto.Drawable(r.back), xproto.Drawable(r.win), g.gc, int16(x), 0, int16(x), 0, uint16(w), uint16(panelH))
	}
}

func drawReplicas(it *item) {
	for _, r := range replicas {
		r.drawItem(it, true)
	}
}

func (r *replica) flush() {
	g := panelGCs
	xproto.CopyArea(g.c, xproto.Drawable(r.back), xproto.Drawable(r.win), g.gc, 0, 0, 0, 0, uint16(r.mw), uint16(panelH))
}

func redrawReplicas() {
	g := panelGCs
	for _, r := range replicas {
		xproto.PolyFillRectangle(g.c, xproto.Drawable(r.back), g.bgGC, []xproto.Rectangle{{X: 0, Y: 0, Width: uint16(r.mw), Height: uint16(panelH)}})
		for _, it := range panelItems {
			r.drawItem(it, false)
		}
		r.flush()
	}
}

// rebuildReplicas recreates the replica windows: one per monitor other than the panel's own,
// in "all" mode; none otherwise.
func rebuildReplicas(own monRect) {
	g := panelGCs
	for _, r := range replicas {
		xproto.DestroyWindow(g.c, r.win)
		xproto.FreePixmap(g.c, r.back)
	}
	replicas = nil
	if panelMode != "all" {
		return
	}
	for _, m := range allMons {
		if m.x == own.x && m.y == own.y && m.w == own.w && m.h == own.h {
			continue
		}
		r := &replica{mx: m.x, my: m.y, mw: m.w, mh: m.h}
		r.win, _ = xproto.NewWindowId(g.c)
		xproto.CreateWindow(g.c, g.scr.RootDepth, r.win, g.scr.Root, int16(m.x), int16(m.y+m.h-panelH), uint16(m.w), uint16(panelH), 0,
			xproto.WindowClassInputOutput, g.scr.RootVisual, xproto.CwBackPixel|xproto.CwEventMask,
			[]uint32{curBg, xproto.EventMaskExposure | xproto.EventMaskButtonPress | xproto.EventMaskPointerMotion | xproto.EventMaskLeaveWindow})
		xproto.ChangeProperty(g.c, xproto.PropModeReplace, r.win, atom(g.c, "_NET_WM_WINDOW_TYPE"),
			xproto.AtomAtom, 32, 1, u32(uint32(atom(g.c, "_NET_WM_WINDOW_TYPE_DOCK"))))
		bottom := uint32(rootH - (m.y + m.h) + panelH)
		xproto.ChangeProperty(g.c, xproto.PropModeReplace, r.win, atom(g.c, "_NET_WM_STRUT_PARTIAL"),
			xproto.AtomCardinal, 32, 12, u32(0, 0, 0, bottom, 0, 0, 0, 0, 0, 0, uint32(m.x), uint32(m.x+m.w-1)))
		xproto.ChangeProperty(g.c, xproto.PropModeReplace, r.win, atom(g.c, "_NET_WM_STRUT"),
			xproto.AtomCardinal, 32, 4, u32(0, 0, 0, bottom))
		name := "gopanel"
		xproto.ChangeProperty(g.c, xproto.PropModeReplace, r.win, xproto.AtomWmName,
			xproto.AtomString, 8, uint32(len(name)), []byte(name))
		r.back, _ = xproto.NewPixmapId(g.c)
		xproto.CreatePixmap(g.c, g.scr.RootDepth, r.back, xproto.Drawable(r.win), uint16(m.w), uint16(panelH))
		xproto.MapWindow(g.c, r.win)
		replicas = append(replicas, r)
	}
}

// replicaOf returns the replica an X event belongs to, if any.
func replicaOf(ev xgb.Event) *replica {
	var w xproto.Window
	switch e := ev.(type) {
	case xproto.ExposeEvent:
		w = e.Window
	case xproto.ButtonPressEvent:
		w = e.Event
	case xproto.MotionNotifyEvent:
		w = e.Event
	case xproto.LeaveNotifyEvent:
		w = e.Event
	default:
		return nil
	}
	for _, r := range replicas {
		if r.win == w {
			return r
		}
	}
	return nil
}

// withReplica runs fn with the replica as the current panel: the monitor globals and every
// item's x/width are those of the replica, so the ordinary hit-testing, tooltip, popup and
// menu code works unchanged. Afterwards the primary panel's values are restored.
func withReplica(r *replica, fn func()) {
	om := [4]int{monX, monY, monW, monH}
	type xw struct{ x, w int }
	saved := make(map[*item]xw, len(panelItems))
	for _, it := range panelItems {
		saved[it] = xw{it.x, it.w}
		it.x, it.w = r.x[it], r.w[it]
		if it.ctxW != nil {
			it.ctxW(it.w)
		}
	}
	monX, monY, monW, monH = r.mx, r.my, r.mw, r.mh
	swapped, activeRep = true, r
	fn()
	swapped, activeRep = false, nil
	monX, monY, monW, monH = om[0], om[1], om[2], om[3]
	for _, it := range panelItems {
		if s, ok := saved[it]; ok {
			it.x, it.w = s.x, s.w
		}
		if it.ctxW != nil {
			it.ctxW(it.w)
			if it.resize != nil {
				it.resize(it.w) // re-render the primary's image (the handler may have rendered the replica's)
			}
		}
	}
	if pendingRelayout {
		pendingRelayout = false
		if reflow != nil {
			reflow()
		}
	}
}
