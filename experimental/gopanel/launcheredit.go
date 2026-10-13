package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
)

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
