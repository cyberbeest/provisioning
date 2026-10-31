package gfx

import (
	"bytes"
	"embed"
	"image"
	"image/draw"
	_ "image/png"

	xdraw "golang.org/x/image/draw"
)

// Country flags: a pair of regional-indicator characters (🇩🇪) is drawn as a small
// bitmap, since the outline fonts in the chain have no colour emoji. The bitmaps are
// the flag images of Google's Noto Color Emoji (Apache License 2.0), trimmed and scaled
// to 16 px height; see flags/NOTICE.
//
//go:embed flags/*.png
var flagFS embed.FS

var flagImgs = map[string]image.Image{}

func isRegional(r rune) bool { return r >= 0x1F1E6 && r <= 0x1F1FF }

// flagImage returns the bitmap for a lower-case country code, or nil.
func flagImage(cc string) image.Image {
	if img, ok := flagImgs[cc]; ok {
		return img
	}
	var img image.Image
	if data, err := flagFS.ReadFile("flags/" + cc + ".png"); err == nil {
		img, _, _ = image.Decode(bytes.NewReader(data))
	}
	flagImgs[cc] = img
	return img
}

// flagSize is the drawn size of a flag in text of the given pixel size.
func flagSize(img image.Image, px float64) (w, h int) {
	h = int(px*0.85 + 0.5)
	if h < 6 {
		h = 6
	}
	b := img.Bounds()
	w = (b.Dx()*h + b.Dy()/2) / b.Dy()
	return w, h
}

func drawFlag(dst *image.RGBA, img image.Image, x, y, w, h int) {
	tmp := image.NewRGBA(image.Rect(0, 0, w, h))
	xdraw.CatmullRom.Scale(tmp, tmp.Bounds(), img, img.Bounds(), xdraw.Src, nil)
	draw.Draw(dst, image.Rect(x, y, x+w, y+h), tmp, image.Point{}, draw.Over)
}
