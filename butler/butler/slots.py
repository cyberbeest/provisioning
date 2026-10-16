"""Slot extraction. Rules only, no model. Returns (value|None, status) status in ok|default|missing."""
import re

def _words(cmd_slot, text):
    t = text.lower()
    best = None
    for lang, d in cmd_slot.get("words", {}).items():
        for phrase, val in d.items():
            if re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", t):
                if best is None or len(phrase) > best[0]: best = (len(phrase), val)
    return best[1] if best else None

def extract(slot, text):
    t = text.lower()
    kind = slot["kind"]
    if kind == "percent":
        top = slot.get("max", 100)   # e.g. volume goes to 150
        m = re.search(r"(\d{1,3})\s*(%|percent|prozent)", t)
        if m: return min(top, int(m.group(1))), "ok"
        w = _words(slot, text)
        if w is not None: return w, "ok"
        if slot.get("mode") == "absolute":
            m = re.search(r"(?<![\w.])(\d{1,3})(?![\w.])", t)   # bare number, e.g. "brightness to 50"
            if m: return min(top, int(m.group(1))), "ok"
        if slot.get("required"): return None, "missing"
        return slot.get("default"), "default"
    return None, "missing"   # site/app/query resolvers: next iteration
