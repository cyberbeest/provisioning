// Package appmenu builds the application menu the way garcon does for Xfce: .desktop
// entries organised by an XDG menu file (merged system + user), with .directory files
// naming and iconifying the categories.
package appmenu

import (
	"bufio"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Entry is one application.
type Entry struct {
	ID          string // desktop file ID, e.g. "xfce4-terminal.desktop"
	File        string
	Name        string
	GenericName string
	Comment     string
	Icon        string
	Exec        string
	Path        string
	Terminal    bool
	Categories  []string
	Keywords    []string
}

func hasCat(e *Entry, c string) bool {
	for _, x := range e.Categories {
		if x == c {
			return true
		}
	}
	return false
}

// locales returns the locale lookup chain, most specific first ("de_DE" -> de_DE, de).
func locales() []string {
	v := os.Getenv("LANGUAGE")
	if v == "" {
		v = os.Getenv("LC_MESSAGES")
	}
	if v == "" {
		v = os.Getenv("LANG")
	}
	var out []string
	for _, l := range strings.Split(v, ":") {
		l = strings.SplitN(l, ".", 2)[0]
		l = strings.SplitN(l, "@", 2)[0]
		if l == "" || l == "C" || l == "POSIX" {
			continue
		}
		out = append(out, l)
		if i := strings.IndexByte(l, '_'); i > 0 {
			out = append(out, l[:i])
		}
	}
	return out
}

// ReadGroup returns the key/value pairs of one group of a desktop-style file, with
// localized keys resolved ("Name[de]" wins over "Name" when the locale matches).
func ReadGroup(path, group string) map[string]string {
	f, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer f.Close()
	locs := locales()
	best := map[string]int{} // key -> locale rank (lower is better; len(locs) = unlocalized)
	out := map[string]string{}
	in := false
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64*1024), 1<<20)
	for sc.Scan() {
		ln := strings.TrimSpace(sc.Text())
		if ln == "" || ln[0] == '#' {
			continue
		}
		if ln[0] == '[' {
			in = ln == "["+group+"]"
			continue
		}
		if !in {
			continue
		}
		k, v, ok := strings.Cut(ln, "=")
		if !ok {
			continue
		}
		k, v = strings.TrimSpace(k), strings.TrimSpace(v)
		base, loc := k, ""
		if i := strings.IndexByte(k, '['); i > 0 && strings.HasSuffix(k, "]") {
			base, loc = k[:i], k[i+1:len(k)-1]
		}
		rank := len(locs)
		if loc != "" {
			rank = -1
			for i, l := range locs {
				if l == loc {
					rank = i
					break
				}
			}
			if rank < 0 {
				continue
			}
		}
		if r, seen := best[base]; !seen || rank < r {
			best[base], out[base] = rank, v
		}
	}
	return out
}

func splitList(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ";") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func inList(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// loadEntry parses one .desktop file; nil if it must not be shown in an Xfce menu.
func loadEntry(path, id string) *Entry {
	m := ReadGroup(path, "Desktop Entry")
	if m == nil || m["Type"] != "Application" || m["Name"] == "" || m["Exec"] == "" {
		return nil
	}
	if m["Hidden"] == "true" || m["NoDisplay"] == "true" {
		return nil
	}
	if only := splitList(m["OnlyShowIn"]); len(only) > 0 && !inList(only, "XFCE") {
		return nil
	}
	if inList(splitList(m["NotShowIn"]), "XFCE") {
		return nil
	}
	if t := m["TryExec"]; t != "" {
		if _, err := exec.LookPath(t); err != nil {
			return nil
		}
	}
	return &Entry{
		ID: id, File: path, Name: m["Name"], GenericName: m["GenericName"], Comment: m["Comment"],
		Icon: m["Icon"], Exec: m["Exec"], Path: m["Path"], Terminal: m["Terminal"] == "true",
		Categories: splitList(m["Categories"]), Keywords: splitList(m["Keywords"]),
	}
}

func dataDirs() []string {
	home, _ := os.UserHomeDir()
	h := os.Getenv("XDG_DATA_HOME")
	if h == "" {
		h = filepath.Join(home, ".local/share")
	}
	dirs := []string{h}
	d := os.Getenv("XDG_DATA_DIRS")
	if d == "" {
		d = "/usr/local/share:/usr/share"
	}
	return append(dirs, strings.Split(d, ":")...)
}

// scanApps loads every entry under <dir>/applications for the given base dirs; earlier
// directories take precedence for the same desktop file ID.
func scanApps(baseDirs []string) map[string]*Entry {
	out := map[string]*Entry{}
	for _, base := range baseDirs {
		root := filepath.Join(base, "applications")
		filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
			if err != nil || d.IsDir() || !strings.HasSuffix(p, ".desktop") {
				return nil
			}
			rel, _ := filepath.Rel(root, p)
			id := strings.ReplaceAll(rel, "/", "-")
			if _, seen := out[id]; seen {
				return nil
			}
			if e := loadEntry(p, id); e != nil {
				out[id] = e
			} else {
				out[id] = nil // shadowed or hidden: the ID stays taken
			}
			return nil
		})
	}
	return out
}
