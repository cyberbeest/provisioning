// io-scanner: green vertical LED sweep tracking disk I/O MB/s. Port of io-scanner.c.
package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	"gopanel/scanner"
)

const sectorBytes = 512.0

type ioSource struct {
	prevRead, prevWrite uint64
	havePrev            bool
	prevAt              time.Time
	read, write, smooth float64
}

// isPhysicalDisk: /sys/block/<name>/slaves exists and is empty. Partitions have no
// /sys/block entry; dm-crypt/LVM devices list their underlying disks as slaves, so this
// avoids counting the same I/O twice on a LUKS machine.
func isPhysicalDisk(name string) bool {
	ents, err := os.ReadDir("/sys/block/" + name + "/slaves")
	return err == nil && len(ents) == 0
}

func (s *ioSource) Sample() {
	b, err := os.ReadFile("/proc/diskstats")
	if err != nil {
		return
	}
	var rd, wr uint64
	any := false
	for _, ln := range strings.Split(string(b), "\n") {
		var major, minor int
		var name string
		var rdIos, rdMerges, rs, rdTicks, wrIos, wrMerges, ws, wrTicks uint64
		if n, _ := fmt.Sscanf(ln, "%d %d %s %d %d %d %d %d %d %d %d", &major, &minor, &name,
			&rdIos, &rdMerges, &rs, &rdTicks, &wrIos, &wrMerges, &ws, &wrTicks); n < 11 || !isPhysicalDisk(name) {
			continue
		}
		rd += rs
		wr += ws
		any = true
	}
	if !any {
		return
	}
	now := time.Now()
	if s.havePrev {
		if dt := now.Sub(s.prevAt).Seconds(); dt > 0 {
			s.read = float64(rd-s.prevRead) * sectorBytes / 1e6 / dt
			s.write = float64(wr-s.prevWrite) * sectorBytes / 1e6 / dt
			s.smooth += (s.read + s.write - s.smooth) * 0.35
		}
	}
	s.prevRead, s.prevWrite, s.prevAt, s.havePrev = rd, wr, now, true
}

func (s *ioSource) Value() float64 { return s.smooth }

func (s *ioSource) Tooltip() string {
	status := "= Very Heavy I/O ="
	switch m := s.smooth; {
	case m < 1:
		status = "= Idle ="
	case m < 20:
		status = "= Light I/O ="
	case m < 100:
		status = "= Busy ="
	case m < 400:
		status = "= Heavy I/O ="
	}
	return fmt.Sprintf("Disk I/O: %.1f MB/s (read %.1f, write %.1f)\n%s", s.read+s.write, s.read, s.write, status)
}

func main() {
	scanner.Main(scanner.Config{
		Name:  "io-scanner",
		LedOn: [3]float64{0, 0.60, 0.08}, LedOff: [3]float64{0, 0.20, 0.05},
		Factor: 0.25, Exponent: 0.301, MinRate: 0, MaxRate: 2.86,
		FPS: 40, OffIsBg: true, SineSweep: true, Enabled: true,
	}, &ioSource{})
}
