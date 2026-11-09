"""Verifies every number in CLAIM-CHECK.md and the README's claim-check section against
dataset.json, so the document cannot drift from the data it describes.

Run: python3 check_claims.py   (exit 0 = every published figure matches the dataset)
"""
import json
import sys

D = json.load(open("dataset.json"))
dg = D["vendors"]["deepgram"]
stt = dg["stt_usd_per_minute"]
agent = dg["voice_agent_usd_per_minute"]

FLOOR = stt["nova3_monolingual_prerecorded_payg"]
STREAM = stt["nova3_monolingual_streaming_payg"]
WHISPER = stt["whisper_large_prerecorded"]
AGENT_STD = agent["standard_payg"]
AGENT_BYO = agent["custom_byo_llm_tts_payg"]
AGENT_ADV = agent["advanced_payg"]

# figures quoted from the cited third-party pages (read 2026-11-08, see CLAIM-CHECK.md)
CB_FLOOR = 0.0047
CB_CHEAPEST_ROW = 0.0058

failures = []


def want(label, got, expected, tol=0.05):
    ok = abs(got - expected) <= tol
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got:.4g} (published {expected})")
    if not ok:
        failures.append(label)


def text(fn):
    return open(fn, encoding="utf-8").read()


docs = {"CLAIM-CHECK.md": text("CLAIM-CHECK.md"), "README.md": text("README.md")}

# arithmetic, recomputed
want("STT floor $/min", FLOOR, 0.0043, 1e-9)
want("costbench floor premium %", (CB_FLOOR / FLOOR - 1) * 100, 9.3, 0.05)
want("costbench cheapest row premium %", (CB_CHEAPEST_ROW / FLOOR - 1) * 100, 34.9, 0.05)
want("whisper premium %", (WHISPER / FLOOR - 1) * 100, 11.6, 0.05)
want("streaming premium %", (STREAM / FLOOR - 1) * 100, 79.1, 0.05)
want("agent std vs byo %", (AGENT_STD / AGENT_BYO - 1) * 100, 50.0, 0.05)
want("advanced / standard", AGENT_ADV / AGENT_STD, 2.17, 0.01)
want("agent / stt ratio", AGENT_STD / FLOOR, 17.44, 0.01)
want("10,000 min STT $", 10000 * FLOOR, 43.00, 0.005)
want("10,000 min agent $", 10000 * AGENT_STD, 750.00, 0.005)

# --- README headline block: the three plan-table traps, recomputed from dataset.json ---
fc = D["vendors"]["firecrawl"]
FC_STD = next(p for p in fc["plans"] if p["name"] == "Standard")["usd_per_month"]
FC_STD_PAGES = next(p for p in fc["plans"] if p["name"] == "Standard")["pages_included"]
JSON_CREDITS_PER_PAGE = 5          # 1 credit per page + 4 for JSON format and prompt-injection check
want("Firecrawl Standard $/1k pages", FC_STD / FC_STD_PAGES * 1000, 0.99, 0.005)
want("Firecrawl Standard pages bought at 5 credits",
     FC_STD_PAGES / JSON_CREDITS_PER_PAGE, 20000, 0.5)
want("Firecrawl JSON $/1k pages",
     FC_STD / (FC_STD_PAGES / JSON_CREDITS_PER_PAGE) * 1000, 4.95, 0.005)

el = D["vendors"]["elevenlabs"]
LAD = {row["name"]: (row["usd"], row["chars"]) for row in el["ladder"]}
CPM = el["chars_per_minute_default"]
want("ElevenLabs Creator $/1k chars", LAD["Creator"][0] / LAD["Creator"][1] * 1000, 0.080, 0.0005)
want("ElevenLabs Pro $/1k chars", LAD["Pro"][0] / LAD["Pro"][1] * 1000, 0.080, 0.0005)
want("ElevenLabs Creator finished minutes", LAD["Creator"][1] / CPM, 306, 1)
want("ElevenLabs Pro finished minutes", LAD["Pro"][1] / CPM, 1376, 1)
want("ElevenLabs Creator->Pro step-up $", LAD["Pro"][0] - LAD["Creator"][0], 77, 0.01)

# --- README FAQ bullets for the other three programs, recomputed from data/ raw vendor reads (run 86) ---
import os
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def jraw(n):
    return json.load(open(os.path.join(DATA, n), encoding="utf-8"))


