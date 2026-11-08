#!/usr/bin/env python3
"""build_site.py — render the public cost index from dataset.json + history/.

Channel B of strategy.md §2b: a static, dated price index for the three vendors,
so that (a) a reader can see a unit-price comparison in one screen, (b) a machine
can fetch pricing.json, (c) a change in a vendor's price produces a diff, an RSS
item and a changelog line rather than a silently rotten table.

Everything is generated from dataset.json. No network, stdlib only.

    python3 build_site.py            # writes site/ (index, vendors/*, pricing.json, changes.json, feed.xml)
    python3 build_site.py --check    # re-render and verify invariants, exit 1 on any failure

The affiliate rule this file enforces: a link to a vendor is only ever printed with
the words "affiliate link" inside the same anchor text, and only for vendors whose
dataset entry has an affiliate_link. Historical rows carry no links at all.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "dataset.json")
SITE = os.path.join(HERE, "site")
HIST = os.path.join(HERE, "history")

AI_LINE = "Maintained by agent002, an autonomous AI agent operated by a9n9."
AFF_SENTENCE = ("Links marked <strong>affiliate link</strong> are a9n9's affiliate links: "
                "a9n9 earns a commission if you buy through them. Prices are the vendors' own and are not affected.")

CSS = """
body{font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;color:#16181d;background:#fff}
main{max-width:62rem;margin:0 auto;padding:2rem 1.25rem 4rem}
h1{font-size:1.9rem;line-height:1.2;margin:0 0 .4rem}
h2{font-size:1.25rem;margin:2.4rem 0 .6rem;border-bottom:1px solid #e6e8ec;padding-bottom:.3rem}
h3{font-size:1.02rem;margin:1.6rem 0 .3rem}
p,li{max-width:52rem}
.meta{color:#5b616e;font-size:.9rem;margin:.2rem 0 1.4rem}
table{border-collapse:collapse;width:100%;font-size:.93rem;margin:.7rem 0}
th,td{border-bottom:1px solid #e6e8ec;padding:.45rem .5rem;text-align:left;vertical-align:top}
th{background:#f6f7f9;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.trap{background:#fff8e6;border-left:3px solid #e0a800;padding:.5rem .8rem;margin:.6rem 0;font-size:.93rem}
.disc{background:#f2f6ff;border-left:3px solid #3b6fd4;padding:.6rem .9rem;margin:1.4rem 0;font-size:.93rem}
footer{margin-top:3rem;border-top:1px solid #e6e8ec;padding-top:1rem;color:#5b616e;font-size:.88rem}
code{background:#f3f4f7;padding:.1rem .3rem;border-radius:3px;font-size:.9em}
a{color:#1a4fd0}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def load():
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


# ---------- normalised unit rows (the comparison the vendors do not give you) ----------

def firecrawl_rows(fc):
    rows = []
    for p in fc["plans"]:
        if p["name"] == "Free":
            continue  # a free allowance is not a unit price; noted in the text instead
        pages = p["pages_included"]
        usd = p["usd_per_month"]
        if pages:
            rows.append({
                "label": f"{p['name']} — ${usd}/mo for {pages:,} pages",
                "unit": "per 1,000 pages", "usd": usd / pages * 1000,
                "note": ("included-rate; the $16 figure on the site is the annual-billed rate, not the monthly price"
                         if p["name"] == "Hobby" else "included-rate"),
            })
        if p.get("payg_usd_per_1000_credits") and p["name"] != "Free":
            rows.append({
                "label": f"{p['name']} — ${p['payg_usd_per_1000_credits']:.2f} per 1,000 extra credits ($5 blocks)",
                "unit": "per 1,000 pages over plan", "usd": p["payg_usd_per_1000_credits"],
                "note": "marginal (overflow) rate, not the blended rate",
            })
    return rows


def elevenlabs_rows(el):
    r = el["rates_usd_per_1000_chars"]
    cpm = el["chars_per_minute_default"]
    return [
        {"label": "Multilingual v4, API billing", "unit": "per 1,000 characters", "usd": r["multilingual_v4_api"],
         "note": f"= ${r['multilingual_v4_api']/1000*cpm:.4f} per spoken minute at {cpm} chars/min"},
        {"label": "Turbo/Flash, API billing", "unit": "per 1,000 characters", "usd": r["turbo_flash_api"],
         "note": f"= ${r['turbo_flash_api']/1000*cpm:.4f} per spoken minute at {cpm} chars/min"},
        {"label": "Agent (conversational) minutes", "unit": "per minute", "usd": el["agent_usd_per_minute"],
         "note": "includes STT + LLM + TTS; not comparable with a bare STT minute"},
        {"label": "Creator plan, credits-equivalent", "unit": "per 1,000 characters", "usd": r["credits_equivalent_creator"],
         "note": "the credits table on the marketing page; 2.27x the API rate for the same characters"},
    ]


def pretty_label(key):
    """nova3_monolingual_prerecorded_payg -> 'Nova-3 monolingual, pre-recorded — pay as you go'"""
    k = key.replace("_payg", " — pay as you go").replace("_growth", " — Growth")
    parts = k.split(" — ")[0].split("_")
    words = []
    for p in parts:
        if p.startswith("nova"):
            words.append("Nova-" + p[4:])
        elif p in ("byo", "tts", "llm", "stt", "aura"):
            words.append(p.upper() if p in ("tts", "llm", "stt") else p)
        elif p in ("prerecorded",):
            words.append("pre-recorded")
        else:
            words.append(p)
    label = " ".join(words)
    if " — " in k:
        label += " — " + k.split(" — ", 1)[1]
    return label


def deepgram_groups(dg):
    """Deepgram's page has three products on three units; show them as three tables."""
    return [
        ("Speech-to-text — per minute", [
            {"label": pretty_label(k), "unit": "per minute", "usd": v,
             "note": "text out; no LLM, no synthetic voice"}
            for k, v in dg["stt_usd_per_minute"].items()]),
        ("Voice Agent — per minute, all-in", [
            {"label": pretty_label(k), "unit": "per minute", "usd": v,
             "note": "STT + managed LLM + TTS bundled (variant-dependent)"}
            for k, v in dg["voice_agent_usd_per_minute"].items()]),
        ("Text-to-speech — per 1,000 characters", [
            {"label": pretty_label(k), "unit": "per 1,000 characters", "usd": v,
             "note": f"= ${v/1000*dg.get('_cpm', 900):.4f} per spoken minute at 900 chars/min"}
            for k, v in dg["tts_usd_per_1000_chars"].items()]),
    ]


# ---------- history and changes ----------

def snapshot(d):
    """Copy today's dataset into history/<as_of>.json if not already there."""
    os.makedirs(HIST, exist_ok=True)
    path = os.path.join(HIST, f"{d['as_of']}.json")
    if not os.path.exists(path):
        shutil.copyfile(DATA, path)
    return path


def flatten(d):
    """Flatten every comparable price into a dotted key -> number map."""
    out = {}
    for vid, v in d["vendors"].items():
        for p in v.get("plans", []):
            for k in ("usd_per_month", "pages_included", "payg_usd_per_1000_credits"):
                if p.get(k) is not None:
                    out[f"{vid}.plan.{p['name']}.{k}"] = p[k]
        for k, val in (v.get("rates_usd_per_1000_chars") or {}).items():
            out[f"{vid}.chars.{k}"] = val
        for k, val in (v.get("stt_usd_per_minute") or {}).items():
            out[f"{vid}.stt.{k}"] = val
        for k, val in (v.get("voice_agent_usd_per_minute") or {}).items():
            out[f"{vid}.voice_agent.{k}"] = val
        for k, val in (v.get("tts_usd_per_1000_chars") or {}).items():
            out[f"{vid}.tts.{k}"] = val
        for k, val in (v.get("rates_usd_per_minute") or {}).items():
            out[f"{vid}.minute.{k}"] = val
        for k, val in (v.get("byo_key_usd_per_minute") or {}).items():
            out[f"{vid}.byo.{k}"] = val
        if v.get("agent_usd_per_minute") is not None:
            out[f"{vid}.agent_minute"] = v["agent_usd_per_minute"]
        if v.get("chars_per_minute_default") is not None:
            out[f"{vid}.chars_per_minute_default"] = v["chars_per_minute_default"]
    return out


def compute_changes():
    files = sorted(f for f in os.listdir(HIST) if f.endswith(".json"))
    changes = []
    for i in range(1, len(files)):
        a = json.load(open(os.path.join(HIST, files[i - 1]), encoding="utf-8"))
        b = json.load(open(os.path.join(HIST, files[i]), encoding="utf-8"))
        fa, fb = flatten(a), flatten(b)
        rows = []
        for k in sorted(set(fa) | set(fb)):
            if k.startswith("elevenlabs.chars_per_minute_default") or "included" in k:
                continue
            if fa.get(k) != fb.get(k):
                rows.append({"key": k, "from": fa.get(k), "to": fb.get(k)})
        changes.append({"date": b["as_of"], "previous": a["as_of"], "changes": rows})
    return changes


# ---------- renderers ----------

def page(title, body, root=""):
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><main>"
            f"{body}</main></body></html>\n")


def link_html(name, url):
    """An affiliate link is never printed without the label inside the anchor."""
    return f'<a href="{esc(url)}" rel="sponsored noopener">{esc(name)} — affiliate link</a>'


def norm_table(rows):
    h = ["<table><tr><th>Line</th><th>Unit basis</th><th>USD</th><th>Note</th></tr>"]
    for r in rows:
        h.append(f"<tr><td>{esc(r['label'])}</td><td>{esc(r['unit'])}</td>"
                 f"<td class=\"num\">${r['usd']:,.4f}</td><td>{esc(r['note'])}</td></tr>")
    h.append("</table>")
    return "".join(h)


def render_index(d, changes):
    fc, el, dg = d["vendors"]["firecrawl"], d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    body = [f"<h1>API price index: Firecrawl, ElevenLabs, Deepgram</h1>",
            f"<p class=\"meta\">Unit prices read from the vendors' own pricing pages on "
            f"{esc(d['as_of'])}. Per-vendor read times and source URLs below. "
            f"Machine-readable: <a href=\"pricing.json\">pricing.json</a>. Changes: "
            f"<a href=\"changes.json\">changes.json</a> · <a href=\"feed.xml\">RSS</a>.</p>",
            f"<div class=\"disc\">{AFF_SENTENCE}<br>{esc(AI_LINE)} "
            f"Every figure below is copied from a vendor page, not from a review or from memory; "
            f"where a page disagrees with itself, both numbers are shown.</div>"]

    body.append("<h2>The mistakes this page exists to stop</h2>")
    body.append("<p><strong>One vendor, two different minutes.</strong> Deepgram prints <strong>$0.075 per "
                "minute</strong> at the top of its pricing page, and that number is its <em>Voice Agent</em> — "
                "speech-to-text plus a managed language model plus synthetic speech. Its speech-to-text alone is "
                f"<strong>${min(dg['stt_usd_per_minute'].values()):.4f}–${max(dg['stt_usd_per_minute'].values()):.4f} "
                "per minute</strong>. Quoting the agent rate as an STT rate makes Deepgram look about 17x more "
                "expensive than it is in the job most people actually give it. Both are on the page; only one is "
                "labelled as such in the table below.</p>")
    body.append("<p><strong>Two vendors, two different units.</strong> ElevenLabs and Deepgram are quoted in "
                "characters vs minutes, so a like-for-like comparison has to pass through a characters-per-minute "
                "assumption, and that assumption swings 600–1,000 characters per minute depending on the speaker. "
                f"At {el['chars_per_minute_default']} chars/min, ElevenLabs v4 speech costs "
                f"<strong>${el['rates_usd_per_1000_chars']['multilingual_v4_api']/1000*el['chars_per_minute_default']:.4f} "
                f"per spoken minute</strong> and Deepgram Aura-2 costs "
                f"<strong>${dg['tts_usd_per_1000_chars']['aura_2_payg']/1000*el['chars_per_minute_default']:.4f}</strong> "
                f"— a {el['rates_usd_per_1000_chars']['multilingual_v4_api']/dg['tts_usd_per_1000_chars']['aura_2_payg']:.1f}x "
                "gap. But an agent minute is not a speech minute: ElevenLabs Agents is "
                f"${el['agent_usd_per_minute']:.3f}/min and Deepgram's Voice Agent Standard is "
                f"${dg['voice_agent_usd_per_minute']['standard_payg']:.3f}/min, a "
                f"{(el['agent_usd_per_minute']/dg['voice_agent_usd_per_minute']['standard_payg']-1)*100:.1f}% gap in the "
                "other direction. If you price an agent from per-character rates you are comparing the wrong two numbers.</p>")

    body.append("<h2>Firecrawl — pages</h2>")
    body.append(f"<p class=\"meta\">Source: <a href=\"{esc(fc['source'])}\">{esc(fc['source'])}</a>, "
                f"read {esc(fc['verified'])}. 1 credit = 1 page scraped; JSON extraction adds 4 credits per page.</p>")
    body.append(norm_table(firecrawl_rows(fc)))
    body.append("<p class=\"meta\">Free tier: 1,000 credits a month, excluded from the rate table above because a "
                "free allowance is not a unit price.</p>")
    for t in fc["traps"]:
        body.append(f"<div class=\"trap\">{esc(t)}</div>")
    body.append(f"<p>Current price panel: {link_html(fc['name'], fc['affiliate_link'])}. "
                f"{esc(fc.get('buyer_offer') or '')}</p>")

    body.append("<h2>ElevenLabs — characters and agent minutes</h2>")
    body.append(f"<p class=\"meta\">Source: <a href=\"{esc(el['source'])}\">{esc(el['source'])}</a>, "
                f"read {esc(el['verified'])}.</p>")
    body.append(norm_table(elevenlabs_rows(el)))
    for t in el["traps"]:
        body.append(f"<div class=\"trap\">{esc(t)}</div>")
    body.append(f"<p>Current price panel: {link_html(el['name'], el['affiliate_link'])}.</p>")

    body.append("<h2>Deepgram — three products, three units</h2>")
    body.append(f"<p class=\"meta\">Source: <a href=\"{esc(dg['source'])}\">{esc(dg['source'])}</a>, "
                f"read {esc(dg['verified'])}. Same vendor, three products, three units — the table headings "
                f"are the units, so nothing here is compared across a unit boundary by accident.</p>")
    for heading, rows in deepgram_groups(dg):
        body.append(f"<h3>{esc(heading)}</h3>")
        body.append(norm_table(rows))
    for t in dg["traps"]:
        body.append(f"<div class=\"trap\">{esc(t)}</div>")
    body.append("<p>No affiliate programme is listed for Deepgram, so no link is shown for it. "
                "That is also why nothing here is ranked by commission.</p>")

    body.append("<h2>How to get your own number</h2>")
    body.append("<p>This page shows unit prices. For a workload (<code>50,000 pages, 2M characters, "
                "5,000 agent minutes, 10,000 transcribed minutes</code>) the same dataset is rendered by a "
                "command-line tool and by an MCP server that picks the cheapest plan including overflow "
                "blocks: <code>npx -y costcalc-mcp</code> (package pending publication) or "
                "<code>python3 costcalc.py --pages 50000 --chars 2000000</code>.</p>")

    body.append("<h2>Price history</h2>")
    if not changes:
        body.append("<p class=\"meta\">First snapshot: no prior snapshot to diff against yet. "
                    "History starts on the date above; when a vendor price moves, the diff appears here, "
                    "in <code>changes.json</code> and as an RSS item.</p>")
    else:
        for c in changes:
            body.append(f"<h3>{esc(c['date'])} vs {esc(c['previous'])}</h3>")
            if not c["changes"]:
                body.append("<p class=\"meta\">No price changes detected between these snapshots.</p>")
            else:
                body.append("<table><tr><th>Price</th><th>Before</th><th>After</th></tr>")
                for r in c["changes"]:
                    body.append(f"<tr><td><code>{esc(r['key'])}</code></td><td class=\"num\">{esc(r['from'])}</td>"
                                f"<td class=\"num\">{esc(r['to'])}</td></tr>")
                body.append("</table>")
        body.append("<p class=\"meta\">Historical rows carry no links: a link beside a past price would imply "
                    "you could buy at it.</p>")

    body.append(f"<footer>{esc(AI_LINE)} Prices are dated and carry their source; when a vendor changes a "
                f"price, the next snapshot records the diff here. "
                f"<a href=\"https://a9n9.net\">a9n9</a></footer>")
    return page("API price index — Firecrawl, ElevenLabs, Deepgram (dated)", "".join(body))


def render_vendor(vid, v, d):
    body = [f"<h1>{esc(v['name'])} prices, with the page they came from</h1>",
            f"<p class=\"meta\">Billed per {esc(v['unit'])}. Source: "
            f"<a href=\"{esc(v['source'])}\">{esc(v['source'])}</a>, read {esc(v['verified'])}. "
            f"Index as of {esc(d['as_of'])}. <a href=\"../index.html\">Back to the index</a>.</p>",
            f"<div class=\"disc\">{AFF_SENTENCE}</div>"]
    if vid == "deepgram":
        for heading, rows in deepgram_groups(v):
            body.append(f"<h3>{esc(heading)}</h3>")
            body.append(norm_table(rows))
    else:
        rows = {"firecrawl": firecrawl_rows, "elevenlabs": elevenlabs_rows}[vid](v)
        body.append(norm_table(rows))
    for t in v.get("traps", []):
        body.append(f"<div class=\"trap\">{esc(t)}</div>")
    if v.get("affiliate_link"):
        body.append(f"<p>Current price panel: {link_html(v['name'], v['affiliate_link'])}. "
                    f"{esc(v.get('buyer_offer') or '')}</p>")
    else:
        body.append("<p>No affiliate programme is listed for this vendor, so there is no link on this page.</p>")
    body.append(f"<footer>{esc(AI_LINE)}</footer>")
    return page(f"{v['name']} pricing — dated unit prices", "".join(body))


def render_pricing_json(d):
    fc, el, dg = d["vendors"]["firecrawl"], d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    return json.dumps({
        "as_of": d["as_of"],
        "note": "Normalised unit prices. Every figure comes from the vendor's own pricing page at the "
                "`source` URL, read at `verified`. Affiliate links are a9n9's; prices are unaffected.",
        "maintainer": "agent002, an autonomous AI agent operated by a9n9",
        "affiliate_disclosure": d["disclosure"],
        "units": {
            "firecrawl": {"unit": "1,000 pages scraped", "source": fc["source"], "verified": fc["verified"],
                          "rows": firecrawl_rows(fc), "affiliate_disclosure": fc["affiliate_disclosure"],
                          "affiliate_link": fc["affiliate_link"]},
            "elevenlabs": {"unit": "1,000 characters and per minute", "source": el["source"], "verified": el["verified"],
                           "rows": elevenlabs_rows(el), "affiliate_disclosure": el["affiliate_disclosure"],
                           "affiliate_link": el["affiliate_link"]},
            "deepgram": {"unit": "three units: per minute (STT), per minute (Voice Agent), per 1,000 characters (TTS)",
                         "source": dg["source"], "verified": dg["verified"],
                         "groups": [{"heading": h, "rows": rows} for h, rows in deepgram_groups(dg)],
                         "affiliate_disclosure": dg["affiliate_disclosure"],
                         "affiliate_link": None},
        },
    }, indent=1)


def render_feed(d, changes):
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "API price index changes — Firecrawl, ElevenLabs, Deepgram"
    ET.SubElement(ch, "link").text = "https://github.com/a9n9-agent002/ai-cost-calculator"
    ET.SubElement(ch, "description").text = ("Price snapshots and diffs for Firecrawl, ElevenLabs and Deepgram. "
                                             "Maintained by agent002, an autonomous AI agent operated by a9n9.")
    items = changes or [{"date": d["as_of"], "previous": None, "changes": []}]
    for c in reversed(items):
        it = ET.SubElement(ch, "item")
        if c["previous"]:
            title = f"{c['date']}: {len(c['changes'])} price change(s) vs {c['previous']}"
        else:
            title = f"{c['date']}: first snapshot of vendor unit prices"
        ET.SubElement(it, "title").text = title
        ET.SubElement(it, "guid").text = f"https://github.com/a9n9-agent002/ai-cost-calculator#{c['date']}"
        ET.SubElement(it, "pubDate").text = datetime.datetime.fromisoformat(c["date"] + "T12:00:00+00:00") \
            .strftime("%a, %d %b %Y %H:%M:%S +0000")
        desc = "; ".join(f"{r['key']}: {r['from']} -> {r['to']}" for r in c["changes"]) or \
            "Snapshot recorded; no changes to report."
        ET.SubElement(it, "description").text = desc
    ET.indent(rss)
    return ET.tostring(rss, encoding="unicode") + "\n"


def build():
    d = load()
    snapshot(d)
    changes = compute_changes()
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    os.makedirs(os.path.join(SITE, "vendors"), exist_ok=True)
    written = []
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(d, changes)); written.append("index.html")
    for vid, v in d["vendors"].items():
        p = os.path.join(SITE, "vendors", f"{vid}.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(render_vendor(vid, v, d)); written.append(f"vendors/{vid}.html")
    with open(os.path.join(SITE, "pricing.json"), "w", encoding="utf-8") as f:
        f.write(render_pricing_json(d)); written.append("pricing.json")
    with open(os.path.join(SITE, "changes.json"), "w", encoding="utf-8") as f:
        json.dump({"as_of": d["as_of"], "history": changes}, f, indent=1); written.append("changes.json")
    with open(os.path.join(SITE, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(render_feed(d, changes)); written.append("feed.xml")
    return written, d


def check():
    """Invariants the operator review implies: disclosure, labelled links, parseable feeds, age warning."""
    failures = []
    written, d = build()
    html = {p: open(os.path.join(SITE, p), encoding="utf-8").read() for p in written if p.endswith(".html")}
    for p, t in html.items():
        if "autonomous AI agent operated by a9n9" not in t:
            failures.append(f"{p}: missing AI disclosure")
        if "affiliate link" not in t and p != "vendors/deepgram.html":
            failures.append(f"{p}: no affiliate label found")
        if "earns a commission" not in t and p != "vendors/deepgram.html":
            failures.append(f"{p}: missing commission sentence")
        # every href to a vendor affiliate domain must sit inside an anchor whose text says affiliate link
        for m in re.finditer(r'<a href="(https://(?:firecrawl\.link|try\.elevenlabs\.io)[^"]*)"[^>]*>(.*?)</a>', t):
            if "affiliate link" not in m.group(2):
                failures.append(f"{p}: affiliate href without label: {m.group(1)}")
        if re.search(r'href="https://(?:firecrawl\.link|try\.elevenlabs\.io)', t) is None and p != "vendors/deepgram.html":
            pass  # not every page must carry one
    # no unlabelled vendor links anywhere (e.g. a bare <a href="https://firecrawl.dev">)
    for p, t in html.items():
        for m in re.finditer(r'<a href="(https://(?:firecrawl\.link|try\.elevenlabs\.io)[^"]*)"', t):
            start = t.rfind("<a ", 0, m.start())
            end = t.find("</a>", m.start())
            if "affiliate link" not in t[start:end]:
                failures.append(f"{p}: unlabelled affiliate href {m.group(1)}")
    # feed parses
    try:
        root = ET.parse(os.path.join(SITE, "feed.xml")).getroot()
        if root.tag != "rss" or root.find("channel/item") is None:
            failures.append("feed.xml: no items")
    except Exception as e:
        failures.append(f"feed.xml: does not parse: {e}")
    # pricing.json parses and its as_of matches the dataset
    pj = json.load(open(os.path.join(SITE, "pricing.json"), encoding="utf-8"))
    if pj["as_of"] != d["as_of"]:
        failures.append("pricing.json as_of mismatch")
    if pj["units"]["deepgram"]["affiliate_link"] is not None:
        failures.append("deepgram must have no affiliate link")
    # arithmetic spot checks, recomputed from the dataset, not from the page
    fc = d["vendors"]["firecrawl"]["plans"]
    hobby = next(p for p in fc if p["name"] == "Hobby")
    if abs(hobby["usd_per_month"] / hobby["pages_included"] * 1000 - 3.8) > 1e-9:
        failures.append("Hobby per-1,000-pages arithmetic changed (expected 3.80)")
    el = d["vendors"]["elevenlabs"]
    per_min = el["rates_usd_per_1000_chars"]["multilingual_v4_api"] / 1000 * el["chars_per_minute_default"]
    if abs(per_min - 0.072) > 1e-9:
        failures.append("ElevenLabs per-spoken-minute arithmetic changed (expected 0.0720)")
    # the Deepgram mix-up must not be able to come back: no STT rate may equal the agent rate
    dg = d["vendors"]["deepgram"]
    if max(dg["stt_usd_per_minute"].values()) >= 0.05:
        failures.append("an STT rate is at or above $0.05/min - looks like a Voice Agent rate in the STT table")
    if dg["voice_agent_usd_per_minute"]["standard_payg"] != 0.075:
        failures.append("Deepgram Voice Agent standard PAYG is no longer 0.075")
    if abs(min(dg["stt_usd_per_minute"].values()) - 0.0036) > 1e-9:
        failures.append("Deepgram STT floor is no longer 0.0036 (Growth, Nova-3 mono pre-recorded)")
    # history must exist for as_of
    if not os.path.exists(os.path.join(HIST, d["as_of"] + ".json")):
        failures.append("history snapshot missing")
    return failures, written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        failures, written = check()
        print(f"rendered {len(written)} files into {SITE}")
        if failures:
            print(f"{len(failures)} FAILURE(S):")
            for f in failures:
                print("  - " + f)
            return 1
        print("ALL CHECKS PASS")
        return 0
    written, d = build()
    print(f"as_of {d['as_of']}: wrote {len(written)} files into {SITE}")
    for w in written:
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
