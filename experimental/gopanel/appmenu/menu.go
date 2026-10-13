package appmenu

import (
	"encoding/xml"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
)

// node is a generic element so document order is preserved (rules and merges are
// order-sensitive).
type node struct {
	Name     string
	Text     string
	Attr     map[string]string
	Children []*node
}

func parseXML(path string) (*node, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	dec := xml.NewDecoder(f)
	dec.Strict = false
	var stack []*node
	var root *node
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			n := &node{Name: t.Name.Local, Attr: map[string]string{}}
			for _, a := range t.Attr {
				n.Attr[a.Name.Local] = a.Value
			}
			if len(stack) > 0 {
				p := stack[len(stack)-1]
				p.Children = append(p.Children, n)
			} else {
				root = n
			}
			stack = append(stack, n)
		case xml.EndElement:
			stack = stack[:len(stack)-1]
		case xml.CharData:
			if len(stack) > 0 {
				stack[len(stack)-1].Text += strings.TrimSpace(string(t))
			}
		}
	}
	return root, nil
}

func configDirs() []string {
	home, _ := os.UserHomeDir()
	h := os.Getenv("XDG_CONFIG_HOME")
	if h == "" {
		h = filepath.Join(home, ".config")
	}
	d := os.Getenv("XDG_CONFIG_DIRS")
	if d == "" {
		d = "/etc/xdg"
	}
	return append([]string{h}, strings.Split(d, ":")...)
}

// expand resolves <MergeFile> elements in place, recursively.
func expand(n *node, selfPath string, depth int) {
	if depth > 8 {
		return
	}
	var out []*node
	for _, c := range n.Children {
		switch c.Name {
		case "MergeFile":
			p := c.Text
			if c.Attr["type"] == "parent" && p == "" {
				// the next file of the same name in the config dirs after ours
				found := false
				for _, d := range configDirs() {
					cand := filepath.Join(d, "menus", filepath.Base(selfPath))
					if found {
						p = cand
						if _, err := os.Stat(cand); err == nil {
							break
						}
						p = ""
					}
					if cand == selfPath {
						found = true
					}
				}
			} else if p != "" && !filepath.IsAbs(p) {
				p = filepath.Join(filepath.Dir(selfPath), p)
			}
			if p == "" {
				continue
			}
			if m, err := parseXML(p); err == nil && m != nil {
				expand(m, p, depth+1)
				out = append(out, m.Children...)
			}
		case "Menu":
			expand(c, selfPath, depth)
			out = append(out, c)
		default:
			out = append(out, c)
		}
	}
	n.Children = out
}

// mergeSubmenus combines sibling <Menu> elements of the same <Name> (later ones appended).
func mergeSubmenus(n *node) {
	var out []*node
	byName := map[string]*node{}
	for _, c := range n.Children {
		if c.Name != "Menu" {
			out = append(out, c)
			continue
		}
		name := ""
		for _, cc := range c.Children {
			if cc.Name == "Name" {
				name = cc.Text
			}
		}
		if prev, ok := byName[name]; ok {
			prev.Children = append(prev.Children, c.Children...)
			continue
		}
		byName[name] = c
		out = append(out, c)
	}
	n.Children = out
	for _, c := range n.Children {
		if c.Name == "Menu" {
			mergeSubmenus(c)
		}
	}
}

type matcher func(*Entry) bool

func parseMatcher(n *node) matcher {
	switch n.Name {
	case "All":
		return func(*Entry) bool { return true }
	case "Category":
		c := n.Text
		return func(e *Entry) bool { return hasCat(e, c) }
	case "Filename":
		f := n.Text
		return func(e *Entry) bool { return e.ID == f }
	case "Not":
		var subs []matcher
		for _, c := range n.Children {
			subs = append(subs, parseMatcher(c))
		}
		return func(e *Entry) bool {
			for _, s := range subs {
				if s(e) {
					return false
				}
			}
			return true
		}
	case "And":
		var subs []matcher
		for _, c := range n.Children {
			subs = append(subs, parseMatcher(c))
		}
		return func(e *Entry) bool {
			for _, s := range subs {
				if !s(e) {
					return false
				}
			}
			return true
		}
	default: // Or, Include, Exclude: any child matches
		var subs []matcher
		for _, c := range n.Children {
			subs = append(subs, parseMatcher(c))
		}
		return func(e *Entry) bool {
			for _, s := range subs {
				if s(e) {
					return true
				}
			}
			return false
		}
	}
}

type menu struct {
	name        string
	directory   string
	deleted     bool
	onlyUnalloc bool
	rules       []rule
	subs        []*menu
	appDirs     []string
	dirDirs     []string
	entries     map[string]*Entry
}

type rule struct {
	include bool
	m       matcher
}

