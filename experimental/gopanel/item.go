package main

import (
	"image"
	"sync/atomic"
)

// Panel colours (the default Xfce GTK theme).
const (
	panelBg = 0xF6F5F4
	hoverBg = 0xDDDBD8
)

// item is one thing in the panel. Only the main goroutine touches its fields;
// widget goroutines change it by posting an itemUpdate.
type item struct {
	kind     string
	name     string // helper name, for kind "helper"
	x, w     int
	expand   bool
	want     func() int          // expanding items: widest useful width (nil = takes whatever is left)
	img      *image.RGBA         // current frame, centred in the item box
	tip      string              // tooltip (Pango-lite markup)
	hl       bool                // highlight while hovered
	click    func(x, y, btn int) // main goroutine; must not block
	tipAt    func(x int) string  // optional: tooltip depends on the pointer position within the item
	hover    func(on bool)
	motion   func(x int) // pointer moved inside the item (x local to the item)
	resize   func(w int) // expanding items: the layout assigned a new width
	hc       *helperConn
	dead     chan struct{} // closed when the item is discarded (reload)
	stop     func()
	conn     atomic.Bool             // helper items: a helper is currently connected
	ptype    string                  // xfce plugin type of that rc file (kitt-scanner, genmon, ...)
	title    string                  // friendly plugin name for menus
	rc       string                  // the plugin's xfce rc file (settings the Properties dialog edits), if any
	drawBuf  []byte                  // scratch for draw()
	reserved bool                    // w is a cached guess from the last run, not yet confirmed
	imgAt    func(w int) *image.RGBA // expanding items whose image depends on the width (taskbar): render for another panel
	ctxW     func(w int)             // tell the item its width without rendering (replica event handling)
	hold     int                     // tray: slot width kept (icons left-aligned in it) while autostarted apps are still docking
}

func newItem(kind string) *item {
	return &item{kind: kind, dead: make(chan struct{})}
}

func (it *item) isDead() bool {
	select {
	case <-it.dead:
		return true
	default:
		return false
	}
}

func (it *item) discard() {
	if !it.isDead() {
		close(it.dead)
	}
	if it.stop != nil {
		it.stop()
	}
}

// interactive items take part in hover/click hit testing.
func (it *item) interactive() bool { return it.w > 0 && (it.hl || it.click != nil || it.tip != "") }

type itemUpdate struct {
	it    *item
	img   *image.RGBA // nil: unchanged
	tip   *string     // nil: unchanged
	w     int         // 0: unchanged
	force bool        // apply w even when it is 0 (hide the item)
}

var updates = make(chan itemUpdate, 64)

// post hands an update to the main goroutine; gives up if the item was discarded.
func (it *item) post(u itemUpdate) {
	u.it = it
	select {
	case updates <- u:
	case <-it.dead:
	}
}

func (it *item) setTip(s string) { it.post(itemUpdate{tip: &s}) }
