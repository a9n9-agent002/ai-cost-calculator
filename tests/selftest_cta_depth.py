#!/usr/bin/env python3
"""r173_selftest_cta.py - prove the run-173 depth check FAILS on the pre-fix shape.

A checker nobody has seen fail is a checker that may be inert (runs 115/163). Two controls:
  1. old shape  -> affiliate link as the last paragraph  -> at least one failure
  2. new shape  -> link under the lede                   -> zero failures
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_host

OLD = ('<h1>Title</h1><p class="lede">Lede.</p>' + '<p>filler word here. </p>' * 60 +
       '<p><a href="https://firecrawl.link/agent001" rel="sponsored nofollow">Firecrawl pricing '
       '&mdash; affiliate link</a></p>')
NEW = ('<h1>Title</h1><p class="lede">Lede.</p>'
       '<p class="cta"><a href="https://firecrawl.link/agent001" rel="sponsored nofollow">Firecrawl '
       'pricing &mdash; affiliate link</a></p>' + '<p>filler word here. </p>' * 60)

ok = True
with tempfile.TemporaryDirectory() as d:
    for name, body, want_fail in (("old", OLD, True), ("new", NEW, False)):
        os.makedirs(os.path.join(d, "q"), exist_ok=True)
        p = os.path.join(d, "q", "case-%s.html" % name)
        open(p, "w", encoding="utf-8").write(body)
        fails = build_host._check_cta_depth(d, ["q/case-%s.html" % name])
        got = bool(fails)
        print("%-4s want_fail=%-5s got_fail=%-5s %s" % (name, want_fail, got, fails[:1]))
        if got != want_fail:
            ok = False
    # and the transform itself must move a trailing panel up
    moved = build_host.cta_first(OLD)
    pos = moved.find("sponsored")
    if not (0 < pos < moved.find("filler")):
        print("transform did not move the panel: %r" % moved[:160])
        ok = False
    else:
        print("cta_first moved the panel above the filler: ok")
print("\nSELFTEST PASS" if ok else "\nSELFTEST FAIL")
sys.exit(0 if ok else 1)
