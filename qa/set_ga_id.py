#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Launch step for GA4: put the real Measurement ID into site.js, once.

    python qa/set_ga_id.py G-ABC123

Refuses a malformed ID, and refuses when site.js already holds a real one. Then run
python qa/qa.py: GA4 READINESS checks that privacy.html #access-log describes Google Analytics.
"""
import re
import sys
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "site.js"
LINE = re.compile(r"^const GA_ID = '([^']*)';", re.M)   # same pattern as GA4 READINESS in qa.py

new_id = sys.argv[1].strip() if len(sys.argv) == 2 else ""
if not re.fullmatch(r"G-[A-Z0-9]+", new_id) or re.fullmatch(r"G-X+", new_id):
    sys.exit("usage: python qa/set_ga_id.py G-ABC123  (a real GA4 Measurement ID: G- then capital letters/digits)")
text = JS.read_bytes().decode("utf-8")           # bytes in, bytes out: line endings stay as they are
found = LINE.findall(text)
if len(found) != 1:
    sys.exit(f"refused: expected exactly one `const GA_ID = '…';` line in {JS.name}, found {len(found)}")
if not re.fullmatch(r"G-X+", found[0]):
    sys.exit(f"refused: GA_ID is already set to {found[0]}; edit site.js by hand if it must change")
JS.write_bytes(LINE.sub(f"const GA_ID = '{new_id}';", text, count=1).encode("utf-8"))
print(f"site.js: GA_ID = '{new_id}'. Now run: python qa/qa.py")
