#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exact-match edit applier for the なかむらクリニック site.

    python qa/apply_edits.py edits.json [--dry]

edits.json = [ {"file": "index.html", "old": "…exact current string…", "new": "…",
                "count": 1 (optional, default 1; use "all" to replace every occurrence)}, … ]

Every edit must match exactly `count` times, otherwise it is reported as a MISS or
AMBIGUOUS and NOT applied (other edits in the same file are still applied).
Files are written back with their original newline bytes untouched (newline="").
Exit code 1 if any edit was not applied.
"""
import sys, io, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv):
    if not argv:
        print(__doc__); return 2
    dry = "--dry" in argv
    src = [a for a in argv if not a.startswith("--")][0]
    edits = json.loads(Path(src).read_text(encoding="utf-8"))
    by_file = {}
    for i, e in enumerate(edits):
        by_file.setdefault(e["file"], []).append((i, e))
    failed = 0
    for fname, items in by_file.items():
        path = ROOT / fname
        if not path.exists():
            for i, _ in items:
                print(f"[MISS] #{i} {fname}: file not found"); failed += 1
            continue
        text = io.open(path, encoding="utf-8", newline="").read()
        for i, e in items:
            old, new = e["old"], e["new"]
            want = e.get("count", 1)
            n = text.count(old)
            if n == 0:
                print(f"[MISS] #{i} {fname}: old string not found — {old[:70]!r}"); failed += 1; continue
            if want != "all" and n != want:
                print(f"[AMBIGUOUS] #{i} {fname}: found {n}x, expected {want} — {old[:70]!r}"); failed += 1; continue
            text = text.replace(old, new)
            print(f"[OK] #{i} {fname}: {n}x — {old[:60]!r}")
        if not dry:
            io.open(path, "w", encoding="utf-8", newline="").write(text)
    print(f"\n{'DRY RUN — nothing written' if dry else 'written'}; failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
