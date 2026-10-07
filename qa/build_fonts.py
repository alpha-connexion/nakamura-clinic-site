"""Build the site's self-hosted web fonts (2026-10-07).

Why: loading three Japanese families from Google Fonts meant ~720 @font-face fragments and dozens of
font files, each arrival re-laying-out the page (Lighthouse mobile 57, 7 s to first text). One trimmed
woff2 per weight, holding only the characters this site uses, renders the same letters at a fraction
of the cost.

Licence: all three families are SIL OFL 1.1. A subset is a Modified Version, and IBM Plex reserves the
name "Plex", so every subset is renamed (NK Display / NK Body / NK Accent). Copyright and licence name
records are kept, and fonts/OFL-*.txt ships next to the files.

Sources (not in git — download into a folder and pass it as the first argument):
  https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Medium.ttf
  https://raw.githubusercontent.com/google/fonts/main/ofl/zenkakugothicnew/ZenKakuGothicNew-Bold.ttf
  https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsansjp/IBMPlexSansJP-Regular.ttf
  https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsansjp/IBMPlexSansJP-SemiBold.ttf
  https://raw.githubusercontent.com/google/fonts/main/ofl/ibmplexsansjp/IBMPlexSansJP-Bold.ttf
  https://raw.githubusercontent.com/google/fonts/main/ofl/shipporimincho/ShipporiMincho-Medium.ttf
  (plus each family's OFL.txt from the same folders)
File names are matched by the part after the last "_" or "/", so "zenkakugothicnew_ZenKakuGothicNew-Bold.ttf"
works too.

Run:   python qa/build_fonts.py <source-folder>
Then:  python qa/qa.py   (rule FONT GLYPH COVERAGE fails if a page uses a character a subset lacks)
Stamp only (no rebuild): python qa/build_fonts.py --stamp-only   (rewrites the ?v=<hash> in styles.css + preloads)

Re-run this script whenever page copy adds a character the QA rule reports as missing.
Needs: pip install fonttools brotli
"""
import glob
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "fonts")

# (output file, source file, new family, weight name, CSS weight, which character set)
FACES = [
    ("nk-display-500.woff2", "ZenKakuGothicNew-Medium.ttf", "NK Display", "Medium", 500, "display-medium"),
    ("nk-display-700.woff2", "ZenKakuGothicNew-Bold.ttf", "NK Display", "Bold", 700, "site"),
    ("nk-body-400.woff2", "IBMPlexSansJP-Regular.ttf", "NK Body", "Regular", 400, "site"),
    ("nk-body-600.woff2", "IBMPlexSansJP-SemiBold.ttf", "NK Body", "SemiBold", 600, "site"),
    ("nk-body-700.woff2", "IBMPlexSansJP-Bold.ttf", "NK Body", "Bold", 700, "site"),
    ("nk-accent-500.woff2", "ShipporiMincho-Medium.ttf", "NK Accent", "Medium", 500, "accent"),
]
# OpenType features kept per family = exactly what Google Fonts' own served slices carry (checked 2026-10-07 by
# reading GSUB/GPOS of the gstatic woff2 files). The originals carry more — notably 'palt' in Shippori Mincho and
# 'liga' everywhere — and keeping them changed line breaks wherever the CSS asks for font-feature-settings:'palt'
# (.pg-lead, .pull-line, .doc-panel-quote), so the site would no longer look as it did under Google Fonts.
FEATURES = {
    "NK Display": ["kern", "mark", "mkmk"],
    "NK Body": ["ccmp", "vert", "vrt2", "halt", "kern", "palt", "vhal", "vkrn", "vpal"],
    "NK Accent": ["ccmp", "vert", "vrt2", "mark", "mkmk", "vpal"],
}

LICENCES = [
    ("OFL-ZenKakuGothicNew.txt", "zenkakugothicnew"),
    ("OFL-IBMPlexSansJP.txt", "ibmplexsansjp"),
    ("OFL-ShipporiMincho.txt", "shipporimincho"),
]

# Faces used only by a few classes get a subset of just those elements' text (plus the safety set).
# Keep in sync with styles.css / pages.css:
#   accent         = every rule with var(--font-accent)                  (all at weight 500)
#   display-medium = every rule with var(--font-display) + font-weight:500 (.hero .tagline, .lane-promise)
CLASS_SETS = {
    "accent": ("pg-lead", "pull-line", "doc-panel-quote"),
    "display-medium": ("tagline", "lane-promise"),
}

PAGES = ["index.html", "hajimete.html", "seikatsushukanbyo.html", "hataraku.html",
         "shisetsu-kijun.html", "privacy.html", "404.html"]
EXTRA_TEXT_FILES = ["site.js", "styles.css", "pages.css"]


def safety_set():
    """Characters always included so ordinary edits rarely need a rebuild."""
    cps = set(range(0x20, 0x7F))                  # printable ASCII
    cps |= set(range(0x3000, 0x3040))             # CJK punctuation 、。「」『』〜 etc.
    cps |= set(range(0x3041, 0x3097)) | set(range(0x3099, 0x30A0))   # hiragana
    cps |= set(range(0x30A0, 0x3100))             # katakana
    cps |= set(range(0xFF01, 0xFF5F))             # full-width ASCII
    cps |= {0x00A0, 0x00D7, 0x2010, 0x2013, 0x2014, 0x2015, 0x2018, 0x2019, 0x201C, 0x201D,
            0x2025, 0x2026, 0x2192, 0x2190, 0x2191, 0x2193, 0x203B, 0x25CB, 0x25CF, 0x25CE,
            0x25A0, 0x25A1, 0x2605, 0x2606, 0xFFE5}
    return cps