func buildMenu(n *node, parent *menu) *menu {
	m := &menu{entries: map[string]*Entry{}}
	if parent != nil {
		m.appDirs, m.dirDirs = parent.appDirs, parent.dirDirs
	}
	for _, c := range n.Children {
		switch c.Name {
		case "Name":
			m.name = c.Text
		case "Directory":
			m.directory = c.Text
		case "Deleted":
			m.deleted = true
		case "NotDeleted":
			m.deleted = false
		case "OnlyUnallocated":
			m.onlyUnalloc = true
		case "NotOnlyUnallocated":
			m.onlyUnalloc = false
		case "DefaultAppDirs":
			for _, d := range dataDirs() {
				m.appDirs = append(m.appDirs, d)
			}
		case "DefaultDirectoryDirs":
			for _, d := range dataDirs() {
				m.dirDirs = append(m.dirDirs, filepath.Join(d, "desktop-directories"))
			}
		case "Include":
			m.rules = append(m.rules, rule{true, parseMatcher(c)})
		case "Exclude":
			m.rules = append(m.rules, rule{false, parseMatcher(c)})
		case "Menu":
			m.subs = append(m.subs, buildMenu(c, m))
		}
	}
	return m
}

// evaluate fills each menu's entries; allocated tracks apps claimed by ordinary menus.
func (m *menu) evaluate(all map[string]*Entry, allocated map[string]bool, pass int) {
	if m.deleted {
		return
	}
	if (pass == 1) != m.onlyUnalloc {
		for id, e := range all {
			if e == nil {
				continue
			}
			if m.onlyUnalloc && allocated[id] {
				continue
			}
			ok := false
			for _, r := range m.rules {
				if r.m(e) {
					ok = r.include
				}
			}
			if ok {
				m.entries[id] = e
			}
		}
		if pass == 1 {
			for id := range m.entries {
				allocated[id] = true
			}
		}
	}
	for _, s := range m.subs {
		s.evaluate(all, allocated, pass)
	}
}

func (m *menu) collect(out map[string]*Entry) {
	if m.deleted {
		return
	}
	for id, e := range m.entries {
		out[id] = e
	}
	for _, s := range m.subs {
		s.collect(out)
	}
}

// Category is one top-level menu section as Whisker lists it.
type Category struct {
	Name, Icon string
	Entries    []*Entry // sorted by name, including nested submenus
}

// sortKey: case- and symbol-insensitive, matching the collation Whisker uses.
func sortKey(s string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(s) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func sortEntries(es []*Entry) {
	sort.SliceStable(es, func(i, j int) bool { return sortKey(es[i].Name) < sortKey(es[j].Name) })
}

func directoryInfo(m *menu) (name, icon string, hidden bool) {
	name = m.name
	if m.directory == "" {
		return
	}
	for _, d := range m.dirDirs {
		p := filepath.Join(d, m.directory)
		if g := ReadGroup(p, "Desktop Entry"); g != nil {
			if g["Name"] != "" {
				name = g["Name"]
			}
			return name, g["Icon"], g["NoDisplay"] == "true" || g["Hidden"] == "true"
		}
	}
	return
}

// Load reads the Xfce application menu (user override first) and returns the top-level
// categories alphabetically, plus every application.
func Load() ([]*Category, []*Entry, error) {
	var path string
	for _, d := range configDirs() {
		p := filepath.Join(d, "menus", "xfce-applications.menu")
		if _, err := os.Stat(p); err == nil {
			path = p
			break
		}
	}
	root, err := parseXML(path)
	if err != nil {
		return nil, nil, err
	}
	expand(root, path, 0)
	mergeSubmenus(root)
	top := buildMenu(root, nil)
	if len(top.appDirs) == 0 {
		top.appDirs = dataDirs()
	}
	all := scanApps(top.appDirs)
	allocated := map[string]bool{}
	top.evaluate(all, allocated, 1)
	top.evaluate(all, allocated, 2)

	var cats []*Category
	for _, s := range top.subs {
		name, icon, hidden := directoryInfo(s)
		if hidden || s.deleted {
			continue
		}
		set := map[string]*Entry{}
		s.collect(set)
		if len(set) == 0 {
			continue
		}
		c := &Category{Name: name, Icon: icon}
		for _, e := range set {
			c.Entries = append(c.Entries, e)
		}
		sortEntries(c.Entries)
		cats = append(cats, c)
	}
	sort.SliceStable(cats, func(i, j int) bool { return sortKey(cats[i].Name) < sortKey(cats[j].Name) })

	set := map[string]*Entry{}
	top.collect(set)
	var every []*Entry
	for _, e := range set {
		every = append(every, e)
	}
	sortEntries(every)
	return cats, every, nil
}
