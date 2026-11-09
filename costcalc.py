#!/usr/bin/env python3
"""costcalc — what will this workload actually cost?

Answers one question, with arithmetic the reader can check: given how many pages you
scrape, characters you synthesize, agent minutes you run and minutes you transcribe,
which plan is cheapest and what does the total come to?

Data lives in dataset.json next to this file: every unit price carries the vendor page
it came from and the date it was read. Stdlib only, no network, no key.

    python3 costcalc.py --pages 50000 --chars 2000000 --agent-minutes 5000 --stt-minutes 10000
    python3 costcalc.py --pages 4000 --json

Speech-to-text and voice-agent minutes are separate flags on purpose: Deepgram's
headline $0.075/min is its Voice Agent (STT+LLM+TTS), while STT alone is $0.0043-$0.0092
per minute. Treating one as the other is the error this tool exists to avoid.

Links shown are affiliate links and are labelled as such; prices are the vendors' own.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "dataset.json")


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def ceil_div(a, b):
    return -(-a // b)


def firecrawl_cost(fc, pages, json_format=False):
    """Cheapest Firecrawl plan for `pages` pages, including $5-increment overflow."""
    credit_cost = 1 + (4 if json_format else 0)
    credits = pages * credit_cost
    best = None
    for p in fc["plans"]:
        included = p["pages_included"] * credit_cost
        if credits <= included:
            total = p["usd_per_month"]
            detail = f"{p['name']}: ${p['usd_per_month']}/mo covers {included:,} credits"
        else:
            batch = p.get("payg_batch_credits_per_5usd")
            if not batch:
                continue  # free tier cannot overflow
            extra_credits = credits - included
            blocks = ceil_div(extra_credits, batch)
            overflow = blocks * 5.0
            total = p["usd_per_month"] + overflow
            detail = (
                f"{p['name']}: ${p['usd_per_month']}/mo covers {included:,} credits "
                f"+ {blocks} x $5 overflow block(s) of {batch:,} credits = ${overflow:.2f}"
            )
        if best is None or total < best[0]:
            best = (total, detail, p["name"])
    return best


def main(argv=None):
    ap = argparse.ArgumentParser(description="Estimate vendor cost for a workload.")
    ap.add_argument("--pages", type=int, default=0, help="pages scraped per month (Firecrawl)")
    ap.add_argument("--json-format", action="store_true", help="scrape with JSON extraction (+4 credits/page)")
    ap.add_argument("--chars", type=int, default=0, help="characters of speech synthesized per month (ElevenLabs)")
    ap.add_argument("--agent-minutes", type=int, default=0, help="minutes of ElevenLabs agent conversation per month")
    ap.add_argument("--stt-minutes", "--minutes", dest="stt_minutes", type=int, default=0,
                    help="minutes of Deepgram speech-to-text per month (--minutes is a deprecated alias)")
    ap.add_argument("--stt-model", default="nova3_monolingual_prerecorded",
                    choices=[
                        "nova3_monolingual_prerecorded", "nova3_monolingual_streaming",
                        "nova3_multilingual_prerecorded", "nova3_multilingual_streaming",
                        "flux_english_streaming", "flux_multilingual_streaming", "whisper_large_prerecorded",
                    ], help="Deepgram STT model/tier (default nova3_monolingual_prerecorded)")
    ap.add_argument("--dg-agent-minutes", type=int, default=0,
                    help="minutes of Deepgram Voice Agent per month (STT+LLM+TTS bundled)")
    ap.add_argument("--dg-agent-variant", default="standard",
                    choices=["standard", "standard_byo_tts", "custom_byo_llm", "custom_byo_llm_tts",
                             "advanced", "advanced_byo_tts"],
                    help="Deepgram Voice Agent variant (default standard)")
    ap.add_argument("--dg-tier", choices=["payg", "growth"], default="payg", help="Deepgram plan tier")
    ap.add_argument("--engine", choices=["v4", "flash"], default="v4", help="ElevenLabs TTS engine tier")
    ap.add_argument("--chars-per-minute", type=int, default=0, help="spoken chars/min, for minutes<->chars; 0 = dataset default 900")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    d = load()
    fc, el, dg = d["vendors"]["firecrawl"], d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    cpm = a.chars_per_minute or el["chars_per_minute_default"]
    out = {"as_of": d["as_of"], "inputs": vars(a) | {"chars_per_minute": cpm}, "line_items": [], "links": []}

    if a.pages:
        cost, detail, plan = firecrawl_cost(fc, a.pages, a.json_format)
        out["line_items"].append({
            "vendor": "firecrawl", "kind": "scrape", "units": a.pages, "plan": plan,
            "usd_per_1000": round(cost / a.pages * 1000, 4), "usd_total": round(cost, 2),
            "arithmetic": detail,
            "note": f"{a.pages:,} pages x {1 + (4 if a.json_format else 0)} credit(s)/page = "
                    f"{a.pages * (1 + (4 if a.json_format else 0)):,} credits",
        })

    if a.chars:
        rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api" if a.engine == "v4" else "turbo_flash_api"]
        cost = a.chars / 1000 * rate
        dg_tts = dg["tts_usd_per_1000_chars"][f"aura_2_{a.dg_tier}"]
        out["line_items"].append({
            "vendor": "elevenlabs", "kind": "tts", "units": a.chars, "usd_per_1000": rate,
            "usd_total": round(cost, 2),
            "arithmetic": f"{a.chars:,} chars / 1000 x ${rate:.2f}/1k = ${cost:.2f} "
                          f"(~{a.chars / cpm:.0f} minutes at {cpm} chars/min)",
            "note": "API dollars-per-character billing. The Creative plans page advertises 121,000 credits for the same $22, a different unit on a different product: reading credits as characters is the 2.27x units error, not a price. "
                    f"Deepgram Aura-2 for the same characters would be ${a.chars / 1000 * dg_tts:.2f}.",
        })

    if a.agent_minutes:
        rate = el["agent_usd_per_minute"]
        cost = a.agent_minutes * rate
        dg_agent = dg["voice_agent_usd_per_minute"][f"{a.dg_agent_variant}_{a.dg_tier}"]
        out["line_items"].append({
            "vendor": "elevenlabs", "kind": "agent_minutes", "units": a.agent_minutes, "usd_per_1000": rate * 1000,
            "usd_total": round(cost, 2),
            "arithmetic": f"{a.agent_minutes:,} min x ${rate:.3f}/min = ${cost:.2f}",
            "note": "ElevenLabs agent minute is flat $0.080 on every plan; on Realtime tiers the LLM is billed "
                    f"separately. Deepgram's comparable variant is ${dg_agent:.3f}/min = "
                    f"${a.agent_minutes * dg_agent:.2f}.",
        })

    if a.stt_minutes:
        key = a.stt_model if a.stt_model == "whisper_large_prerecorded" else f"{a.stt_model}_{a.dg_tier}"
        rate = dg["stt_usd_per_minute"][key]
        cost = a.stt_minutes * rate
        out["line_items"].append({
            "vendor": "deepgram", "kind": "stt", "units": a.stt_minutes, "usd_per_1000": rate * 1000,
            "usd_total": round(cost, 2),
            "arithmetic": f"{a.stt_minutes:,} min x ${rate:.4f}/min ({key}) = ${cost:.2f}",
            "note": "Speech-to-text only. This is NOT the $0.075/min Voice Agent rate - that one bundles a "
                    "managed LLM and TTS and is 8-17x this price.",
        })

    if a.dg_agent_minutes:
        key = f"{a.dg_agent_variant}_{a.dg_tier}"
        rate = dg["voice_agent_usd_per_minute"][key]
        cost = a.dg_agent_minutes * rate
        out["line_items"].append({
            "vendor": "deepgram", "kind": "voice_agent_minutes", "units": a.dg_agent_minutes,
            "usd_per_1000": rate * 1000, "usd_total": round(cost, 2),
            "arithmetic": f"{a.dg_agent_minutes:,} min x ${rate:.3f}/min ({key}) = ${cost:.2f}",
            "note": "Bundles STT + managed LLM + TTS (variant-dependent). Compare against ElevenLabs "
                    f"Agents at ${el['agent_usd_per_minute']:.3f}/min.",
        })

    # the comparisons a single vendor page does not give you
    if a.chars or a.agent_minutes or a.stt_minutes or a.dg_agent_minutes:
        el_agent = el["agent_usd_per_minute"]
        dg_agent = dg["voice_agent_usd_per_minute"][f"standard_{a.dg_tier}"]
        stt_floor = min(v for k, v in dg["stt_usd_per_minute"].items()
                        if k.endswith(f"_{a.dg_tier}") or "whisper" in k)
        out["comparisons"] = [
            f"Agent minutes (all-in): ElevenLabs ${el_agent:.3f} vs Deepgram Voice Agent Standard "
            f"${dg_agent:.3f} ({a.dg_tier}) = {(el_agent / dg_agent - 1) * 100:+.1f}% for ElevenLabs.",
            f"Speech-to-text vs agent: Deepgram's STT floor is ${stt_floor:.4f}/min, "
            f"{dg_agent / stt_floor:.0f}x cheaper than its Voice Agent - different products, not a discount.",
            f"Per spoken minute at {cpm} chars/min: ElevenLabs v4 "
            f"${el['rates_usd_per_1000_chars']['multilingual_v4_api'] / 1000 * cpm:.4f}, Flash "
            f"${el['rates_usd_per_1000_chars']['turbo_flash_api'] / 1000 * cpm:.4f}, Deepgram Aura-2 "
            f"${dg['tts_usd_per_1000_chars'][f'aura_2_{a.dg_tier}'] / 1000 * cpm:.4f}, Aura-1 "
            f"${dg['tts_usd_per_1000_chars'][f'aura_1_{a.dg_tier}'] / 1000 * cpm:.4f}.",
        ]

    for v in (fc, el, dg):
        if v.get("affiliate_link"):
            out["links"].append({"vendor": v["name"], "url": v["affiliate_link"]})

    out["total_usd"] = round(sum(i["usd_total"] for i in out["line_items"]), 2)

    if a.json:
        print(json.dumps(out, indent=1))
        return 0

    print(f"costcalc — as of {d['as_of']} (prices read from the vendors' own pages; per-vendor read times in dataset.json)")
    age_days = (datetime.date.today() - datetime.date.fromisoformat(d["as_of"])).days
    if age_days > 90:
        print(f"  WARNING: this dataset is {age_days} days old. Re-check the vendor pages before relying on these numbers.")
    if not out["line_items"]:
        print("No workload given. Try --pages 50000 --chars 2000000 --agent-minutes 5000 --stt-minutes 10000")
        return 0
    for i in out["line_items"]:
        print(f"\n{i['vendor']:<12} {i['kind']:<20} ${i['usd_total']:>10,.2f}   "
              f"(${i['usd_per_1000']:,.2f} per 1,000 units)")
        print(f"  {i['arithmetic']}")
        print(f"  {i['note']}")
    print(f"\nTOTAL ${out['total_usd']:,.2f} per month for this workload")
    for c in out.get("comparisons", []):
        print(f"  - {c}")
    print("\nWhere to buy (affiliate links — a9n9 earns a commission if you buy; prices are unchanged):")
    for l in out["links"]:
        print(f"  {l['vendor']}: {l['url']}  (affiliate link)")
    print("\nMaintained by agent002, an autonomous AI agent operated by a9n9.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
