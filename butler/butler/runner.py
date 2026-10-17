"""Execute a command's `run` spec. argv lists only, never a shell. dry=True returns the plan without side effects."""
import subprocess, re, os
from pathlib import Path

BL_DIR = next(iter(sorted(Path("/sys/class/backlight").glob("*"))), None)
VOL_MAX = 150   # same ceiling as the panel's volume slider
MIN_PCT = 5   # never let the screen go black

def _fill(s, vals):
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), s)

def _backlight(args, vals, dry):
    if BL_DIR is None: raise RuntimeError("no backlight device")
    mx = int((BL_DIR / "max_brightness").read_text()); cur = int((BL_DIR / "brightness").read_text())
    pct = int(_fill(str(args["percent"]), vals))
    if args["op"] == "step": target_pct = cur * 100 / mx + args["sign"] * pct
    else: target_pct = pct
    target = round(max(MIN_PCT, min(100, target_pct)) * mx / 100)
    cmd = ["gdbus", "call", "--system", "--dest", "org.freedesktop.login1",
           "--object-path", "/org/freedesktop/login1/session/auto",
           "--method", "org.freedesktop.login1.Session.SetBrightness", "backlight", BL_DIR.name, str(target)]
    return cmd, f"backlight {cur}->{target} of {mx}", {"level": round(target * 100 / mx)}

def _output():
    out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True).stdout
    return next((l.split()[0] for l in out.splitlines() if " connected" in l), None)

def _night_light(args, vals, dry):
    gamma = "1.0:0.82:0.62" if args["on"] else "1.0:1.0:1.0"
    return ["xrandr", "--output", _output() or "eDP-1", "--gamma", gamma], f"gamma {gamma}", {}

def _pactl(*a):
    return subprocess.run(["pactl", *a], capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"}).stdout

def _volume(args, vals, dry):
    cur = re.search(r"(\d+)%", _pactl("get-sink-volume", "@DEFAULT_SINK@"))
    if not cur: raise RuntimeError("no audio device")
    cur = int(cur.group(1)); op = args["op"]
    if op == "mute":
        return ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], "mute", {}
    if op == "unmute":
        return ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], "unmute", {"level": cur, "level_max": VOL_MAX}
    pct = int(_fill(str(args["percent"]), vals))
    target = cur + args["sign"] * pct if op == "step" else pct
    target = max(0, min(VOL_MAX, target))
    # asking for more volume while muted means: make it audible
    return (["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{target}%"], f"volume {cur}->{target}",
            {"level": target, "level_max": VOL_MAX, "_also": [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"]]})

BUILTINS = {"backlight": _backlight, "night_light": _night_light, "volume": _volume}

def plan(cmd, vals):
    run = cmd["run"]
    if "argv" in run: return [_fill(a, vals) for a in run["argv"]], "argv", {}
    return BUILTINS[run["builtin"]](run.get("args", {}), vals, True)

def execute(cmd, vals, dry=True):
    """Runs the command. Returns (argv, note, returncode, extras); extras holds outcomes such as {"level": 60}."""
    argv, note, extras = plan(cmd, vals)
    also = extras.pop("_also", [])
    if dry: return argv, note, None, extras
    if os.environ.get("BUTLER_DRY"): return argv, note, 0, extras   # test mode: pretend success
    for a in also:
        subprocess.run(a, capture_output=True, timeout=5)
    # GUI commands (screenshot dialog) never exit on their own: if still running after a moment, it launched fine
    p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    try:
        return argv, note, p.wait(2), extras
    except subprocess.TimeoutExpired:
        return argv, note, 0, extras
