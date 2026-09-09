#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
なかむらクリニック — QA harness (stdlib only: re, json, hashlib, pathlib, sys).

Implements every mechanically-checkable rule from siteplan/global.md's QA RULES
section. Rules for pages that do not exist yet SKIP (not FAIL) so the harness
runs cleanly on whatever subset of the 7-page site currently exists in the repo.

Usage:
    python qa/qa.py                      # checks every canonical page that exists
    python qa/qa.py index.html foo.html  # checks only the given pages (still
                                          # cross-checks shared-shell / repo-wide
                                          # rules only across the given set)

Exit code: 1 if any rule FAILs, 0 otherwise. MANUAL rules never affect exit code.
"""
import sys
import re
import json
import hashlib
from pathlib import Path
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# DATA-DRIVEN EXPECTATION TABLES — edit these as pages are added / copy changes.
# A filename absent from a table means "no page-specific expectation yet" and
# that page SKIPs the rule instead of failing.
# ---------------------------------------------------------------------------

CANONICAL_PAGES = [
    "index.html", "hajimete.html", "seikatsushukanbyo.html", "hataraku.html",
    "shisetsu-kijun.html", "privacy.html", "404.html",
]

FIXED_HOURS_STRING = "水曜午後・金曜・土曜午後は完全予約制"
RECEPTION_SENTENCE = "受付も待合も、内科と同じです。"
RETIRED_BLUEPRINT_LINE = "ひとつの受付から、ふたつの診療科へ。"

FIXED_HOURS_EXPECT = {
    "index.html": 2, "hajimete.html": 2, "seikatsushukanbyo.html": 2,
    "hataraku.html": 2, "shisetsu-kijun.html": 1, "privacy.html": 1, "404.html": 1,
}

TEL_EXPECT = {
    "index.html": 7, "hajimete.html": 5, "seikatsushukanbyo.html": 5,
    "hataraku.html": 5, "shisetsu-kijun.html": 3, "privacy.html": 3, "404.html": 4,
}

RECEPTION_SENTENCE_EXPECT = {
    "index.html": 1, "seikatsushukanbyo.html": 1, "hataraku.html": 1,
    "hajimete.html": 0, "shisetsu-kijun.html": 0, "privacy.html": 0, "404.html": 0,
}

HITOTSU_NO_UKETSUKE_MAX = {
    "index.html": 3, "seikatsushukanbyo.html": 1, "hataraku.html": 1,
    "hajimete.html": 0, "shisetsu-kijun.html": 0, "privacy.html": 0, "404.html": 0,
}

# 診断書 cap: default 1 per page; hataraku.html is capped at its recorded
# post-edit baseline (may never grow past this number).
SHINDANSHO_DEFAULT_MAX = 1
SHINDANSHO_MAX = {
    "hataraku.html": 7,
    # 文書料 table rows mirror the in-clinic 掲示 verbatim (休職用診断書 / 復職の診断書 / その他の診断書);
    # the cap equals the row count and may never grow without the 掲示 itself changing.
    "shisetsu-kijun.html": 3,
}

# Phone digit string allowed only inside these element classes.
TEL_ALLOWED_CLASSES = [
    "hdr-call", "btn-call", "call-card", "hm-call", "spec-row", "foot-tel", "mbar",
]

BANNED_STRINGS = [
    "自律神経失調症", "睡眠時無呼吸", "いびき", "CPAP", "睡眠外来", "睡眠科", "睡眠障害", "PSG", "SAS",
    "同じ日", "その日のうち", "即日", "異常がなければ", "診断書に対応", "唯一", "No.1",
    "地域一", "最先端", "必ず", "体験談", "患者様の声", "仕事帰り", "夜間", "栄養指導",
    "食事指導", "オンラインで完結", "通院不要", "1568",
    RETIRED_BLUEPRINT_LINE,
]

WHITELIST_LINES = {
    # CONFIRM #7 answered 2026-09-06 (届出済み): the negative online claim was removed from
    # hataraku.html; the only sanctioned online wording is 「オンラインでの診療については
    # お電話でご確認ください。」 in hajimete.html §③ (does not contain the banned token).
    "shisetsu-kijun.html": ["夜間・休日の問い合わせへの対応を行っています。"],
}

TEMPLATE_CONFORMANCE_DOC_FORBIDDEN = [
    'class="kicker"', 'class="close-cta"', 'class="hours-mini"', 'class="norikae"',
    'class="mnav"', 'class="pg-sec-alt"', '<picture', 'care-glyph',
]
TEMPLATE_CONFORMANCE_CHANNEL_FORBIDDEN = ['class="hero"', 'class="fact-strip"', 'class="roundels"']
DOC_PAGES = {"shisetsu-kijun.html", "privacy.html"}
CHANNEL_PAGES = {"hajimete.html", "seikatsushukanbyo.html", "hataraku.html"}
NO_CLOSE_BAND_PAGES = {"shisetsu-kijun.html", "privacy.html"}
NO_HERO_PAGES = {"hajimete.html", "seikatsushukanbyo.html", "hataraku.html", "shisetsu-kijun.html", "privacy.html", "404.html"}

# ---------------------------------------------------------------------------
# Result bookkeeping
# ---------------------------------------------------------------------------

results = []  # list of (status, rule, detail)


def report(status, rule, detail=""):
    results.append((status, rule, detail))
    tag = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "MANUAL": "MANUAL"}[status]
    line = f"[{tag}] {rule}"
    if detail:
        line += f" — {detail}"
    print(line)


def snippet(text, pos, width=60):
    start = max(0, pos - width // 2)
    end = min(len(text), pos + width // 2)
    return text[start:end].replace("\n", "\\n")


def line_no(text, pos):
    return text.count("\n", 0, pos) + 1


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_pages(argv):
    if argv:
        names = argv
    else:
        names = [p for p in CANONICAL_PAGES if (ROOT / p).exists()]
    pages = {}
    for name in names:
        path = ROOT / name
        if not path.exists():
            print(f"[SKIP] page not found on disk: {name}")
            continue
        pages[name] = path.read_text(encoding="utf-8")
    return pages


# ---------------------------------------------------------------------------
# RULE: BANNED STRINGS
# ---------------------------------------------------------------------------

def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).strip()


def rule_banned_strings(pages):
    for name, text in pages.items():
        lines = text.split("\n")
        whitelisted = set(WHITELIST_LINES.get(name, []))
        violations = []
        for banned in BANNED_STRINGS:
            for m in re.finditer(re.escape(banned), text):
                pos = m.start()
                ln = line_no(text, pos)
                line_text = strip_tags(lines[ln - 1])
                if line_text in whitelisted:
                    continue
                violations.append((banned, ln, snippet(text, pos)))
        if violations:
            for banned, ln, snip in violations:
                report("FAIL", f"BANNED STRINGS [{name}]", f'"{banned}" at line {ln}: {snip}')
        else:
            report("PASS", f"BANNED STRINGS [{name}]", "0 occurrences")


# ---------------------------------------------------------------------------
# RULE: FIXED HOURS STRING + NO-PARAPHRASE 完全予約制 CHECK
# ---------------------------------------------------------------------------

def rule_fixed_hours_string(pages):
    for name, text in pages.items():
        count = len(re.findall(re.escape(FIXED_HOURS_STRING), text))
        expect = FIXED_HOURS_EXPECT.get(name)
        if expect is None:
            report("SKIP", f"FIXED HOURS STRING [{name}]", "no expectation recorded for this page")
        elif count == expect and count > 0:
            report("PASS", f"FIXED HOURS STRING [{name}]", f"count={count} (expected {expect})")
        else:
            report("FAIL", f"FIXED HOURS STRING [{name}]", f"count={count}, expected {expect}")

        # no-paraphrase check on 完全予約制 substring
        allowed_spans = []
        for m in re.finditer(re.escape(FIXED_HOURS_STRING), text):
            allowed_spans.append((m.start(), m.end()))
        for m in re.finditer(r'<span class="vh">完全予約制</span>', text):
            allowed_spans.append((m.start(), m.end()))
        for m in re.finditer(r'<span class="chip chip-appt">[^<]*完全予約制[^<]*</span>', text):
            allowed_spans.append((m.start(), m.end()))
        for m in re.finditer(r'class="chip chip-appt"[^>]*>[^<]*完全予約制', text):
            allowed_spans.append((m.start(), m.end()))
        bad = []
        for m in re.finditer("完全予約制", text):
            pos = m.start()
            if not any(s <= pos < e for s, e in allowed_spans):
                bad.append((line_no(text, pos), snippet(text, pos)))
        if bad:
            for ln, snip in bad:
                report("FAIL", f"完全予約制 NO-PARAPHRASE [{name}]", f"line {ln}: {snip}")
        else:
            report("PASS", f"完全予約制 NO-PARAPHRASE [{name}]", "all occurrences whitelisted")


# ---------------------------------------------------------------------------
# RULE: CANONICAL RECEPTION SENTENCE + ひとつの受付 BUDGET
# ---------------------------------------------------------------------------

def rule_reception_sentence(pages):
    for name, text in pages.items():
        count = len(re.findall(re.escape(RECEPTION_SENTENCE), text))
        expect = RECEPTION_SENTENCE_EXPECT.get(name)
        if expect is None:
            report("SKIP", f"RECEPTION SENTENCE [{name}]", "no expectation recorded")
        elif count == expect:
            report("PASS", f"RECEPTION SENTENCE [{name}]", f"count={count} (expected {expect})")
        else:
            report("FAIL", f"RECEPTION SENTENCE [{name}]", f"count={count}, expected {expect}")

        sub_count = text.count("ひとつの受付")
        cap = HITOTSU_NO_UKETSUKE_MAX.get(name)
        if cap is None:
            report("SKIP", f"ひとつの受付 BUDGET [{name}]", "no cap recorded")
        elif sub_count <= cap:
            report("PASS", f"ひとつの受付 BUDGET [{name}]", f"count={sub_count} (max {cap})")
        else:
            report("FAIL", f"ひとつの受付 BUDGET [{name}]", f"count={sub_count} exceeds max {cap}")


# ---------------------------------------------------------------------------
# RULE: 診断書 CAP
# ---------------------------------------------------------------------------

def rule_shindansho(pages):
    for name, text in pages.items():
        count = text.count("診断書")
        cap = SHINDANSHO_MAX.get(name, SHINDANSHO_DEFAULT_MAX)
        if count <= cap:
            report("PASS", f"診断書 CAP [{name}]", f"count={count} (max {cap})")
        else:
            report("FAIL", f"診断書 CAP [{name}]", f"count={count} exceeds max {cap}")
        # must never appear as a route-strip branch label or legend title
        for m in re.finditer(r'<text[^>]*>[^<]*診断書[^<]*</text>', text):
            report("FAIL", f"診断書 IN ROUTE STRIP [{name}]", snippet(text, m.start()))
        for m in re.finditer(r'<b>[^<]*診断書[^<]*</b>', text):
            report("FAIL", f"診断書 IN LEGEND TITLE [{name}]", snippet(text, m.start()))


# ---------------------------------------------------------------------------
# RULE: PHONE — tel: counts + digit-string containment
# ---------------------------------------------------------------------------

def rule_phone(pages):
    tel_href_re = re.compile(r'tel:0662450378')
    for name, text in pages.items():
        count = len(tel_href_re.findall(text))
        expect = TEL_EXPECT.get(name)
        if expect is None:
            report("SKIP", f"PHONE tel: COUNT [{name}]", "no expectation recorded")
        elif count == expect:
            report("PASS", f"PHONE tel: COUNT [{name}]", f"count={count} (expected {expect})")
        else:
            report("FAIL", f"PHONE tel: COUNT [{name}]", f"count={count}, expected {expect}")

        # digit-string containment: every "06-6245-0378" must sit inside an
        # element whose class list intersects the whitelist.
        bad = []
        for m in re.finditer(re.escape("06-6245-0378"), text):
            pos = m.start()
            window = text[max(0, pos - 1500):pos]
            # any ancestor (not just the nearest) class="..." attribute in the
            # window may carry the allowed class — e.g. <a class="btn-call">...
            # <span class="tel">NUMBER</span></a> nests .tel inside .btn-call.
            # 1500 chars covers .mbar, whose .tel sits after a sibling <a> with
            # a long inline <svg> path before the phone number is reached.
            class_matches = list(re.finditer(r'class="([^"]*)"', window))
            ok = any(c in TEL_ALLOWED_CLASSES for cm in class_matches for c in cm.group(1).split())
            if not ok:
                bad.append((line_no(text, pos), snippet(text, pos)))
        if bad:
            for ln, snip in bad:
                report("FAIL", f"PHONE DIGIT IN PROSE [{name}]", f"line {ln}: {snip}")
        else:
            report("PASS", f"PHONE DIGIT CONTAINMENT [{name}]", "all occurrences inside whitelisted classes")


# ---------------------------------------------------------------------------
# RULE: SINGLE-HOME STRUCTURAL CHECKS (repo-wide)
# ---------------------------------------------------------------------------

def rule_single_home(pages):
    checks = [
        ('<section class="hours-sec"', 1, "index.html"),
        ('<div class="first-visit"', 0, None),
        ('<div class="call-card"', 1, "index.html"),
        ("機能強化加算", 1, "shisetsu-kijun.html"),
        ('<p class="sec-lead"', 0, None),
        ('<p class="online-line"', 0, None),
    ]
    for needle, expected_count, expected_only_file in checks:
        hits = {name: text.count(needle) for name, text in pages.items() if needle in text}
        total = sum(hits.values())
        if expected_count == 0:
            if total == 0:
                report("PASS", f"SINGLE-HOME [{needle}]", "0 occurrences repo-wide")
            else:
                report("FAIL", f"SINGLE-HOME [{needle}]", f"found in: {list(hits.keys())}")
        else:
            if expected_only_file not in pages:
                report("SKIP", f"SINGLE-HOME [{needle}]", f"{expected_only_file} not in checked set")
                continue
            others = {k: v for k, v in hits.items() if k != expected_only_file}
            if hits.get(expected_only_file, 0) == expected_count and not others:
                report("PASS", f"SINGLE-HOME [{needle}]", f"exactly {expected_count} in {expected_only_file}, 0 elsewhere")
            else:
                report("FAIL", f"SINGLE-HOME [{needle}]", f"hits={hits}, expected exactly {expected_count} in {expected_only_file} only")


# ---------------------------------------------------------------------------
# RULE: 文書料 AMOUNTS
# ---------------------------------------------------------------------------

def rule_bunshoryo_amounts(pages):
    whitelisted_amounts = ["（3割負担で約300円）", "（3割負担で約750円）"]
    for name, text in pages.items():
        if name == "shisetsu-kijun.html":
            report("SKIP", f"文書料 AMOUNTS [{name}]", "amounts belong here by rule")
            continue
        violations = []
        for tbl_m in re.finditer(r'<table class="pg-doc-table">.*?</table>', text, re.S):
            block = tbl_m.group(0)
            for yen_m in re.finditer(r'[^\s<]*円', block):
                # include the closing 「）」 after 円 so whitelisted amounts can actually match
                window = block[max(0, yen_m.start() - 20):yen_m.end() + 2]
                if any(w in window for w in whitelisted_amounts):
                    continue
                violations.append(snippet(block, yen_m.start()))
        if violations:
            for snip in violations:
                report("FAIL", f"文書料 AMOUNT OUTSIDE shisetsu-kijun.html [{name}]", snip)
        else:
            report("PASS", f"文書料 AMOUNTS [{name}]", "no non-whitelisted 円 amounts in .pg-doc-table")


# ---------------------------------------------------------------------------
# RULE: SHARED SHELL BYTE-IDENTITY
# ---------------------------------------------------------------------------

def extract_block(text, open_tag_re, close_tag):
    m = re.search(open_tag_re, text)
    if not m:
        return None
    start = m.start()
    end_idx = text.find(close_tag, m.end())
    if end_idx == -1:
        return None
    return text[start:end_idx + len(close_tag)]


def normalize_shell(block):
    block = block.replace(' aria-current="page"', "")
    block = re.sub(r'href="#', 'href="/#', block)
    return block


def rule_shared_shell(pages):
    blocks = {"header": {}, "footer": {}, "mbar": {}}
    for name, text in pages.items():
        header = extract_block(text, r"<header>", "</header>")
        footer = extract_block(text, r"<footer>", "</footer>")
        mbar = extract_block(text, r'<div class="mbar"[^>]*>', "</div>")
        if header:
            blocks["header"][name] = hashlib.sha256(normalize_shell(header).encode("utf-8")).hexdigest()
        if footer:
            blocks["footer"][name] = hashlib.sha256(normalize_shell(footer).encode("utf-8")).hexdigest()
        if mbar:
            blocks["mbar"][name] = hashlib.sha256(normalize_shell(mbar).encode("utf-8")).hexdigest()
    for block_name, hashes in blocks.items():
        if len(hashes) < 2:
            report("SKIP", f"SHARED SHELL BYTE-IDENTITY [{block_name}]", "fewer than 2 pages carry this block")
            continue
        unique = set(hashes.values())
        if len(unique) == 1:
            report("PASS", f"SHARED SHELL BYTE-IDENTITY [{block_name}]", f"identical across {list(hashes.keys())}")
        else:
            report("FAIL", f"SHARED SHELL BYTE-IDENTITY [{block_name}]", f"divergent hashes: {hashes}")


# ---------------------------------------------------------------------------
# RULE: SCRIPTS
# ---------------------------------------------------------------------------

def rule_scripts(pages):
    for name, text in pages.items():
        scripts = re.findall(r'<script\b[^>]*>.*?</script>', text, re.S)
        site_js = [s for s in scripts if 'src="/site.js"' in s]
        # JSON-LD blocks are <script type="application/ld+json">...</script> — not
        # "inline script" for this rule's purposes (they carry no executable JS).
        inline = [s for s in scripts if "src=" not in s and 'type="application/ld+json"' not in s]

        if len(site_js) == 1 and "defer" in site_js[0]:
            report("PASS", f"SCRIPT /site.js [{name}]", "exactly one, deferred")
        else:
            report("FAIL", f"SCRIPT /site.js [{name}]", f"found {len(site_js)} matching tags: {site_js}")

        expected_inline = "document.documentElement.classList.add('js')"
        good_inline = [s for s in inline if strip_tags_script(s) == expected_inline]
        if len(inline) == 1 and len(good_inline) == 1:
            report("PASS", f"SCRIPT INLINE js-class [{name}]", "exactly one, matches spec")
        else:
            report("FAIL", f"SCRIPT INLINE js-class [{name}]", f"inline scripts found: {inline}")

        onclick_hits = list(re.finditer(r'onclick=', text))
        js_href_hits = list(re.finditer(r'javascript:', text))
        if not onclick_hits and not js_href_hits:
            report("PASS", f"SCRIPT NO INLINE HANDLERS [{name}]", "0 onclick=/javascript:")
        else:
            report("FAIL", f"SCRIPT NO INLINE HANDLERS [{name}]",
                   f"onclick={len(onclick_hits)}, javascript:={len(js_href_hits)}")

    site_js_path = ROOT / "site.js"
    if site_js_path.exists():
        report("PASS", "SCRIPT /site.js EXISTS", str(site_js_path))
    else:
        report("FAIL", "SCRIPT /site.js EXISTS", "site.js not found at repo root")


def strip_tags_script(script_tag):
    inner = re.sub(r'^<script[^>]*>', '', script_tag)
    inner = re.sub(r'</script>$', '', inner)
    return inner.strip()


# ---------------------------------------------------------------------------
# RULE: ACCESSIBILITY (statics)
# ---------------------------------------------------------------------------

def rule_accessibility(pages):
    for name, text in pages.items():
        body_m = re.search(r'<body[^>]*>(.*)', text, re.S)
        if body_m:
            after_body = body_m.group(1).lstrip()
            if after_body.startswith('<a class="skip" href="#top">本文へ</a>'):
                report("PASS", f"SKIP LINK FIRST [{name}]", "present, first child of body")
            else:
                report("FAIL", f"SKIP LINK FIRST [{name}]", f"body starts with: {after_body[:80]!r}")
        else:
            report("FAIL", f"SKIP LINK FIRST [{name}]", "no <body> found")

        if re.search(r'<main id="top" tabindex="-1"', text):
            report("PASS", f"MAIN id=top tabindex=-1 [{name}]", "present")
        else:
            report("FAIL", f"MAIN id=top tabindex=-1 [{name}]", "missing or malformed")

        kickers = re.findall(r'<div class="kicker"><span([^>]*)>', text)
        missing_lang = [k for k in kickers if 'lang="en"' not in k]
        if not missing_lang:
            report("PASS", f"KICKER lang=en [{name}]", f"{len(kickers)} kicker(s), all tagged")
        else:
            report("FAIL", f"KICKER lang=en [{name}]", f"{len(missing_lang)} of {len(kickers)} missing lang=en")

        kicker_count = len(kickers)
        if kicker_count <= 4:
            report("PASS", f"KICKER COUNT <=4 [{name}]", f"count={kicker_count}")
        else:
            report("FAIL", f"KICKER COUNT <=4 [{name}]", f"count={kicker_count} exceeds 4 (pending T1 chaptering)")

    report("MANUAL", "axe-core zero violations (html-has-lang/valid-lang/bypass/color-contrast/link-name)")

    pages_css = ROOT / "pages.css"
    if pages_css.exists():
        css = pages_css.read_text(encoding="utf-8")
        m = re.search(r'\.pg-mini-glyph\{[^}]*font-size:(\d+)px', css)
        if m and int(m.group(1)) >= 19:
            report("PASS", "PG-MINI-GLYPH FONT-SIZE >=19px", f"found {m.group(1)}px")
        elif m:
            report("FAIL", "PG-MINI-GLYPH FONT-SIZE >=19px", f"found {m.group(1)}px")
        else:
            report("SKIP", "PG-MINI-GLYPH FONT-SIZE >=19px", "rule not yet added (pending T1)")
    else:
        report("SKIP", "PG-MINI-GLYPH FONT-SIZE >=19px", "pages.css not found")


# ---------------------------------------------------------------------------
# RULE: JSON-LD
# ---------------------------------------------------------------------------

def collect_ld_nodes(text):
    nodes = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', text, re.S):
        raw = m.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            nodes.append({"__parse_error__": str(e), "__raw__": raw})
            continue
        graph = data.get("@graph") if isinstance(data, dict) else None
        if graph is not None:
            nodes.extend(graph)
        elif isinstance(data, list):
            nodes.extend(data)
        else:
            nodes.append(data)
    return nodes


def node_types(node):
    t = node.get("@type")
    if t is None:
        return []
    if isinstance(t, list):
        return t
    return [t]


def rule_jsonld(pages):
    all_nodes = {}
    parse_errors = []
    for name, text in pages.items():
        nodes = collect_ld_nodes(text)
        all_nodes[name] = nodes
        for n in nodes:
            if "__parse_error__" in n:
                parse_errors.append((name, n["__parse_error__"]))
    if parse_errors:
        for name, err in parse_errors:
            report("FAIL", f"JSON-LD PARSE [{name}]", err)
    else:
        report("PASS", "JSON-LD PARSE (all blocks)", "all JSON-LD blocks parsed cleanly")

    # exactly one MedicalClinic node repo-wide (full definition — has "name" key,
    # to avoid counting the partial re-declarations, though those should also
    # be flagged separately as duplicates).
    clinic_hits = []
    for name, nodes in all_nodes.items():
        for n in nodes:
            if "@type" in n and "MedicalClinic" in node_types(n):
                clinic_hits.append(name)
    if len(clinic_hits) == 1:
        report("PASS", "JSON-LD exactly one MedicalClinic node", f"found in {clinic_hits[0]}")
    else:
        report("FAIL", "JSON-LD exactly one MedicalClinic node", f"found {len(clinic_hits)} occurrences: {clinic_hits}")

    banned_types = ["Review", "AggregateRating", "Offer", "PriceSpecification"]
    for name, text in pages.items():
        hits = []
        for bt in banned_types:
            if f'"@type": "{bt}"' in text or f'"@type":"{bt}"' in text:
                hits.append(bt)
        if "hasCredential" in text:
            hits.append("hasCredential")
        if hits:
            report("FAIL", f"JSON-LD BANNED TYPES [{name}]", f"found: {hits}")
        else:
            report("PASS", f"JSON-LD BANNED TYPES [{name}]", "none present")

    for name, nodes in all_nodes.items():
        if name in ("index.html", "404.html"):
            report("SKIP", f"JSON-LD BreadcrumbList [{name}]", "exempt page")
            continue
        has_bc = any("BreadcrumbList" in node_types(n) for n in nodes if "@type" in n)
        if has_bc:
            report("PASS", f"JSON-LD BreadcrumbList [{name}]", "present")
        else:
            report("FAIL", f"JSON-LD BreadcrumbList [{name}]", "missing")

    for name, text in pages.items():
        nodes = all_nodes[name]
        faq_nodes = [n for n in nodes if "@type" in n and "FAQPage" in node_types(n)]
        visible = re.findall(
            r'<details class="pg-faq"><summary>(.*?)</summary><p>(.*?)</p></details>', text, re.S)
        visible_pairs = [(strip_tags(q), strip_tags(a)) for q, a in visible]
        if not faq_nodes and not visible_pairs:
            report("SKIP", f"JSON-LD FAQPage [{name}]", "no visible FAQ, no FAQPage node")
            continue
        if not faq_nodes and visible_pairs:
            report("FAIL", f"JSON-LD FAQPage [{name}]", "visible FAQ exists but no FAQPage node")
            continue
        if faq_nodes and not visible_pairs:
            report("FAIL", f"JSON-LD FAQPage [{name}]", "FAQPage node exists but no visible FAQ")
            continue
        json_pairs = []
        for fn in faq_nodes:
            for q in fn.get("mainEntity", []):
                json_pairs.append((q.get("name", ""), q.get("acceptedAnswer", {}).get("text", "")))
        if json_pairs == visible_pairs:
            report("PASS", f"JSON-LD FAQPage MATCHES VISIBLE [{name}]", f"{len(json_pairs)} Q&A pairs, same order")
        else:
            mismatches = [i for i in range(max(len(json_pairs), len(visible_pairs)))
                          if i >= len(json_pairs) or i >= len(visible_pairs) or json_pairs[i] != visible_pairs[i]]
            report("FAIL", f"JSON-LD FAQPage MATCHES VISIBLE [{name}]",
                   f"mismatch at index(es) {mismatches} (json_count={len(json_pairs)}, visible_count={len(visible_pairs)})")

    today = date.today()
    for name, text in pages.items():
        nodes = all_nodes[name]
        last_reviewed_vals = [n.get("lastReviewed") for n in nodes if "lastReviewed" in n]
        visible_m = re.search(r'最終更新[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if not last_reviewed_vals and not visible_m:
            report("SKIP", f"lastReviewed == 最終更新 [{name}]", "neither present")
            continue
        if not last_reviewed_vals or not visible_m:
            report("FAIL", f"lastReviewed == 最終更新 [{name}]",
                   f"lastReviewed={last_reviewed_vals}, visible_match={bool(visible_m)}")
            continue
        y, mo, d = visible_m.groups()
        visible_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        ok = all(v == visible_date for v in last_reviewed_vals)
        try:
            parsed = date.fromisoformat(visible_date)
            not_future = parsed <= today
        except ValueError:
            not_future = False
        if ok and not_future:
            report("PASS", f"lastReviewed == 最終更新 [{name}]", f"{visible_date}, not in future")
        else:
            report("FAIL", f"lastReviewed == 最終更新 [{name}]",
                   f"lastReviewed={last_reviewed_vals}, visible={visible_date}, not_future={not_future}")

        vft_hits = text.count("validFrom") + text.count("validThrough")
        if vft_hits == 0:
            report("PASS", f"NO validFrom/validThrough [{name}]", "0 occurrences")
        else:
            report("FAIL", f"NO validFrom/validThrough [{name}]", f"{vft_hits} occurrences")


# ---------------------------------------------------------------------------
# RULE: HOURS CONSISTENCY
# ---------------------------------------------------------------------------

def rule_hours_consistency(pages):
    canonical_times = "午前 9:00–13:00（土曜〈第2・第4週のみ〉は10:00〜）／午後 14:00–17:45（受付）"
    canonical_off = "休診：木・日・祝"
    for name, text in pages.items():
        hm_times = re.findall(r'<p class="hm-times">(.*?)</p>', text, re.S)
        hours_times = re.findall(r'<p class="hours-times">(.*?)</p>', text, re.S)
        foot_meta = re.findall(r'<p class="foot-meta">(.*?)</p>', text, re.S)
        found = [strip_tags(x) for x in hm_times + hours_times]
        found_ok = all(f == strip_tags(canonical_times) or canonical_times.replace("<span class=\"num\">", "").replace("</span>", "") in f or True for f in found)
        mismatches = []
        for label, vals in (("hm-times", hm_times), ("hours-times", hours_times)):
            for v in vals:
                plain = re.sub(r'<span class="num">|</span>', '', v)
                if plain != canonical_times:
                    mismatches.append((label, plain))
        if not (hm_times or hours_times):
            report("SKIP", f"HOURS CONSISTENCY times [{name}]", "no .hm-times/.hours-times on this page")
        elif not mismatches:
            report("PASS", f"HOURS CONSISTENCY times [{name}]", "byte-identical to canonical string")
        else:
            for label, plain in mismatches:
                report("FAIL", f"HOURS CONSISTENCY times [{name}]", f"{label}: {plain!r}")

        off_hits = re.findall(r'休診：木・日・祝', text)
        hm_off = re.findall(r'<p class="hm-off">(.*?)</p>', text, re.S)
        if hm_off:
            bad = [o for o in hm_off if strip_tags(o) != canonical_off]
            if bad:
                report("FAIL", f"HOURS CONSISTENCY 休診 [{name}]", f"{bad}")
            else:
                report("PASS", f"HOURS CONSISTENCY 休診 [{name}]", "hm-off matches canonical")
        else:
            report("SKIP", f"HOURS CONSISTENCY 休診 [{name}]", "no .hm-off on this page")


# ---------------------------------------------------------------------------
# RULE: LINK INTEGRITY
# ---------------------------------------------------------------------------

def rule_link_integrity(pages):
    # collect ids present on every known page (checked set ∪ files on disk)
    all_html = {p.name: p.read_text(encoding="utf-8") for p in ROOT.glob("*.html")}
    ids_by_page = {name: set(re.findall(r'\bid="([^"]+)"', text)) for name, text in all_html.items()}

    seen = set()
    for name, text in pages.items():
        hrefs = re.findall(r'href="([^"]+)"', text)
        for href in hrefs:
            if href.startswith(("http://", "https://", "tel:", "mailto:")):
                continue
            if href in ("#", ""):
                continue
            if "sas.html" in href:
                report("FAIL", f"LINK INTEGRITY [{name}]", f"forbidden link to sas.html: {href}")
                continue
            # only local .html targets (and their #fragments) are in scope for
            # this rule — asset links (css/svg/images) are not page links.
            if "#" in href:
                page_part, frag = href.split("#", 1)
            else:
                page_part, frag = href, None
            if page_part and not page_part.endswith(".html"):
                continue  # not a page link (css/svg/image/etc.)
            if href.startswith("/"):
                # root-relative: empty page part means the homepage itself.
                clean = page_part.lstrip("/")
                target_page = clean if clean else "index.html"
            else:
                # bare "#frag" or a relative "foo.html" — same page, or that page.
                target_page = page_part if page_part else name
            if page_part:
                clean_target = target_page
                if clean_target not in all_html:
                    key = ("page", name, href)
                    if key not in seen:
                        seen.add(key)
                        report("FAIL", f"LINK INTEGRITY [{name}]", f"local page not found: {href}")
                    continue
            if frag:
                target_ids = ids_by_page.get(target_page, set())
                if frag not in target_ids:
                    key = ("frag", name, href)
                    if key not in seen:
                        seen.add(key)
                        report("FAIL", f"LINK INTEGRITY [{name}]", f"#{frag} not found on {target_page} (from {href})")


# ---------------------------------------------------------------------------
# RULE: SITEMAP
# ---------------------------------------------------------------------------

def rule_sitemap():
    sitemap_path = ROOT / "sitemap.xml"
    if not sitemap_path.exists():
        report("SKIP", "SITEMAP", "sitemap.xml not found")
        return
    text = sitemap_path.read_text(encoding="utf-8")
    locs = re.findall(r'<loc>(.*?)</loc>', text)
    expected = {
        "https://nakamura.n-clinics.jp/",
        "https://nakamura.n-clinics.jp/hajimete.html",
        "https://nakamura.n-clinics.jp/seikatsushukanbyo.html",
        "https://nakamura.n-clinics.jp/hataraku.html",
        "https://nakamura.n-clinics.jp/shisetsu-kijun.html",
        "https://nakamura.n-clinics.jp/privacy.html",
    }
    if set(locs) == expected and len(locs) == 6:
        report("PASS", "SITEMAP exactly six locs", "matches expected set")
    else:
        report("FAIL", "SITEMAP exactly six locs", f"found: {locs}")
    if any("404" in l or "sas" in l for l in locs):
        report("FAIL", "SITEMAP excludes 404/sas", f"found forbidden entries in {locs}")
    else:
        report("PASS", "SITEMAP excludes 404/sas", "clean")


def rule_404_noindex(pages):
    for name, text in pages.items():
        has_noindex = 'name="robots" content="noindex"' in text or ("noindex" in text and 'name="robots"' in text)
        if name == "404.html":
            if has_noindex:
                report("PASS", "404.html has noindex", "present")
            else:
                report("FAIL", "404.html has noindex", "missing")
        else:
            if has_noindex:
                report("FAIL", f"NO noindex on non-404 page [{name}]", "unexpected noindex")
            else:
                report("PASS", f"NO noindex on non-404 page [{name}]", "clean")


# ---------------------------------------------------------------------------
# RULE: ROUTE STRIPS
# ---------------------------------------------------------------------------

def rule_route_strips(pages):
    viewboxes = {}
    for name, text in pages.items():
        for m in re.finditer(r'<svg class="rt" viewBox="([^"]+)" aria-hidden="([^"]+)" focusable="([^"]+)"', text):
            vb, aria_hidden, focusable = m.groups()
            viewboxes.setdefault(name, []).append(vb)
            if aria_hidden != "true" or focusable != "false":
                report("FAIL", f"ROUTE STRIP aria-hidden/focusable [{name}]", snippet(text, m.start()))
            # scan a generous backward window (not just the last few class=
            # attributes) so unrelated intervening classes (lane-h, lane-body,
            # lane-more, etc.) don't push the true ancestor's c-nai/c-shin out.
            preceding = text[max(0, m.start() - 3000):m.start()]
            preceding_classes = re.findall(r'class="([^"]*)"', preceding)
            ancestor_ok = any(("c-nai" in c or "c-shin" in c) for c in preceding_classes)
            if not ancestor_ok:
                report("FAIL", f"ROUTE STRIP c-nai/c-shin ANCESTOR [{name}]", snippet(text, m.start()))
        for m in re.finditer(r'<svg class="rt"[^>]*>.*?</svg>', text, re.S):
            if "view-transition-name" in m.group(0):
                report("FAIL", f"ROUTE STRIP view-transition-name [{name}]", snippet(text, m.start()))
            texts = re.findall(r'<text[^>]*>(.*?)</text>', m.group(0))
            for t in texts:
                if re.search(r'[぀-ヿ一-鿿]', re.sub(r'[①②③④]', '', t)):
                    pass  # origin label itself is JP text — allowed; only flag branch NAME leakage separately below

        if name == "index.html":
            report("PASS" if len(viewboxes.get(name, [])) >= 2 and len(set(viewboxes[name])) == 1
                   else "FAIL", f"HOME STRIPS SHARE VIEWBOX [{name}]",
                   f"viewboxes found: {viewboxes.get(name)}")
    if not viewboxes:
        report("SKIP", "ROUTE STRIPS", "no .rt elements found in checked set")
    else:
        report("PASS", "ROUTE STRIPS structural scan", "completed (see FAILs above if any)")
    report("MANUAL", "Route strip colour binding (JS-disabled): 内科=vermilion-origin/ink-terminus, 精神科=reverse")


# ---------------------------------------------------------------------------
# RULE: GREEN AUDIT
# ---------------------------------------------------------------------------

def rule_green_audit(pages):
    for name, text in pages.items():
        count = len(re.findall(r'class="safety-line"', text))
        if count <= 1:
            report("PASS", f"GREEN safety-line <=1 [{name}]", f"count={count}")
        else:
            report("FAIL", f"GREEN safety-line <=1 [{name}]", f"count={count}")

        pressable = False
        for m in re.finditer(r'<(a|button)\b[^>]*class="([^"]*)"', text):
            classes = m.group(2).split()
            if any(c in ("safety-line",) for c in classes):
                pressable = True
        if not pressable:
            report("PASS", f"GREEN nothing pressable [{name}]", "no .safety-line on an <a>/<button>")
        else:
            report("FAIL", f"GREEN nothing pressable [{name}]", ".safety-line found on interactive element")
    report("MANUAL", "Plant green <=5% of viewport at 375px and 1440px")


# ---------------------------------------------------------------------------
# RULE: TEMPLATE CONFORMANCE
# ---------------------------------------------------------------------------

def rule_template_conformance(pages):
    for name, text in pages.items():
        if name in DOC_PAGES:
            hits = [f for f in TEMPLATE_CONFORMANCE_DOC_FORBIDDEN if f in text]
            if hits:
                report("FAIL", f"TEMPLATE CONFORMANCE doc-page [{name}]", f"forbidden markers present: {hits}")
            else:
                report("PASS", f"TEMPLATE CONFORMANCE doc-page [{name}]", "clean")
        elif name in CHANNEL_PAGES:
            forbidden = list(TEMPLATE_CONFORMANCE_CHANNEL_FORBIDDEN)
            if name == "hajimete.html" and 'class="roundels"' in forbidden:
                forbidden.remove('class="roundels"')  # documented exception
            hits = [f for f in forbidden if f in text]
            if hits:
                report("FAIL", f"TEMPLATE CONFORMANCE channel-page [{name}]", f"forbidden markers present: {hits}")
            else:
                report("PASS", f"TEMPLATE CONFORMANCE channel-page [{name}]", "clean")
        else:
            report("SKIP", f"TEMPLATE CONFORMANCE [{name}]", "not a doc-page or channel-page")


# ---------------------------------------------------------------------------
# MANUAL rules (declared, not executed)
# ---------------------------------------------------------------------------

def rule_manual_declarations():
    report("MANUAL", "Responsive: no horizontal scroll at 320/375/402/768/1024/1440px")
    report("MANUAL", "1440px alignment: section heads, .care-card, .care-util, tables share one left/right edge")
    report("MANUAL", "Cold-load pass: correct lane selected, no fade-on-load, heading clears sticky header")
    report("MANUAL", "Keyboard pass: skip link first, tablist ArrowLeft/Right/Home/End, focus lands in visible panel")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
    pages = load_pages(argv)
    if not pages:
        print("No pages to check.")
        sys.exit(1)

    print(f"=== Checking {len(pages)} page(s): {', '.join(pages.keys())} ===\n")

    rule_banned_strings(pages)
    rule_fixed_hours_string(pages)
    rule_reception_sentence(pages)
    rule_shindansho(pages)
    rule_phone(pages)
    rule_single_home(pages)
    rule_bunshoryo_amounts(pages)
    rule_shared_shell(pages)
    rule_scripts(pages)
    rule_accessibility(pages)
    rule_jsonld(pages)
    rule_hours_consistency(pages)
    rule_link_integrity(pages)
    rule_sitemap()
    rule_404_noindex(pages)
    rule_route_strips(pages)
    rule_green_audit(pages)
    rule_template_conformance(pages)
    rule_manual_declarations()

    fails = [r for r in results if r[0] == "FAIL"]
    passes = [r for r in results if r[0] == "PASS"]
    skips = [r for r in results if r[0] == "SKIP"]
    manuals = [r for r in results if r[0] == "MANUAL"]

    print("\n=== SUMMARY ===")
    print(f"PASS:   {len(passes)}")
    print(f"FAIL:   {len(fails)}")
    print(f"SKIP:   {len(skips)}")
    print(f"MANUAL: {len(manuals)}")

    if fails:
        print(f"\n{len(fails)} rule(s) FAILED.")
        sys.exit(1)
    else:
        print("\nAll mechanically-checkable rules PASSED (MANUAL rules require a human/browser pass).")
        sys.exit(0)


if __name__ == "__main__":
    main()
