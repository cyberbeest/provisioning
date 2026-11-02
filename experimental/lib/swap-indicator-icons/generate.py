#!/usr/bin/env python3
"""Renders the swap indicator frames: swap-NN.png, NN = 01..24. Each frame is
an antialiased red disc (bright centre, slightly darker rim,
translucent towards the outer edge) whose diameter and
opacity both scale with the level, centred on a 48x48 canvas.
Usage: generate.py [outdir]   (default: this script's directory)"""
import os, sys
from PIL import Image

S, LEVELS = 48, 24
out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
CENTRE, RIM = (255, 48, 48), (150, 0, 0)
EDGE_ALPHA = 0.2  # opacity at the rim relative to the centre

for n in range(1, LEVELS + 1):
    level = n / LEVELS
    diam = S * (0.15 + 0.85 * level)
    r = diam / 2
    alpha = 255 * (0.25 + 0.75 * level)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    px = img.load()
    c = (S - 1) / 2
    for y in range(S):
        for x in range(S):
            d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
            cov = min(1.0, max(0.0, r - d + 0.5))  # antialiased edge
            if cov <= 0:
                continue
            t = min(1.0, d / r) ** 2
            rgb = tuple(round(a + (b - a) * t) for a, b in zip(CENTRE, RIM))
            px[x, y] = rgb + (round(alpha * cov * (1 - (1 - EDGE_ALPHA) * t)),)
    img.save(os.path.join(out, f"swap-{n:02d}.png"))
