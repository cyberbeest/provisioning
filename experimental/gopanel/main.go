// gopanel: a minimal X11 panel in pure Go (no cgo, no toolkit).
// Two jobs: (1) reserve a strip at the screen bottom via _NET_WM_STRUT_PARTIAL
// so the WM keeps other windows out of it, (2) lay out items in it: launchers,
// built-in widgets (clock, genmon) and frames sent by helper processes.
// The item list mirrors the xfce4-panel plugin list (see config.go).
package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"os"
	"os/signal"
	"runtime/debug"
	"syscall"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/dpms"
	"github.com/jezek/xgb/xproto"

	"gopanel/proto"
)

const version = "0.7.2"

var (
	xc            *xgb.Conn // shared X connection (goroutine-safe)
	xroot         xproto.Window
	drawItem      func(*item) // set by main: repaint one item (main goroutine only)
	toggleWhisker func()      // open/close the application menu (main goroutine only)
	cancelTipFn   func()
	whiskerAnchor int // screen x of the menu button
	taskbars      []*taskbar
	panelH        = 35 // overridden from the xfce4-panel config
	iconSize      = 28
	panelScreenY  uint16 // screen y of the panel's top edge
)

// vcsRevision returns the git revision Go embedded at build time, if any.
func vcsRevision() string {
	bi, ok := debug.ReadBuildInfo()
	if !ok {
		return ""
	}
	rev, dirty := "", ""
	for _, kv := range bi.Settings {
		switch kv.Key {
		case "vcs.revision":
			rev = kv.Value
			if len(rev) > 7 {
				rev = rev[:7]
			}
		case "vcs.modified":
			if kv.Value == "true" {
				dirty = "-dirty"
			}
		}
	}
	return rev + dirty
}

func atom(c *xgb.Conn, name string) xproto.Atom {
	r, err := xproto.InternAtom(c, false, uint16(len(name)), name).Reply()
	if err != nil {
		log.Fatal(err)
	}
	return r.Atom
}

