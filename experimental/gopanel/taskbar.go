package main

import (
	"encoding/binary"
	"image"
	"image/color"
	"image/draw"
	"strings"

	"github.com/jezek/xgb/xproto"
	"gopanel/gfx"
)

// Taskbar: one button per managed window (EWMH). All of it runs on the main goroutine,
// driven by PropertyNotify events, so it needs no locking.

const (
	tbIcon      = 20
	tbMaxButton = 200
	tbGap       = 3
	tbPadX      = 6
)

var (
	tbBorder = color.RGBA{0xcf, 0xcd, 0xc9, 255}
	tbNormal = color.RGBA{0xed, 0xec, 0xea, 255}
	tbHover  = color.RGBA{0xe2, 0xe0, 0xdd, 255}
	tbActive = color.RGBA{0xd2, 0xd0, 0xcc, 255}
	tbAttn   = color.RGBA{0xf5, 0xc2, 0x4a, 255}
)

var atoms = map[string]xproto.Atom{}

// A returns the (cached) atom for name.
func A(name string) xproto.Atom {
	if a, ok := atoms[name]; ok {
		return a
	}
	r, err := xproto.InternAtom(xc, false, uint16(len(name)), name).Reply()
	if err != nil {
		return 0
	}
	atoms[name] = r.Atom
	return r.Atom
}

func getProp(win xproto.Window, prop string, max uint32) *xproto.GetPropertyReply {
	r, err := xproto.GetProperty(xc, false, win, A(prop), xproto.GetPropertyTypeAny, 0, max).Reply()
	if err != nil || r == nil || r.ValueLen == 0 {
		return nil
	}
	return r
}

func propU32s(win xproto.Window, prop string, max uint32) []uint32 {
	r := getProp(win, prop, max)
	if r == nil || r.Format != 32 {
		return nil
	}
	out := make([]uint32, len(r.Value)/4)
	for i := range out {
		out[i] = binary.LittleEndian.Uint32(r.Value[i*4:])
	}
	return out
}

func propString(win xproto.Window, prop string) string {
	r := getProp(win, prop, 1024)
	if r == nil {
		return ""
	}
	return strings.TrimRight(string(r.Value), "\x00")
}

func sendClientMessage(win xproto.Window, msg string, data [5]uint32) {
	ev := xproto.ClientMessageEvent{Format: 32, Window: win, Type: A(msg),
		Data: xproto.ClientMessageDataUnionData32New(data[:])}
	xproto.SendEvent(xc, false, xroot, xproto.EventMaskSubstructureRedirect|xproto.EventMaskSubstructureNotify, string(ev.Bytes()))
}

type twin struct {
	id        xproto.Window
	title     string
	class     string
	icon      *image.RGBA
	minimized bool
	maximized bool
	attention bool
	desktop   uint32
}

type taskbar struct {
	lastN   int
	it      *item
	wins    []*twin // client list order
	active  xproto.Window
	desktop uint32
	hover   int
	w       int
}

func newTaskbarItem() *item {
	it := newItem("taskbar")
	it.expand = true
	tb := &taskbar{it: it, hover: -1}
	taskbars = append(taskbars, tb)
	it.click = tb.onClick
	it.tipAt = tb.tipAt
	it.hl = false
	it.want = func() int { return len(tb.shown()) * (tbMaxButton + tbGap) }
	it.resize = func(w int) { tb.w = w; tb.render() }
	it.motion = func(x int) {
		if i := tb.indexAt(x); i != tb.hover {
			tb.hover = i
			tb.render()
		}
	}
	it.hover = func(on bool) {
		if !on && tb.hover != -1 {
			tb.hover = -1
			tb.render()
		}
	}
	xproto.ChangeWindowAttributes(xc, xroot, xproto.CwEventMask, []uint32{xproto.EventMaskPropertyChange})
	tb.scan()
	return it
}

func (tb *taskbar) close() {}

