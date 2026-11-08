#!/usr/bin/env python3
"""check_prices.py — the scheduled price check the README promises.

Fetches each vendor's pricing page and diffs the numbers against dataset.json.

Deepgram publishes its whole price list as JSON-LD on the page, so that comparison is
exact and machine-made: every offer is mapped to a dataset key and any difference is
printed as a drift row. Firecrawl and ElevenLabs publish HTML tables without structured
data, so for those this script only confirms that the key strings still appear on the
page — a weaker check, and it says so rather than pretending to be exact.

    python3 check_prices.py            # human report; exit 1 if anything drifted
    python3 check_prices.py --json     # machine report

On drift the release route is the one in README.md ("Staying current"): update the entry,
set verified/as_of, re-run test_mcp.py and build_site.py --check, bump the patch version,
publish through /agent/bin/pkg-publish, re-publish server.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "dataset.json")
UA = "Mozilla/5.0 (compatible; costcalc-price-check/1.0; +https://a9n9.net)"

# dataset key -> the vendor's own offer name, exactly as it appears in the JSON-LD
DG_OFFERS = {
    "stt_usd_per_minute": {
        "nova3_monolingual_prerecorded_payg": "Speech-to-text: Nova-3 Monolingual (Pre-recorded) — Pay as you go",
        "nova3_monolingual_prerecorded_growth": "Speech-to-text: Nova-3 Monolingual (Pre-recorded) — Growth",
        "nova3_monolingual_streaming_payg": "Speech-to-text: Nova-3 Monolingual (Streaming) — Pay as you go",
        "nova3_monolingual_streaming_growth": "Speech-to-text: Nova-3 Monolingual (Streaming) — Growth",
        "nova3_multilingual_prerecorded_payg": "Speech-to-text: Nova-3 Multilingual (Pre-recorded) — Pay as you go",
        "nova3_multilingual_prerecorded_growth": "Speech-to-text: Nova-3 Multilingual (Pre-recorded) — Growth",
        "nova3_multilingual_streaming_payg": "Speech-to-text: Nova-3 Multilingual (Streaming) — Pay as you go",
        "nova3_multilingual_streaming_growth": "Speech-to-text: Nova-3 Multilingual (Streaming) — Growth",
        "flux_english_streaming_payg": "Speech-to-text: Flux STT English (Streaming) — Pay as you go",
        "flux_english_streaming_growth": "Speech-to-text: Flux STT English (Streaming) — Growth",
        "flux_multilingual_streaming_payg": "Speech-to-text: Flux STT Multilingual (Streaming) — Pay as you go",
        "flux_multilingual_streaming_growth": "Speech-to-text: Flux STT Multilingual (Streaming) — Growth",
        "whisper_large_prerecorded": "Speech-to-text: Whisper Large (Pre-recorded) — Pay as you go",
    },
    "voice_agent_usd_per_minute": {
        "standard_payg": "Voice Agent: Standard (per minute) — Pay as you go",
        "standard_growth": "Voice Agent: Standard (per minute) — Growth",
        "standard_byo_tts_payg": "Voice Agent: Standard, BYO TTS (per minute) — Pay as you go",
        "standard_byo_tts_growth": "Voice Agent: Standard, BYO TTS (per minute) — Growth",
        "custom_byo_llm_payg": "Voice Agent: Custom, BYO LLM (per minute) — Pay as you go",
        "custom_byo_llm_growth": "Voice Agent: Custom, BYO LLM (per minute) — Growth",
        "custom_byo_llm_tts_payg": "Voice Agent: Custom, BYO LLM and TTS (per minute) — Pay as you go",
        "custom_byo_llm_tts_growth": "Voice Agent: Custom, BYO LLM and TTS (per minute) — Growth",
        "advanced_payg": "Voice Agent: Advanced (per minute) — Pay as you go",
        "advanced_growth": "Voice Agent: Advanced (per minute) — Growth",
        "advanced_byo_tts_payg": "Voice Agent: Advanced, BYO TTS (per minute) — Pay as you go",
        "advanced_byo_tts_growth": "Voice Agent: Advanced, BYO TTS (per minute) — Growth",
    },
    "tts_usd_per_1000_chars": {
        "aura_2_payg": "Text-to-speech: Aura-2 — Pay as you go",
        "aura_2_growth": "Text-to-speech: Aura-2 — Growth",
        "aura_1_payg": "Text-to-speech: Aura-1 — Pay as you go",
        "aura_1_growth": "Text-to-speech: Aura-1 — Growth",
        "flux_tts_payg": "Text-to-speech: Flux TTS — Pay as you go",
    },
}

# strings that must still be present on the pages without structured data
SPOT_CHECKS = {
    "firecrawl": {
        "url": "https://firecrawl.dev/pricing",
        "must_contain": ["$19", "5,000", "$99", "100,000", "$399", "500,000", "$749", "1,000,000"],
    },
    "elevenlabs": {
        "url": "https://elevenlabs.io/pricing/api",
        "must_contain": ["0.08", "0.04"],
    },
}


def fetch(url):
    r = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", UA, url],
                       capture_output=True, text=True)
    return r.stdout or ""


def dg_offers_from_page(html):
    out = {}
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            j = json.loads(block)
        except Exception:
            continue
        found = []

        def walk(o):
            if isinstance(o, dict):
                if "price" in o and "name" in o:
                    found.append((o["name"], o["price"], (o.get("priceSpecification") or {}).get("unitText")))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(j)
        for name, price, unit in found:
            out[name] = (float(price), unit)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = json.load(open(DATA, encoding="utf-8"))
    report = {"as_of": d["as_of"], "checked_at": None, "drift": [], "missing": [], "spot": {}}

    # Deepgram: exact
    html = fetch(SPOT_CHECKS and d["vendors"]["deepgram"]["source"])
    offers = dg_offers_from_page(html)
    if not offers:
        report["missing"].append("deepgram: no JSON-LD offers found on the page (page changed or fetch failed)")
    for group, mapping in DG_OFFERS.items():
        for key, offer_name in mapping.items():
            have = d["vendors"]["deepgram"][group].get(key)
            got = offers.get(offer_name)
            if got is None:
                if offers:
                    report["missing"].append(f"deepgram {group}.{key}: offer {offer_name!r} not on the page")
                continue
            price, unit = got
            if have != price:
                report["drift"].append({"key": f"deepgram.{group}.{key}", "dataset": have,
                                        "page": price, "offer": offer_name, "unit": unit})

    # the unit label is the thing that went wrong last time — check it explicitly
    allowed_units = {
        "stt_usd_per_minute": "minute",
        "voice_agent_usd_per_minute": "minute",
        "tts_usd_per_1000_chars": "1,000 characters",
    }
    for group, unit in allowed_units.items():
        for key, offer_name in DG_OFFERS[group].items():
            got = offers.get(offer_name)
            if got and got[1] and got[1] != unit:
                report["drift"].append({"key": f"deepgram.{group}.{key}.unit", "dataset": unit,
                                        "page": got[1], "offer": offer_name})

    # Firecrawl / ElevenLabs: presence only, stated as such
    for vid, spec in SPOT_CHECKS.items():
        page = fetch(spec["url"])
        hit = {s: (s in page) for s in spec["must_contain"]}
        report["spot"][vid] = {"url": spec["url"], "bytes": len(page), "found": hit}
        for s, ok in hit.items():
            if not ok:
                report["missing"].append(f"{vid}: string {s!r} no longer on {spec['url']}")

    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"price check — dataset as_of {d['as_of']}")
        print(f"  deepgram: {len(offers)} structured offers read; "
              f"{len([r for r in report['drift'] if r['key'].startswith('deepgram')])} drift row(s)")
        for r in report["drift"]:
            print(f"    DRIFT {r['key']}: dataset {r['dataset']} -> page {r['page']}")
        for vid, s in report["spot"].items():
            print(f"  {vid}: {s['bytes']:,} bytes; "
                  f"{sum(s['found'].values())}/{len(s['found'])} key strings present")
        for m in report["missing"]:
            print(f"    MISSING {m}")
        if not report["drift"] and not report["missing"]:
            print("  VERDICT: no drift detected")
    return 1 if (report["drift"] or report["missing"]) else 0


if __name__ == "__main__":
    sys.exit(main())
