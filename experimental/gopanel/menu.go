package main

import (
	"image"
	"image/color"
	"image/draw"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"gopanel/gfx"
)

// menuItem is one row of a popup menu (the shape dbusmenu delivers).
type menuItem struct {
	id       int32
	label    string
	sep      bool
	disabled bool
	toggle   string // "", "checkmark", "radio"
	checked  bool
	icon     *image.RGBA
	children []*menuItem
}

// menuReq asks the main goroutine to show a menu above the panel at screen x.
type menuReq struct {
	items    []*menuItem
	anchorX  int
	onSelect func(*menuItem)
}

var menuReqs = make(chan menuReq, 4)

const (
	menuRowH   = 24
	menuSepH   = 9
	menuPadX   = 10
	menuIndent = 20 // column for check marks / radio dots / icons
	menuArrowW = 14
)

var (
	menuBg     = color.RGBA{0xfa, 0xfa, 0xf8, 255}
	menuBorder = color.RGBA{0xb4, 0xb2, 0xae, 255}
	menuHilite = color.RGBA{0x35, 0x84, 0xe4, 255}
	menuInk    = color.RGBA{0x1e, 0x1e, 0x1e, 255}
	menuDimInk = color.RGBA{0x90, 0x90, 0x90, 255}
	menuWhite  = color.RGBA{255, 255, 255, 255}
)

type menuLevel struct {
	win     xproto.Window
	items   []*menuItem
	x, y    int
	w, h    int
	hover   int // index or -1
	parent  int // index in the parent level whose submenu this is
	rowTops []int
}

type menuMgr struct {
	c        *xgb.Conn
	scr      *xproto.ScreenInfo
	gc       xproto.Gcontext
	levels   []*menuLevel
	onSelect func(*menuItem)
}

func newMenuMgr(c *xgb.Conn, scr *xproto.ScreenInfo, gc xproto.Gcontext) *menuMgr {
	return &menuMgr{c: c, scr: scr, gc: gc}
}

func (m *menuMgr) active() bool { return len(m.levels) > 0 }

func stripMnemonic(s string) string {
	out := make([]rune, 0, len(s))
	r := []rune(s)
	for i := 0; i < len(r); i++ {
		if r[i] == '_' {
			if i+1 < len(r) && r[i+1] == '_' {
				out = append(out, '_')
				i++
			}
			continue
		}
		out = append(out, r[i])
	}
	return string(out)
}

func spansFor(text string, c color.RGBA) []gfx.Span {
	return []gfx.Span{{Text: text, Scale: 1, Color: c}}
}

// open shows a menu with its bottom edge just above the panel.
func (m *menuMgr) open(req menuReq) {
	m.close()
	m.onSelect = req.onSelect
	lv := m.layout(req.items, 0, 0, -1)
	lv.x = min(max(monX+req.anchorX-lv.w/2, monX), monX+monW-lv.w)
	lv.y = monY + monH - panelH - lv.h - 2
	m.show(lv)
	xproto.GrabPointer(m.c, false, lv.win, xproto.EventMaskButtonPress|xproto.EventMaskButtonRelease|xproto.EventMaskPointerMotion,
		xproto.GrabModeAsync, xproto.GrabModeAsync, xproto.WindowNone, xproto.CursorNone, xproto.TimeCurrentTime)
	xproto.GrabKeyboard(m.c, false, lv.win, xproto.TimeCurrentTime, xproto.GrabModeAsync, xproto.GrabModeAsync)
}

func (m *menuMgr) layout(items []*menuItem, x, y, parent int) *menuLevel {
	lv := &menuLevel{items: items, x: x, y: y, hover: -1, parent: parent}
	w, h := 0, 4
	for _, it := range items {
		lv.rowTops = append(lv.rowTops, h)
		if it.sep {
			h += menuSepH
			continue
		}
		h += menuRowH
		tw := gfx.Measure(spansFor(stripMnemonic(it.label), menuInk), labelPx).W
		if len(it.children) > 0 {
			tw += menuArrowW
		}
		w = max(w, tw)
	}
	lv.w, lv.h = w+2*menuPadX+menuIndent+2, h+4
	lv.w = max(lv.w, 120)
	return lv
}

