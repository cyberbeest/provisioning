package main

import (
	"bufio"
	"fmt"
	"log"
	"net"
	"os"
	"path/filepath"
	"strings"
)

// Control socket: one line in ("reload", "restart", "quit"), one line out.
// Same-uid processes can connect, including firejailed ones whose view of
// $XDG_RUNTIME_DIR includes it, so commands must stay harmless (no "launch X").
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
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				line, _ := bufio.NewReader(conn).ReadString('\n')
				switch cmd := strings.TrimSpace(line); cmd {
				case "reload", "restart", "quit":
					cmds <- cmd
					fmt.Fprintln(conn, "ok")
				default:
					fmt.Fprintln(conn, "unknown command; try: reload restart quit")
				}
			}()
		}
	}()
}