func (tb *taskbar) skipped(w xproto.Window) bool {
	for _, t := range propU32s(w, "_NET_WM_WINDOW_TYPE", 32) {
		switch xproto.Atom(t) {
		case A("_NET_WM_WINDOW_TYPE_DOCK"), A("_NET_WM_WINDOW_TYPE_DESKTOP"), A("_NET_WM_WINDOW_TYPE_SPLASH"),
			A("_NET_WM_WINDOW_TYPE_TOOLBAR"), A("_NET_WM_WINDOW_TYPE_MENU"), A("_NET_WM_WINDOW_TYPE_NOTIFICATION"),
			A("_NET_WM_WINDOW_TYPE_DROPDOWN_MENU"), A("_NET_WM_WINDOW_TYPE_POPUP_MENU"), A("_NET_WM_WINDOW_TYPE_TOOLTIP"):
			return true
		}
	}
	for _, s := range propU32s(w, "_NET_WM_STATE", 32) {
		if xproto.Atom(s) == A("_NET_WM_STATE_SKIP_TASKBAR") {
			return true
		}
	}
	return false
}

// scan rebuilds the window list from _NET_CLIENT_LIST, keeping entries we already know.
func (tb *taskbar) scan() {
	if d := propU32s(xroot, "_NET_CURRENT_DESKTOP", 1); len(d) == 1 {
		tb.desktop = d[0]
	}
	if a := propU32s(xroot, "_NET_ACTIVE_WINDOW", 1); len(a) == 1 {
		tb.active = xproto.Window(a[0])
	} else {
		tb.active = 0
	}
	known := map[xproto.Window]*twin{}
	for _, w := range tb.wins {
		known[w.id] = w
	}
	tb.wins = nil
	for _, id := range propU32s(xroot, "_NET_CLIENT_LIST", 512) {
		w := xproto.Window(id)
		if tw := known[w]; tw != nil {
			tb.wins = append(tb.wins, tw)
			continue
		}
		if tb.skipped(w) {
			continue
		}
		xproto.ChangeWindowAttributes(xc, w, xproto.CwEventMask, []uint32{xproto.EventMaskPropertyChange})
		tw := &twin{id: w}
		tb.refresh(tw)
		tb.wins = append(tb.wins, tw)
	}
	tb.render()
}

func (tb *taskbar) refresh(tw *twin) {
	tw.title = propString(tw.id, "_NET_WM_NAME")
	if tw.title == "" {
		tw.title = propString(tw.id, "WM_NAME")
	}
	tw.minimized, tw.maximized, tw.attention = false, false, false
	horz, vert := false, false
	for _, s := range propU32s(tw.id, "_NET_WM_STATE", 32) {
		switch xproto.Atom(s) {
		case A("_NET_WM_STATE_HIDDEN"):
			tw.minimized = true
		case A("_NET_WM_STATE_DEMANDS_ATTENTION"):
			tw.attention = true
		case A("_NET_WM_STATE_MAXIMIZED_HORZ"):
			horz = true
		case A("_NET_WM_STATE_MAXIMIZED_VERT"):
			vert = true
		}
	}
	tw.maximized = horz && vert
	tw.desktop = 0xffffffff
	if d := propU32s(tw.id, "_NET_WM_DESKTOP", 1); len(d) == 1 {
		tw.desktop = d[0]
	}
	if tw.class == "" {
		if r := getProp(tw.id, "WM_CLASS", 256); r != nil {
			parts := strings.Split(strings.TrimRight(string(r.Value), "\x00"), "\x00")
			tw.class = parts[len(parts)-1]
		}
	}
	tw.icon = tb.windowIcon(tw)
}

func (tb *taskbar) windowIcon(tw *twin) *image.RGBA {
	if v := propU32s(tw.id, "_NET_WM_ICON", 1<<20); len(v) > 2 {
		var best *pixmap
		for i := 0; i+2 < len(v); {
			w, h := int(v[i]), int(v[i+1])
			if w <= 0 || h <= 0 || i+2+w*h > len(v) {
				break
			}
			if best == nil || (best.W < tbIcon && int32(w) > best.W) || (int32(w) >= tbIcon && int32(w) < best.W) {
				data := make([]byte, w*h*4)
				for p := 0; p < w*h; p++ { // ARGB32 native-endian -> big-endian A,R,G,B bytes
					binary.BigEndian.PutUint32(data[p*4:], v[i+2+p])
				}
				best = &pixmap{W: int32(w), H: int32(h), Data: data}
			}
			i += 2 + w*h
		}
		if best != nil {
			return fitIconSized(argbToRGBA(*best), tbIcon)
		}
	}
	for _, name := range []string{strings.ToLower(tw.class), "application-x-executable"} {
		if name == "" {
			continue
		}
		if findIcon(name) != "" {
			return loadIconSized(name, tbIcon)
		}
	}
	return nil
}

