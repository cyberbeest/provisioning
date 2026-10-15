#!/usr/bin/env python3
"""Battery report: reads ~/.local/state/wattage-panel/history.csv and writes a self-contained
HTML page (inline SVG, no external resources): runtime estimates, wattage ranges for locked and
unlocked use, and a multi-day timeline of on/off, power state, battery charge and power draw.

    battery-report.py [--days N]  (default 14) [--out FILE] [--no-open] [--browser auto|firefox|chrome]

Why energy deltas and not the logged watts column: with the screen off the board's power_now
reading pins to a 3.8 W floor, so the only trustworthy figure is the drop in energy_now over
time. The page opens in a window without tabs or address bar (Firefox with a dedicated profile by
default, or Chrome app mode).
Short runs are quantised by the fuel gauge (~0.29 Wh steps), so power is only derived
over stretches of at least MIN_RUN_MIN minutes and then aggregated, never per 5-minute row.
"""
import argparse
import csv
import datetime as dt
import html
import os
import shutil
import subprocess
import sys

HIST = os.path.expanduser("~/.local/state/wattage-panel/history.csv")
FULL_WH_DEFAULT = 28.88
GAP_S = 12 * 60          # rows further apart than this: the machine was off or asleep
MIN_RUN_MIN = 30         # shortest battery stretch used for a power figure
MIN_RUN_WH = 0.5         # ... and it must have used at least this much
LIGHT_W, HEAVY_W = 5.5, 7.5   # screen-on tiers (watts)

# state key -> (label, colour)
STATES = {
    "off":         ("Off / asleep",           "#2b3142"),
    "ac_on":       ("Plugged in, in use",     "#34d399"),
    "ac_locked":   ("Plugged in, locked",     "#1b7a5c"),
    "charging":    ("Charging",               "#fbbf24"),
    "batt_on":     ("Battery, in use",        "#38bdf8"),
    "batt_locked": ("Battery, locked",        "#a78bfa"),
}


def full_wh():
    try:
        with open("/sys/class/power_supply/BAT0/energy_full") as f:
            return int(f.read()) / 1e6
    except (OSError, ValueError):
        return FULL_WH_DEFAULT


def shutdown_pct():
    """Charge at which UPower powers the machine off (19-low-battery-shutdown.sh sets 5)."""
    try:
        with open("/etc/UPower/UPower.conf") as f:
            for line in f:
                if line.startswith("PercentageAction="):
                    return float(line.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return 5.0


def load(path, full):
    """-> list of dicts (t, status, pct, locked, wh) for rows that carry a screen flag."""
    rows = []
    try:
        fh = open(path, newline="")
    except OSError:
        return rows
    with fh:
        for r in csv.reader(fh):
            if not r or not r[0].isdigit() or len(r) < 5:
                continue
            try:
                t, status, pct = int(r[0]), r[1], float(r[3])
                locked = r[4] == "off"
                wh = float(r[5]) / 1e6 if len(r) > 5 else pct / 100 * full
            except ValueError:
                continue
            rows.append(dict(t=t, status=status, pct=pct, locked=locked, wh=wh))
    rows.sort(key=lambda x: x["t"])
    return rows


def state_of(r):
    if r["status"] == "battery":
        return "batt_locked" if r["locked"] else "batt_on"
    if r["status"] == "charging":
        return "charging"
    return "ac_locked" if r["locked"] else "ac_on"


def split_runs(rows):
    """Contiguous stretches (no gap larger than GAP_S)."""
    runs, cur = [], []
    for r in rows:
        if cur and r["t"] - cur[-1]["t"] > GAP_S:
            runs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        runs.append(cur)
    return runs


def battery_stretches(runs):
    """Same-state battery stretches long enough for a trustworthy power figure."""
    out = []
    for run in runs:
        cur = []
        for r in run + [None]:
            if r is not None and r["status"] == "battery" and (not cur or r["locked"] == cur[-1]["locked"]):
                cur.append(r)
                continue
            if len(cur) > 1:
                secs = cur[-1]["t"] - cur[0]["t"]
                used = cur[0]["wh"] - cur[-1]["wh"]
                if secs >= MIN_RUN_MIN * 60 and used >= MIN_RUN_WH:
                    out.append(dict(t0=cur[0]["t"], t1=cur[-1]["t"], secs=secs, used=used,
                                    w=used / (secs / 3600), locked=cur[0]["locked"]))
            cur = [r] if r is not None and r["status"] == "battery" else []
    return out


def wquantile(items, q):
    """Weighted quantile of (value, weight) pairs."""
    items = sorted(items)
    total = sum(w for _, w in items)
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= q * total:
            return v
    return items[-1][0]


def summarise(stretches, full):
    if not stretches:
        return None
    secs = sum(s["secs"] for s in stretches)
    used = sum(s["used"] for s in stretches)
    avg = used / (secs / 3600)
    pairs = [(s["w"], s["secs"]) for s in stretches]
    return dict(n=len(stretches), hours=secs / 3600, wh=used, avg=avg,
                lo=min(s["w"] for s in stretches), hi=max(s["w"] for s in stretches),
                p10=wquantile(pairs, 0.10), p50=wquantile(pairs, 0.50), p90=wquantile(pairs, 0.90),
                runtime=full / avg)


def smoothed_power(run, window_s=1800):
    """(t, watts) points for battery rows inside one contiguous run, via energy deltas."""
    pts = []
    for i, r in enumerate(run):
        if r["status"] != "battery":
            continue
        j = i
        while j > 0 and run[j - 1]["status"] == "battery" and r["t"] - run[j - 1]["t"] <= window_s:
            j -= 1
        dtm = r["t"] - run[j]["t"]
        if dtm >= 900:
            pts.append((r["t"], max(0.0, (run[j]["wh"] - r["wh"]) / (dtm / 3600))))
    return pts


# ---------------------------------------------------------------- SVG building blocks
def esc(s):
    return html.escape(str(s), quote=True)


def fmt_h(hours):
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h}h {m:02d}m" if h else f"{m}m"


