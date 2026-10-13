package main

import (
	"context"
	"encoding/xml"
	"fmt"
	"image"
	"image/draw"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/godbus/dbus/v5"
	"github.com/godbus/dbus/v5/prop"
	xdraw "golang.org/x/image/draw"
)

// StatusNotifier (SNI) host: the modern system tray protocol. If no watcher owns
// org.kde.StatusNotifierWatcher (the xfce panel's systray plugin normally does) we
// become the watcher ourselves.

const (
	watcherName  = "org.kde.StatusNotifierWatcher"
	watcherPath  = "/StatusNotifierWatcher"
	itemIface    = "org.kde.StatusNotifierItem"
	trayGap      = 4
	trayEdge     = 3
	defaultItemP = "/StatusNotifierItem"
)

type pixmap struct {
	W, H int32
	Data []byte
}

type trayTooltip struct {
	IconName    string
	IconData    []pixmap
	Title, Desc string
}

type trayIcon struct {
	service, owner string
	path           dbus.ObjectPath
	id, title      string
	status         string
	menu           dbus.ObjectPath
	itemIsMenu     bool
	tip            string
	img            *image.RGBA
}

type tray struct {
	it    *item
	conn  *dbus.Conn
	mu    sync.Mutex
	icons []*trayIcon // registration order
	own   bool        // we are the StatusNotifierWatcher
}

// ---- own watcher, used only when nobody else provides one --------------------------

type watcher struct {
	t *tray
}

func (w *watcher) RegisterStatusNotifierItem(sender dbus.Sender, service string) *dbus.Error {
	w.t.register(string(sender), service)
	return nil
}

func (w *watcher) RegisterStatusNotifierHost(service string) *dbus.Error { return nil }

func (t *tray) serveWatcher() bool {
	reply, err := t.conn.RequestName(watcherName, dbus.NameFlagDoNotQueue)
	if err != nil || reply != dbus.RequestNameReplyPrimaryOwner {
		return false
	}
	w := &watcher{t}
	t.conn.Export(w, watcherPath, watcherName)
	props, err := prop.Export(t.conn, watcherPath, prop.Map{watcherName: {
		"IsStatusNotifierHostRegistered": {Value: true, Writable: false, Emit: prop.EmitFalse},
		"ProtocolVersion":                {Value: int32(0), Writable: false, Emit: prop.EmitFalse},
		"RegisteredStatusNotifierItems":  {Value: []string{}, Writable: false, Emit: prop.EmitTrue},
	}})
	if err == nil {
		_ = props
	}
	log.Println("tray: acting as StatusNotifierWatcher")
	return true
}

// ---- host ------------------------------------------------------------------------------

func newTrayItem() *item {
	it := newItem("tray")
	it.hl = false
	t := &tray{it: it}
	conn, err := dbus.ConnectSessionBus()
	if err != nil {
		log.Println("tray: no session bus:", err)
		return it
	}
	t.conn = conn
	it.stop = func() { conn.Close() }

	ownWatcher := t.serveWatcher()
	t.own = ownWatcher
	if ownWatcher { // nobody else collected the running items for us
		go func() {
			t.rescan()
		}()
	}
	sigs := make(chan *dbus.Signal, 64)
	conn.Signal(sigs)
	for _, opt := range [][]dbus.MatchOption{
		{dbus.WithMatchInterface(itemIface)},
		{dbus.WithMatchInterface(watcherName)},
		{dbus.WithMatchSender("org.freedesktop.DBus"), dbus.WithMatchMember("NameOwnerChanged")},
	} {
		conn.AddMatchSignal(opt...)
	}
	if !ownWatcher {
		host := fmt.Sprintf("org.kde.StatusNotifierHost-%d-gopanel", os.Getpid())
		conn.RequestName(host, dbus.NameFlagDoNotQueue)
		w := conn.Object(watcherName, watcherPath)
		if err := w.Call(watcherName+".RegisterStatusNotifierHost", 0, host).Err; err != nil {
			log.Println("tray: no StatusNotifierWatcher:", err)
		}
		var items []string
		if v, err := w.GetProperty(watcherName + ".RegisteredStatusNotifierItems"); err == nil {
			v.Store(&items)
		}
		for _, s := range items {
			t.register("", s)
		}
	}
	t.render()

	it.click = t.onClick
	it.tipAt = t.tipAt
	go func() {
		for {
			select {
			case s := <-sigs:
				if s == nil {
					return
				}
				t.onSignal(s)
			case <-it.dead:
				return
			}
		}
	}()
	return it
}

