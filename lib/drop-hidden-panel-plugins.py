#!/usr/bin/env python3
"""Removes from panel-1's plugin-ids every plugin the user hid with the panel's
"Remove from panel" (records in ~/.config/cyberbeest/panel-hidden/<id>, see
lib/panel-icon.sh), so a re-run of 12-xfce-panel-layout.sh doesn't put them back.
Usage: drop-hidden-panel-plugins.py XML HIDDEN_DIR   (edits XML in place; no-op without records)"""
import os
import sys
import xml.etree.ElementTree as ET

xml_path, hidden_dir = sys.argv[1:3]
try:
    hidden = {n for n in os.listdir(hidden_dir) if n.isdigit()}
except OSError:
    sys.exit(0)
if not hidden:
    sys.exit(0)

tree = ET.parse(xml_path)
for panels in tree.getroot().findall("property"):
    if panels.get("name") != "panels":
        continue
    for panel in panels.findall("property"):
        for ids in panel.findall("property"):
            if ids.get("name") != "plugin-ids":
                continue
            for v in ids.findall("value"):
                if v.get("value") in hidden:
                    ids.remove(v)
with open(xml_path, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.1" encoding="UTF-8"?>\n\n')
    f.write(ET.tostring(tree.getroot(), encoding="unicode"))
    f.write("\n")