def ring(frac, big, small, color, size=150):
    r = size / 2 - 11
    c = 2 * 3.14159265 * r
    frac = max(0.0, min(1.0, frac))
    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" class="ring">'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#ffffff14" stroke-width="10"/>'
            f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="10" '
            f'stroke-linecap="round" stroke-dasharray="{c*frac:.1f} {c:.1f}" '
            f'transform="rotate(-90 {size/2} {size/2})" style="filter:drop-shadow(0 0 6px {color}aa)"/>'
            f'<text x="50%" y="49%" text-anchor="middle" class="rbig">{esc(big)}</text>'
            f'<text x="50%" y="66%" text-anchor="middle" class="rsmall">{esc(small)}</text></svg>')


def rng_txt(s):
    if s["p90"] - s["p10"] < 0.15:
        return f'{s["p50"]:.2f} W'
    return f'{s["p10"]:.1f}–{s["p90"]:.1f} W'


def card(title, color, s, note=""):
    if not s:
        return (f'<div class="card"><div class="ctitle" style="color:{color}">{esc(title)}</div>'
                f'<div class="nodata">no data in this period yet</div></div>')
    return (f'<div class="card" style="--accent:{color}">'
            f'<div class="ctitle" style="color:{color}">{esc(title)}</div>'
            f'{ring(s["runtime"] / 40, fmt_h(s["runtime"]), "per full charge", color)}'
            f'<div class="cstats"><div><b>{s["avg"]:.2f} W</b><span>average</span></div>'
            f'<div><b>{rng_txt(s)}</b><span>typical range</span></div></div>'
            f'<div class="cfoot">{s["n"]} {"stretch" if s["n"] == 1 else "stretches"} · {fmt_h(s["hours"])} observed · low {s["lo"]:.2f} / high {s["hi"]:.2f} W'
            f'{("<br>" + esc(note)) if note else ""}</div></div>')


