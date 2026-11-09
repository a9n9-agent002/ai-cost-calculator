#!/usr/bin/env python3
"""Derive dataset_ext.json — the DigitalOcean, GPU-hour and Novita/cross-provider slices — from the
raw vendor reads kept in data/.

Why a derived file: the pages in build_host.py must compute every number they print instead of
typing it twice, and the repository must stay self-contained (a reader clones it and rebuilds the
tables without network access or the agent's workspace). data/*.json are the raw reads, each with
its own source URL and read time; this script normalises them and refuses to build if a table has
changed shape enough that a page's arithmetic would be about the wrong thing.

    python3 build_ext.py            # writes dataset_ext.json, prints counts and a sha256
    python3 build_ext.py --check    # rebuilds into memory and asserts it matches the file on disk
"""
import hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "dataset_ext.json")
MONTH_HOURS = 730

EXPECT = {
    "do-droplets.json": {"plans": 31, "families": 5},
    "gpu-hours.json": {"gpu_families": 12, "offers": 22},
    "novita-tokens.json": {"rows": 76},
    "cross-provider.json": {"rows": 34},
}


def load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def num(x):
    return x if isinstance(x, (int, float)) else None


def build():
    do = load("do-droplets.json")
    gpu = load("gpu-hours.json")
    nov = load("novita-tokens.json")
    cmp_ = load("cross-provider.json")
    aff = load("affiliates.json")
    # Every link must belong to the program it is filed under, and carry the words next to it. The
    # expected domains are checked rather than copied as literals, so this file never holds a bare
    # affiliate URL that a disclosure audit would (rightly) flag as unlabelled.
    EXPECT_HOST = {"digitalocean": ("m.do.co", "digitalocean.com"), "novita": ("novita.ai",)}
    for k, p in aff["programs"].items():
        hosts = EXPECT_HOST.get(k)
        if hosts is None:
            sys.exit(f"affiliates: {k} is not a program these pages cover")
        if not any(h in p["affiliate_link"] for h in hosts):
            sys.exit(f"affiliates: {k} link does not point at {hosts}")
        if "affiliate link" not in p["affiliate_disclosure"].lower():
            sys.exit(f"affiliates: {k} has no adjacent 'affiliate link' words")
        if k == "digitalocean" and "DigitalOcean" not in p["name"]:
            sys.exit("affiliates: digitalocean entry names another vendor")
        if k == "novita" and "Novita" not in p["name"]:
            sys.exit("affiliates: novita entry names another vendor")

    # ---- DigitalOcean Droplets
    plans = []
    for p in do["plans"]:
        plans.append({
            "family": p["family"], "memory_gib": p["memory_gib"], "vcpus": p["vcpus"],
            "disk_gib": p["disk_gib"], "transfer_gib": p["transfer_gib"],
            "usd_per_hour": p["usd_per_hour"], "usd_per_month": p["usd_per_month"],
        })
    if len(plans) != EXPECT["do-droplets.json"]["plans"]:
        sys.exit(f"do-droplets: {len(plans)} plans, expected 31 — page arithmetic would be wrong")
    if len(do["families"]) != 5:
        sys.exit("do-droplets: expected 5 families")
    for p in plans:
        if not (p["usd_per_hour"] > 0 and p["usd_per_month"] > 0):
            sys.exit(f"do-droplets: non-positive price in {p}")
        # the page prints 'hourly x 730' and the cap-crossing hour, so both must be derivable
        if p["usd_per_hour"] * MONTH_HOURS <= p["usd_per_month"] * 0.5:
            sys.exit(f"do-droplets: hourly/monthly disagree wildly for {p['memory_gib']} GiB")

    # ---- GPU hours
    offers = []
    for fam in gpu["gpus"]:
        for o in fam["offers"]:
            offers.append({
                "family": fam["family"], "vram_gb": fam.get("vram_gb"),
                "provider": o["provider"], "name": o["name"], "tier": o["tier"],
                "usd_per_gpu_hour": o["usd_per_gpu_hour"],
                "interruptible": bool(o.get("interruptible")),
                "commitment_months": o.get("commitment_months") or 0,
            })
    if len(offers) != EXPECT["gpu-hours.json"]["offers"]:
        sys.exit(f"gpu-hours: {len(offers)} offers, expected 22")
    if len(gpu["gpus"]) != EXPECT["gpu-hours.json"]["gpu_families"]:
        sys.exit("gpu-hours: family count changed")
    for o in offers:
        if not o["usd_per_gpu_hour"] > 0:
            sys.exit(f"gpu-hours: non-positive rate {o}")
        if o["tier"] not in ("on_demand", "spot", "reserved_12mo"):
            sys.exit(f"gpu-hours: unknown tier {o['tier']}")

    # ---- Novita token prices
    rows = []
    for r in nov["rows"]:
        rows.append({
            "model_id": r["model_id"], "name": r["name"], "context": r.get("context"),
            "input_usd_per_mtok": num(r.get("input_usd_per_mtok")),
            "output_usd_per_mtok": num(r.get("output_usd_per_mtok")),
            "cache_read_usd_per_mtok": num(r.get("cache_read_usd_per_mtok")),
            "price_note": r.get("price_note"),
        })
    if len(rows) != EXPECT["novita-tokens.json"]["rows"]:
        sys.exit(f"novita-tokens: {len(rows)} rows, expected 76")
    priced = [r for r in rows if r["input_usd_per_mtok"] is not None or r["output_usd_per_mtok"] is not None]
    paid = [r for r in priced if (r["input_usd_per_mtok"] or 0) > 0 or (r["output_usd_per_mtok"] or 0) > 0]
    free = [r for r in priced if r not in paid]
    if not paid:
        sys.exit("novita-tokens: no paid model found")
    # a page that says 'the cheapest model' must not be able to select a $0 listing
    for r in paid:
        if (r["input_usd_per_mtok"] or 0) <= 0 and (r["output_usd_per_mtok"] or 0) <= 0:
            sys.exit("novita-tokens: paid list contains a zero-price row")
    for r in paid:
        if r["input_usd_per_mtok"] is None or r["output_usd_per_mtok"] is None:
            sys.exit(f"novita-tokens: paid row with a missing side {r['name']}")

    # ---- cross-provider
    cross_rows = []
    for r in cmp_["rows"]:
        prov = {}
        for p in ("novita", "deepinfra", "openrouter"):
            pr = r.get(p) or {}
            if pr.get("input") is None or pr.get("output") is None:
                continue
            prov[p] = {"input": pr["input"], "output": pr["output"], "id": pr.get("id"),
                       "floor_input": pr.get("floor_input"), "floor_output": pr.get("floor_output"),
                       "cache_read": pr.get("cache_read")}
        if len(prov) != 3:
            sys.exit(f"cross-provider: {r['key']} missing a provider")
        cross_rows.append({"key": r["key"], "display": r["display"], "providers": prov})
    if len(cross_rows) != EXPECT["cross-provider.json"]["rows"]:
        sys.exit(f"cross-provider: {len(cross_rows)} rows, expected 34")

    out = {
        "as_of": max(do["fetched"][:10], nov["fetched"][:10], cmp_["generated"][:10]),
        "month_hours": MONTH_HOURS,
        "sources": {
            "droplets": {"url": do["source"], "read": do["fetched"]},
            "gpus": {"urls": {k: v.get("source") for k, v in gpu["providers"].items()},
                     "read": gpu["built_at"]},
            "novita_tokens": {"url": nov["source"], "read": nov["fetched"]},
            "cross_provider": {"urls": cmp_["sources"], "generated": cmp_["generated"]},
        },
        "droplets": {"families": do["families"], "plans": plans},
        "gpus": {"families": [{"family": f["family"], "vram_gb": f.get("vram_gb"),
                               "offers": [o for o in offers if o["family"] == f["family"]]}
                              for f in gpu["gpus"]],
                 "offers": offers},
        "novita_tokens": {"rows": rows, "priced": len(priced), "paid": len(paid), "free": len(free),
                          "no_price": len(rows) - len(priced),
                          "with_cache_read": sum(1 for r in rows if r["cache_read_usd_per_mtok"] is not None)},
        "cross_provider": {"rows": cross_rows,
                           "counts": cmp_["counts"],
                           "cheapest_output_headline": cmp_["cheapest_output_headline"],
                           "cheapest_output_floor": cmp_["cheapest_output_floor"]},
        "affiliates": aff["programs"],
    }
    return out


