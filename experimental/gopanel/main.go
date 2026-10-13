// gopanel: a minimal X11 panel in pure Go (no cgo, no toolkit).
// Two jobs: (1) reserve a strip at the screen bottom via _NET_WM_STRUT_PARTIAL
// so the WM keeps other windows out of it, (2) lay out items in it: launchers,
// built-in widgets (clock, genmon) and frames sent by helper processes.
// The item list mirrors the xfce4-panel plugin list (see config.go).
package main

import (
	"context"
	"encoding/binary"
	"fmt"
	"github.com/godbus/dbus/v5"
	"github.com/jezek/xgb/randr"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime/debug"
	"syscall"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/dpms"
	"github.com/jezek/xgb/xproto"

	"gopanel/proto"
)

const version = "0.18.2"

var ctlCmds chan<- string // control commands into the main loop

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

	if conn, err := net.Dial("unix", sockPath()); err == nil { // before touching X
		conn.Close()
		log.Fatal("gopanel already running")
	}

	c, err := xgb.NewConn()
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()
	scr := xproto.Setup(c).DefaultScreen(c)
	initRandr(c, scr.Root)
	queryMonitor(c, scr)
	sw := uint16(monW)

	xc, xroot = c, scr.Root
	wid, _ := xproto.NewWindowId(c)
	panelWin = wid
	xproto.CreateWindow(c, scr.RootDepth, wid, scr.Root,
		int16(monX), int16(panelTopY()), sw, uint16(panelH), 0,
		xproto.WindowClassInputOutput, scr.RootVisual,
		xproto.CwBackPixel|xproto.CwEventMask,
		[]uint32{panelBg, xproto.EventMaskExposure | xproto.EventMaskButtonPress |
			xproto.EventMaskPointerMotion | xproto.EventMaskLeaveWindow})

	// Window type DOCK + strut: this is "where the rest of the desktop is".
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_WINDOW_TYPE"),
		xproto.AtomAtom, 32, 1, u32(uint32(atom(c, "_NET_WM_WINDOW_TYPE_DOCK"))))
	setStrut := func() {
		bottom := uint32(rootH - (monY + monH) + panelH)
		xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT_PARTIAL"),
			xproto.AtomCardinal, 32, 12, u32(0, 0, 0, bottom, 0, 0, 0, 0, 0, 0, uint32(monX), uint32(monX+monW-1)))
		xproto.ChangeProperty(c, xproto.PropModeReplace, wid, atom(c, "_NET_WM_STRUT"),
			xproto.AtomCardinal, 32, 4, u32(0, 0, 0, bottom))
	}
	setStrut()
	name := "gopanel"
	xproto.ChangeProperty(c, xproto.PropModeReplace, wid, xproto.AtomWmName,
		xproto.AtomString, 8, uint32(len(name)), []byte(name))

	gc, _ := xproto.NewGcontextId(c)
	xproto.CreateGC(c, gc, xproto.Drawable(wid), 0, nil)
	xproto.MapWindow(c, wid)
	xscr, xgc = scr, gc
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
		fixed := 4 // 4px right margin
		var exp []*item
		for _, it := range items {
			if it.expand {
				exp = append(exp, it)
			} else {
				fixed += it.w
			}
		}
		// Share the free width between the expanding items, but never give one more than it
		// can use (the taskbar wants at most a full-width button per window): the surplus goes
		// to the others (the expanding separator), so buttons are not squeezed next to dead space.
		left := max(monW-fixed, 0)
		alloc := map[*item]int{}
		rest := append([]*item(nil), exp...)
		for len(rest) > 0 {
			share := left / len(rest)
			capped := false
			for i, it := range rest {
				if it.want != nil {
					if w := it.want(); w <= share {
						alloc[it] = w
						left -= w
						rest = append(rest[:i], rest[i+1:]...)
						capped = true
						break
					}
				}
			}
			if !capped {
				for _, it := range rest {
					alloc[it] = share
				}
				break
			}
		}
		x := 0
		for _, it := range items {
			it.x = x
			if it.expand {
				if nw := alloc[it]; nw != it.w {
					it.w = nw
					if it.resize != nil {
						it.resize(nw)
					}
				}
			}
			x += it.w
		}
		xt.place()
		saveWidths(items)
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
	reflow = func() {
		relayout()
		redrawAll()
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
		reserveWidths(items)
		relayout()
		redrawAll()
		time.AfterFunc(3*time.Second, func() { ctlCmds <- "unreserve" })
	}

	cmds := make(chan string, 4)
	ctlCmds = cmds
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

	go reapZombies()
	install(cfg)
	whReady := make(chan whiskerData, 1)
	go preloadWhisker(whReady)

	// Helpers are told to pause while the display is in standby or the screensaver
	// (lock screen) is active: nothing to see, and animation would only burn battery.
	dpmsC := make(chan bool, 1)
	hasDPMS := dpms.Init(c) == nil
	go func() { // own goroutine: a reply that never comes must not freeze the main loop
		bus, _ := dbus.ConnectSessionBus()
		for {
			time.Sleep(2 * time.Second)
			off := false
			if hasDPMS {
				if info, err := dpms.Info(c).Reply(); err == nil {
					off = info.State && info.PowerLevel != dpms.DPMSModeOn
				}
			}
			if !off && bus != nil {
				var active bool
				ctx, cancel := context.WithTimeout(context.Background(), time.Second)
				err := bus.Object("org.xfce.ScreenSaver", "/org/xfce/ScreenSaver").CallWithContext(ctx, "org.xfce.ScreenSaver.GetActive", 0).Store(&active)
				cancel()
				off = err == nil && active
			}
			select {
			case dpmsC <- off:
			default:
			}
		}
	}()
	pauseLine := func() string {
		if paused {
			return "pause"
		}
		return "resume"
	}

	grabMediaKeys()
	handle := func(ev xgb.Event) {
		if xt.handle(ev) {
			return
		}
		switch e := ev.(type) {
		case randr.ScreenChangeNotifyEvent:
			// monitor plugged/unplugged or resolution changed: follow the primary monitor
			wh.close()
			menus.close()
			closePopup()
			queryMonitor(c, scr)
			xproto.ConfigureWindow(c, wid, xproto.ConfigWindowX|xproto.ConfigWindowY|xproto.ConfigWindowWidth|xproto.ConfigWindowHeight,
				[]uint32{uint32(monX), uint32(panelTopY()), uint32(monW), uint32(panelH)})
			setStrut()
			relayout()
			redrawAll()
		case xproto.KeyPressEvent:
			mediaKey(e.Detail)
		case xproto.ExposeEvent:
			if e.Count == 0 {
				redrawAll()
			}
		case xproto.PropertyNotifyEvent:
			// Another window took focus (a dictation typing back into its window,
			// the user switching windows): popups hold a keyboard grab that would
			// swallow its keystrokes, so let go of it.
			if e.Window == xroot && (wh.isOpen || menus.active()) {
				if r, err := xproto.GetAtomName(xc, e.Atom).Reply(); err == nil && r.Name == "_NET_ACTIVE_WINDOW" {
					wh.close()
					menus.close()
				}
			}
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
			it := hit(e.EventX)
			if e.Detail == 3 && (it == nil || it.kind == "separator" || it.kind == "launcher" || it.kind == "clock" || it.kind == "helper") {
				panelMenu(int(e.EventX), cmds)
			} else if it != nil && it.click != nil {
				it.click(int(e.EventX)-it.x, int(e.EventY), int(e.Detail))
			}
		}
	}

	xtTick := xtrayTick()
	for {
		select {
		case <-xtTick:
			xt.tryAcquire()
		case ev, ok := <-events:
			if !ok {
				return
			}
			if ee, isExp := ev.(xproto.ExposeEvent); isExp && ee.Window == tip.win {
				tip.paint()
				continue
			}
			if popupHandle(ev) {
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
			closePopup()
			menus.open(req)
		case u := <-updates:
			it := u.it
			if it.isDead() {
				continue
			}
			it.reserved = false
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
				if target == nil { // not in the panel configuration, or a duplicate: tell it to exit
					he.hc.send("quit")
					go func(hc *helperConn) { time.Sleep(300 * time.Millisecond); hc.kill() }(he.hc)
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
			case "calendar", "volume", "power": // also handy for testing; toggles
				if curPop != nil {
					closePopup()
				} else if cmd == "calendar" {
					openCalendar(monW - 60)
				} else if cmd == "power" {
					openPowerPopup(monW - 300)
				} else {
					openVolumePopup(monW - 400)
				}
			case "dismiss": // close every open popup (Dictate asks before it types)
				wh.close()
				menus.close()
				closePopup()
			case "unreserve": // cached widths that nobody confirmed: give the space back
				if unreserve(items) {
					relayout()
					redrawAll()
				}
			case "yield":
				xt.yieldTray()
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
	it.hc, it.reserved = hc, false
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

// xfcePanelRunning reports whether the stock xfce4-panel is up.
func xfcePanelRunning() bool {
	return exec.Command("pgrep", "-x", "xfce4-panel").Run() == nil
}

// panelMenu is the right-click menu of the panel background: switch the stock
// XFCE panel on or off, restart or quit this panel.
func panelMenu(x int, cmds chan<- string) {
	xfce := &menuItem{id: 1, label: tr("Start XFCE panel")}
	if xfcePanelRunning() {
		xfce = &menuItem{id: 1, label: tr("Stop XFCE panel")}
	}
	menuReqs <- menuReq{
		items:   []*menuItem{xfce, {sep: true}, {id: 2, label: tr("Restart this panel")}, {id: 3, label: tr("Quit this panel")}},
		anchorX: x,
		onSelect: func(mi *menuItem) {
			switch mi.id {
			case 1:
				go toggleXfcePanel()
			case 2:
				go func() { cmds <- "restart" }()
			case 3:
				go func() {
					if !xfcePanelRunning() { // never leave the desktop without a panel
						toggleXfcePanel()
					}
					cmds <- "quit"
				}()
			}
		},
	}
}

// toggleXfcePanel stops or starts the stock panel. The xfce-panel-watchdog user
// service relaunches a dead panel within seconds, so a stop leaves a marker file
// it respects; a start removes the marker and lets the watchdog bring the panel
// up with the proper session environment, launching it directly only if the
// watchdog (not installed everywhere) does not.
func toggleXfcePanel() {
	if !xfcePanelRunning() {
		ctlCmds <- "yield" // so its systray can own the XEmbed tray selection
		time.Sleep(300 * time.Millisecond)
	}
	dir := os.Getenv("XDG_RUNTIME_DIR")
	if dir == "" {
		dir = os.TempDir()
	}
	marker := filepath.Join(dir, "cyberbeest-xfce-panel-stopped")
	if xfcePanelRunning() {
		os.WriteFile(marker, nil, 0o600)
		exec.Command("xfce4-panel", "--quit").Run()
		return
	}
	os.Remove(marker)
	for i := 0; i < 14; i++ {
		time.Sleep(500 * time.Millisecond)
		if xfcePanelRunning() {
			return
		}
	}
	exec.Command("systemd-run", "--user", "--collect", "--quiet", "-p", "KillMode=process", // see cyberbeest-panel-choice.sh
		"--setenv=DISPLAY", "--setenv=XAUTHORITY", "--setenv=XDG_CURRENT_DESKTOP", "--setenv=XDG_SESSION_TYPE",
		"xfce4-panel").Run()
}