def site_text():
    """Every character in the pages, site.js and the stylesheets, minus comments (never rendered)."""
    chars = set()
    for name in PAGES + EXTRA_TEXT_FILES:
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            text = fh.read()
        if name.endswith(".css"):
            text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        elif name.endswith(".html"):
            text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        chars |= set(text)
    return chars


class _ClassText(HTMLParser):
    """Collects the text inside any element carrying one of the given classes (nesting-aware)."""
    VOID = {"br", "img", "wbr", "hr", "input", "meta", "link", "source"}

    def __init__(self, classes):
        super().__init__(convert_charrefs=True)
        self.classes = set(classes)
        self.stack = []        # one bool per open element: does it (or an ancestor) match?
        self.chars = set()

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            return
        cls = set((dict(attrs).get("class") or "").split())
        inside = bool(self.stack and self.stack[-1]) or bool(cls & self.classes)
        self.stack.append(inside)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1]:
            self.chars |= set(data)


def class_text(classes):
    chars = set()
    for name in PAGES:
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            parser = _ClassText(classes)
            parser.feed(re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S))
            chars |= parser.chars
    return chars


def needed_text(which):
    return site_text() if which == "site" else class_text(CLASS_SETS[which])


def find_source(folder, wanted):
    for path in glob.glob(os.path.join(folder, "*")):
        base = os.path.basename(path)
        if base == wanted or base.endswith("_" + wanted):
            return path
    sys.exit(f"missing source font {wanted} in {folder}")


def rename(font, family, style):
    ps_family = family.replace(" ", "")
    new = {
        1: family,
        2: "Regular",
        3: f"{ps_family}-{style};nakamura-clinic-subset",
        4: f"{family} {style}",
        6: f"{ps_family}-{style}",
        16: family,
        17: style,
    }
    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 2, 3, 4, 6, 16, 17, 18, 21, 22, 25):
            name.removeNames(nameID=rec.nameID)
    for nid, value in new.items():
        name.setName(value, nid, 3, 1, 0x409)
        name.setName(value, nid, 1, 0, 0)
    if "CFF " in font:
        font["CFF "].cff.fontNames = [new[6]]


def font_versions():
    """Short content hash per font file. The ?v= query changes whenever a subset is rebuilt, so the files can be
    served with a one-year immutable cache (netlify.toml) and a rebuilt font is never served stale."""
    out = {}
    for out_name, *_ in FACES:
        with open(os.path.join(OUT, out_name), "rb") as fh:
            out[out_name] = hashlib.sha256(fh.read()).hexdigest()[:10]
    return out


def stamp_versions():
    """Write /fonts/<file>?v=<hash> into styles.css (@font-face) and every page's <link rel=preload>. Both must
    match exactly or the browser downloads the font twice (QA rule FONT URLS VERSIONED checks this)."""
    versions = font_versions()
    targets = ["styles.css"] + PAGES
    for name in targets:
        path = os.path.join(ROOT, name)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = text
        for out_name, ver in versions.items():
            new = re.sub(r"/fonts/" + re.escape(out_name) + r"(\?v=[0-9a-f]+)?(?=[\"'])",
                         f"/fonts/{out_name}?v={ver}", new)
        if new != text:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
    return versions


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--stamp-only":
        for k, v in stamp_versions().items():
            print(f"{k:24s} v={v}")
        return
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    from fontTools import subset   # only a real build needs fonttools; --stamp-only and qa.py do not

    src = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    base = safety_set()
    sets = {which: base | {ord(c) for c in needed_text(which) if ord(c) >= 0x20}
            for which in ["site", *CLASS_SETS]}
    gaps = {}
    for out_name, src_name, family, style, _weight, which in FACES:
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = FEATURES[family]   # match Google Fonts' served feature set (see FEATURES)
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.notdef_outline = True
        options.hinting = False
        options.desubroutinize = True
        font = subset.load_font(find_source(src, src_name), options)
        source_cmap = font.getBestCmap()
        gaps[out_name] = "".join(sorted(chr(cp) for cp in sets[which]
                                        if cp not in source_cmap and not chr(cp).isspace() and cp >= 0x80))
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=sets[which])
        subsetter.subset(font)
        rename(font, family, style)
        out_path = os.path.join(OUT, out_name)
        subset.save_font(font, out_path, options)
        print(f"{out_name:24s} {os.path.getsize(out_path)/1024:7.1f} KB  ({len(sets[which])} code points)")
    # Characters the ORIGINAL font never had: they fall back to the system face exactly as they did under
    # Google Fonts, so QA accepts them. Only non-ASCII is listed (ASCII gaps would mean a broken source).
    with open(os.path.join(ROOT, "qa", "font-source-gaps.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(gaps, fh, ensure_ascii=False, indent=2)
    for out_name, key in LICENCES:
        lic = find_source(src, f"{key}_OFL.txt") if glob.glob(os.path.join(src, f"{key}_OFL.txt")) else None
        if lic:
            with open(lic, encoding="utf-8") as fh, open(os.path.join(OUT, out_name), "w", encoding="utf-8", newline="\n") as out:
                out.write(fh.read())
    for k, v in stamp_versions().items():
        print(f"stamped {k} v={v}")


if __name__ == "__main__":
    main()