_do = jraw("do-droplets.json")
_gpu = jraw("gpu-hours.json")
_nov = jraw("novita-tokens.json")
_cmp = jraw("cross-provider.json")

_six = next(p for p in _do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
want("DO $6 at 730 hours", _six["usd_per_hour"] * 730, 6.52, 0.005)
want("DO monthly cap binds after hours", _six["usd_per_month"] / _six["usd_per_hour"], 671.9, 0.05)
want("DO $6 with daily backups", _six["usd_per_month"] * 1.30, 7.80, 0.005)
_small = next(p for p in _do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 0.5)
_big = next(p for p in _do["plans"] if p["family"] == "Basic" and p["memory_gib"] == 16.0)
want("DO $/GiB on 0.5 GiB plan", _small["usd_per_month"] / _small["memory_gib"], 8.00, 0.005)
want("DO $/GiB on 1 GiB plan", _six["usd_per_month"] / _six["memory_gib"], 6.00, 0.005)
_bestrate = min((p["usd_per_month"] / p["memory_gib"], p["memory_gib"], p["usd_per_month"]) for p in _do["plans"])
want("DO best $/GiB", _bestrate[0], 5.25, 0.005)
want("DO best-rate plan size", _bestrate[1], 16, 0.5)
want("DO best-rate plan price", _bestrate[2], 84, 0.5)

_h100 = {o["tier"] + ":" + o["provider"]: o["usd_per_gpu_hour"]
         for f in _gpu["gpus"] if f["family"] == "H100" for o in f["offers"]}
want("H100 on-demand Novita", _h100["on_demand:novita"], 3.39, 0.005)
want("H100 on-demand DigitalOcean", _h100["on_demand:digitalocean"], 4.41, 0.005)
want("H100 DO premium %", (_h100["on_demand:digitalocean"] / _h100["on_demand:novita"] - 1) * 100, 30.1, 0.05)
want("H100 reserved 12mo x 730", _h100["reserved_12mo:digitalocean"] * 730, 2379.80, 0.05)

_paid = [r for r in _nov["rows"] if (r.get("input_usd_per_mtok") or 0) > 0]
_cache = [r for r in _nov["rows"] if r.get("cache_read_usd_per_mtok")]
_ins = sorted(r["input_usd_per_mtok"] for r in _paid)
want("Novita paid model count", len(_paid), 73, 0.5)
want("Novita total model count", len(_nov["rows"]), 76, 0.5)
want("Novita cache-read count", len(_cache), 48, 0.5)
want("Novita cheapest input $/Mtok", _ins[0], 0.02, 1e-9)
want("Novita dearest input $/Mtok", _ins[-1], 4.00, 1e-9)

_MIX, _PROVS = (40, 10), ("novita", "deepinfra", "openrouter")


def _bill(r, p):
    return _MIX[0] * r[p]["input"] + _MIX[1] * r[p]["output"]


_best = max(_cmp["rows"], key=lambda r: max(_bill(r, p) for p in _PROVS) / min(_bill(r, p) for p in _PROVS))
for p, exp in (("novita", 96.00), ("deepinfra", 78.00), ("openrouter", 12.66)):
    want(f"cross-provider {p} bill for {_best['key']}", _bill(_best, p), exp, 0.005)
want("cross-provider spread", max(_bill(_best, p) for p in _PROVS) / min(_bill(_best, p) for p in _PROVS),
     7.58, 0.01)

_wins, _ties = {p: 0 for p in _PROVS}, 0
for r in _cmp["rows"]:
    _b = {p: _bill(r, p) for p in _PROVS}
    _lo = min(_b.values())
    _w = [p for p in _PROVS if abs(_b[p] - _lo) < 1e-9]
    if len(_w) > 1:
        _ties += 1
    else:
        _wins[_w[0]] += 1
want("cross-provider ties", _ties, 9, 0.5)
for p, exp in (("novita", 4), ("deepinfra", 8), ("openrouter", 13)):
    want(f"cross-provider per-mix wins {p}", _wins[p], exp, 0.5)

# the strings a reader sees must carry those figures
required = {
    "CLAIM-CHECK.md": ["$0.0043", "$0.0048", "$0.075", "$0.050", "9.3%", "34.9%", "17.4×",
                       "$43.00", "$750.00", "Whisper Large", "11.6%", "79%", "2.67×",
                       "affiliate"],
    "README.md": ["9.3%", "34.9%", "17.4×", "$43.00", "$750.00", "CLAIM-CHECK.md",
                  "$4.95 per 1,000 pages", "20,000", "$0.080 per 1,000 characters", "306", "1,376", "$77",
                  "$6.52", "671.9", "$7.80", "$8.00/GiB", "$5.25/GiB", "$3.39", "$4.41", "30.1%",
                  "$2,379.80", "538–555", "76 models", "48 of the 76", "$0.02", "$4.00",
                  "$96.00", "$78.00", "$12.66", "7.58×", "9 of the 34"],
}
for doc_name, needles in required.items():
    body = docs[doc_name]
    for n in needles:
        ok = n in body
        print(f"{'ok  ' if ok else 'FAIL'} {doc_name} contains {n!r}")
        if not ok:
            failures.append(f"{doc_name}:{n}")

# run 87: the ten per-model rows in the README table, recomputed from the raw catalogue read. Each row
# prints its three-provider bill in fixed order (Novita / DeepInfra / OpenRouter) plus the spread, so the
# table cannot drift from data/cross-provider.json.
cp = json.load(open("data/cross-provider.json"))
raw = {r["key"]: r for r in cp["rows"]}
MODEL_ROWS = [("deepseek-v4-pro", "DeepSeek V4 Pro"), ("deepseek-v4-flash-0731", "DeepSeek V4 Flash"),
              ("glm-5.3", "GLM 5.3"), ("deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash 1017"),
              ("ling-3.0-flash", "Ling 3.0 Flash"), ("gpt-oss-120b", "gpt-oss-120b"),
              ("qwen3.7-max", "Qwen3.7 Max"), ("qwen3.5-35b-a3b", "Qwen3.5 35B A3B"),
              ("glm-5.2", "GLM 5.2"), ("gemma-4-26b-a4b", "Gemma 4 26B A4B")]
spreads = []
for key, name in MODEL_ROWS:
    row = raw[key]
    bills = {p: 40 * row[p]["input"] + 10 * row[p]["output"]
             for p in ("novita", "deepinfra", "openrouter")}
    triplet = " / ".join(f"${bills[p]:,.2f}" for p in ("novita", "deepinfra", "openrouter"))
    spread = max(bills.values()) / min(bills.values())
    spreads.append(spread)
    line = f"| {name} | {triplet} | {spread:.2f}× |"
    ok = line in docs["README.md"]
    print(f"{'ok  ' if ok else 'FAIL'} README model row: {line}")
    if not ok:
        failures.append(f"README model row {name}")
all_spreads = []
for r in cp["rows"]:
    if all(r.get(p) for p in ("novita", "deepinfra", "openrouter")):
        b = {p: 40 * r[p]["input"] + 10 * r[p]["output"] for p in ("novita", "deepinfra", "openrouter")}
        all_spreads.append(max(b.values()) / min(b.values()))
n_close = sum(1 for s in all_spreads if s < 1.5)
claim = f"For {n_close} of them the monthly bill"
print(f"{'ok  ' if claim in docs['README.md'] else 'FAIL'} README states the within-1.5x count "
      f"({n_close} of {len(all_spreads)})")
if claim not in docs["README.md"]:
    failures.append("README within-1.5x sentence")

# the README's self-description of the ten pages must contain the phrases the pages are titled on — that
# is the whole point of the section (GitHub's in:readme index matches the README body, not the page titles)
MODEL_PHRASES = ["deepseek v4 pro pricing", "deepseek v4 flash pricing", "glm 5.3 pricing",
                 "deepseek v4.1 flash 1017 pricing", "ling 3.0 flash pricing", "gpt oss 120b pricing",
                 "qwen3.7 max pricing", "qwen3.5 35b a3b pricing", "glm 5.2 pricing",
                 "gemma 4 26b a4b pricing"]
for ph in MODEL_PHRASES:
    ok = ph in docs["README.md"]
    print(f"{'ok  ' if ok else 'FAIL'} README carries the typed phrase {ph!r}")
    if not ok:
        failures.append(f"README phrase {ph}")

# the disclaimer must state agent authorship, not imply a person
if "autonomous AI agent" not in docs["CLAIM-CHECK.md"]:
    failures.append("CLAIM-CHECK.md missing AI-authorship line")
    print("FAIL CLAIM-CHECK.md missing AI-authorship line")
else:
    print("ok   CLAIM-CHECK.md states autonomous AI authorship")

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL CLAIM CHECKS PASS")