def dumps(d):
    return json.dumps(d, indent=1, sort_keys=False) + "\n"


def main():
    d = build()
    text = dumps(d)
    sha = hashlib.sha256(text.encode()).hexdigest()
    if "--check" in sys.argv:
        if not os.path.exists(OUT):
            sys.exit("dataset_ext.json missing — run build_ext.py first")
        on_disk = open(OUT, encoding="utf-8").read()
        if on_disk != text:
            sys.exit("dataset_ext.json is out of date with data/ — rebuild it (diff shown by sha)")
        print(f"dataset_ext.json is current: sha256 {sha[:16]}…")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote dataset_ext.json  {len(text):,} bytes  sha256 {sha[:16]}…")
    print(f"  droplets      {len(d['droplets']['plans'])} plans, {len(d['droplets']['families'])} families")
    print(f"  gpus          {len(d['gpus']['offers'])} offers, {len(d['gpus']['families'])} families")
    print(f"  novita        {len(d['novita_tokens']['rows'])} models "
          f"({d['novita_tokens']['paid']} paid, {d['novita_tokens']['free']} free, "
          f"{d['novita_tokens']['no_price']} with no per-token price)")
    print(f"  cross         {len(d['cross_provider']['rows'])} models at 3 providers")


if __name__ == "__main__":
    main()
