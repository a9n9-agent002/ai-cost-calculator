#!/usr/bin/env python3
"""Every rendered page's <title> must carry a phrase Google Autocomplete actually completes.

Why this exists (run 86): three of twenty pages — including index.html, the sitemap's priority-1.0
entry page — carried titles such as "API price index — Firecrawl, ElevenLabs, Deepgram (dated)";
no completion list contains any of those words in that order, so the page is aimed at itself. Run 82
fixed ten of them by hand and nothing stopped the other three; this checker makes it a build invariant.
A title is a query, not a sentence.

    python3 check_titles.py          # exit 0 = every page owns a typed phrase
"""
import json, os, re, sys, glob, html as H

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "site")
PHRASES = json.load(open(os.path.join(HERE, "typed_phrases.json"), encoding="utf-8"))["phrases"]


def norm(s):
    """Compare a title to a typed phrase on words, not on separators.

    People type `gpt oss 120b pricing`; the product is called gpt-oss-120b, so the title carries a
    hyphen the query does not. Folding `-` and `_` to spaces is the difference between measuring the
    phrase and measuring hyphenation. Dots are kept: `glm 5.3` and `glm 5 3` are different products.
    """
    return re.sub(r"\s+", " ", s.lower().replace("-", " ").replace("_", " ")).strip()


PHRASES_N = {p: norm(p) for p in PHRASES}

fails, checks = [], 0
seen = {}
for path in sorted(glob.glob(os.path.join(SITE, "**", "*.html"), recursive=True)):
    checks += 1
    rel = os.path.relpath(path, SITE)
    h = open(path, encoding="utf-8").read()
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    if not m:
        fails.append(f"{rel}: no <title>")
        continue
    title = H.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    tl = title.lower()
    hit = next((p for p in sorted(PHRASES, key=len, reverse=True) if PHRASES_N[p] in norm(title)), None)
    if not hit:
        fails.append(f"{rel}: title carries no measured typed phrase: {title!r}")
    elif hit in seen:
        fails.append(f"{rel}: claims the same typed phrase as {seen[hit]} ({hit!r})")
    else:
        seen[hit] = rel
    # a title pasted from a template usually also repeats a stock opening; the SERPs measured in run 85
    # had 0/34 descriptions repeating their title, so the same cheap test applies here
    dm = re.search(r'<meta name="description" content="([^"]*)"', h)
    if dm and H.unescape(dm.group(1)).lower().startswith(tl[:20]):
        fails.append(f"{rel}: description repeats the title's opening")

print(f"{checks} pages checked, {len(fails)} failed")
for f in fails:
    print("  FAIL:", f)
print("ALL TITLES CARRY A TYPED PHRASE" if not fails else "TITLE CONTRACT BROKEN")
sys.exit(1 if fails else 0)
