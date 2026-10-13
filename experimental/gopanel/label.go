package main

import (
	"image"
	"image/color"
	"image/draw"
	"os"
	"path/filepath"
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

// stackedPx is the font size of a two-line label (the panel is 35px high).
const stackedPx = 11.5

// renderStacked draws plain text on two balanced lines ("8.2W -2:12" -> "8.2W" over
// "-2:12", "🔒 Never ⏻ Never" -> "🔒 Never" over "⏻ Never") to save panel width. Text with
// markup, or that cannot be split, is not stacked; nil means "render it normally".
func renderStacked(text string) *image.RGBA {
	text = strings.TrimSpace(text)
	if text == "" || strings.ContainsAny(text, "<&") {
		return nil
	}
	words := strings.Fields(text)
	if len(words) < 2 {
		return nil
	}
	width := func(s string) int { return gfx.Measure(gfx.ParseMarkup(s, inkBlack), stackedPx).W }
	best, bestW := 1, 1<<30
	for i := 1; i < len(words); i++ {
		l, r := strings.Join(words[:i], " "), strings.Join(words[i:], " ")
		if w := max(width(l), width(r)); w < bestW {
			best, bestW = i, w
		}
	}
	lines := []string{strings.Join(words[:best], " "), strings.Join(words[best:], " ")}
	var imgs [2]*image.RGBA
	w, h := 0, 0
	for i, l := range lines {
		sp := gfx.ParseMarkup(l, inkBlack)
		m := gfx.Measure(sp, stackedPx)
		img := image.NewRGBA(image.Rect(0, 0, max(m.W, 1), max(m.H, 1)))
		gfx.Draw(img, 0, 0, sp, stackedPx)
		imgs[i] = img
		w = max(w, m.W)
		h += m.H
	}
	out := image.NewRGBA(image.Rect(0, 0, w, h))
	y := 0
	for _, img := range imgs {
		b := img.Bounds()
		draw.Draw(out, image.Rect((w-b.Dx())/2, y, (w-b.Dx())/2+b.Dx(), y+b.Dy()), img, image.Point{}, draw.Over)
		y += b.Dy()
	}
	return out
}

// stacked lists what gets the two-line treatment: helper names and substrings of genmon
// commands, one per line in ~/.config/gopanel/stacked.conf (default below when absent).
var stackedList = loadStackedList()

func loadStackedList() []string {
	def := []string{"wattage-panel", "panel-status-genmon"}
	dir, err := os.UserConfigDir()
	if err != nil {
		return def
	}
	b, err := os.ReadFile(filepath.Join(dir, "gopanel", "stacked.conf"))
	if err != nil {
		return def
	}
	var out []string
	for _, l := range strings.Split(string(b), "\n") {
		if l = strings.TrimSpace(l); l != "" && !strings.HasPrefix(l, "#") {
			out = append(out, l)
		}
	}
	return out
}

func isStacked(key string) bool {
	for _, s := range stackedList {
		if strings.Contains(key, s) {
			return true
		}
	}
	return false
}
