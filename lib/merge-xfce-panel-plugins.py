#!/usr/bin/env python3
"""Merges panel-1's plugin-ids array and plugin definitions from an existing
xfce4-panel.xml into a freshly-rendered one from xfce4-panel.xml.template,
so any plugin id NOT owned by provisioning (a hand-added launcher, or one of
the optional toggle scripts' own genmon icons -- see
lib/wireguard-vpn-toggle/vpn-panel-icon.sh, lib/setup_i2p_extras.py) survives
a re-run of 12-xfce-panel-layout.sh instead of being wiped by a wholesale
file overwrite. Provisioning's own ids are always taken from the fresh
template (position, config, everything) -- only ids outside that set are
carried over, appended after the template's own ids in their prior relative
order. See 12-xfce-panel-layout.sh's comment on why ids can't be matched by
number alone across runs (xfce4-panel recycles freed ids on panel restart).

Usage: merge-xfce-panel-plugins.py OLD_XML NEW_XML PROVISIONING_ID...
Writes the merged result to NEW_XML in place. If OLD_XML doesn't exist yet
(first-ever run), NEW_XML is left untouched.
"""
import sys
import xml.etree.ElementTree as ET

XML_DECLARATION = '<?xml version="1.1" encoding="UTF-8"?>\n\n'


def find_property(parent, name):
    for prop in parent.findall("property"):
        if prop.get("name") == name:
            return prop
    return None


def plugin_ids_array(root):
    panels = find_property(root, "panels")
    panel_1 = find_property(panels, "panel-1")
    return find_property(panel_1, "plugin-ids")


def main():
    old_path, new_path, *provisioning_ids = sys.argv[1:]
    provisioning_ids = {int(i) for i in provisioning_ids}

    try:
        old_root = ET.parse(old_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        return 0

    old_ids_prop = plugin_ids_array(old_root)
    if old_ids_prop is None:
        return 0
    old_ids = [int(v.get("value")) for v in old_ids_prop.findall("value")]
    extra_ids = [i for i in old_ids if i not in provisioning_ids]
    if not extra_ids:
        return 0

    old_plugins = find_property(old_root, "plugins")
    extra_plugin_elements = []
    for plugin_id in extra_ids:
        elem = find_property(old_plugins, f"plugin-{plugin_id}")
        if elem is not None:
            extra_plugin_elements.append(elem)

    new_tree = ET.parse(new_path)
    new_root = new_tree.getroot()
    new_ids_prop = plugin_ids_array(new_root)
    for plugin_id in extra_ids:
        ET.SubElement(new_ids_prop, "value", {"type": "int", "value": str(plugin_id)})

    new_plugins = find_property(new_root, "plugins")
    notes = find_property(new_plugins, "notes")
    insert_at = list(new_plugins).index(notes) if notes is not None else len(new_plugins)
    for offset, elem in enumerate(extra_plugin_elements):
        new_plugins.insert(insert_at + offset, elem)

    ET.indent(new_tree, space="  ")
    with open(new_path, "wb") as f:
        f.write(XML_DECLARATION.encode("utf-8"))
        new_tree.write(f, encoding="utf-8", xml_declaration=False)
        f.write(b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
