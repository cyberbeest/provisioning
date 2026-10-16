package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// restartExe finds the binary to re-exec for `gopanel restart`. After an update replaced the
// files, /proc/self/exe reads "<path> (deleted)" -- and when the installer swapped the whole
// directory, <path> is where the old directory was moved to, which is gone too. So the
// running image's own path is only the first guess; then how we were started, then the
// installed locations.
func restartExe() string {
	home, _ := os.UserHomeDir()
	var cands []string
	if exe, err := os.Executable(); err == nil {
		cands = append(cands, strings.TrimSuffix(exe, " (deleted)"))
	}
	if p, err := exec.LookPath(os.Args[0]); err == nil {
		if abs, err := filepath.Abs(p); err == nil {
			cands = append(cands, abs)
		}
	}
	cands = append(cands, filepath.Join(home, ".local/bin/gopanel"), filepath.Join(home, ".local/lib/gopanel/gopanel"))
	for _, c := range cands {
		if st, err := os.Stat(c); err == nil && !st.IsDir() && st.Mode()&0o111 != 0 {
			return c
		}
	}
	return ""
}