// register adds an item given the watcher's "service" string: "busname", "busname/path"
// (path may itself contain slashes) or, from RegisterStatusNotifierItem, a bare path
// with the sender's unique name supplied separately.
func (t *tray) register(sender, service string) {
	svc, path := service, dbus.ObjectPath(defaultItemP)
	if strings.HasPrefix(service, "/") { // path only: owner is the sender
		svc, path = sender, dbus.ObjectPath(service)
	} else if i := strings.Index(service, "/"); i > 0 {
		svc, path = service[:i], dbus.ObjectPath(service[i:])
	}
	owner := svc
	if !strings.HasPrefix(svc, ":") {
		if err := t.conn.BusObject().Call("org.freedesktop.DBus.GetNameOwner", 0, svc).Store(&owner); err != nil {
			return
		}
	}
	t.mu.Lock()
	for _, ic := range t.icons {
		if ic.owner == owner && ic.path == path {
			t.mu.Unlock()
			return
		}
	}
	ic := &trayIcon{service: svc, owner: owner, path: path}
	t.icons = append(t.icons, ic)
	t.mu.Unlock()
	t.refresh(ic)
	t.render()
}

func (t *tray) unregister(match func(*trayIcon) bool) {
	t.mu.Lock()
	var keep []*trayIcon
	for _, ic := range t.icons {
		if !match(ic) {
			keep = append(keep, ic)
		}
	}
	changed := len(keep) != len(t.icons)
	t.icons = keep
	t.mu.Unlock()
	if changed {
		t.render()
	}
}

func (t *tray) onSignal(s *dbus.Signal) {
	switch {
	case s.Name == "org.freedesktop.DBus.NameOwnerChanged" && len(s.Body) == 3:
		name, _ := s.Body[0].(string)
		newOwner, _ := s.Body[2].(string)
		if name == watcherName && newOwner == "" && !t.own { // xfce4-panel went away: take over
			if t.own = t.serveWatcher(); t.own {
				go t.rescan() // apps that registered once with the old watcher will not do it again
			}
		}
		if newOwner == "" {
			t.unregister(func(ic *trayIcon) bool { return ic.owner == name || ic.service == name })
		}
	case s.Name == watcherName+".StatusNotifierItemRegistered" && len(s.Body) == 1:
		if str, ok := s.Body[0].(string); ok {
			t.register("", str)
		}
	case s.Name == watcherName+".StatusNotifierItemUnregistered" && len(s.Body) == 1:
		if str, ok := s.Body[0].(string); ok {
			t.unregister(func(ic *trayIcon) bool { return strings.HasPrefix(str, ic.service) || strings.HasPrefix(str, ic.owner) })
		}
	case strings.HasPrefix(s.Name, itemIface+".New"):
		t.mu.Lock()
		var hit *trayIcon
		for _, ic := range t.icons {
			if ic.owner == s.Sender && ic.path == s.Path {
				hit = ic
			}
		}
		t.mu.Unlock()
		if hit != nil {
			t.refresh(hit)
			t.render()
		}
	}
}

