#!/usr/bin/env python3
"""Butler matcher as a long-running child process, for the panel's menu (gopanel).

Talks JSON lines over stdin/stdout, so it is private to whoever started it (no socket).
  in : {"op":"match","seq":N,"text":"..."}   -> {"seq":N,"hits":[{id,sentence,category,score,needs_value,confirm}]}
       {"op":"run","id":"<command id>","text":"<sentence>"}  -> {"ran":"<id>","ok":bool,"reply":"..."}
       {"op":"quit"}
  out: {"commands":[{id,sentence,category,needs_value,confirm}]} first (catalog order), then
       {"ready":true,"lang":"en"} once the model is loaded.
Only commands from the catalog can run, and slot values are re-derived from the sentence here:
the caller never supplies an argv.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from butler import loader, slots, runner  # noqa: E402

MIN_SCORE = 0.6          # below this a hit is not worth sending
LANG = "de" if os.environ.get("LC_ALL", os.environ.get("LANG", "")).startswith("de") else "en"


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def slot_vals(cmd, text):
    if "slot" not in cmd:
        return {}, "-"
    v, st = slots.extract(cmd["slot"], text)
    return ({cmd["slot"]["kind"]: v} if v is not None else {}), st


def sentence_for(cmd, vals):
    kinds = {cmd["slot"]["kind"]} if "slot" in cmd else set()
    return cmd["sentence"][LANG].format_map({k: vals.get(k, "…") for k in kinds})


def main():
    cmds, errs = loader.load()
    if errs:
        out({"error": "; ".join(errs[:3])})
        return 1
    # the command list goes out first, so a menu page can show it while the model still loads
    listing = []
    for c in cmds:
        vals, st = slot_vals(c, "")
        listing.append({"id": c["id"], "sentence": sentence_for(c, vals), "category": c["category"][LANG],
                        "needs_value": st == "missing", "confirm": bool(c.get("confirm"))})
    out({"commands": listing})
    from butler.matcher import Matcher
    matcher = Matcher(cmds)
    by_id = {c["id"]: c for c in cmds}
    out({"ready": True, "lang": LANG})
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        op = req.get("op")
        if op == "quit":
            return 0
        if op == "match":
            text = str(req.get("text", ""))[:300]
            hits = []
            if len(text.strip()) >= 3:
                for cmd, score in matcher.match(text, 3):
                    if score < MIN_SCORE:
                        continue
                    vals, st = slot_vals(cmd, text)
                    hits.append({"id": cmd["id"], "sentence": sentence_for(cmd, vals),
                                 "category": cmd["category"][LANG], "score": round(score, 3),
                                 "needs_value": st == "missing", "confirm": bool(cmd.get("confirm"))})
            out({"seq": req.get("seq"), "hits": hits})
        elif op == "run":
            cmd = by_id.get(req.get("id"))
            if cmd is None:
                out({"ran": req.get("id"), "ok": False, "reply": "unknown command"})
                continue
            vals, st = slot_vals(cmd, str(req.get("text", ""))[:300])
            if st == "missing":
                out({"ran": cmd["id"], "ok": False, "reply": "needs a value"})
                continue
            try:
                _, _, rc, extras = runner.execute(cmd, vals, dry=False)
                shown = {**vals, **extras}
                done = cmd.get("done", cmd["reply"])[LANG].format_map(shown)
                out({"ran": cmd["id"], "ok": rc == 0, "reply": cmd["reply"][LANG].format(**vals),
                     "osd": done, "level": extras.get("level", -1),
                     "level_max": extras.get("level_max", 100)})
            except Exception as e:  # noqa: BLE001 - reported to the caller
                out({"ran": cmd["id"], "ok": False, "reply": str(e)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
