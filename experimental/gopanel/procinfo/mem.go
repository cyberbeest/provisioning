package procinfo

import (
	"os"
	"sort"
	"strconv"
	"strings"
)

// MemProc is one row of a top-RAM list.
type MemProc struct {
	Name   string
	PssKiB uint64
}

func kibField(text, key string) (uint64, bool) {
	for _, ln := range strings.Split(text, "\n") {
		if strings.HasPrefix(ln, key) {
			f := strings.Fields(ln[len(key):])
			if len(f) > 0 {
				v, err := strconv.ParseUint(f[0], 10, 64)
				return v, err == nil
			}
		}
	}
	return 0, false
}

const minTopKiB = 1024 // hide processes using less than 1 MiB

// TopMem returns the n biggest process groups by proportional set size. PSS (not RSS)
// because a shared library page mapped into N processes counts fully in every one's RSS,
// which would wildly overstate e.g. ten GTK wrapper processes; PSS sums to real usage.
// Falls back to VmRSS when smaps_rollup can't be read. One scan, no delta needed.
func TopMem(n int, friendly bool) []MemProc {
	totals := map[string]uint64{}
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		pid := e.Name()
		if pid[0] < '0' || pid[0] > '9' {
			continue
		}
		st, err := os.ReadFile("/proc/" + pid + "/status")
		if err != nil {
			continue
		}
		s := string(st)
		var name string
		for _, ln := range strings.Split(s, "\n") {
			if strings.HasPrefix(ln, "Name:") {
				name = strings.TrimSpace(ln[5:])
				break
			}
		}
		rss, ok := kibField(s, "VmRSS:")
		if name == "" || !ok {
			continue
		}
		pss := rss
		if sm, err := os.ReadFile("/proc/" + pid + "/smaps_rollup"); err == nil {
			if v, ok := kibField(string(sm), "Pss:"); ok {
				pss = v
			}
		}
		if pss < minTopKiB {
			continue
		}
		if friendly {
			name = Alias(name)
		}
		totals[name] += pss
	}
	var rows []MemProc
	for k, v := range totals {
		rows = append(rows, MemProc{k, v})
	}
	sort.Slice(rows, func(i, j int) bool { return rows[i].PssKiB > rows[j].PssKiB })
	if len(rows) > n {
		rows = rows[:n]
	}
	return rows
}
