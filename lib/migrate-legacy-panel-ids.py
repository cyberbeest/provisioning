#!/usr/bin/env python3
"""One-time migration of a pre-2026-09-23 panel layout to the current plugin
id scheme: provisioning owns ids 200 and up (its template at 201-219, the
optional toggle icons at 227-229), everything below 200 belongs to the user.
xfce4-panel hands out the lowest free id to a plugin added by hand through
its own "Add New Items" dialog, so with provisioning out of the low range a
hand-added plugin can never land on (and later be clobbered by) an id a
future provisioning icon claims.

Legacy layouts had provisioning's own plugins at the low ids (template at
1-19, toggles at 27-29). This rewrites a copy of such a file with each of
those moved up by 200, which 12-xfce-panel-layout.sh's normal merge
(lib/merge-xfce-panel-plugins.py) then treats exactly like a re-run on an
already-current layout: template ids taken fresh from the template (with
the whiskermenu's "recent" list carried over), toggle icons and hand-added
plugins carried over in place.

A legacy layout is recognized by whiskermenu sitting at plugin-1 with no
plugin-201 anywhere -- every legacy template put it there, and every
current one puts it at 201. Detection is on the file as a whole, not per
id: after migration a hand-added plugin may legitimately land on e.g.
plugin-1 again, and must not be mistaken for a legacy provisioning one.
Within a legacy file, each low id is only moved if its plugin type (and,
for the genmon toggles, the rc file's Command=) matches what provisioning
put there -- anything else is the user's and stays where it is.

Usage:
  migrate-legacy-panel-ids.py migrate OLD_XML OUT_XML PANEL_DIR CLEANUP_LIST
      Writes OLD_XML (migrated if it's a legacy layout, else unchanged) to
      OUT_XML, copies each moved toggle's rc file to its new name, and
      writes the panel-config files/dirs orphaned by the migration to
      CLEANUP_LIST (empty if nothing was migrated). Nothing is deleted yet:
      the still-running old panel has those files open.
  migrate-legacy-panel-ids.py cleanup PANEL_DIR CLEANUP_LIST
      Deletes what CLEANUP_LIST names -- run after the old panel is gone.
"""
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

XML_DECLARATION = '<?xml version="1.1" encoding="UTF-8"?>\n\n'
ID_OFFSET = 200

# Legacy template id -> plugin type it had.
LEGACY_TEMPLATE = {
    1: "whiskermenu", 2: "tasklist", 3: "separator", 4: "separator",
    5: "separator", 6: "clock", 7: "systray", 8: "separator",
    11: "genmon", 12: "power-manager-plugin", 13: "wattage-panel",
    14: "kitt-scanner", 15: "mem-liquid", 17: "pulseaudio",
    18: "launcher", 19: "genmon",
}
# Legacy optional toggle id -> its genmon rc's Command= script name.
LEGACY_TOGGLES = {
    27: "i2pd-genmon.sh",
    28: "vpn-genmon.sh",
    29: "dot-genmon.sh",
}
# Provisioning plugins that no longer exist at all -- dropped outright.
# genmon-16: the standalone shutdown-timer widget, merged into genmon-11 on
# 2026-09-05 (panel-status-genmon.sh) but left behind on machines laid out
# before that, since the merge carried it over as a non-provisioning id.
RETIRED_GENMONS = {
    16: "shutdown-timer-genmon.sh",
}

PANEL_CONFIG_NAME = re.compile(r"^.+-(\d+)(\.rc)?$")


def find_property(parent, name):
    for prop in parent.findall("property"):
        if prop.get("name") == name:
            return prop
    return None


def genmon_command(panel_dir, plugin_id):
    try:
        with open(os.path.join(panel_dir, f"genmon-{plugin_id}.rc")) as f:
            for line in f:
                if line.startswith("Command="):
                    return os.path.basename(line.split("=", 1)[1].strip())
    except OSError:
        pass
    return None


