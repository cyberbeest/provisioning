"""python -m butler.cli [--lang de] [--run N] "make the display brighter"  (dry run unless --run)."""
import sys, time, argparse
from . import loader, slots, runner

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("text"); ap.add_argument("--lang", default="en")
    ap.add_argument("--run", type=int, help="execute the Nth (1-3) result for real")
    a = ap.parse_args()
    cmds, errs = loader.load()
    if errs: print("\n".join("catalog error: " + e for e in errs), file=sys.stderr); return 1
    from .matcher import Matcher
    t = time.time(); m = Matcher(cmds); load_s = time.time() - t
    t = time.time(); top = m.match(a.text); ms = (time.time() - t) * 1000
    print(f"[load {load_s:.1f}s, match {ms:.0f}ms]")
    for n, (c, sc) in enumerate(top, 1):
        vals, status = {}, "-"
        if "slot" in c:
            v, status = slots.extract(c["slot"], a.text)
            if v is not None: vals[c["slot"]["kind"]] = v
        title = c["title"][a.lang]
        line = f"{n}. {sc:.2f}  {c['category'][a.lang]} / {title}"
        if "slot" in c: line += f"  [{c['slot']['kind']}={vals.get(c['slot']['kind'])} ({status})]"
        if status == "missing": line += "  -> would ask for a value"
        else:
            argv, note, _ = runner.plan(c, vals)
            line += f"\n      {c['reply'][a.lang].format(**{k: v for k, v in vals.items()})}  |  {' '.join(argv)}  ({note})"
        print(line + ("  CONFIRM" if c.get("confirm") else ""))
    if a.run:
        c, _ = top[a.run - 1]; vals = {}
        if "slot" in c:
            v, st = slots.extract(c["slot"], a.text)
            if st == "missing": print("needs a value"); return 2
            vals[c["slot"]["kind"]] = v
        print(runner.execute(c, vals, dry=False))
if __name__ == "__main__": sys.exit(main() or 0)
