package main

import (
	"image"
	"image/color"
	"image/draw"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"gopanel/gfx"
)

// popup is a small card window above the panel (calendar, volume slider): an
// override-redirect window with pointer and keyboard grabs, so a click outside or
// Esc dismisses it. One at a time, driven from the main goroutine.
type popup struct {
	win     xproto.Window
	x, y    int
	w, h    int
	paint   func(img *image.RGBA)     // draw the content on the pre-filled card
	press   func(x, y, btn int)       // local coordinates
	motion  func(x, y int, held bool) // pointer moved; held = button 1 down
	release func()                    // button released
	key     func(code xproto.Keycode) // evdev code + 8
	closed  func()                    // called when the popup goes away
}

var (
	curPop *popup
	xscr   *xproto.ScreenInfo
	xgc    xproto.Gcontext
)

// openPopup shows p centred above anchorX (screen coordinates), replacing any popup.
func openPopup(p *popup, anchorX int) {
	closePopup()
	p.x = min(max(anchorX-p.w/2, 0), int(xscr.WidthInPixels)-p.w)
	p.y = int(xscr.HeightInPixels) - panelH - p.h - 2
	p.win, _ = xproto.NewWindowId(xc)
	xproto.CreateWindow(xc, xscr.RootDepth, p.win, xroot, int16(p.x), int16(p.y), uint16(p.w), uint16(p.h), 0,
		xproto.WindowClassInputOutput, xscr.RootVisual,
		xproto.CwOverrideRedirect|xproto.CwEventMask, []uint32{1, xproto.EventMaskExposure})
	xproto.MapWindow(xc, p.win)
	curPop = p
	p.repaint()
	xproto.GrabPointer(xc, false, p.win, xproto.EventMaskButtonPress|xproto.EventMaskButtonRelease|xproto.EventMaskPointerMotion,
		xproto.GrabModeAsync, xproto.GrabModeAsync, xproto.WindowNone, xproto.CursorNone, xproto.TimeCurrentTime)
	xproto.GrabKeyboard(xc, false, p.win, xproto.TimeCurrentTime, xproto.GrabModeAsync, xproto.GrabModeAsync)
}

func closePopup() {
	p := curPop
	if p == nil {
		return
	}
	curPop = nil
	xproto.UngrabPointer(xc, xproto.TimeCurrentTime)
	xproto.UngrabKeyboard(xc, xproto.TimeCurrentTime)
	xproto.DestroyWindow(xc, p.win)
	if p.closed != nil {
		p.closed()
	}
}

func (p *popup) repaint() {
	img := image.NewRGBA(image.Rect(0, 0, p.w, p.h))
	draw.Draw(img, img.Bounds(), image.NewUniform(menuBg), image.Point{}, draw.Src)
	b := image.NewUniform(menuBorder)
	draw.Draw(img, image.Rect(0, 0, p.w, 1), b, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, p.h-1, p.w, p.h), b, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, 0, 1, p.h), b, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(p.w-1, 0, p.w, p.h), b, image.Point{}, draw.Src)
	p.paint(img)
	buf := make([]byte, p.w*p.h*4)
	for i := 0; i < p.w*p.h; i++ {
		px := img.Pix[i*4:]
		buf[i*4], buf[i*4+1], buf[i*4+2] = px[2], px[1], px[0]
	}
	putBGRX(xc, xproto.Drawable(p.win), xgc, xscr.RootDepth, 0, 0, p.w, p.h, buf)
}

// popupHandle consumes events while a popup is open.
func popupHandle(ev xgb.Event) bool {
	p := curPop
	if p == nil {
		return false
	}
	switch e := ev.(type) {
	case xproto.ExposeEvent:
		if e.Window == p.win && e.Count == 0 {
			p.repaint()
			return true
		}
	case xproto.MotionNotifyEvent:
		if p.motion != nil {
			p.motion(int(e.RootX)-p.x, int(e.RootY)-p.y, e.State&xproto.ButtonMask1 != 0)
		}
		return true
	case xproto.ButtonPressEvent:
		x, y := int(e.RootX)-p.x, int(e.RootY)-p.y
		if x < 0 || y < 0 || x >= p.w || y >= p.h {
			closePopup() // click outside
			return true
		}
		if p.press != nil {
			p.press(x, y, int(e.Detail))
		}
		return true
	case xproto.ButtonReleaseEvent:
		if p.release != nil {
			p.release()
		}
		return true
	case xproto.KeyPressEvent:
		if e.Detail == 9 { // Esc
			closePopup()
		} else if p.key != nil {
			p.key(e.Detail)
		}
		return true
	}
	return false
}

func textW(s string) int { return gfx.Measure(spansFor(s, menuInk), labelPx).W }

func fillRect(img *image.RGBA, r image.Rectangle, c color.RGBA) {
	draw.Draw(img, r, image.NewUniform(c), image.Point{}, draw.Src)
}