func (m *menuMgr) show(lv *menuLevel) {
	wid, _ := xproto.NewWindowId(m.c)
	xproto.CreateWindow(m.c, m.scr.RootDepth, wid, m.scr.Root, int16(lv.x), int16(lv.y), uint16(lv.w), uint16(lv.h), 0,
		xproto.WindowClassInputOutput, m.scr.RootVisual,
		xproto.CwOverrideRedirect|xproto.CwEventMask, []uint32{1, xproto.EventMaskExposure})
	xproto.MapWindow(m.c, wid)
	lv.win = wid
	m.levels = append(m.levels, lv)
	m.paint(lv)
}

func (m *menuMgr) paint(lv *menuLevel) {
	img := image.NewRGBA(image.Rect(0, 0, lv.w, lv.h))
	draw.Draw(img, img.Bounds(), image.NewUniform(menuBg), image.Point{}, draw.Src)
	border := image.NewUniform(menuBorder)
	draw.Draw(img, image.Rect(0, 0, lv.w, 1), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, lv.h-1, lv.w, lv.h), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, 0, 1, lv.h), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(lv.w-1, 0, lv.w, lv.h), border, image.Point{}, draw.Src)
	for i, it := range lv.items {
		top := lv.rowTops[i] + 2
		if it.sep {
			draw.Draw(img, image.Rect(4, top+menuSepH/2, lv.w-4, top+menuSepH/2+1), border, image.Point{}, draw.Src)
			continue
		}
		ink := menuInk
		if it.disabled {
			ink = menuDimInk
		}
		if i == lv.hover && !it.disabled {
			draw.Draw(img, image.Rect(2, top, lv.w-2, top+menuRowH), image.NewUniform(menuHilite), image.Point{}, draw.Src)
			ink = menuWhite
		}
		sp := spansFor(stripMnemonic(it.label), ink)
		tm := gfx.Measure(sp, labelPx)
		gfx.Draw(img, menuPadX+menuIndent, top+(menuRowH-tm.H)/2, sp, labelPx)
		mark := ""
		switch {
		case it.toggle == "checkmark" && it.checked:
			mark = "✓"
		case it.toggle == "radio" && it.checked:
			mark = "●"
		case len(it.children) > 0:
			mark = ""
		}
		if it.icon != nil {
			ib := it.icon.Bounds()
			draw.Draw(img, image.Rect(menuPadX-2, top+(menuRowH-ib.Dy())/2, menuPadX-2+ib.Dx(), top+(menuRowH-ib.Dy())/2+ib.Dy()), it.icon, image.Point{}, draw.Over)
		} else if mark != "" {
			gfx.Draw(img, menuPadX-2, top+(menuRowH-tm.H)/2, spansFor(mark, ink), labelPx)
		}
		if len(it.children) > 0 {
			gfx.Draw(img, lv.w-menuPadX-menuArrowW+4, top+(menuRowH-tm.H)/2, spansFor("▸", ink), labelPx)
		}
	}
	buf := make([]byte, lv.w*lv.h*4)
	for i := 0; i < lv.w*lv.h; i++ {
		p := img.Pix[i*4:]
		buf[i*4], buf[i*4+1], buf[i*4+2] = p[2], p[1], p[0]
	}
	putBGRX(m.c, xproto.Drawable(lv.win), m.gc, m.scr.RootDepth, 0, 0, lv.w, lv.h, buf)
}

func (m *menuMgr) close() {
	if !m.active() {
		return
	}
	xproto.UngrabPointer(m.c, xproto.TimeCurrentTime)
	xproto.UngrabKeyboard(m.c, xproto.TimeCurrentTime)
	for _, lv := range m.levels {
		xproto.DestroyWindow(m.c, lv.win)
	}
	m.levels = nil
}

func (m *menuMgr) closeAbove(n int) { // keep the first n levels
	for len(m.levels) > n {
		lv := m.levels[len(m.levels)-1]
		xproto.DestroyWindow(m.c, lv.win)
		m.levels = m.levels[:len(m.levels)-1]
	}
}

