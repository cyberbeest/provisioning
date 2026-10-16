package main

import (
	"errors"
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// Who may talk to the panel's two sockets.
//
// Firejail'd apps (browsers, messengers, wallets) run in their own mount namespace and
// their profiles already hide $XDG_RUNTIME_DIR/gopanel*.sock. This is the second wall: even
// if a profile or a --whitelist ever exposes the path, the connection is refused because
// the peer (SO_PEERCRED) is not in the panel's mount namespace. Tray icons are unaffected:
// they arrive over D-Bus (StatusNotifier) and XEmbed, never over these sockets.
//
//   - control socket:  same uid (or root) and same mount namespace as the panel.
//   - helper socket:   additionally a descendant of the panel, because helpers are only ever
//     started by the supervisor. A random same-uid process cannot take over a helper's slot.
//
// Unreadable /proc/<pid>/ns/mnt (non-dumpable, other pid namespace, already exited) fails
// closed. The pid could in theory be recycled between accept and check; the worst case is
// a spurious refusal or a peer that was admitted a moment before it exited.

func peerUcred(conn net.Conn) (*syscall.Ucred, error) {
	uc, ok := conn.(*net.UnixConn)
	if !ok {
		return nil, errors.New("not a unix connection")
	}
	raw, err := uc.SyscallConn()
	if err != nil {
		return nil, err
	}
	var cred *syscall.Ucred
	var cerr error
	if err := raw.Control(func(fd uintptr) {
		cred, cerr = syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
	}); err != nil {
		return nil, err
	}
	return cred, cerr
}

// checkPeer returns nil if conn's peer may use the socket; helper selects the stricter rule.
func checkPeer(conn net.Conn, helper bool) error {
	cred, err := peerUcred(conn)
	if err != nil {
		return err
	}
	if cred.Uid == 0 && !helper {
		return nil // root can do anything to us anyway (sudo helper scripts)
	}
	if int(cred.Uid) != os.Getuid() {
		return fmt.Errorf("uid %d", cred.Uid)
	}
	pid := int(cred.Pid)
	mine, err := os.Readlink("/proc/self/ns/mnt")
	if err != nil {
		return err
	}
	theirs, err := os.Readlink("/proc/" + strconv.Itoa(pid) + "/ns/mnt")
	if err != nil {
		return fmt.Errorf("pid %d: mount namespace unreadable (sandboxed or gone)", pid)
	}
	if theirs != mine {
		return fmt.Errorf("pid %d: other mount namespace (sandboxed)", pid)
	}
	if helper && !descendantOf(pid, os.Getpid()) {
		return fmt.Errorf("pid %d: not started by the panel", pid)
	}
	return nil
}

// descendantOf reports whether pid is ancestor or one of its descendants.
func descendantOf(pid, ancestor int) bool {
	for depth := 0; depth < 64 && pid > 1; depth++ {
		if pid == ancestor {
			return true
		}
		b, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
		if err != nil {
			return false
		}
		s := string(b)
		f := strings.Fields(s[strings.LastIndexByte(s, ')')+1:]) // state ppid ...
		if len(f) < 2 {
			return false
		}
		if pid, err = strconv.Atoi(f[1]); err != nil {
			return false
		}
	}
	return pid == ancestor
}

// acceptLoop runs handle for every admitted connection, at most max at a time. It never
// gives up on a transient Accept error (fd exhaustion must not silence the socket for good).
func acceptLoop(ln net.Listener, what string, helper bool, max int, handle func(net.Conn)) {
	sem := make(chan struct{}, max)
	var lastLog time.Time
	logf := func(format string, a ...any) { // one line per second, a flood must not fill the journal
		if time.Since(lastLog) > time.Second {
			lastLog = time.Now()
			log.Printf(what+": "+format, a...)
		}
	}
	for {
		conn, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return
			}
			logf("accept: %v", err)
			time.Sleep(100 * time.Millisecond)
			continue
		}
		if err := checkPeer(conn, helper); err != nil {
			logf("refused: %v", err)
			conn.Close()
			continue
		}
		select {
		case sem <- struct{}{}:
			go func() {
				defer func() { <-sem }()
				handle(conn)
			}()
		default:
			logf("refused: too many connections")
			conn.Close()
		}
	}
}
