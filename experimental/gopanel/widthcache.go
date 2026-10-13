package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// Item widths of the last run, so the panel opens with everything already where it will end
// up instead of shuffling while helpers connect and the tray fills. Only items whose width is
// decided asynchronously are cached; one that does not report within a few seconds gets its
// reserved space back ("unreserve").

var (
	widthCache  = map[string]int{}
	widthLoaded bool
	widthSaved  string
)

func widthCachePath() string {
	dir, err := os.UserCacheDir()
	if err != nil {
		return ""
	}
	return filepath.Join(dir, "gopanel", "widths.tsv")
}

func itemKey(i int, it *item) string { return fmt.Sprintf("%d:%s:%s", i, it.kind, it.name) }

func cachesWidth(it *item) bool {
	switch it.kind {
	case "tray", "helper", "genmon", "power":
		return true
	}
	return false
}

func loadWidthCache() {
	widthLoaded = true
	p := widthCachePath()
	if p == "" {
		return
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return
	}
	widthSaved = string(b)
	for _, l := range strings.Split(string(b), "\n") {
		if k, v, ok := strings.Cut(l, "\t"); ok {
			if n, err := strconv.Atoi(v); err == nil && n > 0 && n < 2000 {
				widthCache[k] = n
			}
		}
	}
}

// reserveWidths gives not-yet-sized items their last known width.
func reserveWidths(items []*item) {
	if !widthLoaded {
		loadWidthCache()
	}
	for i, it := range items {
		if it.w == 0 && !it.expand && cachesWidth(it) {
			if w := widthCache[itemKey(i, it)]; w > 0 {
				it.w, it.reserved = w, true
			}
		}
	}
}

// unreserve releases the space of items that never reported a width; true if anything changed.
func unreserve(items []*item) bool {
	changed := false
	for _, it := range items {
		if it.reserved {
			it.w, it.reserved = 0, false
			changed = true
		}
	}
	return changed
}

// saveWidths writes the current widths if they changed (called after layout passes).
func saveWidths(items []*item) {
	var lines []string
	for i, it := range items {
		if cachesWidth(it) && it.w > 0 && !it.reserved {
			lines = append(lines, itemKey(i, it)+"\t"+strconv.Itoa(it.w))
		}
	}
	sort.Strings(lines)
	out := strings.Join(lines, "\n") + "\n"
	if out == widthSaved || len(lines) == 0 {
		return
	}
	widthSaved = out
	if p := widthCachePath(); p != "" {
		go func() {
			os.MkdirAll(filepath.Dir(p), 0o755)
			os.WriteFile(p, []byte(out), 0o644)
		}()
	}
}
