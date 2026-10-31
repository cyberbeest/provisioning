package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"time"
)

// addLauncher puts an application on the panel as a new launcher plugin, the way the XFCE
// panel does: a launcher-<id> directory holding a copy of the .desktop file, the plugin's
// items, and its id in plugin-ids right after the last launcher (the panel's own ordering
// pulls launchers next to the menu button anyway). Ids below 200 are the user's.
func addLauncher(src string) {
	data, err := os.ReadFile(src)
	if err != nil {
		return
	}
	cfg := xfconfAll()
	if cfg == nil {
		return
	}
	ids := cfg["/panels/panel-1/plugin-ids"]
	id, last := 100, -1
	for i, v := range ids {
		n, err := strconv.Atoi(v)
		if err != nil {
			continue
		}
		if n < 200 && n >= id {
			id = n + 1
		}
		if cfg["/plugins/plugin-"+v] != nil && cfg["/plugins/plugin-"+v][0] == "launcher" {
			last = i
		}
	}
	for cfg["/plugins/plugin-"+strconv.Itoa(id)] != nil {
		id++
	}
	sid := strconv.Itoa(id)
	home, _ := os.UserHomeDir()
	dir := filepath.Join(home, ".config/xfce4/panel/launcher-"+sid)
	file := strconv.FormatInt(time.Now().Unix(), 10) + ".desktop"
	if os.MkdirAll(dir, 0o755) != nil || os.WriteFile(filepath.Join(dir, file), data, 0o755) != nil {
		return
	}
	xq := func(args ...string) error {
		return exec.Command("xfconf-query", append([]string{"-c", "xfce4-panel"}, args...)...).Run()
	}
	xq("-p", "/plugins/plugin-"+sid, "-n", "-t", "string", "-s", "launcher")
	xq("-p", "/plugins/plugin-"+sid+"/items", "-n", "-a", "-t", "string", "-s", file)
	args := []string{"-p", "/panels/panel-1/plugin-ids", "-n", "-a"}
	add := func() { args = append(args, "-t", "int", "-s", sid) }
	if last < 0 {
		last = len(ids) - 1
	}
	for i, v := range ids {
		if n, err := strconv.Atoi(v); err == nil {
			args = append(args, "-t", "int", "-s", strconv.Itoa(n))
		}
		if i == last {
			add()
		}
	}
	if len(ids) == 0 {
		add()
	}
	xq(args...)
}

// removeLauncher takes a launcher off the panel, in the xfce4-panel config (the XFCE panel
// would show the same change): a plugin that launches several programs just loses that
// entry; a plugin with only this one is deleted -- its id leaves plugin-ids, its properties
// and its launcher-<id> directory go. It asks first (there is no way to add one back from
// this panel) and then asks the panel to rebuild its items.
func removeLauncher(id, file, name string, cmds chan<- string) {
	q := fmt.Sprintf(tr("Remove \"%s\" from the panel?"), name)
	if _, err := exec.LookPath("zenity"); err == nil {
		if exec.Command("zenity", "--question", "--no-markup", "--title", tr("Remove from panel"), "--text", q,
			"--ok-label", tr("Remove"), "--cancel-label", tr("Cancel")).Run() != nil {
			return
		}
	}
	cfg := xfconfAll()
	if cfg == nil {
		return
	}
	var rest []string
	for _, f := range cfg["/plugins/plugin-"+id+"/items"] {
		if f != file {
			rest = append(rest, f)
		}
	}
	xq := func(args ...string) error {
		return exec.Command("xfconf-query", append([]string{"-c", "xfce4-panel"}, args...)...).Run()
	}
	if len(rest) > 0 {
		args := []string{"-p", "/plugins/plugin-" + id + "/items", "-n", "-a"}
		for _, f := range rest {
			args = append(args, "-t", "string", "-s", f)
		}
		xq(args...)
	} else {
		args := []string{"-p", "/panels/panel-1/plugin-ids", "-n", "-a"}
		for _, v := range cfg["/panels/panel-1/plugin-ids"] {
			if n, err := strconv.Atoi(v); err == nil && v != id {
				args = append(args, "-t", "int", "-s", strconv.Itoa(n))
			}
		}
		xq(args...)
		xq("-p", "/plugins/plugin-"+id, "-r", "-R")
		home, _ := os.UserHomeDir()
		os.RemoveAll(filepath.Join(home, ".config/xfce4/panel/launcher-"+id))
	}
	cmds <- "reload"
}
