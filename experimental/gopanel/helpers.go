package main

import (
	"bufio"
	"fmt"
	"image"
	"io"
	"log"
	"net"
	"os"
	"strconv"
	"strings"

	"gopanel/proto"
)

// helperConn is one connected helper process. The main goroutine owns every
// field except conn/out/done; the per-connection goroutines only send events.
type helperConn struct {
	name string
	w, h int
	img  *image.RGBA
	out  chan string   // lines to the helper; dropped when full
	done chan struct{} // closed when the connection ends
	kill func()        // closes the connection
}

func (hc *helperConn) send(line string) {
	select {
	case hc.out <- line + "\n":
	default:
	}
}

type helperEvent struct {
	hc   *helperConn
	kind string // "hello", "image", "tooltip", "label", "bye"
	img  *image.RGBA
	text string
}

const maxHelperPixels = 4 << 20 // 16 MB of RGBA per frame, far beyond any panel item

// helperServer accepts helpers on a Unix socket and forwards what they say to ev.
// Same-uid processes (including jailed ones that can see the path) can connect and
// draw into the panel, but nothing here can launch or run anything.
func helperServer(ev chan<- helperEvent) {
	path := proto.SockPath()
	os.Remove(path)
	ln, err := net.Listen("unix", path)
	if err != nil {
		log.Println("helper socket disabled:", err)
		return
	}
	os.Chmod(path, 0o600)
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go serveHelper(conn, ev)
		}
	}()
}

func serveHelper(conn net.Conn, ev chan<- helperEvent) {
	defer conn.Close()
	fmt.Fprintf(conn, "panel %d\n", panelH)
	r := bufio.NewReader(conn)

	line, err := r.ReadString('\n')
	f := strings.Fields(line)
	if err != nil || len(f) != 3 || f[0] != "hello" {
		return
	}
	w, err := strconv.Atoi(f[2])
	if err != nil || w < 0 || w > 4096 {
		return
	}
	hc := &helperConn{name: f[1], w: w, h: panelH, out: make(chan string, 16), done: make(chan struct{}), kill: func() { conn.Close() }}
	hc.img = image.NewRGBA(image.Rect(0, 0, hc.w, hc.h))
	defer close(hc.done)

	go func() {
		for {
			select {
			case s := <-hc.out:
				if _, err := io.WriteString(conn, s); err != nil {
					conn.Close()
					return
				}
			case <-hc.done:
				return
			}
		}
	}()

	ev <- helperEvent{hc: hc, kind: "hello"}
	defer func() { ev <- helperEvent{hc: hc, kind: "bye"} }()

lines:
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return
		}
		for _, kind := range []string{"tooltip", "label"} {
			if line == kind+"\n" || strings.HasPrefix(line, kind+" ") {
				text := strings.TrimSuffix(strings.TrimPrefix(line, kind), "\n")
				text = strings.TrimPrefix(text, " ")
				text = strings.NewReplacer(`\n`, "\n", `\\`, `\`).Replace(text)
				ev <- helperEvent{hc: hc, kind: kind, text: text}
				continue lines
			}
		}
		f := strings.Fields(line)
		if len(f) == 3 && f[0] == "image" {
			iw, e1 := strconv.Atoi(f[1])
			ih, e2 := strconv.Atoi(f[2])
			if e1 != nil || e2 != nil || iw != hc.w || ih != hc.h || iw*ih > maxHelperPixels {
				return // protocol violation
			}
			img := image.NewRGBA(image.Rect(0, 0, iw, ih))
			if _, err := io.ReadFull(r, img.Pix); err != nil {
				return
			}
			ev <- helperEvent{hc: hc, kind: "image", img: img}
		}
		// unknown lines are ignored for forward compatibility
	}
}