// rowAt returns the level and row index under a root-window point, topmost level first.
func (m *menuMgr) rowAt(rx, ry int) (int, int) {
	for li := len(m.levels) - 1; li >= 0; li-- {
		lv := m.levels[li]
		if rx < lv.x || rx >= lv.x+lv.w || ry < lv.y || ry >= lv.y+lv.h {
			continue
		}
		for i, it := range lv.items {
			top := lv.y + lv.rowTops[i] + 2
			h := menuRowH
			if it.sep {
				h = menuSepH
			}
			if ry >= top && ry < top+h {
				return li, i
			}
		}
		return li, -1
	}
	return -1, -1
}

// setHover highlights row i of level li and opens or closes submenus accordingly.
func (m *menuMgr) setHover(li, i int) {
	lv := m.levels[li]
	if lv.hover != i {
		lv.hover = i
		m.paint(lv)
	}
	if li+1 < len(m.levels) && m.levels[li+1].parent == i {
		return // its submenu is already open
	}
	m.closeAbove(li + 1)
	if i >= 0 && !lv.items[i].disabled && len(lv.items[i].children) > 0 {
		top := lv.y + lv.rowTops[i] + 2
		sub := m.layout(lv.items[i].children, 0, 0, i)
		sub.x, sub.y = lv.x+lv.w-3, top-2
		if sub.x+sub.w > monX+monW {
			sub.x = lv.x - sub.w + 3
		}
		sub.y = min(sub.y, monY+monH-panelH-sub.h)
		m.show(sub)
	}
}

func (m *menuMgr) activate(it *menuItem) {
	if it == nil || it.sep || it.disabled || len(it.children) > 0 {
		return
	}
	cb := m.onSelect
	m.close()
	if cb != nil {
		cb(it)
	}
}

// handle consumes input while a menu is open; it returns true if the event was ours.
func (m *menuMgr) handle(ev xgb.Event) bool {
	if !m.active() {
		return false
	}
	switch e := ev.(type) {
	case xproto.ExposeEvent:
		for _, lv := range m.levels {
			if lv.win == e.Window && e.Count == 0 {
				m.paint(lv)
				return true
			}
		}
	case xproto.MotionNotifyEvent:
		if li, i := m.rowAt(int(e.RootX), int(e.RootY)); li >= 0 {
			m.setHover(li, i)
		}
		return true
	case xproto.ButtonPressEvent:
		li, i := m.rowAt(int(e.RootX), int(e.RootY))
		if li < 0 {
			m.close() // click outside
			return true
		}
		if i >= 0 && e.Detail == 1 {
			m.activate(m.levels[li].items[i])
		}
		return true
	case xproto.ButtonReleaseEvent:
		return true
	case xproto.KeyPressEvent:
		m.key(e.Detail)
		return true
	}
	return false
}

// key handles evdev keycodes: Esc, Up, Down, Left, Right, Return/KP Enter.
func (m *menuMgr) key(code xproto.Keycode) {
	li := len(m.levels) - 1
	lv := m.levels[li]
	step := func(d int) {
		n := len(lv.items)
		i := lv.hover
		for k := 0; k < n; k++ {
			i = (i + d + n) % n
			if !lv.items[i].sep && !lv.items[i].disabled {
				m.setHover(li, i)
				return
			}
		}
	}
	switch code {
	case 9: // Esc
		m.close()
	case 111: // Up
		if lv.hover < 0 {
			lv.hover = 0
		}
		step(-1)
	case 116: // Down
		step(1)
	case 114: // Right: open submenu
		if lv.hover >= 0 && len(lv.items[lv.hover].children) > 0 {
			m.setHover(li, lv.hover)
			if li+1 < len(m.levels) {
				sub := m.levels[li+1]
				for i, it := range sub.items {
					if !it.sep && !it.disabled {
						m.setHover(li+1, i)
						break
					}
				}
			}
		}
	case 113: // Left: close submenu
		if li > 0 {
			m.closeAbove(li)
		}
	case 36, 104: // Return, KP Enter
		if lv.hover >= 0 {
			m.activate(lv.items[lv.hover])
		}
	}
}
