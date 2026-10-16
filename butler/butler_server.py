#!/usr/bin/env python3
"""Butler matcher as a long-running child process, for the panel's menu (gopanel).

Talks JSON lines over stdin/stdout, so it is private to whoever started it (no socket).
  in : {"op":"match","seq":N,"text":"..."[,"k":N,"fact_min":0.55]}   -> {"seq":N,"hits":[{id,sentence,category,score,needs_value,confirm}]}
       {"op":"run","id":"<command id>","text":"<sentence>"}  -> {"ran":"<id>","ok":bool,"reply":"..."}
       {"op":"quit"}
  out: {"indexing":N} when N new sentences are being embedded (can take a minute), {"commands":[{id,sentence,category,needs_value,confirm}]} first (catalog order), then
       {"ready":true,"lang":"en"} once the model is loaded.
Only commands from the catalog can run, and slot values are re-derived from the sentence here:
the caller never supplies an argv.
"""
import json
import os
import sys
import time
from pathlib import Path

def name_process(name="butler"):
    """Shows up as `butler` instead of `python` in /proc comm, so the panel's CPU and memory lists can say "Butler"."""
    try:
        import ctypes
        ctypes.CDLL(None).prctl(15, name.encode(), 0, 0, 0)   # PR_SET_NAME
    except (OSError, AttributeError):
        pass


name_process()
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from butler import loader, slots, runner  # noqa: E402

FACT_MIN = 0.55          # facts (factbook answers) score lower than commands: they are whole sentences
RECHECK_S = 2.0          # at most this often, look whether catalog files changed
APP_MIN = 0.5           # apps score as short phrases against short names: lower bar, the panel filters further
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


def fingerprint():
    """Names, sizes and mtimes of every file the catalog is built from: when it changes, the running server is stale."""
    fp = []
    for d in (loader.CATALOG_DIR, loader.FACTS_DIR, loader.USER_DIR, loader.APPS_FILE.parent):
        for f in sorted(Path(d).glob("*.json")):
            try:
                st = f.stat()
                fp.append((str(f), st.st_size, st.st_mtime_ns))
            except OSError:
                pass
    return fp


def build():
    """Loads catalog and factbook and announces them. Returns (cmds, facts, matcher, by_id), or None if the catalog is broken."""
    cmds, errs = loader.load()
    if errs:
        out({"error": "; ".join(errs[:3])})
        return None
    # the command list goes out first, so a menu page can show it while the model still loads
    listing = []
    for c in cmds:
        vals, st = slot_vals(c, "")
        listing.append({"id": c["id"], "sentence": sentence_for(c, vals), "category": c["category"][LANG],
                        "needs_value": st == "missing", "confirm": bool(c.get("confirm"))})
    out({"commands": listing})
    from butler.matcher import Matcher
    facts = loader.load_facts()
    apps = loader.load_apps()
    matcher = Matcher(cmds + facts + apps, on_index=lambda n: out({"indexing": n}))   # first start after a catalog change: the caller can say why it takes long
    by_id = {c["id"]: c for c in cmds + facts if "run" in c}   # only these can be run, whatever the caller sends
    out({"ready": True, "lang": LANG})
    return cmds, facts, matcher, by_id


def main():
    state = build()
    if state is None:
        return 1
    cmds, facts, matcher, by_id = state
    seen, checked = fingerprint(), time.monotonic()
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        op = req.get("op")
        if op == "quit":
            return 0
        if op in ("match", "run") and time.monotonic() - checked > RECHECK_S:
            checked = time.monotonic()
            now = fingerprint()
            if now != seen:   # catalog or factbook edited while running: pick it up without a restart
                seen = now
                new = build()
                if new is not None:
                    cmds, facts, matcher, by_id = new
        if op == "match":
            text = str(req.get("text", ""))[:300]
            hits = []
            if len(text.strip()) >= 3:
                for cmd, score in matcher.match(text, min(int(req.get("k", 4)), 30)):
                    if cmd.get("kind") == "app":   # the panel launches it: only the desktop id goes back
                        if score >= float(req.get("app_min", APP_MIN)):
                            hits.append({"id": cmd["id"], "kind": "app", "sentence": "", "category": cmd["category"][LANG],
                                         "score": round(score, 3)})
                        continue
                    if cmd.get("kind") == "fact":
                        if score >= float(req.get("fact_min", FACT_MIN)):
                            hit = {"id": cmd["id"], "kind": "fact", "sentence": cmd["answer"][LANG],
                                   "category": cmd["category"][LANG], "score": round(score, 3)}
                            if "run" in cmd:   # the fact suggests a command: label, and whether Enter must be pressed twice
                                hit.update({"action": cmd["sentence"][LANG], "confirm": bool(cmd.get("confirm"))})
                            hits.append(hit)
                        continue
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
