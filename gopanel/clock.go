package main

import (
	"image"
	"image/color"
	"time"

	"gopanel/gfx"
)

// newClockItem: time over date, right-aligned.
func newClockItem() *item {
	it := newItem("clock")
	ink := color.RGBA{0, 0, 0, 255}
	render := func(now time.Time) (*image.RGBA, string) {
		lines := []string{now.Format("15:04"), now.Format("2006-01-02")}
		px := 11.5 // Sans ~8.6pt: the clock was the biggest text in the panel
		var ws [2]int
		var spans [2][]gfx.Span
		w, h := 0, 0
		for i, l := range lines {
			spans[i] = gfx.ParseMarkup(l, ink)
			m := gfx.Measure(spans[i], px)
			ws[i], h = m.W, m.H
			if m.W > w {
				w = m.W
			}
		}
		img := image.NewRGBA(image.Rect(0, 0, w+6, 2*h)) // 6px blank on the left: the item centres the image, so this moves the text right
		for i := range lines {
			gfx.Draw(img, w+6-ws[i], i*h, spans[i], px)
		}
		return img, longDate(now)
	}
	it.hl = true
	it.click = func(x, y, btn int) {
		if btn == 1 {
			openCalendar(it.x + it.w/2)
		}
	}
	go func() {
		for {
			now := time.Now()
			img, tip := render(now)
			it.post(itemUpdate{img: img, tip: &tip, w: img.Bounds().Dx() + 4})
			next := now.Truncate(time.Minute).Add(time.Minute + 50*time.Millisecond)
			select {
			case <-time.After(time.Until(next)):
			case <-it.dead:
				return
			}
		}
	}()
	return it
}