def range_chart(groups, width=1180):
    """Horizontal whisker chart of power per group: min–max faint, p10–p90 bar, median dot."""
    rows = [g for g in groups if g[2]]
    if not rows:
        return ""
    row_h, top, left, right = 46, 28, 170, 30
    h = top + row_h * len(rows) + 30
    xmax = max(10.0, max(g[2]["hi"] for g in rows) * 1.08)
    xmax = float(int(xmax) + 1)
    pw = width - left - right

    def X(v):
        return left + pw * v / xmax

    o = [f'<svg viewBox="0 0 {width} {h}" class="chart" role="img" aria-label="Power draw ranges">']
    step = 1 if xmax <= 12 else 2
    v = 0
    while v <= xmax:
        o.append(f'<line x1="{X(v):.1f}" y1="{top-8}" x2="{X(v):.1f}" y2="{h-26}" class="grid"/>'
                 f'<text x="{X(v):.1f}" y="{h-8}" text-anchor="middle" class="axis">{v:g} W</text>')
        v += step
    for i, (label, color, s) in enumerate(rows):
        y = top + i * row_h + row_h / 2
        o.append(f'<text x="{left-14}" y="{y+4:.1f}" text-anchor="end" class="rowlbl">{esc(label)}</text>')
        o.append(f'<line x1="{X(s["lo"]):.1f}" y1="{y}" x2="{X(s["hi"]):.1f}" y2="{y}" stroke="{color}" '
                 f'stroke-opacity=".35" stroke-width="2" stroke-linecap="round"/>')
        o.append(f'<rect x="{X(s["p10"]):.1f}" y="{y-9}" width="{max(3, X(s["p90"])-X(s["p10"])):.1f}" height="18" '
                 f'rx="9" fill="{color}" fill-opacity=".55" style="filter:drop-shadow(0 0 8px {color}88)"/>')
        o.append(f'<circle cx="{X(s["p50"]):.1f}" cy="{y}" r="6" fill="#fff" stroke="{color}" stroke-width="3"/>')
        o.append(f'<text x="{X(s["hi"])+10:.1f}" y="{y+4:.1f}" class="val">{s["p50"]:.1f} W median</text>')
    o.append("</svg>")
    return "".join(o)


