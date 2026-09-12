#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared-shell synchroniser: copies the <header>…</header>, <footer>…</footer>,
<div class="mbar">…</div> and the .notice band from index.html into every other
canonical page, so a shell change is made ONCE and stays byte-identical
(qa/qa.py hashes exactly these blocks).

    python qa/sync_shell.py [--dry]

Per-page differences that are preserved automatically:
  - aria-current="page" on the page's own nav.main link (re-applied by href)
  - nothing else: if a page needs a different shell, that is a design error.
"""
import sys, io, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ["hajimete.html", "seikatsushukanbyo.html", "hataraku.html",
         "shisetsu-kijun.html", "privacy.html", "404.html"]
SOURCE = "index.html"

BLOCKS = [
    ("header", r"<header>", "</header>"),
    ("footer", r"<footer>", "</footer>"),
    ("mbar", r'<div class="mbar"[^>]*>', "</div>"),
    ("notice", r'<!-- お知らせ帯', "</div></div>"),
]


def span(text, open_re, close_tag):
    m = re.search(open_re, text)
    if not m:
        return None
    end = text.find(close_tag, m.end())
    if end == -1:
        return None
    return m.start(), end + len(close_tag)


def main(argv):
    dry = "--dry" in argv
    src = io.open(ROOT / SOURCE, encoding="utf-8", newline="").read()
    canon = {}
    for name, o, c in BLOCKS:
        s = span(src, o, c)
        if not s:
            print(f"[WARN] {SOURCE} has no {name} block"); continue
        block = src[s[0]:s[1]].replace(' aria-current="page"', "")
        # index.html links same-page anchors as href="#x"; every other page must use href="/#x"
        canon[name] = re.sub(r'href="#', 'href="/#', block)
    changed = 0
    for page in PAGES:
        path = ROOT / page
        if not path.exists():
            continue
        text = io.open(path, encoding="utf-8", newline="").read()
        original = text
        for name, o, c in BLOCKS:
            if name not in canon:
                continue
            s = span(text, o, c)
            if not s:
                print(f"[WARN] {page} has no {name} block — not inserted"); continue
            block = canon[name]
            if name == "header":
                # re-apply aria-current to this page's own link, but only inside nav.main
                # (document pages linked from .hdr-util carry no aria-current)
                nav_s = block.find('<nav class="main"'); nav_e = block.find('</nav>', nav_s)
                if nav_s != -1 and nav_e != -1:
                    nav = block[nav_s:nav_e].replace(f'<a href="/{page}">', f'<a href="/{page}" aria-current="page">', 1)
                    block = block[:nav_s] + nav + block[nav_e:]
            text = text[:s[0]] + block + text[s[1]:]
        if text != original:
            changed += 1
            print(f"[SYNC] {page}")
            if not dry:
                io.open(path, "w", encoding="utf-8", newline="").write(text)
        else:
            print(f"[same] {page}")
    print(f"\n{'DRY RUN' if dry else 'written'}; pages changed={changed}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
