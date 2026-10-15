"""Load and validate command catalogs.

Shipped catalogs: catalog/*.json (next to this file).
User overlay: ~/.config/cyberbeest/butler/learned.json  {"<id>": {"en": [...], "de": [...]}}
              ~/.config/cyberbeest/butler/disabled.json ["<id>", ...]
Overlay never edits shipped files, so updates cannot clobber it.
"""
import json, hashlib, os, re
from pathlib import Path

LANGS = ("en", "de")
MIN_EXAMPLES = 4
SLOT_KINDS = {"percent", "site", "app", "query"}
BUILTINS = {"backlight", "night_light", "volume"}
HERE = Path(__file__).parent
CATALOG_DIR = HERE / "catalog"
USER_DIR = Path.home() / ".config/cyberbeest/butler"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def validate_command(cmd, where):
    errs = []
    def need(cond, msg):
        if not cond: errs.append(f"{where}: {msg}")
    cid = cmd.get("id", "?")
    where = f"{where}/{cid}"
    need(re.fullmatch(r"[a-z][a-z0-9_]*", str(cmd.get("id", ""))), "id must be snake_case")
    for key in ("title", "sentence", "reply"):
        need(all(isinstance(cmd.get(key, {}).get(l), str) and cmd[key][l] for l in LANGS), f"{key} needs {LANGS}")
    ex = cmd.get("examples", {})
    for l in LANGS:
        lst = ex.get(l, [])
        need(len(lst) >= MIN_EXAMPLES, f"needs >= {MIN_EXAMPLES} {l} examples (has {len(lst)})")
        need(all(isinstance(s, str) and s.strip() for s in lst), f"empty/non-string {l} example")
        need(len(set(s.lower() for s in lst)) == len(lst), f"duplicate {l} example")
    slot = cmd.get("slot")
    slot_names = set()
    if slot is not None:
        need(slot.get("kind") in SLOT_KINDS, f"slot kind must be one of {sorted(SLOT_KINDS)}")
        need(slot.get("mode", "relative") in ("relative", "absolute"), "slot mode relative|absolute")
        slot_names.add(slot.get("kind"))
        if slot.get("kind") == "percent" and slot.get("mode") == "relative" and not slot.get("required"):
            need(isinstance(slot.get("default"), int), "relative percent slot needs int default")
        for l, d in slot.get("words", {}).items():
            need(l in LANGS and all(isinstance(v, int) for v in d.values()), "slot words: {lang:{phrase:int}}")
    run = cmd.get("run", {})
    if "argv" in run:
        need(isinstance(run["argv"], list) and run["argv"] and all(isinstance(a, str) for a in run["argv"]),
             "run.argv must be a non-empty list of strings (no shell strings)")
        refs = {m for a in run["argv"] for m in _PLACEHOLDER.findall(a)}
    elif "builtin" in run:
        need(run["builtin"] in BUILTINS, f"unknown builtin {run['builtin']!r}")
        refs = {m for v in run.get("args", {}).values() if isinstance(v, str) for m in _PLACEHOLDER.findall(v)}
    else:
        errs.append(f"{where}: run needs 'argv' or 'builtin'"); refs = set()
    refs |= {m for k in ("reply", "sentence") for l in LANGS for m in _PLACEHOLDER.findall(cmd.get(k, {}).get(l, ""))}
    for l, t in cmd.get("done", {}).items():
        need(l in LANGS, "done: languages en/de")
        need(set(_PLACEHOLDER.findall(t)) <= slot_names | {"level"}, f"done {l!r} has unknown placeholders")
    need(refs <= slot_names | {"arg"}, f"placeholders {refs - slot_names - {'arg'}} have no slot")
    need(isinstance(cmd.get("confirm", False), bool), "confirm must be bool")
    if "answer" in cmd:   # a help entry: the typed symptom shows this text, Enter runs the action
        need(all(isinstance(cmd["answer"].get(l), str) and cmd["answer"][l] for l in LANGS), f"answer needs {LANGS}")
    return errs


def load(catalog_dir=CATALOG_DIR, user_dir=USER_DIR):
    """Returns (commands, errors). commands: list of dicts with 'category' added and learned examples merged."""
    cmds, errs, seen = [], [], {}
    for f in sorted(Path(catalog_dir).glob("*.json")):
        data = _read(f)
        cat = data.get("category", {})
        if not all(cat.get(l) for l in LANGS): errs.append(f"{f.name}: category needs {LANGS}")
        for c in data.get("commands", []):
            errs += validate_command(c, f.name)
            if c.get("id") in seen: errs.append(f"{f.name}: duplicate id {c['id']} (also in {seen[c['id']]})")
            seen[c.get("id")] = f.name
            cmds.append({**c, "category": cat, "_file": f.name})
    learned = _read(Path(user_dir) / "learned.json") or {}
    disabled = set(_read(Path(user_dir) / "disabled.json") or [])
    for c in cmds:
        c["_learned"] = {l: list(learned.get(c["id"], {}).get(l, [])) for l in LANGS}
    cmds = [c for c in cmds if c["id"] not in disabled]
    # same sentence under two different commands makes matching ambiguous
    owner = {}
    for c in cmds:
        for l in LANGS:
            for s in c["examples"].get(l, []) + c["_learned"][l]:
                k = s.lower()
                if k in owner and owner[k] != c["id"]:
                    errs.append(f"example {s!r} used by both {owner[k]} and {c['id']}")
                owner[k] = c["id"]
    return cmds, errs


FACTS_DIR = Path(os.environ.get("BUTLER_FACTS") or HERE.parents[2] / "factbook/facts")


def load_facts(facts_dir=FACTS_DIR):
    """The factbook as pseudo-commands (kind "fact"): the user asks a question, the nearest fact is shown verbatim.
    Missing or broken factbook means no facts, never an error: Butler's commands do not depend on it."""
    out = []
    for f in sorted(Path(facts_dir).glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            topic = {l: data["topic"][l] for l in LANGS}
            for x in data["facts"]:
                if all(isinstance(x.get(l), str) and x[l] for l in LANGS) and x.get("id"):
                    out.append({"id": "fact:" + x["id"], "kind": "fact", "category": topic, "answer": {l: x[l] for l in LANGS},
                                "examples": {l: [x[l]] for l in LANGS}, "_learned": {l: [] for l in LANGS}})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def all_examples(c):
    """(sentence, is_negative) pairs for a command."""
    out = [(s, False) for l in LANGS for s in c["examples"].get(l, []) + c["_learned"][l]]
    out += [(s, True) for l in LANGS for s in c.get("negative", {}).get(l, [])]
    return out


def catalog_hash(cmds, model_tag):
    h = hashlib.sha256(model_tag.encode())
    for c in cmds:
        for s, neg in all_examples(c):
            h.update(f"{c['id']}|{int(neg)}|{s}\n".encode())
    return h.hexdigest()[:16]


if __name__ == "__main__":
    cmds, errs = load()
    for e in errs: print("ERROR", e)
    n = sum(len(all_examples(c)) for c in cmds)
    print(f"{len(cmds)} commands, {n} sentences, {len(errs)} errors")
    raise SystemExit(1 if errs else 0)
