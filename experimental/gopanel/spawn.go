package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// supervisor keeps one helper process running: it starts the helper if no connection
// from that name appears shortly after panel start (a surviving helper from a previous
// panel instance reconnects within a second and is adopted), restarts it if it dies,
// and terminates it when stopped. `gopanel restart` keeps the same pid, so children
// find their parent still alive and just reconnect.
type supervisor struct {
	name      string
	connected func() bool
	stop      chan struct{}
}

func helperPath(name string) string {
	exe, _ := os.Executable()
	home, _ := os.UserHomeDir()
	for _, p := range []string{
		filepath.Join(filepath.Dir(exe), "helpers", name, name),
		filepath.Join(home, ".local/lib/gopanel", name),
	} {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
	}
	return ""
}

func (s *supervisor) run() {
	select {
	case <-time.After(4 * time.Second): // old helpers reconnect after a restart; do not spawn duplicates
	case <-s.stop:
		return
	}
	path := helperPath(s.name)
	if path == "" {
		log.Printf("helper %q: no binary found, not started", s.name)
		return
	}
	backoff := time.Second
	for {
		if s.connected() {
			select {
			case <-time.After(2 * time.Second):
				continue
			case <-s.stop:
				return
			}
		}
		cmd := exec.Command(path)
		cmd.Env = append(os.Environ(), fmt.Sprintf("GOPANEL_PARENT=%d", os.Getpid()))
		cmd.Stdout, cmd.Stderr = os.Stderr, os.Stderr
		started := time.Now()
		if err := cmd.Start(); err != nil {
			log.Printf("helper %s: %v", s.name, err)
		} else {
			log.Printf("helper %s: started pid %d", s.name, cmd.Process.Pid)
			done := make(chan struct{})
			go func() { cmd.Wait(); close(done) }()
			select {
			case <-done:
				log.Printf("helper %s exited", s.name)
			case <-s.stop:
				cmd.Process.Signal(syscall.SIGTERM)
				<-done
				return
			}
		}
		if time.Since(started) > 10*time.Second {
			backoff = time.Second
		}
		select {
		case <-time.After(backoff):
		case <-s.stop:
			return
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

// reapZombies collects exited helpers that this process image never started: after
// `gopanel restart` (exec) the children of the previous image are ours, but nobody Wait()s
// for them, so a killed or exited one would stay a zombie.
func reapZombies() {
	for range time.Tick(5 * time.Second) {
		me := strconv.Itoa(os.Getpid())
		ents, _ := os.ReadDir("/proc")
		for _, e := range ents {
			pid, err := strconv.Atoi(e.Name())
			if err != nil {
				continue
			}
			b, err := os.ReadFile("/proc/" + e.Name() + "/stat")
			if err != nil {
				continue
			}
			// "pid (comm) S ppid ..." -- comm may contain spaces/parens, so cut after the last ')'
			s := string(b)
			f := strings.Fields(s[strings.LastIndex(s, ")")+1:])
			if len(f) > 1 && f[0] == "Z" && f[1] == me {
				syscall.Wait4(pid, nil, syscall.WNOHANG, nil)
			}
		}
	}
}
