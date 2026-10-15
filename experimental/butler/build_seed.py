#!/usr/bin/env python3
"""Writes the shipped embedding cache (seed/sentences-<model>.npz) for the current catalogs and factbook.

A fresh install would otherwise spend a minute embedding every sentence on its first search. Run this after
changing a catalog or a fact, and commit the result; sentences missing from the seed are still embedded on
the machine (only those), so a stale seed costs time, not correctness. Vectors are stored as float16.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from butler import loader, matcher  # noqa: E402


def main():
    cmds, errs = loader.load(user_dir="/nonexistent")   # the shipped catalogs only, no user overlay
    if errs:
        print("\n".join(errs))
        return 1
    matcher.SEED = Path("/nonexistent/seed.npz")         # embed everything, do not read the old seed
    matcher.CACHE = Path(__file__).resolve().parent / "seed" / ".build"
    items = cmds + loader.load_facts()
    matcher.Matcher(items, on_index=lambda n: print(f"embedding {n} sentences ..."))
    cache = next((matcher.CACHE).glob("sentences-*.npz"))
    with np.load(cache) as z:
        k, v = z["keys"], z["vecs"]
    out = Path(__file__).resolve().parent / "seed" / f"sentences-{matcher.MODEL_TAG}.npz"
    out.parent.mkdir(exist_ok=True)
    np.savez_compressed(out, keys=k, vecs=v.astype(np.float16))
    for f in (matcher.CACHE).glob("*"):
        f.unlink()
    matcher.CACHE.rmdir()
    print(f"{len(k)} sentences -> {out} ({out.stat().st_size // 1024} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
