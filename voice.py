#!/usr/bin/env python3
"""voice.py — how many minutes of finished audio does a plan buy, and what does a minute cost?

Written for the person who makes audio (podcast, audiobook, course, YouTube voice-over) rather than
for the person wiring an API into an agent. Their question is in minutes, not characters, and every
vendor answers it in characters.

    python3 voice.py --episodes 4 --minutes 45          # a weekly 45-minute podcast
    python3 voice.py --minutes 600                      # 10 hours a month
    python3 voice.py --hours 4.5 --chars-per-minute 900 # slower delivery
    python3 voice.py --minutes 600 --json

All prices come from dataset.json, which carries the page each number was read from and the date.
Nothing here is a guess: run `git log -1 dataset.json` for the dataset's own history.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DISCLOSURE = "affiliate link: a9n9 earns a commission if you buy through it"


def load():
    with open(os.path.join(HERE, "dataset.json")) as f:
        return json.load(f)


def engines(el, dg):
    """Cost of one finished minute of synthesized speech, per engine, at the vendor's own unit rates."""
    return [
        # (vendor, engine, usd_per_1000_chars, note)
        ("ElevenLabs", "v4 (multilingual, default)", el["rates_usd_per_1000_chars"]["multilingual_v4_api"],
         "the default voice; highest quality tier"),
        ("ElevenLabs", "v4 Turbo / Flash", el["rates_usd_per_1000_chars"]["turbo_flash_api"],
         "lower latency, cheaper, same API"),
        ("Deepgram", "Aura-2", dg["tts_usd_per_1000_chars"]["aura_2_payg"], "pay-as-you-go"),
        ("Deepgram", "Aura-1", dg["tts_usd_per_1000_chars"]["aura_1_payg"], "pay-as-you-go, previous generation"),
        ("Deepgram", "Flux TTS", dg["tts_usd_per_1000_chars"]["flux_tts_payg"], "pay-as-you-go"),
    ]


