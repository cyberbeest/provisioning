package main

import (
	"bufio"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Control socket: one line in ("reload", "restart", "quit"), one line out.
// Only same-uid (or root) processes in the panel's own mount namespace are admitted (see
// peer.go), so firejailed apps are refused even if they can see the path. Commands must
// still stay harmless (no "launch X"): any unsandboxed process of the user may send them.
func sockPath() string {
	dir := os.Getenv("XDG_RUNTIME_DIR")
	if dir == "" {
		dir = os.TempDir()
	}
	return filepath.Join(dir, "gopanel.sock")
}

func ctlClient(cmd string) {
	conn, err := net.Dial("unix", sockPath())
	if err != nil {
		fmt.Fprintln(os.Stderr, "gopanel not running:", err)
		os.Exit(1)
	}
	defer conn.Close()
	fmt.Fprintln(conn, cmd)
	reply, _ := bufio.NewReader(conn).ReadString('\n')
	fmt.Print(reply)
}

// ctlServer forwards valid commands to cmds; the main loop acts on them.
func ctlServer(cmds chan<- string) {
	path := sockPath()
	if conn, err := net.Dial("unix", path); err == nil { // already running?
		conn.Close()
		log.Fatal("gopanel already running")
	}
	os.Remove(path) // stale
	ln, err := net.Listen("unix", path)
	if err != nil {
		log.Println("control socket disabled:", err)
		return
	}
	os.Chmod(path, 0o600)
	go acceptLoop(ln, "control socket", false, 8, func(conn net.Conn) {
		defer conn.Close()
		conn.SetDeadline(time.Now().Add(2 * time.Second))
		line, _ := bufio.NewReader(io.LimitReader(conn, 256)).ReadString('\n')
		switch cmd := strings.TrimSpace(line); cmd {
		case "reload", "restart", "quit", "menu", "yield", "calendar", "volume", "power", "dismiss", "unreserve", "profile", "layout":
			cmds <- cmd
			fmt.Fprintln(conn, "ok")
		default:
			fmt.Fprintln(conn, "unknown command; try: reload restart quit menu")
		}
	})
}
