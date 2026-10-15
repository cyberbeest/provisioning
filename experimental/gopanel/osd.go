package main

import (
	"image"
	"image/color"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
)

// cmdOSD shows the outcome of a Butler command ("Display brightness now 60%") in the middle of
// the screen, with a level bar when the command has one. A new message replaces the old one.
type osd struct {
	c     *xgb.Conn
	scr   *xproto.ScreenInfo
	gc    xproto.Gcontext
	win   xproto.Window
	img   *image.RGBA
	shown bool
	gen   int // bumped per message; a hide timer only acts on the message it belongs to
}

const osdHold = 1500 * time.Millisecond

func newOSD(c *xgb.Conn, scr *xproto.ScreenInfo, gc xproto.Gcontext) *osd {
	return &osd{c: c, scr: scr, gc: gc}
}

func renderOSD(text string, level, levelMax int) *image.RGBA {
	if levelMax <= 0 {
		levelMax = 100
	}
	const px, padX, padY, barH, barGap = 22.0, 28, 18, 8, 12
	w := textWidth(text, px)*115/100 + 8 // the measure is for regular weight, bold is wider
	if level >= 0 {
		w = max(w, 260)
	}
	w += 2 * padX
	h := 2*padY + int(px) + 8
	if level >= 0 {
		h += barGap + barH
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	rect(img, img.Bounds(), color.RGBA{0x2a, 0x2f, 0x38, 255})
	frame(img, img.Bounds(), color.RGBA{0x70, 0x70, 0x70, 255})
	textAt(img, padX, padY, text, color.RGBA{0xf2, 0xf2, 0xf2, 255}, true, px, 0)
	if level >= 0 {
		y := padY + int(px) + 8 + barGap
		track := image.Rect(padX, y, w-padX, y+barH)
		rect(img, track, color.RGBA{0x50, 0x55, 0x60, 255})
		fill := track
		fill.Max.X = track.Min.X + track.Dx()*min(level, levelMax)/levelMax
		rect(img, fill, whFocus)
	}
	return img
}

// show displays the message centred on the working area; hide comes back through out.
func (o *osd) show(text string, level, levelMax int, out chan<- butlerResult) {
	if text == "" {
		return
	}
	o.hide()
	img := renderOSD(text, level, levelMax)
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	x := monX + (monW-w)/2
	y := monY + (monH-panelH-h)/2
	wid, _ := xproto.NewWindowId(o.c)
	xproto.CreateWindow(o.c, o.scr.RootDepth, wid, o.scr.Root, int16(x), int16(y), uint16(w), uint16(h), 0,
		xproto.WindowClassInputOutput, o.scr.RootVisual,
		xproto.CwOverrideRedirect|xproto.CwEventMask, []uint32{1, xproto.EventMaskExposure})
	xproto.MapWindow(o.c, wid)
	o.win, o.img, o.shown = wid, img, true
	o.gen++
	o.paint()
	gen := o.gen
	time.AfterFunc(osdHold, func() {
		select {
		case out <- butlerResult{osdHide: true, gen: gen}:
		default:
		}
	})
}

func (o *osd) paint() {
	if !o.shown {
		return
	}
	b := o.img.Bounds()
	w, h := b.Dx(), b.Dy()
	buf := make([]byte, w*h*4)
	for i := 0; i < w*h; i++ {
		p := o.img.Pix[i*4:]
		buf[i*4], buf[i*4+1], buf[i*4+2] = p[2], p[1], p[0]
	}
	putBGRX(o.c, xproto.Drawable(o.win), o.gc, o.scr.RootDepth, 0, 0, w, h, buf)
}

func (o *osd) hide() {
	if o.shown {
		xproto.DestroyWindow(o.c, o.win)
		o.shown = false
	}
}

// hideIf hides the message the timer was started for, not a newer one.
func (o *osd) hideIf(gen int) {
	if gen == o.gen {
		o.hide()
	}
}
