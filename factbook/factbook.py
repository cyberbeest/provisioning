#!/usr/bin/env python3
"""Cyberbeest Factbook: lint the facts and build the derived files.

    factbook.py lint          validate facts/*.json (exit 1 on errors)
    factbook.py build [DIR]   lint, then write hints.json and corpus.jsonl into DIR (default: build/)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGS = ("en", "de")
MAX_LEN = 300
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# A fact is read on its own (hint popup, chatbot snippet), so it must not lean on context.
DANGLING = {
    "en": ("it ", "this ", "that ", "they ", "these ", "those ", "he ", "she ", "also ", "but ", "and "),
    "de": ("es ", "dies ", "auch ", "aber ", "und "),
}
DUP_THRESHOLD = 0.7


def load():
    facts, errors = [], []
    for path in sorted((HERE / "facts").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}: invalid JSON: {e}")
            continue
        for key in ("topic", "source", "checked", "facts"):
            if key not in doc:
                errors.append(f"{path.name}: missing '{key}'")
        topic = doc.get("topic", {})
        for lang in LANGS:
            if not topic.get(lang):
                errors.append(f"{path.name}: topic.{lang} missing")
        for f in doc.get("facts", []):
            f = dict(f, _file=path.name, _topic=topic)
            facts.append(f)
    return facts, errors


def words(text):
    return set(re.findall(r"[a-zäöüß0-9]+", text.lower()))


def lint(facts, errors):
    seen = {}
    for f in facts:
        fid = f.get("id", "<no id>")
        where = f"{f['_file']}:{fid}"
        if not ID_RE.match(fid):
            errors.append(f"{where}: id must be lowercase kebab-case")
        if fid in seen:
            errors.append(f"{where}: duplicate id (also in {seen[fid]})")
        seen[fid] = f["_file"]
        for lang in LANGS:
            text = f.get(lang, "").strip()
            if not text:
                errors.append(f"{where}: missing '{lang}'")
                continue
            if len(text) > MAX_LEN:
                errors.append(f"{where}: {lang} is {len(text)} chars (max {MAX_LEN})")
            if not text.endswith((".", "?", "!", "”", "“")):
                errors.append(f"{where}: {lang} should end with a full stop")
            if text.lower().startswith(DANGLING[lang]):
                errors.append(f"{where}: {lang} starts with a context-dependent word: '{text.split()[0]}'")
        if f.get("en") and f.get("en") == f.get("de"):
            errors.append(f"{where}: de is identical to en")
        ask = f.get("ask")
        if ask is not None:   # extra sentences people would type to find this fact (Butler matches them)
            for lang in LANGS:
                lst = ask.get(lang) if isinstance(ask, dict) else None
                if not (isinstance(lst, list) and len(lst) >= 3 and all(isinstance(x, str) and x.strip() for x in lst)):
                    errors.append(f"{where}: ask.{lang} needs a list of at least 3 sentences")
        act = f.get("action")
        if act is not None:   # the command Butler suggests with this fact
            ok = isinstance(act, dict) and all(isinstance(act.get("label", {}).get(l), str) and act["label"][l] for l in LANGS)
            ok = ok and isinstance(act.get("run"), list) and act["run"] and all(isinstance(a, str) for a in act["run"])
            if not ok:
                errors.append(f"{where}: action needs label {{en,de}} and run (a non-empty argv list)")
            if ask is None:
                errors.append(f"{where}: an action needs 'ask' sentences, or nobody finds it")
        if "tip" in f and not isinstance(f["tip"], bool):
            errors.append(f"{where}: tip must be true/false")
    for i, a in enumerate(facts):
        wa = words(a.get("en", ""))
        for b in facts[i + 1:]:
            wb = words(b.get("en", ""))
            if wa and wb and len(wa & wb) / len(wa | wb) >= DUP_THRESHOLD:
                errors.append(f"{a['id']} / {b['id']}: near-duplicate")
    return errors


def build(facts, out):
    out.mkdir(parents=True, exist_ok=True)
    hints = [{"id": f["id"], "en": f["en"], "de": f["de"]} for f in facts if f.get("tip")]
    (out / "hints.json").write_text(json.dumps(hints, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    with open(out / "corpus.jsonl", "w", encoding="utf-8") as fh:
        for f in facts:
            row = {"id": f["id"], "topic": f["_topic"], "en": f["en"], "de": f["de"], "manual": f.get("manual")}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(facts)} facts, {len(hints)} hints -> {out}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "lint"
    facts, errors = load()
    lint(facts, errors)
    for e in errors:
        print("ERROR", e)
    if errors:
        return 1
    if cmd == "build":
        build(facts, Path(argv[2]) if len(argv) > 2 else HERE / "build")
    else:
        print(f"ok: {len(facts)} facts")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
