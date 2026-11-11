import os, re, subprocess, tempfile, shutil, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["SITE_BASE"] = "https://a9n9-agent002.github.io/dated-price-index"
import build_host as B

scratch = tempfile.mkdtemp(prefix="destnote-")
try:
    written, d = B.build(scratch)
    aff = re.compile(r'<a href="([^"]+)" rel="sponsored nofollow"')
    n_anchors = 0
    notes = {"Alexandria": 0, "elevenlabs.io": 0, "digitalocean.com": 0, "novita.ai": 0}
    for rel in written:
        if not rel.endswith(".html"):
            continue
        t = open(os.path.join(scratch, rel), encoding="utf-8").read()
        for m in aff.finditer(t):
            n_anchors += 1
            tail = t[m.end():m.end() + 600]
            for k in notes:
                if k in tail[:260]:
                    notes[k] += 1
    print("affiliate anchors rendered:", n_anchors, notes)
    # sample one anchor per vendor
    seen = set()
    for rel in written:
        if not rel.endswith(".html"):
            continue
        t = open(os.path.join(scratch, rel), encoding="utf-8").read()
        for m in aff.finditer(t):
            tail = t[m.end():m.end() + 600]
            for k in notes:
                if k in tail[:260] and k not in seen:
                    seen.add(k)
                    print("\n--", rel, "->", k)
                    print(re.sub(r"\s+", " ", tail[:300]))
    # selftest: remove one note from a rendered file and prove the checker flags it
    sample = None
    for rel in written:
        if rel.startswith("q/") and "digitalocean.com" in open(os.path.join(scratch, rel), encoding="utf-8").read():
            sample = rel
            break
    print("\nselftest sample:", sample)
    before = B._check_dest_note(scratch, [sample])
    p = os.path.join(scratch, sample)
    orig = open(p, encoding="utf-8").read()
    mutated = orig.replace("opens digitalocean.com", "opens the vendor")
    open(p, "w", encoding="utf-8").write(mutated)
    after = B._check_dest_note(scratch, [sample])
    open(p, "w", encoding="utf-8").write(orig)
    print("control failures:", len(before), "| mutated failures:", len(after))
    print("mutated message:", after[:1])
    assert len(before) == 0 and len(after) >= 1, "selftest did not catch the mutation"
    print("SELFTEST PASS: the check fails when the note is removed")
finally:
    shutil.rmtree(scratch, ignore_errors=True)
