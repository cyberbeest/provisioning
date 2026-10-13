package main

import (
	"image"
	"image/color"
	"image/draw"
	"strings"

	"gopanel/gfx"
)

const (
	labelPx   = 13.0 // Sans 10 at 96 dpi
	labelEdge = 4
)

var inkBlack = color.RGBA{0, 0, 0, 255}

// renderLabel draws one line of Pango-lite markup; nil for empty text.
func renderLabel(markup string) *image.RGBA {
	if strings.TrimSpace(markup) == "" {
		return nil
	}
	spans := gfx.ParseMarkup(markup, inkBlack)
	m := gfx.Measure(spans, labelPx)
	if m.W == 0 || m.H == 0 {
		return nil
	}
	img := image.NewRGBA(image.Rect(0, 0, m.W, m.H))
	gfx.Draw(img, 0, 0, spans, labelPx)
	return img
}

// iconText composes an icon and an optional text label side by side, vertically centred.
func iconText(icon *image.RGBA, markup string, gap int) *image.RGBA {
	txt := renderLabel(markup)
	iw, ih, tw, th := 0, 0, 0, 0
	if icon != nil {
		iw, ih = icon.Bounds().Dx(), icon.Bounds().Dy()
	}
	if txt != nil {
		tw, th = txt.Bounds().Dx(), txt.Bounds().Dy()
	}
	w, h := iw+tw, max(ih, th, 1)
	if iw > 0 && tw > 0 {
		w += gap
	}
	if w == 0 {
		return nil
	}
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	if icon != nil {
		draw.Draw(img, image.Rect(0, (h-ih)/2, iw, (h-ih)/2+ih), icon, image.Point{}, draw.Over)
	}
	if txt != nil {
		x := iw
		if iw > 0 {
			x += gap
		}
		draw.Draw(img, image.Rect(x, (h-th)/2, x+tw, (h-th)/2+th), txt, image.Point{}, draw.Over)
	}
	return img
}