func (tb *taskbar) onProperty(e xproto.PropertyNotifyEvent) {
	name := ""
	if r, err := xproto.GetAtomName(xc, e.Atom).Reply(); err == nil {
		name = r.Name
	}
	if e.Window == xroot {
		switch name {
		case "_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW", "_NET_CURRENT_DESKTOP":
			tb.scan()
		}
		return
	}
	for _, tw := range tb.wins {
		if tw.id == e.Window {
			switch name {
			case "_NET_WM_NAME", "WM_NAME", "_NET_WM_STATE", "_NET_WM_ICON", "WM_HINTS", "_NET_WM_DESKTOP":
				tb.refresh(tw)
				tb.render()
			}
			return
		}
	}
}

func (tb *taskbar) shown() []*twin {
	var out []*twin
	for _, w := range tb.wins {
		if w.desktop == 0xffffffff || w.desktop == tb.desktop {
			out = append(out, w)
		}
	}
	return out
}

func (tb *taskbar) buttonWidth(n int) int {
	if n == 0 {
		return 0
	}
	return min(tbMaxButton, (tb.w-(n-1)*tbGap)/n)
}

func (tb *taskbar) indexAt(x int) int {
	vis := tb.shown()
	bw := tb.buttonWidth(len(vis))
	if bw <= 0 {
		return -1
	}
	i := x / (bw + tbGap)
	if i < len(vis) && x-i*(bw+tbGap) < bw {
		return i
	}
	return -1
}

func (tb *taskbar) tipAt(x int) string {
	vis := tb.shown()
	if i := tb.indexAt(x); i >= 0 {
		return strings.NewReplacer("&", "&amp;", "<", "&lt;").Replace(vis[i].title)
	}
	return ""
}

func ellipsize(text string, maxW int, ink color.RGBA) string {
	r := []rune(text)
	for len(r) > 0 {
		s := string(r)
		if len(r) < len([]rune(text)) {
			s += "…"
		}
		if gfx.Measure(spansFor(s, ink), labelPx).W <= maxW {
			return s
		}
		r = r[:len(r)-1]
	}
	return ""
}

func (tb *taskbar) render() {
	if n := len(tb.shown()); n != tb.lastN { // the width the buttons want changed: re-share the free space
		tb.lastN = n
		if reflow != nil {
			reflow()
		}
	}
	if tb.w <= 0 {
		return
	}
	vis := tb.shown()
	img := image.NewRGBA(image.Rect(0, 0, tb.w, panelH))
	bw := tb.buttonWidth(len(vis))
	bh := panelH - 6
	for i, w := range vis {
		x0, y0 := i*(bw+tbGap), 3
		fill := tbNormal
		switch {
		case w.id == tb.active && !w.minimized:
			fill = tbActive
		case i == tb.hover:
			fill = tbHover
		}
		border := tbBorder
		if w.attention {
			border = tbAttn
		}
		fillRRect(img, x0, y0, bw, bh, 3, fill, border)
		tx := x0 + tbPadX
		if w.icon != nil {
			ib := w.icon.Bounds()
			draw.Draw(img, image.Rect(tx, y0+(bh-ib.Dy())/2, tx+ib.Dx(), y0+(bh-ib.Dy())/2+ib.Dy()), w.icon, image.Point{}, draw.Over)
			tx += ib.Dx() + 5
		}
		ink := color.RGBA{0, 0, 0, 255}
		if w.minimized {
			ink = color.RGBA{0x70, 0x70, 0x70, 255}
		}
		title := w.title
		if w.minimized {
			title = "[" + title + "]"
		}
		if avail := x0 + bw - tbPadX - tx; avail > 8 {
			label := ellipsize(title, avail, ink)
			sp := spansFor(label, ink)
			m := gfx.Measure(sp, labelPx)
			gfx.Draw(img, tx, y0+(bh-m.H)/2, sp, labelPx)
		}
	}
	tb.it.img = img
	if drawItem != nil && tb.it.w > 0 {
		drawItem(tb.it)
	}
}

