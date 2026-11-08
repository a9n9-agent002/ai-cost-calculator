"""Tests for voice.py — arithmetic is asserted, not eyeballed.

Run: python3 tests/test_voice.py     (stdlib only, no network, no dataset rewrite)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
FAILS = []


def run(args):
    p = subprocess.run([PY, os.path.join(HERE, "voice.py")] + args, capture_output=True, text=True)
    if p.returncode != 0:
        FAILS.append(f"exit {p.returncode} for {args}: {p.stderr[-400:]}")
    return p.stdout


def check(name, cond, detail=""):
    if not cond:
        FAILS.append(f"{name} {detail}")
    print(f"{'PASS' if cond else 'FAIL'}  {name}{'' if cond else '  ' + detail}")


def main():
    data = json.load(open(os.path.join(HERE, "dataset.json")))
    el = data["vendors"]["elevenlabs"]

    # 1. the ladder is the vendor's own table: 6 tiers, 10,000 chars free, $0.08/1k flat
    ladder = el["ladder"]
    check("ladder has 6 tiers", len(ladder) == 6, str([r["name"] for r in ladder]))
    check("free tier is 10,000 chars", ladder[0]["chars"] == 10000, str(ladder[0]))
    check("starter is $6 / 75,000", (ladder[1]["usd"], ladder[1]["chars"]) == (6, 75000))
    check("business is $990 / 12,375,000", (ladder[5]["usd"], ladder[5]["chars"]) == (990, 12375000))
    check("vendor minutes basis is 1,000 chars/min", el["vendor_minutes_basis"] == 1000)

    # 2. a 4 x 45-minute podcast = 180 min = 180,000 chars -> Creator, not Starter, not Pro
    out = run(["--episodes", "4", "--minutes", "45"])
    check("180 min at 1000 c/min = 180,000 chars", "180,000 characters" in out, out[:200])
    check("cheapest covering plan is Creator $22", "**Creator** $22/month" in out)
    check("Starter is marked not enough", "75   not enough" in out)
    check("Pro marked as costing more", "1,238   covers it, costs more" in out)
    check("leftover allowance computed (95 min)", "95 minutes of allowance go unused" in out)

    # 3. slow delivery at 900 c/min needs more chars for the same minutes
    out900 = run(["--episodes", "4", "--minutes", "45", "--chars-per-minute", "900"])
    check("900 c/min: 162,000 chars", "162,000 characters" in out900, out900[:160])
    check("900 c/min: still Creator", "**Creator** $22/month" in out900)

    # 4. the engine ranking is arithmetic, and the vendor I earn from is not the cheapest
    outj = run(["--minutes", "600", "--json"])
    j = json.loads(outj)
    rates = {r["engine"]: r["usd_per_finished_minute"] for r in j["engines"]}
    check("v4 = $0.080/min at 1000 c/min", abs(rates["v4 (multilingual, default)"] - 0.08) < 1e-9, str(rates))
    check("turbo = $0.040/min", abs(rates["v4 Turbo / Flash"] - 0.04) < 1e-9)
    check("deepgram aura-2 = $0.030/min", abs(rates["Aura-2"] - 0.03) < 1e-9)
    check("deepgram aura-1 = $0.015/min", abs(rates["Aura-1"] - 0.015) < 1e-9)
    check("cheapest engine is Deepgram Aura-1", j["cheapest_engine"]["engine"] == "Aura-1", j["cheapest_engine"]["engine"])
    check("600 min -> Pro 99 (Creator's 275 min is short)", j["elevenlabs_plan"]["name"] == "Pro", str(j["elevenlabs_plan"]))
    # 600,000 chars at $0.08/1k is $48 of arithmetic, but the only covering plan is $99: 2.06x
    check("600 min -> granularity penalty 2.06x", abs(j["elevenlabs_plan"]["granularity_factor"] - 2.0625) < 1e-3,
          str(j["elevenlabs_plan"]["granularity_factor"]))
    # every plan block is exactly $1 per 12,500 chars -- the ladder has no volume discount
    ratios = {r["name"]: round(r["chars"] / r["usd_per_month"], 1) for r in j["elevenlabs_plans"] if r["usd_per_month"]}
    check("all paid plans are ~$1 per 12,500 chars (within 0.1%)",
          all(abs(r["chars"] / r["usd_per_month"] - 12500) / 12500 < 0.001
              for r in j["elevenlabs_plans"] if r["usd_per_month"]), str(ratios))

    # 5. the cliff hint fires when the workload is just over a block boundary
    out300 = run(["--minutes", "300"])
    check("300 min: cliff hint names Creator", "over Creator's 275,000-character allowance" in out300)
    check("300 min: cliff hint quantifies the saving", "$77 less a month" in out300)
    check("300 min: hint says 25 minutes of trims", "25.0 minutes" in out300)
    out1200 = run(["--minutes", "1200"])
    check("1,200 min: same plan as 300 min", "**Pro** $99/month" in out1200)

    # 6. beyond the top plan the tool refuses to invent an overage price
    out_big = run(["--hours", "400"])
    check("24,000 min: no plan covers it", "No single listed plan covers" in out_big)
    check("24,000 min: says ask sales, no extrapolation", "do not extrapolate" in out_big)

    # 6. disclosure: exactly one affiliate link, labelled right beside it
    occ = out.count(el["affiliate_link"])
    check("exactly one affiliate link in output", occ == 1, f"count={occ}")
    check("'affiliate link' appears beside it", "(affiliate link:" in out)
    check("no other vendor link in output", "firecrawl.link" not in out and "m.do.co" not in out)

    # 7. every number in the output traces to the dataset's read dates
    check("output carries the plan source URL", el["plan_source"] in out)
    check("output carries the plan read timestamp", el["plan_verified"] in out)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S)")
        for f in FAILS:
            print(" -", f)
        return 1
    print("ALL VOICE TESTS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