def timeline(rows, runs, t0, t1, shutdown, width=1240):
    left, right = 54, 18
    pw = width - left - right
    span = max(1, t1 - t0)

    def X(t):
        return left + pw * (t - t0) / span

    y_days, band_y, band_h = 18, 50, 34
    pct_y, pct_h = band_y + band_h + 44, 150
    w_y, w_h = pct_y + pct_h + 40, 110
    height = w_y + w_h + 34
    o = [f'<svg viewBox="0 0 {width} {height}" class="chart timeline" id="tl" role="img" '
         f'aria-label="Multi-day battery timeline">',
         '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         '<rect width="6" height="6" fill="#2b3142"/><line x1="0" y1="0" x2="0" y2="6" stroke="#3a4156" stroke-width="2"/>'
         '</pattern></defs>']

    # day grid + labels
    d = dt.datetime.fromtimestamp(t0).replace(hour=0, minute=0, second=0, microsecond=0)
    while d.timestamp() <= t1:
        x = X(max(d.timestamp(), t0))
        if d.timestamp() >= t0:
            o.append(f'<line x1="{x:.1f}" y1="{y_days+6}" x2="{x:.1f}" y2="{w_y+w_h}" class="grid day"/>')
        nxt = d + dt.timedelta(days=1)
        xm = X(max(d.timestamp(), t0) + (min(nxt.timestamp(), t1) - max(d.timestamp(), t0)) / 2)
        if X(min(nxt.timestamp(), t1)) - X(max(d.timestamp(), t0)) >= 70:
            o.append(f'<text x="{xm:.1f}" y="{y_days}" text-anchor="middle" class="axis day">{d.strftime("%a %d %b")}</text>')
        d = nxt
    for h in (6, 12, 18):
        d = dt.datetime.fromtimestamp(t0).replace(hour=h, minute=0, second=0, microsecond=0)
        while d.timestamp() <= t1:
            if d.timestamp() >= t0:
                o.append(f'<line x1="{X(d.timestamp()):.1f}" y1="{band_y}" x2="{X(d.timestamp()):.1f}" '
                         f'y2="{w_y+w_h}" class="grid hour"/>')
            d += dt.timedelta(days=1)

    # lane 1: state band (off = hatched background)
    o.append(f'<rect x="{left}" y="{band_y}" width="{pw}" height="{band_h}" rx="8" fill="url(#hatch)"/>')
    o.append(f'<text x="{left}" y="{band_y-9}" class="lane">power state</text>')
    transitions = []
    for run in runs:
        seg_start, cur = run[0], state_of(run[0])
        for k in range(1, len(run) + 1):
            nxt = run[k] if k < len(run) else None
            st = state_of(nxt) if nxt else None
            if nxt and st == cur:
                continue
            end_t = nxt["t"] if nxt else run[-1]["t"] + 300
            x0, x1 = X(seg_start["t"]), X(min(end_t, t1))
            lbl = STATES[cur][0]
            o.append(f'<rect x="{x0:.1f}" y="{band_y}" width="{max(1.2, x1-x0):.1f}" height="{band_h}" '
                     f'fill="{STATES[cur][1]}" data-tip="{esc(lbl)}&#10;{dt.datetime.fromtimestamp(seg_start["t"]):%a %H:%M} – '
                     f'{dt.datetime.fromtimestamp(end_t):%H:%M}"/>')
            if nxt:
                transitions.append((nxt["t"], cur, st))
            seg_start, cur = nxt, st
    for t, a, b in transitions:
        x = X(t)
        o.append(f'<line x1="{x:.1f}" y1="{band_y-4}" x2="{x:.1f}" y2="{band_y+band_h+4}" class="trans" '
                 f'data-tip="{esc(STATES[a][0])} → {esc(STATES[b][0])}&#10;{dt.datetime.fromtimestamp(t):%a %H:%M}"/>')
    # run start/end markers (power on / off)
    for run in runs:
        for t, kind in ((run[0]["t"], "on"), (run[-1]["t"], "off")):
            if kind == "off" and run[-1]["t"] >= t1 - GAP_S:
                continue
            cx = X(t)
            o.append(f'<circle cx="{cx:.1f}" cy="{band_y+band_h+13}" r="3.2" '
                     f'class="pw{kind}" data-tip="{"Back on" if kind=="on" else "Went quiet"} {dt.datetime.fromtimestamp(t):%a %H:%M}"/>')

    # lane 2: battery charge
    o.append(f'<text x="{left}" y="{pct_y-9}" class="lane">battery charge</text>')
    for p in (0, 25, 50, 75, 100):
        y = pct_y + pct_h * (1 - p / 100)
        o.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" class="grid"/>'
                 f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" class="axis">{p}%</text>')
    for run in runs:
        if len(run) < 2:
            continue
        pts = [(X(r["t"]), pct_y + pct_h * (1 - r["pct"] / 100)) for r in run]
        line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = line + f" L{pts[-1][0]:.1f},{pct_y+pct_h} L{pts[0][0]:.1f},{pct_y+pct_h} Z"
        o.append(f'<path d="{area}" fill="#38bdf8" fill-opacity=".2"/>')
        o.append(f'<path d="{line}" fill="none" stroke="#7dd3fc" stroke-width="2.2" stroke-linejoin="round" '
                 f'style="filter:drop-shadow(0 0 5px #38bdf8aa)"/>')
        # recolour discharge stretches over the line
        seg = []
        for r in run + [None]:
            if r is not None and r["status"] == "battery":
                seg.append(r)
                continue
            if len(seg) > 1:
                col = STATES["batt_locked"][1] if all(s["locked"] for s in seg) else STATES["batt_on"][1]
                o.append('<path d="M' + " L".join(f'{X(s["t"]):.1f},{pct_y + pct_h * (1 - s["pct"] / 100):.1f}' for s in seg)
                         + f'" fill="none" stroke="{col}" stroke-width="2.6" stroke-linejoin="round"/>')
            seg = []

    # reference lines: empty, and the charge at which the machine shuts itself down
    y0 = pct_y + pct_h
    ys = pct_y + pct_h * (1 - shutdown / 100)
    o.append(f'<line x1="{left}" y1="{y0:.1f}" x2="{left+pw}" y2="{y0:.1f}" stroke="#e6e9f2" stroke-opacity=".7" stroke-width="1.6"/>')
    o.append(f'<line x1="{left}" y1="{ys:.1f}" x2="{left+pw}" y2="{ys:.1f}" stroke="#f87171" stroke-width="1.6" '
             f'style="filter:drop-shadow(0 0 4px #f87171aa)"/>')
    o.append(f'<text x="{left+pw-6}" y="{ys-6:.1f}" text-anchor="end" class="shut">{shutdown:g}% · safety shutdown</text>')

    # lane 3: power draw while on battery
    o.append(f'<text x="{left}" y="{w_y-9}" class="lane">power draw on battery (30 min average)</text>')
    pts_all = [p for run in runs for p in smoothed_power(run)]
    wmax = max([p[1] for p in pts_all] + [10.0])
    wmax = float(int(wmax) + 1)
    for v in range(0, int(wmax) + 1, 2 if wmax > 8 else 1):
        y = w_y + w_h * (1 - v / wmax)
        o.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+pw}" y2="{y:.1f}" class="grid"/>'
                 f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" class="axis">{v} W</text>')
    for run in runs:
        pts = smoothed_power(run)
        for (t, w), (tn, _) in zip(pts, pts[1:] + [(pts[-1][0] + 300, 0)] if pts else []):
            r = next(r for r in run if r["t"] == t)
            col = STATES["batt_locked" if r["locked"] else "batt_on"][1]
            x0, x1 = X(t), X(min(tn, t + 600))
            yy = w_y + w_h * (1 - w / wmax)
            o.append(f'<rect x="{x0:.1f}" y="{yy:.1f}" width="{max(1.2, x1-x0):.1f}" height="{w_y+w_h-yy:.1f}" '
                     f'fill="{col}" fill-opacity=".8" data-tip="{w:.2f} W (30 min average)&#10;{dt.datetime.fromtimestamp(t):%a %H:%M}"/>')
    o.append('<line id="cursor" x1="0" y1="0" x2="0" y2="0" class="cursor"/>')
    o.append("</svg>")
    return "".join(o)