// fillRRect draws an anti-aliased rounded rectangle with a 1px border.
func fillRRect(img *image.RGBA, x, y, w, h int, r float64, fill, border color.RGBA) {
	for py := y; py < y+h; py++ {
		for px := x; px < x+w; px++ {
			if px < 0 || py < 0 || px >= img.Bounds().Dx() || py >= img.Bounds().Dy() {
				continue
			}
			d := rrDist(float64(px)+.5, float64(py)+.5, float64(x), float64(y), float64(w), float64(h), r)
			cov := clamp(0.5-d, 0, 1)
			if cov <= 0 {
				continue
			}
			c := fill
			if d > -1 {
				c = border
			}
			o := py*img.Stride + px*4
			a := uint32(float64(c.A) * cov)
			img.Pix[o], img.Pix[o+1], img.Pix[o+2], img.Pix[o+3] =
				uint8(uint32(c.R)*a/255), uint8(uint32(c.G)*a/255), uint8(uint32(c.B)*a/255), uint8(a)
		}
	}
}

func rrDist(px, py, x, y, w, h, r float64) float64 {
	dx := abs(px-(x+w/2)) - (w/2 - r)
	dy := abs(py-(y+h/2)) - (h/2 - r)
	return hypot(maxf(dx, 0), maxf(dy, 0)) + minf(maxf(dx, dy), 0) - r
}

func (tb *taskbar) activate(tw *twin) {
	sendClientMessage(tw.id, "_NET_ACTIVE_WINDOW", [5]uint32{2, 0, 0, 0, 0})
}

func (tb *taskbar) iconify(tw *twin) {
	sendClientMessage(tw.id, "WM_CHANGE_STATE", [5]uint32{3, 0, 0, 0, 0})
}

func (tb *taskbar) onClick(x, y, btn int) {
	vis := tb.shown()
	if (btn == 4 || btn == 5) && len(vis) > 0 { // wheel cycles through the windows
		cur, d := -1, 1
		for i, w := range vis {
			if w.id == tb.active {
				cur = i
			}
		}
		if btn == 4 {
			d = -1
		}
		next := (cur + d + len(vis)) % len(vis)
		if cur < 0 && d < 0 {
			next = len(vis) - 1
		}
		tb.activate(vis[next])
		return
	}
	i := tb.indexAt(x)
	if i < 0 {
		return
	}
	tw := vis[i]
	switch btn {
	case 1:
		if tw.id == tb.active && !tw.minimized {
			tb.iconify(tw)
		} else {
			tb.activate(tw)
		}
	case 2:
		sendClientMessage(tw.id, "_NET_CLOSE_WINDOW", [5]uint32{0, 2, 0, 0, 0})
	case 3:
		min := &menuItem{id: 1, label: tr("Minimize")}
		if tw.minimized {
			min.label = tr("Restore")
		}
		max := &menuItem{id: 2, label: tr("Maximize")}
		if tw.maximized {
			max.label = tr("Unmaximize")
		}
		menuReqs <- menuReq{
			items:   []*menuItem{min, max, {sep: true}, {id: 3, label: tr("Close")}},
			anchorX: tb.it.x + i*(tb.buttonWidth(len(vis))+tbGap) + tb.buttonWidth(len(vis))/2,
			onSelect: func(mi *menuItem) {
				switch mi.id {
				case 1:
					if tw.minimized {
						tb.activate(tw)
					} else {
						tb.iconify(tw)
					}
				case 2:
					op := uint32(1) // _NET_WM_STATE_ADD
					if tw.maximized {
						op = 0
					}
					sendClientMessage(tw.id, "_NET_WM_STATE", [5]uint32{op, uint32(A("_NET_WM_STATE_MAXIMIZED_HORZ")), uint32(A("_NET_WM_STATE_MAXIMIZED_VERT")), 2, 0})
				case 3:
					sendClientMessage(tw.id, "_NET_CLOSE_WINDOW", [5]uint32{0, 2, 0, 0, 0})
				}
			},
		}
	}
}