func u32(v ...uint32) []byte {
	b := make([]byte, 4*len(v))
	for i, x := range v {
		binary.LittleEndian.PutUint32(b[4*i:], x)
	}
	return b
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "version" {
		fmt.Println("gopanel", version, vcsRevision())
		return
	}
	if len(os.Args) > 1 { // gopanel reload | restart | quit
		ctlClient(os.Args[1])
		return
	}
	sig := make(chan os.Signal, 1) // register first: default SIGHUP action would kill us
	signal.Notify(sig, syscall.SIGHUP)

	cfg := xfconfAll()
	panelH = atoi(cfg["/panels/panel-1/size"], panelH)
	iconSize = min(atoi(cfg["/panels/panel-1/icon-size"], iconSize), panelH-2)
	if iconSize < 8 {
		iconSize = panelH - 2
	}

	c, err := xgb.NewConn()
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()
	scr := xproto.Setup(c).DefaultScreen(c)
	sw, sh := scr.WidthInPixels, scr.HeightInPixels

	panelScreenY = sh - uint16(panelH)
	xc, xroot = c, scr.Root
	wid, _ := xproto.NewWindowId(c)
	xproto.CreateWindow(c, scr.RootDepth, wid, scr.Root,
		0, int16(int(sh)-panelH), sw, uint16(panelH), 0,
		xproto.WindowClassInputOutput, scr.RootVisual,
		xproto.CwBackPixel|xproto.CwEventMask,
		[]uint32{panelBg, xproto.EventMaskExposure | xproto.EventMaskButtonPress |
			xproto.EventMaskPointerMotion | xproto.EventMaskLeaveWindow})

	// Window type DOCK + strut: this is "where the rest of the desktop is".
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_WINDOW_TYPE"),
		xproto.AtomAtom, 32, 1, u32(uint32(atom(c, "_NET_WM_WINDOW_TYPE_DOCK"))))
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT_PARTIAL"),
		xproto.AtomCardinal, 32, 12, u32(0, 0, 0, uint32(panelH), 0, 0, 0, 0, 0, 0, 0, uint32(sw)-1))
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT"),
		xproto.AtomCardinal, 32, 4, u32(0, 0, 0, uint32(panelH)))
	name := "gopanel"
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, xproto.AtomWmName,
		xproto.AtomString, 8, uint32(len(name)), []byte(name))

	gc, _ := xproto.NewGcontextId(c)
	xproto.CreateGC(c, gc, xproto.Drawable(wid), 0, nil)
	xproto.MapWindow(c, wid)
	tip := newTooltip(c, scr, gc)
	menus := newMenuMgr(c, scr, gc)
	wh := newWhisker(c, scr, gc)
	toggleWhisker = func() {
		cancelTipFn()
		wh.toggle(whiskerAnchor)
	}

	var (
		items   []*item
		helpers []*helperConn
		sups    = map[string]*supervisor{}
		hover   *item
		paused  bool
	)

	// relayout assigns x positions; expanding items share whatever width is left.
	relayout := func() {
		fixed, nexp := 4, 0 // 4px right margin
		for _, it := range items {
			if it.expand {
				nexp++
			} else {
				fixed += it.w
			}
		}
		extra := max(int(sw)-fixed, 0)
		x := 0
		for _, it := range items {
			it.x = x
			if it.expand {
				if nw := extra / nexp; nw != it.w {
					it.w = nw
					if it.resize != nil {
						it.resize(nw)
					}
				}
			}
			x += it.w
		}
	}

	// draw composites the item's image (premultiplied RGBA, centred) over the panel or
	// hover colour and pushes the item's box to the window.
	draw := func(it *item) {
		if it.w <= 0 {
			return
		}
		bg := uint32(panelBg)
		if it == hover && it.hl {
			bg = hoverBg
		}
		br, bgn, bb := uint32(byte(bg>>16)), uint32(byte(bg>>8)), uint32(byte(bg))
		buf := make([]byte, it.w*panelH*4)
		for i := 0; i < it.w*panelH; i++ {
			buf[i*4], buf[i*4+1], buf[i*4+2] = byte(bb), byte(bgn), byte(br)
		}
		if img := it.img; img != nil {
			ib := img.Bounds()
			ox, oy := (it.w-ib.Dx())/2, (panelH-ib.Dy())/2
			for y := 0; y < ib.Dy(); y++ {
				if oy+y < 0 || oy+y >= panelH {
					continue
				}
				for x := 0; x < ib.Dx(); x++ {
					if ox+x < 0 || ox+x >= it.w {
						continue
					}
					p := img.Pix[y*img.Stride+x*4:]
					o := ((oy+y)*it.w + ox + x) * 4
					inv := 255 - uint32(p[3])
					buf[o] = byte(uint32(p[2]) + bb*inv/255)
					buf[o+1] = byte(uint32(p[1]) + bgn*inv/255)
					buf[o+2] = byte(uint32(p[0]) + br*inv/255)
				}
			}
		}
		putBGRX(c, xproto.Drawable(wid), gc, scr.RootDepth, it.x, 0, it.w, panelH, buf)
	}
	drawItem = draw
	redrawAll := func() {
		xproto.ClearArea(c, false, wid, 0, 0, 0, 0)
		for _, it := range items {
			draw(it)
		}
	}
	hit := func(x int16) *item {
		for _, it := range items {
			if it.interactive() && int(x) >= it.x && int(x) < it.x+it.w {
				return it
			}
		}
		return nil
	}

	// Tooltips appear after the pointer rests on an item for a moment.
	tipC := make(chan *item, 1)
	var tipTimer *time.Timer
	cancelTip := func() {
		if tipTimer != nil {
			tipTimer.Stop()
		}
		tip.hide()
	}
	ptrX := 0 // last pointer x, screen coordinates
	tipText := func(it *item) string {
		if it.tipAt != nil {
			return it.tipAt(ptrX - it.x)
		}
		return it.tip
	}
	armTip := func(it *item) {
		if it == nil || (it.tip == "" && it.tipAt == nil) {
			return
		}
		tipTimer = time.AfterFunc(500*time.Millisecond, func() {
			select {
			case tipC <- it:
			default:
			}
		})
	}
	cancelTipFn = cancelTip
	setHover := func(it *item) {
		if it == hover {
			return
		}
		old := hover
		hover = it
		cancelTip()
		if old != nil {
			if old.hover != nil {
				old.hover(false)
			}
			draw(old)
		}
		if it != nil {
			if it.hover != nil {
				it.hover(true)
			}
			draw(it)
			armTip(it)
		}
	}

	// install replaces the item list (initial build and reload): old items are
	// discarded, still-connected helpers are re-bound by name, and helper
	// supervisors are started/stopped to match.
	install := func(cfg map[string][]string) {
		hover = nil
		cancelTip()
		for _, it := range items {
			it.discard()
		}
		for _, tb := range taskbars {
			tb.close()
		}
		taskbars = nil
		items = buildItems(cfg)
		want := map[string]bool{}
		for _, it := range items {
			if it.kind == "helper" {
				want[it.name] = true
				for _, hc := range helpers {
					if hc.name == it.name && it.hc == nil {
						bindHelper(it, hc)
					}
				}
			}
		}
		for n, s := range sups {
			if !want[n] {
				close(s.stop)
				delete(sups, n)
			}
		}
		for _, it := range items {
			if it.kind != "helper" || sups[it.name] != nil {
				continue
			}
			it := it
			s := &supervisor{name: it.name, stop: make(chan struct{}), connected: func() bool { return it.conn.Load() }}
			sups[it.name] = s
			go s.run()
		}
		relayout()
		redrawAll()
	}

	cmds := make(chan string, 4)
	ctlServer(cmds)
	watchConfig(cmds)
	defer os.Remove(sockPath())
	hev := make(chan helperEvent, 16)
	helperServer(hev)
	defer os.Remove(proto.SockPath())
	go func() {
		for range sig {
			cmds <- "reload"
		}
	}()

	events := make(chan xgb.Event)
	go func() {
		for {
			ev, err := c.WaitForEvent()
			if ev == nil && err == nil {
				close(events)
				return
			}
			if ev != nil {
				events <- ev
			}
		}
	}()

	install(cfg)
	whReady := make(chan whiskerData, 1)
	go preloadWhisker(whReady)

	// Helpers are told to pause while the display is in standby: nothing to see,
	// and animation would only burn battery. (A locked-but-lit screen is not
	// detected yet; the C plugins also asked the screensaver over D-Bus.)
	dpmsC := make(chan bool, 1)
	if dpms.Init(c) == nil {
		go func() { // own goroutine: a reply that never comes must not freeze the main loop
			for {
				time.Sleep(2 * time.Second)
				if info, err := dpms.Info(c).Reply(); err == nil {
					select {
					case dpmsC <- info.State && info.PowerLevel != dpms.DPMSModeOn:
					default:
					}
				}
			}
		}()
	}
	pauseLine := func() string {
		if paused {
			return "pause"
		}
		return "resume"
	}

	handle := func(ev xgb.Event) {
		switch e := ev.(type) {
		case xproto.ExposeEvent:
			if e.Count == 0 {
				redrawAll()
			}
		case xproto.PropertyNotifyEvent:
			for _, tb := range taskbars {
				tb.onProperty(e)
			}
		case xproto.MotionNotifyEvent:
			ptrX = int(e.EventX)
			it := hit(e.EventX)
			setHover(it)
			if it != nil && it.motion != nil {
				it.motion(ptrX - it.x)
			}
			if it != nil && it.tipAt != nil && tip.shown && tip.forIt == it { // moved to another icon
				if txt := tipText(it); txt == "" {
					tip.hide()
				} else if txt != tip.text {
					tip.show(it, txt, ptrX)
				}
			} else if it != nil && it.tipAt != nil && !tip.shown {
				cancelTip()
				armTip(it)
			}
		case xproto.LeaveNotifyEvent:
			setHover(nil)
		case xproto.ButtonPressEvent:
			cancelTip()
			if it := hit(e.EventX); it != nil && it.click != nil {
				it.click(int(e.EventX)-it.x, int(e.EventY), int(e.Detail))
			}
		}
	}

	for {
		select {
		case ev, ok := <-events:
			if !ok {
				return
			}
			if ee, isExp := ev.(xproto.ExposeEvent); isExp && ee.Window == tip.win {
				tip.paint()
				continue
			}
			if menus.handle(ev) {
				continue
			}
			if wh.handle(ev) {
				continue
			}
			handle(ev)
		case d := <-whReady:
			if !wh.loaded {
				wh.setData(d)
			}
		case req := <-menuReqs:
			cancelTip()
			menus.open(req)
		case u := <-updates:
			it := u.it
			if it.isDead() {
				continue
			}
			if u.img != nil {
				it.img = u.img
			}
			if u.tip != nil {
				it.tip = *u.tip
				if tip.shown && tip.forIt == it {
					if it.tip == "" {
						tip.hide()
					} else {
						tip.show(it, it.tip, it.x+it.w/2)
					}
				}
			}
			if u.w != it.w && !it.expand && u.w >= 0 && (u.w > 0 || u.force || u.img != nil) {
				it.w = u.w
				relayout()
				redrawAll()
				continue
			}
			draw(it)
		case it := <-tipC:
			if txt := tipText(it); it == hover && txt != "" && !it.isDead() {
				tip.show(it, txt, it.x+it.w/2)
			}
		case he := <-hev:
			switch he.kind {
			case "hello":
				var target *item
				for _, it := range items {
					if it.kind == "helper" && it.name == he.hc.name && it.hc == nil {
						target = it
						break
					}
				}
				if target == nil {
					he.hc.kill() // not in the panel configuration
					continue
				}
				helpers = append(helpers, he.hc)
				bindHelper(target, he.hc)
				he.hc.send(pauseLine())
				relayout()
				redrawAll()
			case "image":
				he.hc.img = he.img
				if it := itemFor(items, he.hc); it != nil {
					it.img = he.img
					draw(it)
				}
			case "label":
				if it := itemFor(items, he.hc); it != nil {
					it.img = renderLabel(he.text)
					w := 0
					if it.img != nil {
						w = it.img.Bounds().Dx() + 2*labelEdge
					}
					if w != it.w {
						it.w = w
						relayout()
						redrawAll()
					} else {
						draw(it)
					}
				}
			case "tooltip":
				if it := itemFor(items, he.hc); it != nil {
					it.tip = he.text
					if tip.shown && tip.forIt == it {
						tip.show(it, it.tip, it.x+it.w/2)
					}
				}
			case "bye":
				for i, hc := range helpers {
					if hc == he.hc {
						helpers = append(helpers[:i], helpers[i+1:]...)
						break
					}
				}
				if it := itemFor(items, he.hc); it != nil {
					unbindHelper(it)
					if hover == it {
						hover = nil
						cancelTip()
					}
				}
				relayout()
				redrawAll()
			}
		case off := <-dpmsC:
			if off != paused {
				paused = off
				for _, hc := range helpers {
					hc.send(pauseLine())
				}
			}
		case cmd := <-cmds:
			switch cmd {
			case "reload": // re-read the xfce4-panel config, rebuild all items
				log.Println("reload")
				install(xfconfAll())
			case "restart": // replace this process with the (possibly rebuilt) binary
				os.Remove(sockPath())
				os.Remove(proto.SockPath())
				exe, _ := os.Executable()
				log.Fatal(syscall.Exec(exe, []string{exe}, os.Environ()))
			case "menu":
				toggleWhisker()
			case "quit":
				for _, s := range sups {
					close(s.stop)
				}
				time.Sleep(200 * time.Millisecond) // let supervisors terminate their children
				return
			}
		}
	}
}

func itemFor(items []*item, hc *helperConn) *item {
	for _, it := range items {
		if it.hc == hc {
			return it
		}
	}
	return nil
}

// bindHelper attaches a connected helper to its panel item.
func bindHelper(it *item, hc *helperConn) {
	it.hc = hc
	it.conn.Store(true)
	it.w, it.img, it.hl = hc.w, hc.img, false
	it.click = func(x, y, btn int) { hc.send(fmt.Sprintf("click %d %d %d", x, y, btn)) }
	it.hover = func(on bool) {
		if on {
			hc.send("hover on")
		} else {
			hc.send("hover off")
		}
	}
}

func unbindHelper(it *item) {
	it.hc = nil
	it.conn.Store(false)
	it.w, it.img, it.tip, it.click, it.hover = 0, nil, "", nil, nil
}