func argbToRGBA(p pixmap) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, int(p.W), int(p.H)))
	for i := 0; i+3 < len(p.Data) && i/4 < int(p.W*p.H); i += 4 {
		a := uint32(p.Data[i])
		o := (i / 4) * 4
		img.Pix[o] = byte(uint32(p.Data[i+1]) * a / 255) // premultiply
		img.Pix[o+1] = byte(uint32(p.Data[i+2]) * a / 255)
		img.Pix[o+2] = byte(uint32(p.Data[i+3]) * a / 255)
		img.Pix[o+3] = byte(a)
	}
	return img
}

func fitIcon(src image.Image) *image.RGBA { return fitIconSized(src, iconSize) }

func fitIconSized(src image.Image, size int) *image.RGBA {
	b := src.Bounds()
	if b.Dx() == 0 || b.Dy() == 0 {
		return nil
	}
	w, h := size, size
	if b.Dx() > b.Dy() {
		h = max(b.Dy()*size/b.Dx(), 1)
	} else if b.Dy() > b.Dx() {
		w = max(b.Dx()*size/b.Dy(), 1)
	}
	dst := image.NewRGBA(image.Rect(0, 0, size, size))
	r := image.Rect((size-w)/2, (size-h)/2, (size-w)/2+w, (size-h)/2+h)
	xdraw.CatmullRom.Scale(dst, r, src, b, draw.Over, nil)
	return dst
}

func bestPixmap(pms []pixmap) *image.RGBA {
	var best *pixmap
	for i := range pms {
		p := &pms[i]
		if p.W <= 0 || p.H <= 0 || len(p.Data) < int(p.W*p.H*4) {
			continue
		}
		if best == nil || (best.W < int32(iconSize) && p.W > best.W) || (p.W >= int32(iconSize) && p.W < best.W) {
			best = p
		}
	}
	if best == nil {
		return nil
	}
	return fitIcon(argbToRGBA(*best))
}

func themedIcon(name, themePath string) *image.RGBA {
	if name == "" {
		return nil
	}
	if filepath.IsAbs(name) {
		return loadIcon(name)
	}
	if themePath != "" {
		for _, ext := range []string{".png", ".svg"} {
			if m, _ := filepath.Glob(filepath.Join(themePath, "*", "*", name+ext)); len(m) > 0 {
				return loadIcon(m[len(m)-1])
			}
			if m, _ := filepath.Glob(filepath.Join(themePath, name+ext)); len(m) > 0 {
				return loadIcon(m[0])
			}
		}
	}
	return loadIcon(name)
}

// refresh reads the item's properties (icon, status, tooltip, menu).
func (t *tray) refresh(ic *trayIcon) {
	var props map[string]dbus.Variant
	obj := t.conn.Object(ic.owner, ic.path)
	if err := obj.Call("org.freedesktop.DBus.Properties.GetAll", 0, itemIface).Store(&props); err != nil {
		log.Println("tray: GetAll", ic.owner, ic.path, err)
		return
	}
	str := func(k string) string {
		if v, ok := props[k]; ok {
			s, _ := v.Value().(string)
			return s
		}
		return ""
	}
	var pms []pixmap
	status := str("Status")
	nameKey, pmKey := "IconName", "IconPixmap"
	if status == "NeedsAttention" && (str("AttentionIconName") != "" || props["AttentionIconPixmap"].Value() != nil) {
		nameKey, pmKey = "AttentionIconName", "AttentionIconPixmap"
	}
	img := themedIcon(str(nameKey), str("IconThemePath"))
	if img == nil {
		if v, ok := props[pmKey]; ok {
			v.Store(&pms)
			img = bestPixmap(pms)
		}
	}
	var tt trayTooltip
	if v, ok := props["ToolTip"]; ok {
		v.Store(&tt)
	}
	tip := tt.Title
	if tt.Desc != "" {
		tip += "\n" + tt.Desc
	}
	if tip == "" {
		tip = str("Title")
	}
	var menu dbus.ObjectPath
	if v, ok := props["Menu"]; ok {
		menu, _ = v.Value().(dbus.ObjectPath)
	}
	isMenu := false
	if v, ok := props["ItemIsMenu"]; ok {
		isMenu, _ = v.Value().(bool)
	}
	t.mu.Lock()
	ic.id, ic.title, ic.status, ic.img, ic.tip, ic.menu, ic.itemIsMenu = str("Id"), str("Title"), status, img, tip, menu, isMenu
	t.mu.Unlock()
}