CSS = """
:root{--bg:#070a12;--fg:#e6e9f2;--mut:#8b93a7;--card:#ffffff0a;--line:#ffffff14}
*{box-sizing:border-box}
body{margin:0;color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
 background:radial-gradient(1200px 600px at 12% -10%,#1b2a55 0,transparent 60%),
 radial-gradient(900px 500px at 95% 10%,#3b1d5e 0,transparent 55%),var(--bg);min-height:100vh}
.wrap{max-width:1300px;margin:0 auto;padding:36px 20px 60px}
h1{font-size:34px;letter-spacing:-.5px;margin:0;background:linear-gradient(90deg,#7dd3fc,#c4b5fd 60%,#f0abfc);
 -webkit-background-clip:text;background-clip:text;color:transparent}
.sub{color:var(--mut);margin:4px 0 26px}
h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut);margin:38px 0 14px;font-weight:600}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px;backdrop-filter:blur(6px)}
.kpi b{display:block;font-size:30px;letter-spacing:-.5px}
.kpi span{color:var(--mut);font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
.card{background:linear-gradient(160deg,#ffffff10,#ffffff04);border:1px solid var(--line);border-radius:20px;
 padding:18px 18px 16px;text-align:center;box-shadow:0 10px 40px #0006}
.ctitle{font-weight:650;font-size:16px;margin-bottom:6px}
.ring{display:block;margin:4px auto 6px}
.rbig{fill:var(--fg);font-size:23px;font-weight:700}.rsmall{fill:var(--mut);font-size:10.5px}
.cstats{display:flex;justify-content:space-around;margin:8px 0 10px}
.cstats b{display:block;font-size:17px}.cstats span{color:var(--mut);font-size:12px}
.cfoot{color:var(--mut);font-size:12px;border-top:1px solid var(--line);padding-top:9px}
.nodata{color:var(--mut);padding:60px 0}
.panel{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:14px;overflow-x:auto}
.chart{width:100%;height:auto;display:block;min-width:760px}
.grid{stroke:#ffffff10;stroke-width:1}.grid.day{stroke:#ffffff26}.grid.hour{stroke:#ffffff08;stroke-dasharray:2 4}
.axis{fill:var(--mut);font-size:11px}.axis.day{fill:#c7cde0;font-size:12px;font-weight:600}
.shut{fill:#f87171;font-size:11px;font-weight:600}
.lane{fill:var(--mut);font-size:11px;letter-spacing:.08em;text-transform:uppercase}
.rowlbl{fill:var(--fg);font-size:13.5px}.val{fill:var(--mut);font-size:12px}
.trans{stroke:#ffffffcc;stroke-width:1.2;stroke-dasharray:2 2}
.pwon{fill:#34d399}.pwoff{fill:#f87171}
.cursor{stroke:#fff;stroke-opacity:.35;stroke-width:1;pointer-events:none}
.legend{display:flex;flex-wrap:wrap;gap:8px 18px;margin:12px 4px 2px;color:var(--mut);font-size:13px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:4px;margin-right:6px;vertical-align:-1px}
#tip{position:fixed;pointer-events:none;background:#0d1224ee;border:1px solid #ffffff30;border-radius:10px;
 padding:7px 10px;font-size:12.5px;white-space:pre;display:none;box-shadow:0 8px 30px #000a;z-index:9}
"""

