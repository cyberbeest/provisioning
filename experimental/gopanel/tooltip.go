package main

import (
	"image"
	"image/color"
	"image/draw"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"gopanel/gfx"
)

// tooltip is a transient override-redirect window drawn with gfx text.
type tooltip struct {
	c     *xgb.Conn
	scr   *xproto.ScreenInfo
	gc    xproto.Gcontext
	win   xproto.Window
	img   *image.RGBA
	shown bool
	forIt *item
	text  string
}

func newTooltip(c *xgb.Conn, scr *xproto.ScreenInfo, gc xproto.Gcontext) *tooltip {
	return &tooltip{c: c, scr: scr, gc: gc}
}

// render builds the tooltip bitmap: dark box, light text, 1px border.
func renderTip(markup string) *image.RGBA {
	fg := color.RGBA{0xf2, 0xf2, 0xf2, 255}
	lines := gfx.SplitSpans(gfx.ParseMarkup(markup, fg))
	const px, padX, padY = 13.0, 8, 5
	type ln struct {
		sp []gfx.Span
		m  gfx.Metrics
	}
	var ls []ln
	w, h := 0, 0
	for _, sp := range lines {
		m := gfx.Measure(sp, px)
		if m.H == 0 {
			m.H = int(px) + 2 // blank line
		}
		ls = append(ls, ln{sp, m})
		h += m.H + 1
		if m.W > w {
			w = m.W
		}
	}
	img := image.NewRGBA(image.Rect(0, 0, w+2*padX, h+2*padY))
	draw.Draw(img, img.Bounds(), image.NewUniform(color.RGBA{0x2b, 0x2b, 0x2b, 255}), image.Point{}, draw.Src)
	border := image.NewUniform(color.RGBA{0x70, 0x70, 0x70, 255})
	b := img.Bounds()
	draw.Draw(img, image.Rect(0, 0, b.Dx(), 1), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, b.Dy()-1, b.Dx(), b.Dy()), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(0, 0, 1, b.Dy()), border, image.Point{}, draw.Src)
	draw.Draw(img, image.Rect(b.Dx()-1, 0, b.Dx(), b.Dy()), border, image.Point{}, draw.Src)
	y := padY
	for _, l := range ls {
		gfx.Draw(img, padX, y, l.sp, px)
		y += l.m.H + 1
	}
	return img
}

// show displays text above the panel, centred on anchorX (screen coordinates).
func (t *tooltip) show(it *item, markup string, anchorX int) {
	t.hide()
	img := renderTip(markup)
	w, h := img.Bounds().Dx(), img.Bounds().Dy()
	x := monX + anchorX - w/2
	if x+w > monX+monW {
		x = monX + monW - w
	}
	if x < monX {
		x = monX
	}
	y := monY + monH - panelH - h - 4
	wid, _ := xproto.NewWindowId(t.c)
	xproto.CreateWindow(t.c, t.scr.RootDepth, wid, t.scr.Root, int16(x), int16(y), uint16(w), uint16(h), 0,
		xproto.WindowClassInputOutput, t.scr.RootVisual,
		xproto.CwOverrideRedirect|xproto.CwEventMask, []uint32{1, xproto.EventMaskExposure})
	xproto.MapWindow(t.c, wid)
	t.win, t.img, t.shown, t.forIt, t.text = wid, img, true, it, markup
	t.paint()
}

// paint converts the RGBA bitmap to the server's BGRX format and uploads it.
func (t *tooltip) paint() {
	if !t.shown {
		return
	}
	b := t.img.Bounds()
	w, h := b.Dx(), b.Dy()
	buf := make([]byte, w*h*4)
	for i := 0; i < w*h; i++ {
		p := t.img.Pix[i*4:]
		buf[i*4], buf[i*4+1], buf[i*4+2] = p[2], p[1], p[0]
	}
	putBGRX(t.c, xproto.Drawable(t.win), t.gc, t.scr.RootDepth, 0, 0, w, h, buf)
}

func (t *tooltip) hide() {
	if t.shown {
		xproto.DestroyWindow(t.c, t.win)
		t.shown, t.forIt = false, nil
	}
}