func (t *tray) visible() []*trayIcon {
	var out []*trayIcon
	for _, ic := range t.icons {
		if ic.status != "Passive" && ic.img != nil {
			out = append(out, ic)
		}
	}
	return out
}

// render composes all visible icons into the item's single image.
func (t *tray) render() {
	t.mu.Lock()
	vis := t.visible()
	t.mu.Unlock()
	if len(vis) == 0 {
		t.it.post(itemUpdate{img: image.NewRGBA(image.Rect(0, 0, 1, 1)), w: 0, force: true})
		return
	}
	w := len(vis)*iconSize + (len(vis)-1)*trayGap
	img := image.NewRGBA(image.Rect(0, 0, w, iconSize))
	for i, ic := range vis {
		x := i * (iconSize + trayGap)
		draw.Draw(img, image.Rect(x, 0, x+iconSize, iconSize), ic.img, image.Point{}, draw.Over)
	}
	t.it.post(itemUpdate{img: img, w: w + 2*trayEdge})
}

func (t *tray) iconAt(x int) *trayIcon {
	t.mu.Lock()
	defer t.mu.Unlock()
	vis := t.visible()
	i := (x - trayEdge) / (iconSize + trayGap)
	if x < trayEdge || i < 0 || i >= len(vis) {
		return nil
	}
	return vis[i]
}

func (t *tray) tipAt(x int) string {
	if ic := t.iconAt(x); ic != nil {
		return ic.tip
	}
	return ""
}

// onClick: left activates (or opens the menu for menu-only items), middle is the
// secondary action, right asks the item for its context menu.
func (t *tray) onClick(x, y, btn int) {
	ic := t.iconAt(x)
	if ic == nil || t.conn == nil {
		return
	}
	sx, sy := int32(t.it.x+x), int32(int(panelScreenY)+y)
	obj := t.conn.Object(ic.owner, ic.path)
	switch btn {
	case 1:
		if ic.itemIsMenu && ic.menu != "" {
			go t.showMenu(ic, int(sx))
			return
		}
		method := itemIface + ".Activate"
		if ic.itemIsMenu {
			method = itemIface + ".ContextMenu"
		}
		go obj.Call(method, 0, sx, sy)
	case 2:
		go obj.Call(itemIface+".SecondaryActivate", 0, sx, sy)
	case 3:
		if ic.menu != "" {
			go t.showMenu(ic, int(sx))
			return
		}
		go obj.Call(itemIface+".ContextMenu", 0, sx, sy)
	case 4, 5:
		d := int32(-1)
		if btn == 5 {
			d = 1
		}
		go obj.Call(itemIface+".Scroll", 0, d, "vertical")
	}
}

const menuIface = "com.canonical.dbusmenu"

// showMenu fetches the item's dbusmenu layout and asks the main goroutine to pop it up.
func (t *tray) showMenu(ic *trayIcon, anchorX int) {
	obj := t.conn.Object(ic.owner, ic.menu)
	obj.Call(menuIface+".AboutToShow", 0, int32(0)) // lets the app refresh its menu
	call := obj.Call(menuIface+".GetLayout", 0, int32(0), int32(-1), []string{})
	if call.Err != nil || len(call.Body) < 2 {
		return
	}
	root, ok := call.Body[1].([]interface{})
	if !ok {
		return
	}
	top := parseMenuNode(root)
	if top == nil || len(top.children) == 0 {
		return
	}
	menuReqs <- menuReq{items: top.children, anchorX: anchorX, onSelect: func(mi *menuItem) {
		go obj.Call(menuIface+".Event", 0, mi.id, "clicked", dbus.MakeVariant(int32(0)), uint32(time.Now().Unix()))
	}}
}

