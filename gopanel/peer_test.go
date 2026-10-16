package main

import (
	"bufio"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// pyClient connects to a unix socket, sends line, prints the first reply line or "NOREPLY".
const pyClient = `
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
try:
    s.connect(sys.argv[1])
    s.sendall(sys.argv[2].encode())
    print(s.makefile().readline().strip() or "NOREPLY")
except Exception as e:
    print("NOREPLY", type(e).__name__)
`

func runClient(t *testing.T, wrap []string, sock, send string) string {
	t.Helper()
	args := append(append([]string{}, wrap...), "python3", "-I", "-c", pyClient, sock, send)
	out, err := exec.Command(args[0], args[1:]...).CombinedOutput()
	if err != nil {
		t.Fatalf("%v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

func needTools(t *testing.T, tools ...string) {
	for _, tool := range tools {
		if _, err := exec.LookPath(tool); err != nil {
			t.Skip(tool, "not installed")
		}
	}
}

func TestDescendantOf(t *testing.T) {
	if !descendantOf(os.Getpid(), os.Getpid()) {
		t.Error("a process is its own ancestor")
	}
	cmd := exec.Command("sleep", "5")
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()
	if !descendantOf(cmd.Process.Pid, os.Getpid()) {
		t.Error("child not recognised")
	}
	if descendantOf(1, os.Getpid()) || descendantOf(os.Getppid(), os.Getpid()) {
		t.Error("init / parent must not count as descendants")
	}
}

// The control socket answers a normal client and ignores one from another mount namespace.
func TestControlSocketRefusesSandboxedPeer(t *testing.T) {
	needTools(t, "python3", "firejail")
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
	cmds := make(chan string, 4)
	ctlServer(cmds)
	sock := sockPath()

	if got := runClient(t, nil, sock, "dismiss\n"); got != "ok" {
		t.Fatalf("normal client: got %q, want ok", got)
	}
	// The control socket deliberately admits root without a namespace check (root can do
	// anything to the panel anyway), so a jailed client is only refused when it is not root.
	if os.Getuid() != 0 {
		if got := runClient(t, []string{"firejail", "--quiet", "--noprofile"}, sock, "dismiss\n"); !strings.HasPrefix(got, "NOREPLY") {
			t.Fatalf("firejailed client was served: %q", got)
		}
	}
	if n := len(cmds); n != 1 {
		t.Fatalf("%d commands reached the panel, want exactly 1", n)
	}
}

// The helper socket admits the panel's own children, and refuses a jailed process and an
// unrelated same-uid process (reparented away from us with a double fork).
func TestHelperSocketAdmitsOnlyOwnChildren(t *testing.T) {
	needTools(t, "python3", "firejail", "sh")
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
	ev := make(chan helperEvent, 8)
	helperServer(ev)
	sock := filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "gopanel-helper.sock")
	panelH = 24

	// our child: gets the greeting
	if got := runClient(t, nil, sock, "hello t 10\n"); got != "panel 24" {
		t.Fatalf("child helper: got %q, want the greeting", got)
	}
	// jailed: dropped before the greeting
	if got := runClient(t, []string{"firejail", "--quiet", "--noprofile"}, sock, "hello t 10\n"); !strings.HasPrefix(got, "NOREPLY") {
		t.Fatalf("jailed helper was greeted: %q", got)
	}
	// orphan: sh exits at once, python is reparented to init/subreaper and writes its answer to a file
	out := filepath.Join(t.TempDir(), "answer")
	script := `python3 -I -c '` + strings.ReplaceAll(pyClient, "'", `'"'"'`) + `' ` + sock + ` "hello t 10
" > ` + out + ` 2>&1 &`
	if err := exec.Command("sh", "-c", script).Run(); err != nil {
		t.Fatal(err)
	}
	var got string
	for i := 0; i < 50 && got == ""; i++ {
		time.Sleep(100 * time.Millisecond)
		b, _ := os.ReadFile(out)
		got = strings.TrimSpace(string(b))
	}
	if !strings.HasPrefix(got, "NOREPLY") {
		t.Fatalf("orphaned same-uid process was greeted: %q", got)
	}
}

// An over-long line and a silent peer must not hang or grow the panel.
func TestHelperSocketBoundsInput(t *testing.T) {
	t.Setenv("XDG_RUNTIME_DIR", t.TempDir())
	ev := make(chan helperEvent, 8)
	helperServer(ev)
	conn, err := net.Dial("unix", filepath.Join(os.Getenv("XDG_RUNTIME_DIR"), "gopanel-helper.sock"))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	r := bufio.NewReader(conn)
	if _, err := r.ReadString('\n'); err != nil { // greeting
		t.Fatal(err)
	}
	junk := make([]byte, 64<<10) // no newline anywhere
	for i := range junk {
		junk[i] = 'x'
	}
	conn.SetWriteDeadline(time.Now().Add(3 * time.Second))
	conn.Write(junk)
	conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	if _, err := r.ReadByte(); err == nil {
		t.Fatal("expected the panel to drop the connection")
	} else if ne, ok := err.(net.Error); ok && ne.Timeout() {
		t.Fatal("connection still open after a 64 KB line")
	}
}