JS = """
const tip=document.getElementById('tip'),tl=document.getElementById('tl');
document.addEventListener('mousemove',e=>{
  const t=e.target.closest&&e.target.closest('[data-tip]');
  if(t){tip.textContent=t.getAttribute('data-tip');tip.style.display='block';
    tip.style.left=Math.min(e.clientX+14,innerWidth-220)+'px';tip.style.top=(e.clientY+14)+'px';}
  else tip.style.display='none';
  if(tl){const r=tl.getBoundingClientRect(),c=document.getElementById('cursor'),vb=tl.viewBox.baseVal;
    const x=(e.clientX-r.left)*vb.width/r.width,y=(e.clientY-r.top)*vb.height/r.height;
    if(e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom){
      c.setAttribute('x1',x);c.setAttribute('x2',x);c.setAttribute('y1',20);c.setAttribute('y2',vb.height-26);}
    else{c.setAttribute('x1',0);c.setAttribute('x2',0);}}
});
"""


def build(days, full):
    rows_all = load(HIST, full)
    if len(rows_all) < 2:
        return None
    t1 = rows_all[-1]["t"]
    t0 = max(rows_all[0]["t"], t1 - days * 86400)
    rows = [r for r in rows_all if r["t"] >= t0]
    runs = split_runs(rows)
    stretches = battery_stretches(runs)

    locked = summarise([s for s in stretches if s["locked"]], full)
    used = [s for s in stretches if not s["locked"]]
    tiers = {
        "light": summarise([s for s in used if s["w"] < LIGHT_W], full),
        "moderate": summarise([s for s in used if LIGHT_W <= s["w"] < HEAVY_W], full),
        "heavy": summarise([s for s in used if s["w"] >= HEAVY_W], full),
    }
    in_use = summarise(used, full)

    # period totals
    on_secs = sum(b["t"] - a["t"] for run in runs for a, b in zip(run, run[1:]))
    period = t1 - t0
    bat_secs = sum(b["t"] - a["t"] for run in runs for a, b in zip(run, run[1:]) if a["status"] == "battery")
    lock_secs = sum(b["t"] - a["t"] for run in runs for a, b in zip(run, run[1:]) if a["locked"])
    charges = sum(1 for run in runs for a, b in zip(run, run[1:])
                  if a["status"] != "charging" and b["status"] == "charging")
    now = rows[-1]

    kpis = [
        (f'{now["pct"]:.0f}%', f'battery now ({STATES[state_of(now)][0].lower()})'),
        (f'{on_secs / max(1, period) * 100:.0f}%', "of the period powered on"),
        (fmt_h(bat_secs / 3600), "spent on battery"),
        (f'{lock_secs / max(1, on_secs) * 100:.0f}%', "of on-time locked / screen off"),
        (str(charges), "charge sessions started"),
    ]
    kpi_html = "".join(f'<div class="kpi"><b>{esc(a)}</b><span>{esc(b)}</span></div>' for a, b in kpis)

    cards = "".join([
        card("Locked / screen off", STATES["batt_locked"][1], locked, "Notification-mode standby."),
        card("Light work", "#67e8f9", tiers["light"], f"under {LIGHT_W:g} W in use"),
        card("Moderate work", STATES["batt_on"][1], tiers["moderate"], f"{LIGHT_W:g}–{HEAVY_W:g} W in use"),
        card("Heavy work", "#fb7185", tiers["heavy"], f"over {HEAVY_W:g} W in use"),
    ])
    rng = range_chart([("Locked / screen off", STATES["batt_locked"][1], locked),
                       ("Light work", "#67e8f9", tiers["light"]),
                       ("Moderate work", STATES["batt_on"][1], tiers["moderate"]),
                       ("Heavy work", "#fb7185", tiers["heavy"]),
                       ("All in use", "#e2e8f0", in_use)])
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(l)}</span>' for l, c in STATES.values())
    stamp = dt.datetime.fromtimestamp(t1).strftime("%a %d %b %Y, %H:%M")
    d0, d1 = dt.datetime.fromtimestamp(t0).date(), dt.datetime.fromtimestamp(t1).date()
    n_days = (d1 - d0).days + 1
    # "Used" = the screen was on in at least two log rows (~10 minutes) that day.
    on_rows = {}
    for r in rows:
        if not r["locked"]:
            day = dt.datetime.fromtimestamp(r["t"]).date()
            on_rows[day] = on_rows.get(day, 0) + 1
    used_days = sum(1 for n in on_rows.values() if n >= 2)
    span_txt = (f'{d0:%d %b} – {d1:%d %b} · {n_days} day{"s" if n_days != 1 else ""}, '
                f'used on {used_days} of them')

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Battery Report</title>
<style>{CSS}</style></head><body><div class="wrap">
<h1>Battery Report</h1>
<div class="sub">{esc(span_txt)} · last reading {esc(stamp)} · full charge {full:.2f} Wh</div>
<div class="hero">{kpi_html}</div>
<h2>Expected runtime per full charge</h2><div class="cards">{cards}</div>
<h2>Power draw ranges</h2><div class="panel">{rng}</div>
<h2>Timeline</h2><div class="panel">{timeline(rows, runs, t0, t1, shutdown_pct())}
<div class="legend">{legend}<span><i style="background:#34d399;border-radius:50%"></i>back on</span>
<span><i style="background:#f87171;border-radius:50%"></i>went quiet</span></div></div>
</div><div id="tip"></div><script>{JS}</script></body></html>"""


VIEW_PROFILE = os.path.expanduser("~/.mozilla/firefox/battery-view")
VIEW_USER_JS = """user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.couldRestoreSession.count", -1);
user_pref("browser.sessionstore.max_tabs_undo", 0);
user_pref("browser.sessionstore.max_windows_undo", 0);
user_pref("browser.sessionstore.interval", 3600000);
"""
# Hides the tab strip, toolbar and sidebar button; the window keeps its system title bar.
VIEW_USER_CHROME = """#TabsToolbar, #nav-bar, #PersonalToolbar, #sidebar-main, #sidebar-box { visibility: collapse !important; }
"""


def firefox_view_profile():
    """Dedicated Firefox profile whose windows show only the page (no tabs, no address bar)."""
    os.makedirs(os.path.join(VIEW_PROFILE, "chrome"), exist_ok=True)
    for name, text in (("user.js", VIEW_USER_JS), ("chrome/userChrome.css", VIEW_USER_CHROME)):
        path = os.path.join(VIEW_PROFILE, name)
        try:
            if open(path).read() == text:
                continue
        except OSError:
            pass
        with open(path, "w") as f:
            f.write(text)
    return VIEW_PROFILE


def view(path, browser):
    """Open the page in an ordinary window without controls. Both browsers are jailed and can only
    read ~/Downloads and ~/Pictures, hence the default output path. Chrome has an app mode;
    Firefox gets its own profile with a userChrome.css that hides the toolbars."""
    url = "file://" + path
    if browser == "auto":
        browser = "firefox" if shutil.which("firefox") else "chrome"
    if browser == "firefox":
        cmd = ["firefox", "--no-remote", "--profile", firefox_view_profile(), "--width", "1360",
               "--height", "1000", "--new-window", url]
    else:
        cmd = ["google-chrome", f"--app={url}", "--window-size=1360,1000"]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--out", default=os.path.expanduser("~/Downloads/.battery-report.html"))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--browser", choices=("auto", "firefox", "chrome"), default="auto")
    a = ap.parse_args()
    page = build(a.days, full_wh())
    if page is None:
        msg = "Not enough battery history yet. Use the laptop on battery for a while and try again."
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", "-i", "battery", "Battery Report", msg])
        sys.exit(msg)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write(page)
    print(a.out)
    if not a.no_open:
        view(a.out, a.browser)


if __name__ == "__main__":
    main()