def plan_fit(ladder, chars_needed, cpm):
    """Cheapest plan whose monthly allowance covers the need. Returns (plan, rows)."""
    rows = []
    covering = None
    for p in ladder:
        minutes = p["chars"] / cpm
        covers = p["chars"] >= chars_needed
        leftover = (p["chars"] - chars_needed) / cpm
        rows.append({
            "name": p["name"], "usd_per_month": p["usd"], "chars": p["chars"],
            "minutes": round(minutes, 1),
            "covers": covers,
            "usd_per_finished_minute": (p["usd"] / chars_needed * 1.0 * cpm / cpm) if chars_needed else None,
        })
        if covers and covering is None:
            covering = p
    # effective price per finished minute at THIS workload = plan price / minutes used
    for r in rows:
        used = min(chars_needed, r["chars"]) / cpm
        r["usd_per_finished_minute"] = round(r["usd_per_month"] / used, 4) if used else None
        r["leftover_minutes"] = round((r["chars"] - chars_needed) / cpm, 1) if r["chars"] >= chars_needed else None
    return covering, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Minutes-per-month and cost-per-finished-minute for hosted text-to-speech.")
    ap.add_argument("--episodes", type=float, default=1.0, help="episodes per month (default 1)")
    ap.add_argument("--minutes", type=float, default=None, help="finished minutes per episode (or per month with no --episodes)")
    ap.add_argument("--hours", type=float, default=None, help="finished hours per month (alternative to --minutes)")
    ap.add_argument("--chars-per-minute", type=float, default=None,
                    help="spoken characters per minute; default is the vendor's own 1,000 (see --help notes)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    d = load()
    el, dg = d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    cpm = a.chars_per_minute or el["vendor_minutes_basis"]
    if a.hours is not None:
        minutes_total = a.hours * 60
    elif a.minutes is not None:
        minutes_total = a.minutes * a.episodes
    else:
        ap.error("give --minutes (per episode) or --hours (per month)")
    chars_needed = minutes_total * cpm

    covering, rows = plan_fit(el["ladder"], chars_needed, cpm)
    eng = engines(el, dg)
    eng_rows = [{"vendor": v, "engine": name, "usd_per_1000_chars": rate,
                 "usd_per_finished_minute": round(rate / 1000 * cpm, 5), "note": note}
                for v, name, rate, note in eng]
    eng_sorted = sorted(eng_rows, key=lambda r: r["usd_per_finished_minute"])

    out = {
        "as_of": d["as_of"],
        "inputs": {"minutes_total": round(minutes_total, 2), "chars_per_minute": cpm,
                   "chars_needed": int(round(chars_needed))},
        "elevenlabs_plan": None if not covering else {"name": covering["name"], "usd_per_month": covering["usd"],
                                                     "chars": covering["chars"],
                                                     "granularity_factor": round(
                                                         covering["usd"] / (chars_needed / 1000 * el[
                                                             "rates_usd_per_1000_chars"]["multilingual_v4_api"]), 4)},
        "elevenlabs_plans": rows,
        "engines": eng_rows,
        "cheapest_engine": eng_sorted[0],
        "notes": [el["vendor_minutes_basis_note"] if "vendor_minutes_basis_note" in el else el["ladder_note"],
                  el["promo_note"]],
        "affiliate_disclosure": el["affiliate_disclosure"],
        "affiliate_link": el["affiliate_link"],
        "source": el["plan_source"],
        "plan_verified": el["plan_verified"],
    }

    if a.json:
        print(json.dumps(out, indent=1))
        return 0

    print(f"Voice workload: {minutes_total:,.0f} finished minutes per month "
          f"({chars_needed:,.0f} characters at {cpm:,.0f} chars/min)")
    print(f"Dataset as of {d['as_of']}; plan table read from {el['plan_source']} at {el['plan_verified']}\n")

    print("ElevenLabs plans (v4 voices, monthly list price, characters included):")
    print(f"  {'plan':<22}{'$/mo':>7}{'chars':>13}{'minutes':>10}   fit")
    cover_name = covering["name"] if covering else None
    for r in rows:
        if not r["covers"]:
            fit = "not enough"
        elif r["name"] == cover_name:
            fit = "<- cheapest that covers it"
        else:
            fit = "covers it, costs more"
        print(f"  {r['name']:<22}{r['usd_per_month']:>7}{r['chars']:>13,}{r['minutes']:>10,.0f}   {fit}")

    if covering:
        used = minutes_total
        print(f"\n  Cheapest plan that covers {minutes_total:,.0f} min: **{covering['name']}** "
              f"${covering['usd']}/month")
        print(f"  That is ${covering['usd'] / used:.4f} per finished minute *if you use only your "
              f"{used:,.0f} of the {covering['chars'] / cpm:,.0f} minutes included* — "
              f"{(covering['chars'] - chars_needed) / cpm:,.0f} minutes of allowance go unused.")
        rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]
        linear = chars_needed / 1000 * rate
        print(f"  The per-character rate alone would price {chars_needed:,.0f} characters at ${linear:,.2f}. "
              f"The plan costs ${covering['usd']:.2f} — {covering['usd'] / linear:.2f}x that — because plans "
              f"come in fixed blocks priced at ~$1 per 12,500 characters ($0.08/1k, rounded up), so the "
              f"top-up you cannot buy is the extra you pay for.")
        # The cliff: a workload just over one block's allowance buys the whole next block.
        idx = [p["name"] for p in el["ladder"]].index(covering["name"])
        if idx > 0:
            below = el["ladder"][idx - 1]
            over = chars_needed - below["chars"]
            if over > 0 and chars_needed <= below["chars"] * 1.30:
                cut_min = over / cpm
                print(f"  WORTH A SECOND LOOK: you are only {over:,.0f} characters ({cut_min:,.1f} minutes, "
                      f"{over / chars_needed * 100:.1f}% of the workload) over {below['name']}'s "
                      f"{below['chars']:,}-character allowance. Trimming that much script keeps you on "
                      f"{below['name']} at ${below['usd']} instead of ${covering['usd']} — "
                      f"${covering['usd'] - below['usd']} less a month for {cut_min:,.1f} fewer minutes.")
    else:
        print(f"\n  No single listed plan covers {minutes_total:,.0f} minutes a month. The top plan "
              f"({rows[-1]['name']}) includes {rows[-1]['chars']:,} characters "
              f"(~{rows[-1]['minutes']:,.0f} min). The page does not document buying a second allowance "
              f"or what overage costs, so ask sales — do not extrapolate a price from this table.")

    print("\nWhat one finished minute costs, by engine (per-character rate x chars/min):")
    for r in eng_sorted:
        print(f"  ${r['usd_per_finished_minute']:.4f}/min  {r['vendor']:<11}{r['engine']:<28}(${r['usd_per_1000_chars']:.3f}/1k chars, {r['note']})")
    cheapest = eng_sorted[0]
    print(f"\n  Cheapest for pure narration: {cheapest['vendor']} {cheapest['engine']} at "
          f"${cheapest['usd_per_finished_minute']:.4f}/min — {eng_sorted[-1]['usd_per_finished_minute']/cheapest['usd_per_finished_minute']:.1f}x "
          f"cheaper than the most expensive option here.")
    print(f"\n  For {minutes_total:,.0f} minutes, pay-as-you-go arithmetic before any plan allowance:")
    for r in eng_sorted:
        print(f"    ${r['usd_per_finished_minute'] * minutes_total:>9,.2f}   {r['vendor']} {r['engine']}")
    print("  ElevenLabs' API is billed through the monthly plans above, so its practical bill is the plan "
          "fit, not the per-minute figure — the per-minute figure is what tells you how much of that plan "
          "price you are actually using.")

    print("\nTwo traps in this table:")
    print(f"  - The 'minutes' column is characters / {cpm:,.0f}. ElevenLabs' own page divides by 1,000 "
          f"('75,000 ~75 min'); a measured speech rate is nearer 900 chars/min, so slow, technical or "
          f"numbers-heavy copy needs ~11% more characters than the vendor's column implies.")
    print("  - First-month prices on the same page ($1 Starter, $11 Creator on 2026-11-08) are promotions. "
          "The monthly bill after month one is the list price above.")

    print(f"\nElevenLabs plans: {el['affiliate_link']} ({DISCLOSURE})")
    print("Prices are the vendor's own and are not affected by the link.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
