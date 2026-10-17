package main

import (
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
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

func cachesWidth(it *item) bool { return !it.expand }

// isTray: items whose width depends on which apps happen to be running (Telegram and friends
// dock their icon some seconds after login). They keep their recorded slot for longer, and a
// different tray is no reason to forget the recorded layout.
func isTray(it *item) bool { return it.kind == "tray" || it.kind == "xtray" }

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

// reserveWidths gives not-yet-sized items their last known width, so they appear in their
// final place as they come up, instead of everything shifting while the rest connects.
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
		if isTray(it) {
			it.hold = widthCache[itemKey(i, it)]
		}
	}
}

// unreserve releases the space of items that never reported a width; true if anything changed.
// Tray items are only released with late set.
func unreserve(items []*item, late bool) bool {
	changed := false
	for _, it := range items {
		if isTray(it) {
			if !late {
				continue
			}
			if it.hold > 0 {
				it.hold, changed = 0, true
			}
		}
		if it.reserved {
			it.w, it.reserved = 0, false
			changed = true
		}
	}
	return changed
}

// recordWidths schedules a snapshot of the layout. It is taken only after things have been
// quiet for a while, never mid-startup, so the cache always holds a settled layout.
var (
	recordTimer *time.Timer
	recordArmed bool // false until the startup check has run
)

func scheduleRecord() {
	if !recordArmed {
		return
	}
	if recordTimer != nil {
		recordTimer.Stop()
	}
	recordTimer = time.AfterFunc(5*time.Second, func() { ctlCmds <- "record-widths" })
}

// saveWidths writes the current widths of every confirmed item if they changed.
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

// checkWidths runs once startup has had time to finish: if the layout did not come out the
// way the cache predicted, the recorded widths are forgotten (the next quiet moment records
// the real ones), so a changed setup never keeps being "corrected" from stale data.
func checkWidths(items []*item) {
	for i, it := range items {
		if want := widthCache[itemKey(i, it)]; cachesWidth(it) && !isTray(it) && want > 0 && it.w != want {
			log.Printf("layout differs from the recorded one (%s: %d, recorded %d): forgetting it", itemKey(i, it), it.w, want)
			widthCache = map[string]int{}
			widthSaved = ""
			if p := widthCachePath(); p != "" {
				os.Remove(p)
			}
			return
		}
	}
}