def migrate(old_path, out_path, panel_dir, cleanup_path):
    with open(cleanup_path, "w"):
        pass
    try:
        tree = ET.parse(old_path)
    except (FileNotFoundError, ET.ParseError):
        if os.path.exists(old_path):
            shutil.copyfile(old_path, out_path)
        return 0
    shutil.copyfile(old_path, out_path)

    root = tree.getroot()
    panels = find_property(root, "panels")
    panel_1 = find_property(panels, "panel-1") if panels is not None else None
    ids_prop = find_property(panel_1, "plugin-ids") if panel_1 is not None else None
    plugins = find_property(root, "plugins")
    if ids_prop is None or plugins is None:
        return 0

    values = ids_prop.findall("value")
    ids = [int(v.get("value")) for v in values]

    def plugin_type(plugin_id):
        elem = find_property(plugins, f"plugin-{plugin_id}")
        return elem.get("value") if elem is not None else None

    if 1 not in ids or plugin_type(1) != "whiskermenu" or 1 + ID_OFFSET in ids:
        return 0

    moved, dropped = {}, []
    for plugin_id in ids:
        ptype = plugin_type(plugin_id)
        if LEGACY_TEMPLATE.get(plugin_id) == ptype:
            moved[plugin_id] = plugin_id + ID_OFFSET
        elif plugin_id in LEGACY_TOGGLES and ptype == "genmon" \
                and genmon_command(panel_dir, plugin_id) == LEGACY_TOGGLES[plugin_id]:
            moved[plugin_id] = plugin_id + ID_OFFSET
        elif plugin_id in RETIRED_GENMONS and ptype == "genmon" \
                and genmon_command(panel_dir, plugin_id) == RETIRED_GENMONS[plugin_id]:
            dropped.append(plugin_id)

    for value in values:
        plugin_id = int(value.get("value"))
        if plugin_id in moved:
            value.set("value", str(moved[plugin_id]))
        elif plugin_id in dropped:
            ids_prop.remove(value)
    for old_id, new_id in moved.items():
        find_property(plugins, f"plugin-{old_id}").set("name", f"plugin-{new_id}")
        print(f"plugin-{old_id} -> plugin-{new_id}")
    for old_id in dropped:
        plugins.remove(find_property(plugins, f"plugin-{old_id}"))
        print(f"plugin-{old_id} dropped (retired)")

    # The toggle icons aren't in the template, so nothing else would write
    # their rc under the new id -- carry it over. (The template ones are
    # rewritten from scratch by 11a-/12-.)
    for old_id in LEGACY_TOGGLES:
        if old_id not in moved:
            continue
        src = os.path.join(panel_dir, f"genmon-{old_id}.rc")
        dst = os.path.join(panel_dir, f"genmon-{old_id + ID_OFFSET}.rc")
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

    # Every low-id config file/dir that no longer backs a plugin: the ones
    # just moved or dropped, plus any older leftovers (plugins removed by
    # past layouts whose rc/launcher dir was never deleted). Left in place,
    # a plugin the user later adds by hand would inherit one -- e.g. a new
    # genmon landing on id 27 would come up as a stale copy of the i2pd
    # icon.
    kept_ids = {int(v.get("value")) for v in ids_prop.findall("value")}
    orphans = []
    if os.path.isdir(panel_dir):
        for name in sorted(os.listdir(panel_dir)):
            m = PANEL_CONFIG_NAME.match(name)
            if not m:
                continue
            plugin_id = int(m.group(1))
            if plugin_id < ID_OFFSET and plugin_id not in kept_ids:
                orphans.append(name)
    with open(cleanup_path, "w") as f:
        for name in orphans:
            f.write(name + "\n")

    ET.indent(tree, space="  ")
    with open(out_path, "wb") as f:
        f.write(XML_DECLARATION.encode("utf-8"))
        tree.write(f, encoding="utf-8", xml_declaration=False)
        f.write(b"\n")
    return 0


def cleanup(panel_dir, cleanup_path):
    try:
        with open(cleanup_path) as f:
            names = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return 0
    for name in names:
        # Bare names only, straight from migrate()'s own listdir -- never a
        # path that could reach outside panel_dir.
        if "/" in name or not PANEL_CONFIG_NAME.match(name):
            continue
        path = os.path.join(panel_dir, name)
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            continue
        print(f"removed stale {name}")
    return 0


def main():
    if len(sys.argv) == 6 and sys.argv[1] == "migrate":
        return migrate(*sys.argv[2:])
    if len(sys.argv) == 4 and sys.argv[1] == "cleanup":
        return cleanup(*sys.argv[2:])
    print(__doc__.split("Usage:")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
