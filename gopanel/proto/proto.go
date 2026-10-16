// Package proto is the helper side of the gopanel helper protocol (see PROTOCOL.md).
// A helper never talks to X: it sends premultiplied RGBA frames to the panel and
// receives hover/click/pause messages back.
package proto

import (
	"bufio"
	"fmt"
	"image"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

func SockPath() string {
	dir := os.Getenv("XDG_RUNTIME_DIR")
	if dir == "" {
		dir = os.TempDir()
	}
	return filepath.Join(dir, "gopanel-helper.sock")
}

type Client struct {
	mu            sync.Mutex
	conn          net.Conn
	Width, Height int
	Events        chan string // lines from the panel; closed when the connection ends
}

// Dial connects, learns the panel height, and announces a slot width computed from it.
func Dial(name string, widthFor func(panelH int) int) (*Client, error) {
	conn, err := net.Dial("unix", SockPath())
	if err != nil {
		return nil, err
	}
	r := bufio.NewReader(conn)
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	line, err := r.ReadString('\n')
	if err != nil {
		conn.Close()
		return nil, err
	}
	conn.SetReadDeadline(time.Time{})
	f := strings.Fields(line)
	if len(f) != 2 || f[0] != "panel" {
		conn.Close()
		return nil, fmt.Errorf("bad greeting %q", line)
	}
	h, err := strconv.Atoi(f[1])
	if err != nil {
		conn.Close()
		return nil, err
	}
	c := &Client{conn: conn, Height: h, Width: widthFor(h), Events: make(chan string, 16)}
	if _, err := fmt.Fprintf(conn, "hello %s %d\n", name, c.Width); err != nil {
		conn.Close()
		return nil, err
	}
	go func() {
		defer close(c.Events)
		for {
			l, err := r.ReadString('\n')
			if err != nil {
				return
			}
			if strings.TrimSpace(l) == "quit" { // duplicate or no longer configured: do not reconnect forever
				os.Exit(0)
			}
			select {
			case c.Events <- strings.TrimSpace(l):
			default: // helper too slow to read events: drop
			}
		}
	}()
	return c, nil
}

// SendImage sends one frame; img must be Width x Height with a tight stride.
func (c *Client) SendImage(img *image.RGBA) error {
	b := img.Bounds()
	hdr := []byte(fmt.Sprintf("image %d %d\n", b.Dx(), b.Dy()))
	c.mu.Lock()
	defer c.mu.Unlock()
	c.conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
	_, err := (&net.Buffers{hdr, img.Pix[:b.Dx()*b.Dy()*4]}).WriteTo(c.conn)
	return err
}

func (c *Client) sendText(kind, markup string) error {
	esc := strings.NewReplacer(`\`, `\\`, "\n", `\n`).Replace(markup)
	c.mu.Lock()
	defer c.mu.Unlock()
	c.conn.SetWriteDeadline(time.Now().Add(2 * time.Second))
	_, err := fmt.Fprintf(c.conn, "%s %s\n", kind, esc)
	return err
}

// SetLabel makes the slot a one-line text label (Pango-lite markup); the panel
// renders it and sizes the slot to fit. An empty label hides the slot.
func (c *Client) SetLabel(markup string) error { return c.sendText("label", markup) }

// SetTooltip sets the tooltip shown when the pointer rests on the slot (Pango-lite
// markup, newlines allowed).
func (c *Client) SetTooltip(markup string) error { return c.sendText("tooltip", markup) }

// ParentAlive reports whether the panel that spawned this helper (GOPANEL_PARENT)
// still exists; helpers started by hand have no parent and always report true.
func ParentAlive() bool {
	v := os.Getenv("GOPANEL_PARENT")
	if v == "" {
		return true
	}
	pid, err := strconv.Atoi(v)
	if err != nil {
		return true
	}
	return syscall.Kill(pid, 0) != syscall.ESRCH
}

func (c *Client) Close() { c.conn.Close() }
