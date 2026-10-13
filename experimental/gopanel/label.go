package main

import (
	"image"
	"image/color"
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
