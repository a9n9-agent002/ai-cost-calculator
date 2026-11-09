#!/usr/bin/env python3
"""Self-test for check_titles.py: it must FAIL on the exact defect it exists to catch.

A checker that always passes is the run-77 class (a check that silently asserts nothing). This copies
the rendered site to a scratch dir, puts back the old untyped title on index.html, and asserts that
check_titles exits non-zero — then puts back a duplicate phrase and asserts that fails too.
"""
import os, shutil, subprocess, sys, tempfile, re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "site")
CK = os.path.join(HERE, "check_titles.py")


def run(site):
    p = subprocess.run([sys.executable, CK, site], capture_output=True, text=True)
    return p.returncode, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""


failures = 0

# 1. the real site passes
rc, last = run(SRC)
print(f"clean site      -> rc={rc}  {last}")
if rc != 0:
    failures += 1

# 2. the pre-run-86 title must fail
tmp = tempfile.mkdtemp(prefix="titles-")
shutil.copytree(SRC, os.path.join(tmp, "site"))
p = os.path.join(tmp, "site", "index.html")
h = open(p, encoding="utf-8").read()
h = re.sub(r"<title>.*?</title>", "<title>API price index — Firecrawl, ElevenLabs, Deepgram (dated)</title>", h, count=1)
open(p, "w", encoding="utf-8").write(h)
rc, last = run(os.path.join(tmp, "site"))
print(f"old untyped     -> rc={rc}  {last}")
if rc == 0:
    failures += 1

# 3. two pages claiming the same typed phrase must fail
p2 = os.path.join(tmp, "site", "voices.html")
open(p, "w", encoding="utf-8").write(
    open(p2, encoding="utf-8").read().replace(
        "<title>TTS pricing comparison: what a text-to-speech plan buys in finished minutes</title>",
        "<title>Fake title</title>"))
p3 = os.path.join(tmp, "site", "vendors", "firecrawl.html")
h3 = open(p3, encoding="utf-8").read()
h3 = re.sub(r"<title>.*?</title>", "<title>firecrawl cost per page</title>", h3, count=1)
open(p3, "w", encoding="utf-8").write(h3)
p4 = os.path.join(tmp, "site", "vendors", "elevenlabs.html")
h4 = open(p4, encoding="utf-8").read()
h4 = re.sub(r"<title>.*?</title>", "<title>firecrawl cost per page again</title>", h4, count=1)
open(p4, "w", encoding="utf-8").write(h4)
rc, last = run(os.path.join(tmp, "site"))
print(f"duplicate claim -> rc={rc}  {last}")
if rc == 0:
    failures += 1

shutil.rmtree(tmp, ignore_errors=True)
print("SELFTEST PASS" if not failures else f"SELFTEST FAILED ({failures})")
sys.exit(1 if failures else 0)