// parseMenuNode converts a dbusmenu layout node (ia{sv}av) into menuItems.
func parseMenuNode(n []interface{}) *menuItem {
	if len(n) < 3 {
		return nil
	}
	id, _ := n[0].(int32)
	props, _ := n[1].(map[string]dbus.Variant)
	pstr := func(k string) string {
		if v, ok := props[k]; ok {
			s, _ := v.Value().(string)
			return s
		}
		return ""
	}
	pbool := func(k string, def bool) bool {
		if v, ok := props[k]; ok {
			if b, ok := v.Value().(bool); ok {
				return b
			}
		}
		return def
	}
	mi := &menuItem{id: id, label: pstr("label"), sep: pstr("type") == "separator",
		disabled: !pbool("enabled", true), toggle: pstr("toggle-type")}
	if v, ok := props["toggle-state"]; ok {
		if s, ok := v.Value().(int32); ok {
			mi.checked = s == 1
		}
	}
	if nm := pstr("icon-name"); nm != "" {
		mi.icon = loadIconSized(nm, 16)
	}
	kids, _ := n[2].([]dbus.Variant)
	for _, kv := range kids {
		kn, _ := kv.Value().([]interface{})
		if child := parseMenuNode(kn); child != nil && pboolOf(kn, "visible") {
			mi.children = append(mi.children, child)
		}
	}
	return mi
}

func pboolOf(n []interface{}, key string) bool {
	if len(n) < 2 {
		return true
	}
	props, _ := n[1].(map[string]dbus.Variant)
	if v, ok := props[key]; ok {
		if b, ok := v.Value().(bool); ok {
			return b
		}
	}
	return true
}

// rescan scans a few times: some apps (blueman) reconnect to the bus when the watcher
// changes hands and only publish their item a moment later.
func (t *tray) rescan() {
	for _, d := range []time.Duration{time.Second, 4 * time.Second, 10 * time.Second} {
		time.Sleep(d)
		t.scanForItems()
	}
}

// scanForItems finds live StatusNotifier items by introspecting every bus
// connection, for use after taking over as watcher: the previous watcher's list
// died with it and not every app re-registers (blueman does not).
func (t *tray) scanForItems() {
	var names []string
	if err := t.conn.BusObject().Call("org.freedesktop.DBus.ListNames", 0).Store(&names); err != nil {
		return
	}
	self := t.conn.Names()[0]
	for _, n := range names {
		if !strings.HasPrefix(n, ":") || n == self {
			continue
		}
		t.scanNode(n, "/", 0)
	}
}

type introNode struct {
	Interfaces []struct {
		Name string `xml:"name,attr"`
	} `xml:"interface"`
	Nodes []struct {
		Name string `xml:"name,attr"`
	} `xml:"node"`
}

func (t *tray) scanNode(bus, path string, depth int) {
	if depth > 4 {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 700*time.Millisecond)
	defer cancel()
	var xmlData string
	if err := t.conn.Object(bus, dbus.ObjectPath(path)).CallWithContext(ctx, "org.freedesktop.DBus.Introspectable.Introspect", 0).Store(&xmlData); err != nil {
		return
	}
	var n introNode
	if xml.Unmarshal([]byte(xmlData), &n) != nil {
		return
	}
	for _, i := range n.Interfaces {
		if i.Name == itemIface {
			log.Println("tray: scan found", bus+path)
			t.register("", bus+path)
			return
		}
	}
	for _, c := range n.Nodes {
		if c.Name != "" {
			t.scanNode(bus, strings.TrimSuffix(path, "/")+"/"+c.Name, depth+1)
		}
	}
}
