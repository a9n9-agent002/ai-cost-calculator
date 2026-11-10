#!/usr/bin/env python3
"""Independent check of the four DigitalOcean / GPU / Novita pages.

This does NOT read dataset_ext.json: it recomputes every headline figure from the raw vendor reads in
data/ and then looks for that exact figure in the rendered HTML. A page that drifts from the raw data
fails here even if build_host.py still "passes" its own invariants.

    python3 check_ext.py
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
Q = os.path.join(HERE, "site", "q")
DATA = os.path.join(HERE, "data")


def j(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def page(slug):
    with open(os.path.join(Q, slug + ".html"), encoding="utf-8") as f:
        return f.read()


def money2(x):
    return f"{x:,.2f}"


fails, checks = [], 0


def want(cond, msg):
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


do = j("do-droplets.json")
gpu = j("gpu-hours.json")
nov = j("novita-tokens.json")
cmp_ = j("cross-provider.json")
aff = j("affiliates.json")["programs"]

# ---------------------------------------------------------------- DigitalOcean
six = next(p for p in do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
small = next(p for p in do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 0.5)
t = page("digitalocean-droplet-pricing")
want(len(do["plans"]) == 31, "raw droplet table is not 31 plans")
want(f"${money2(six['usd_per_hour'])}" in t, "page missing the $6 plan's hourly rate")
want(f"${money2(six['usd_per_hour'] * 730)}" in t, "page missing 730h total $6.52")
want(f"{six['usd_per_month'] / six['usd_per_hour']:.1f} hours" in t, "page missing the 671.9-hour cap")
want(f"${money2(six['usd_per_month'] * 1.30)}" in t, "page missing daily-backup total $7.80")
want(f"${money2(small['usd_per_month'] * 1.30)}" in t, "page missing the $4 plan's backup total $5.20")
want(t.count("<tr>") == 31 + 1 + 4 + 1, f"droplet table rows {t.count('<tr>')} != 31 plans + 4 picks + 2 headers")
want(not re.search(r"\$0\.00<", t.split("<table>")[1].split("</table>")[0]),
     "a $0.00 price cell in the droplet table")
# run 86: the RAM-rate paragraph used to call the 0.5 GiB plan "the cheapest memory on the page" and then
# call the smallest Droplet the most expensive RAM — a self-contradiction rendered from two different
# computations. Assert the sentence now states the three rates it is comparing, and that the wrong claim is gone.
_small_p = next(p for p in do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 0.5)
_best_rate = min((p["usd_per_month"] / p["memory_gib"], p["memory_gib"], p["usd_per_month"]) for p in do["plans"])
want(f"${money2(_small_p['usd_per_month'] / _small_p['memory_gib'])} per GiB" in t,
     "droplet page missing the 0.5 GiB plan's $/GiB")
want(f"${money2(six['usd_per_month'] / six['memory_gib'])} per GiB" in t,
     "droplet page missing the 1 GiB plan's $/GiB comparison")
want(f"${money2(_best_rate[0])} per GiB" in t, "droplet page missing the best $/GiB on the page")
want("cheapest memory on the page" not in t, "droplet page still claims the 0.5 GiB plan is the cheapest memory")
_ratio = (_small_p["usd_per_month"] / _small_p["memory_gib"]) / _best_rate[0]
want(f"{_ratio:.2f}× the rate of the smallest plan" in t, "droplet page missing the small-vs-best RAM ratio")

# ---------------------------------------------------------------- GPU
offers = [o for f in gpu["gpus"] for o in f["offers"]]
t = page("h100-price-per-hour")
want(len(offers) == 22, f"raw gpu table has {len(offers)} offers, expected 22")
want(t.count("<tr>") == 22 + 4 + 1 + 1, f"gpu tables rows {t.count('<tr>')} unexpected")
l40s = {o["provider"]: o for o in next(f for f in gpu["gpus"] if f["family"] == "L40S")["offers"]}
r4090 = next(o for o in next(f for f in gpu["gpus"] if f["family"] == "RTX 4090")["offers"]
             if o["tier"] == "on_demand")
pct = (1 - l40s["novita"]["usd_per_gpu_hour"] / r4090["usd_per_gpu_hour"]) * 100
want(f"{pct:.1f}% cheaper" in t, f"page missing the L40S-vs-4090 {pct:.1f}% saving")
h100 = {o["tier"] + ":" + o["provider"]: o for o in next(f for f in gpu["gpus"] if f["family"] == "H100")["offers"]}
want(f"730 × ${money2(h100['reserved_12mo:digitalocean']['usd_per_gpu_hour'])} = "
     f"<strong>${money2(h100['reserved_12mo:digitalocean']['usd_per_gpu_hour'] * 730)}</strong>" in t,
     "page missing the reserved-commitment total")
want(f"{l40s['digitalocean']['usd_per_gpu_hour'] / l40s['novita']['usd_per_gpu_hour']:.2f}×" in t,
     "page missing the L40S two-cloud spread")

# ---------------------------------------------------------------- Novita
paid = [r for r in nov["rows"] if (r["input_usd_per_mtok"] or 0) > 0 or (r["output_usd_per_mtok"] or 0) > 0]
t = page("novita-ai-api-pricing")
want(len(paid) == 73, f"raw novita table has {len(paid)} paid rows, expected 73")
want(f"{len(nov['rows'])} models" in t, "page missing the 76-model count")
want(t.count("<tr>") == 73 + 1, f"novita table rows {t.count('<tr>')} != 73 + header")
want("48 of the 76" in t, "page missing the cache-read coverage count")
body_cells = re.sub(r"<ul>.*?</ul>", "", t, flags=re.S)   # the free/unpriced list is allowed to name them
for r in paid:
    pass
for r in nov["rows"]:
    if r not in paid:
        want(f"<td>{r['name']}</td>" not in body_cells,
             f"unpriced/free model {r['name']} appears as a table row")

# ---------------------------------------------------------------- cross-provider
MIX = (40, 10)
PROVS = ("novita", "deepinfra", "openrouter")


def bill(r, p):
    v = r[p]          # data/cross-provider.json is the raw shape: one key per provider
    return MIX[0] * v["input"] + MIX[1] * v["output"]


best = max(cmp_["rows"], key=lambda r: max(bill(r, p) for p in PROVS)
           / min(bill(r, p) for p in PROVS))
t = page("llm-api-pricing-comparison")
want(t.count("<tr>") == len(cmp_["rows"]) + 1, f"comparison rows {t.count('<tr>')} != 34 + header")
for p in ("novita", "deepinfra", "openrouter"):
    want(f"${money2(bill(best, p))}" in t, f"comparison page missing the {p} bill for {best['key']}")
want("7.58×" in t, "comparison page missing the 7.58x spread")
want(f"<strong>Novita {cmp_['cheapest_output_headline']['novita']}</strong>" in t,
     "comparison page missing the headline win count")

# ---------------------------------------------------------------- per-model pages (run 87)
# Recomputed from data/cross-provider.json (the raw catalogue read), not from dataset_ext.json — so a
# drift in the derived file fails here even if build_host.py's own invariants still pass.
MODELS = [
    ("deepseek-v4-pro-pricing", "deepseek-v4-pro"),
    ("deepseek-v4-flash-pricing", "deepseek-v4-flash-0731"),
    ("glm-5-3-pricing", "glm-5.3"),
    ("deepseek-v4-1-flash-1017-pricing", "deepseek-v4.1-flash-1017"),
    ("ling-3-0-flash-pricing", "ling-3.0-flash"),
    ("gpt-oss-120b-pricing", "gpt-oss-120b"),
    ("qwen3-7-max-pricing", "qwen3.7-max"),
    ("qwen3-5-35b-a3b-pricing", "qwen3.5-35b-a3b"),
    ("glm-5-2-pricing", "glm-5.2"),
    ("gemma-4-26b-a4b-pricing", "gemma-4-26b-a4b"),
]
raw = {r["key"]: r for r in cmp_["rows"]}
for slug, key in MODELS:
    t = page(slug)
    row = raw[key]
    bills = {p: 40 * row[p]["input"] + 10 * row[p]["output"]
             for p in ("novita", "deepinfra", "openrouter") if row.get(p)}
    low, high = min(bills.values()), max(bills.values())
    for p, b in bills.items():
        want(f"${money2(b)}" in t, f"{slug}: missing the {p} bill ${money2(b)} recomputed from the raw read")
    want(f"{high / low:.2f}&times;" in t, f"{slug}: missing the recomputed {high / low:.2f}x spread")
    # Run 126: the page now also prices 4M in + 1M out and 400M in + 100M out, and states the spread is
    # unchanged because billing is linear. Recompute all six bills from the raw read.
    for vi, vo in ((4, 1), (400, 100)):
        vb = {p: vi * row[p]["input"] + vo * row[p]["output"] for p in bills}
        for p, b in vb.items():
            want(f"${money2(b)}" in t, f"{slug}: missing the {vi}M/{vo}M {p} bill ${money2(b)}")
    want("affiliate link" in t.lower() or "affiliate link" in t, f"{slug}: no disclosure wording")
    want("autonomous AI agent operated by a9n9" in t, f"{slug}: missing AI authorship line")
    want("REPLACE-WITH" not in t, f"{slug}: placeholder domain in body")
    hot = [p for p, b in bills.items() if abs(b - low) < 0.005]
    approved_now = {p["affiliate_link"] for p in aff.values()}
    has_link = any(href.replace("&amp;", "&") in approved_now
                   for href in re.findall(r'<a href="(https?://[^\"]+)"', t))
    want(has_link == ("novita" in hot),
         f"{slug}: affiliate link present={has_link} but Novita cheapest={('novita' in hot)} — "
         f"a link must follow merit, not habit")

# ---------------------------------------------------------------- links and disclosures
APPROVED = {p["affiliate_link"] for p in aff.values()}
# Run 110: a page may cite the vendor's OWN documentation that a claim is read from (the ElevenLabs
# terms/help-centre precedent on the free-tier page). These are documentation URLs on the vendor's
# site, not referral links to a product, and nothing on them is purchasable — allowed explicitly so
# the "only the approved set" rule still holds for every commercial link.
DOC_ALLOW = {
    "https://novita.ai/docs/guides/payment-methods",
    "https://novita.ai/docs/guides/llm-billing",
    # run 111: the Sandbox page that publishes the $100 promotional credit — the citation for the correction
    "https://docs.novita.ai/guides/sandbox-pricing",
}
for slug in ("digitalocean-droplet-pricing", "h100-price-per-hour", "novita-ai-api-pricing",
             "llm-api-pricing-comparison"):
    t = page(slug)
    for href in re.findall(r'<a href="(https?://[^"]+)"', t):
        href = href.replace("&amp;", "&")
        want(href in APPROVED or href in DOC_ALLOW, f"{slug}: link outside the approved set: {href}")
    for doc in DOC_ALLOW & set(re.findall(r'<a href="(https?://[^"]+)"', t)):
        want("affiliate" not in doc, "a documentation URL must never be an affiliate link")
    for m in re.finditer(r'<a href="(https?://[^"]+)"[^>]*>(.*?)</a>', t, flags=re.S):
        if m.group(1).replace("&amp;", "&") in APPROVED:
            want("affiliate link" in m.group(2).lower(), f"{slug}: affiliate anchor without the words")
    want("autonomous AI agent operated by a9n9" in t, f"{slug}: missing AI disclosure")
    want("earns a commission" in t, f"{slug}: missing commission sentence")
    want("REPLACE-WITH" not in t, f"{slug}: placeholder domain in page body")

print(f"{checks} assertions, {len(fails)} failed")
for f in fails:
    print("  FAIL:", f)
sys.exit(1 if fails else 0)
