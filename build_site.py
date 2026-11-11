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
import argparse, tempfile
import datetime
import html as html_lib
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


def href(u):
    """Affiliate hrefs must reach the file as the approved bytes.

    esc() turns the Novita link's `&utm_source` into `&amp;utm_source`, so the published file no
    longer contains the approved link string byte-for-byte and the publish guard reads it as an
    unapproved referral link. A bare `&` is legal in an HTML attribute value that does not form a
    character reference, so the URL parses identically.
    """
    return esc(u).replace("&amp;", "&")


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
        {"label": "Creator plan — $22 for 275,000 characters", "unit": "per 1,000 characters",
         "usd": el["ladder"][2]["usd"] / el["ladder"][2]["chars"] * 1000,
         "note": "the plan's own allowance: identical to the pay-as-you-go rate, i.e. no volume discount"},
        {"label": "Creative plan, 121,000 credits (a different product)", "unit": "per 1,000 credits", "usd": r["credits_equivalent_creator"],
         "note": "credits are not characters; reading 121,000 as characters gives $0.1818/1,000, 2.27x the API rate — a units error, not a price"},
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

_CTA = re.compile(r'<p>(?:(?!</p>).)*?rel="sponsored[^"]*".*?</p>', re.S)


def _cta_first(body):
    """Move a single-vendor page's labelled link panel up under the lede (run 173).

    Measured 2026-11-10: on this site the affiliate link sat at 72-99% of the words on every
    question page and at 92-95% on voices.html and the vendor pages, while the two independent
    pages ranking beside my dev.to article put the commercial mention in their first sentences.
    Only applied where the page carries exactly ONE sponsored panel, so the multi-vendor index
    (two panels, each beside its own product section) is untouched.
    """
    ms = list(_CTA.finditer(body))
    if len(ms) != 1:
        return body
    m = ms[0]
    rest = body[:m.start()] + body[m.end():]
    end_h1 = rest.find("</h1>")
    if end_h1 < 0:
        return body
    cut = rest.find("</p>", end_h1 + 5)
    if cut < 0:
        return body
    cut += len("</p>")
    return rest[:cut] + m.group(0).replace("<p>", '<p class="cta">', 1) + rest[cut:]


def page(title, body, root="", desc=None):
    """Every page needs its own description (run 85). Until then this emitted NO meta description at
    all, so the site's front door (priority 1.0 in the sitemap) had none, and the question pages
    repeated their own title as one. Length band 110-158 follows the 34 page-1 descriptions measured
    on 2026-11-08 21:35Z (min 46, median 138, max 175; 2 over 160)."""
    if not desc:
        raise SystemExit(f"refusing to render {title!r} without a meta description")
    if not 110 <= len(desc) <= 158:
        raise SystemExit(f"meta description for {title!r} is {len(desc)} chars, target 110-158: {desc!r}")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title>"
            f"<meta name=\"description\" content=\"{esc(desc)}\">"
            f"<style>{CSS}</style></head><body><main>"
            f"{_cta_first(body)}</main></body></html>\n")


DEST_NOTES = {
    "firecrawl": (" (opens Firecrawl's Alexandria data-provider catalogue; the plan "
                  "ladder quoted here is read from firecrawl.dev/pricing)"),
    "elevenlabs": (" (opens elevenlabs.io, whose home page lists plan prices; the per-1,000-character "
                   "API rates quoted here are on its Pricing → API page)"),
    "digitalocean": (" (opens digitalocean.com, whose home page lists no prices at all; the Droplet "
                     "prices quoted here are on its Pricing page)"),
    "novita": (" (opens novita.ai, whose home page lists some model rates; the full price list "
               "quoted here is on its Pricing page)"),
}


def el_minutes(chars, cpm):
    """Finished minutes a character allowance buys at `cpm` characters per spoken minute."""
    return chars / float(cpm)


def link_html(name, url):
    """An affiliate link is never printed without the label inside the anchor.

    Run 108 followed every approved link to its destination. Run 177 tried to steer the click and
    measured that the approved links cannot be deep-linked (`/pricing` on the link host is 404 for
    ElevenLabs; Firecrawl's `/agent001/pricing` is a Dub "Link Not Found" page), while the
    destinations carry far fewer prices than the pages that price them (digitalocean.com home: 0
    "$" strings vs 41 on /pricing; elevenlabs.io home: 36 vs 292 on /pricing/api). So every anchor
    says where the click goes and where the numbers are.
    """
    anchor = f'<a href="{href(url)}" rel="sponsored noopener">{esc(name)} — affiliate link</a>'
    for dom, key in (("firecrawl.link", "firecrawl"), ("try.elevenlabs.io", "elevenlabs"),
                     ("m.do.co", "digitalocean"), ("novita.ai", "novita")):
        if dom in url:
            anchor += DEST_NOTES[key]
            break
    return anchor


def norm_table(rows):
    h = ["<table><tr><th>Line</th><th>Unit basis</th><th>USD</th><th>Note</th></tr>"]
    for r in rows:
        h.append(f"<tr><td>{esc(r['label'])}</td><td>{esc(r['unit'])}</td>"
                 f"<td class=\"num\">${r['usd']:,.4f}</td><td>{esc(r['note'])}</td></tr>")
    h.append("</table>")
    return "".join(h)


def _question_count():
    """The number of question pages, read from build_host.QUESTIONS so the index cannot drift from the
    page set (run-82 defect class: a link that names a page nobody generates)."""
    import build_host
    return len(build_host.QUESTIONS)


def render_index(d, changes):
    fc, el, dg = d["vendors"]["firecrawl"], d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    body = [f"<h1>AI API pricing comparison: five programs, dated unit prices</h1>",
            f"<p class=\"meta\">Unit prices read from the vendors' own pricing pages on "
            f"{esc(d['as_of'])}. Per-vendor read times and source URLs below. "
            f"Machine-readable: <a href=\"pricing.json\">pricing.json</a>. Changes: "
            f"<a href=\"changes.json\">changes.json</a> · <a href=\"feed.xml\">RSS</a>. "
            f"<strong>Making audio?</strong> <a href=\"voices.html\">Voice minutes: what a plan buys</a>. "
            f"<strong>One question?</strong> <a href=\"q/index.html\">{_question_count()} answers</a> — droplet "
            f"pricing, GPU price per hour, Novita API pricing, a three-provider LLM comparison, plus the "
            f"scraping and speech questions.</p>",
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
                "blocks: <code>npx -y elevenlabs-cost-calculator</code> (package pending publication) or "
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
    return page("AI API pricing comparison: Firecrawl, ElevenLabs, Deepgram, Novita, DigitalOcean",
                "".join(body),
                desc=(f"Unit prices for Firecrawl credits, ElevenLabs characters and Deepgram minutes, "
                      f"read {d['as_of']} from each vendor's own page, with a diff when a price moves."))


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
    unit_short = ("minute of speech (STT, Voice Agent)" if vid == "deepgram"
                  else v["unit"].split(" (")[0])
    return page(f"{v['name']} pricing — dated unit prices", "".join(body),
                desc=(f"{v['name']} prices per {unit_short}, read {d['as_of']} from the vendor's own "
                      f"page, with the traps its plan table does not print."))


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
    ET.SubElement(ch, "title").text = "API price changes — Firecrawl, ElevenLabs, Deepgram"
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


def render_voices(d):
    """The creator's page: how many finished minutes a plan buys, and what a minute costs.

    A voice maker asks in minutes; every vendor prices in characters. This page does the conversion at
    the vendor's own basis (1,000 chars/min, from the '~75 min' column on the ElevenLabs page) and then
    shows the thing the plan table hides: plans are sold in fixed blocks, so a workload just over a block
    boundary pays for a whole extra block.
    """
    el, dg = d["vendors"]["elevenlabs"], d["vendors"]["deepgram"]
    cpm = el["vendor_minutes_basis"]
    # run 139: the workload table and the per-minute table were computed on the vendor's 1,000-character
    # column while the page's own prose warned that real delivery is about 900 characters a minute. That
    # overstates the characters a given duration needs by 11.1% and can push a reader a block up the ladder
    # (300 finished minutes: 270,000 characters = Creator $22 at 900, 300,000 = Pro $99 at 1,000). Every
    # workload figure below is now computed at `wb`, the rate the page states it uses.
    wb = el["chars_per_minute_default"]
    rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]
    body = [f"<h1>TTS pricing comparison: how many finished minutes a plan buys</h1>",
            f"<p class=\"meta\">Plans and prices read from "
            f"<a href=\"{esc(el['plan_source'])}\">{esc(el['plan_source'])}</a> on "
            f"{esc(el['plan_verified'])}. Dataset {esc(d['as_of'])}.</p>",
            f"<div class=\"disc\">{AFF_SENTENCE}<br>{esc(AI_LINE)} Every figure is computed from the "
            f"vendors' own unit prices; the arithmetic is printed so you can check it.</div>"]

    body.append("<h2>Why this page exists</h2>")
    body.append("<p>If you make audio — a podcast, an audiobook, a course, a YouTube voice-over — your "
                "question is <em>how many minutes do I get</em>. Every vendor answers in <strong>characters</strong>, "
                "and the conversion is printed once in small grey text. ElevenLabs' own table says "
                f"<code>75,000 ~75 min</code> and <code>12,375,000 ~12,375 min</code>, i.e. it divides characters "
                f"by {cpm:,}. That number is the whole answer: at {wb:,} characters a minute — the basis every "
                f"figure below uses — the same allowance buys {1000/wb*100-100:.1f}% more finished minutes "
                f"than that column claims.</p>")

    body.append(f"<h2>What each workload needs, and what it costs</h2>")
    body.append(f"<table><tr><th>Finished minutes / month</th><th>Characters needed at {wb:,}/min</th>"
                "<th>Cheapest ElevenLabs plan that covers it</th><th>$/month</th>"
                "<th>Effective $ per finished minute</th><th>The per-character rate alone would be</th></tr>")
    for minutes in (60, 180, 300, 600, 1200, 2400, 6000):
        chars = minutes * wb
        cov = next((p for p in el["ladder"] if p["chars"] >= chars), None)
        linear = chars / 1000 * rate
        if cov:
            eff = cov["usd"] / minutes
            body.append(f"<tr><td class=\"num\">{minutes:,}</td><td class=\"num\">{chars:,}</td>"
                        f"<td>{esc(cov['name'])} ({cov['chars']:,} chars ≈ {el_minutes(cov['chars'], wb):,.0f} min)</td>"
                        f"<td class=\"num\">${cov['usd']:,}</td>"
                        f"<td class=\"num\">${eff:.4f}</td><td class=\"num\">${linear:.2f}</td></tr>")
        else:
            body.append(f"<tr><td class=\"num\">{minutes:,}</td><td class=\"num\">{chars:,}</td>"
                        f"<td>None — the top plan includes {el['ladder'][-1]['chars']:,} chars</td>"
                        f"<td class=\"num\">ask sales</td><td class=\"num\">—</td>"
                        f"<td class=\"num\">${linear:.2f}</td></tr>")
    body.append("</table>")
    body.append("<p><strong>Read the last two columns together.</strong> Every paid block on this ladder costs "
                "about <strong>$1 per 12,500 characters</strong> ($0.08 per 1,000), so there is no volume "
                "discount to wait for — but the blocks are fixed, and you cannot buy a top-up. A workload "
                "that lands just over a block boundary buys the next whole block: 600 minutes needs "
                f"{(600*wb):,} characters, which is ${600*wb/1000*rate:,.2f} of arithmetic and a "
                "<strong>$99</strong> plan. That is the only real pricing decision on the page, and the plan "
                "table does not show it.</p>")
    cov306 = next(p for p in el["ladder"] if p["usd"] == 99)
    brim = el["ladder"][[p["usd"] for p in el["ladder"]].index(99) - 1]["chars"]
    body.append("<p><strong>The cliff is wide enough to change what you write.</strong> Creator's allowance "
                f"stops at {brim:,} characters, which is {el_minutes(brim, wb):,.1f} finished minutes at "
                f"{wb:,} characters a minute; the next block does not stop until "
                f"{el_minutes(cov306['chars'], wb):,.1f}. So minute {el_minutes(brim, wb)+1:,.0f} costs "
                f"<strong>${cov306['usd'] - 22:,}</strong> on its own — the same audio, one minute longer, "
                f"{cov306['usd']/22:.1f}x the bill. If your month lands in that band, either use the headroom "
                "or trim the script: a few characters off the boundary is the only discount on this "
                "ladder.</p>")

    body.append("<h2>What one finished minute costs, by engine</h2>")
    body.append(f"<p class=\"meta\">Per-character rate × {wb:,} characters per minute. Rates: ElevenLabs "
                f"{esc(el['source'])}, Deepgram {esc(dg['source'])}.</p>")
    rows = [
        ("ElevenLabs", "v4 (default)", el["rates_usd_per_1000_chars"]["multilingual_v4_api"]),
        ("ElevenLabs", "v4 Turbo / Flash", el["rates_usd_per_1000_chars"]["turbo_flash_api"]),
        ("Deepgram", "Aura-2", dg["tts_usd_per_1000_chars"]["aura_2_payg"]),
        ("Deepgram", "Aura-1", dg["tts_usd_per_1000_chars"]["aura_1_payg"]),
        ("Deepgram", "Flux TTS", dg["tts_usd_per_1000_chars"]["flux_tts_payg"]),
    ]
    rows.sort(key=lambda r: r[2])
    body.append("<table><tr><th>Engine</th><th>USD per 1,000 characters</th><th>USD per finished minute</th>"
                "<th>Cost of 10 hours (600 min)</th></tr>")
    for vendor, engine, r in rows:
        body.append(f"<tr><td>{esc(vendor)} {esc(engine)}</td><td class=\"num\">${r:.3f}</td>"
                    f"<td class=\"num\">${r/1000*wb:.4f}</td><td class=\"num\">${r/1000*wb*600:.2f}</td></tr>")
    body.append("</table>")
    body.append("<p>The cheapest engine for plain narration is not the one with a commission on this page — "
                "Deepgram Aura-1 is "
                f"${dg['tts_usd_per_1000_chars']['aura_1_payg']/1000*wb:.4f} a minute against ElevenLabs v4's "
                f"${el['rates_usd_per_1000_chars']['multilingual_v4_api']/1000*wb:.4f}, a "
                f"{el['rates_usd_per_1000_chars']['multilingual_v4_api']/dg['tts_usd_per_1000_chars']['aura_1_payg']:.1f}x gap. "
                "Whether that is worth it depends on what you need beyond narration (voice cloning, dubbing, "
                "multiple languages, agent hosting wins); on price alone it does not.</p>")

    body.append("<h2>Price it for your own script</h2>")
    body.append("<p>Characters in your script <em>are</em> the input — no estimate needed. If your finished "
                "audio is 43 minutes, paste the script into a character counter, take that number, and read it "
                "against the allowance column above. If you only know the duration, multiply minutes by "
                f"{wb:,} for the table above, or by {cpm:,} if you want the vendor's own column.</p>")
    body.append(f"<p>ElevenLabs plan costs above are list prices: {link_html(el['name'], el['affiliate_link'])}. "
                f"The same page prints first-month promotions (Starter $1, Creator $11 on {esc(d['as_of'])}) — "
                f"those are not prices and the bill reverts after month one.</p>")
    body.append(f"<footer>{esc(AI_LINE)} Computed from <code>dataset.json</code> in this repository by "
                f"<code>voice.py</code> and <code>build_site.py</code>. "
                f"<a href=\"index.html\">Unit price index</a></footer>")
    return page("TTS pricing comparison: what a text-to-speech plan buys in finished minutes",
                "".join(body),
                desc=(f"At 900 characters a minute a speech plan buys 11.1% more finished minutes than its "
                      f"own column claims, and one minute past Creator costs the whole $77 step-up."))


def build(out_dir=None):
    """Render the public index into out_dir (default site/).

    --check passes a scratch dir: a checker must not rewrite the folder it checks. It used to,
    and that replaced a correct SITE_BASE sitemap with the placeholder base.
    """
    root = out_dir or SITE
    d = load()
    snapshot(d)
    changes = compute_changes()
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "vendors"), exist_ok=True)
    written = []
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(d, changes)); written.append("index.html")
    with open(os.path.join(root, "voices.html"), "w", encoding="utf-8") as f:
        f.write(render_voices(d)); written.append("voices.html")
    for vid, v in d["vendors"].items():
        p = os.path.join(root, "vendors", f"{vid}.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(render_vendor(vid, v, d)); written.append(f"vendors/{vid}.html")
    with open(os.path.join(root, "pricing.json"), "w", encoding="utf-8") as f:
        f.write(render_pricing_json(d)); written.append("pricing.json")
    with open(os.path.join(root, "changes.json"), "w", encoding="utf-8") as f:
        json.dump({"as_of": d["as_of"], "history": changes}, f, indent=1); written.append("changes.json")
    with open(os.path.join(root, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(render_feed(d, changes)); written.append("feed.xml")
    # site/ is rebuilt from scratch above, so re-render the host-ready layer (q/*.html, sitemap.xml,
    # robots.txt) here: otherwise a plain `build_site.py` would delete the pages the host serves.
    try:
        import build_host
        written.extend(build_host.build(root)[0])
    except Exception as e:  # a broken host layer must not silently vanish from the deployed folder
        raise SystemExit(f"build_site: host-ready layer failed: {e}")
    return written, d


def check():
    """Invariants the operator review implies: disclosure, labelled links, parseable feeds, age warning."""
    scratch = tempfile.mkdtemp(prefix="sitecheck-")
    try:
        written, d = build(scratch)
        return _check_in(scratch, written, d)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _check_in(S, written, d):
    failures = []
    html = {p: open(os.path.join(S, p), encoding="utf-8").read() for p in written if p.endswith(".html")}
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
    # run 177: every affiliate anchor says where the click lands (the approved links cannot be
    # deep-linked; digitalocean.com's home page has 0 "$" strings vs 41 on /pricing)
    NOTE_FOR = (("firecrawl.link", "Alexandria"), ("try.elevenlabs.io", "elevenlabs.io"),
                ("m.do.co", "digitalocean.com"), ("novita.ai", "novita.ai"))
    for p, t in html.items():
        for m in re.finditer(r'<a href="(https://(?:firecrawl\.link|try\.elevenlabs\.io|m\.do\.co|novita\.ai)[^"]*)"\s+rel="sponsored[^"]*"[^>]*>', t):
            tail = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t[m.end():m.end() + 600]))
            want = next((k for dom, k in NOTE_FOR if dom in m.group(1)), None)
            if want is None:
                failures.append(f"{p}: affiliate href to an unrecognised host: {m.group(1)}")
            elif want not in tail[:260]:
                failures.append(f"{p}: affiliate anchor does not say where it lands (expected {want!r})")
    # run 85: the SERP snippet layer. One description per page, 110-158 chars, a number in it, never the
    # title repeated, and every number in the description already visible on that page.
    # run 131: a literal backslash before a quote in an attribute (the `<p class=\"lede\">` defect)
    # parses as a different class name. Two pages shipped like that; this makes it a check failure.
    for p, t in html.items():
        if '\\"' in t:
            failures.append(f"{p}: contains a literal backslash before a quote (attribute will not parse)")
    seen = {}
    for p, t in html.items():
        m = re.search(r'<meta name="description" content="([^"]*)"', t)
        if not m:
            failures.append(f"{p}: no meta description")
            continue
        dsc = html_lib.unescape(m.group(1))
        if not 110 <= len(dsc) <= 158:
            failures.append(f"{p}: description is {len(dsc)} chars, outside the measured 110-158 band")
        if not re.search(r"\d", dsc):
            failures.append(f"{p}: description carries no number")
        ti = re.search(r"<title>(.*?)</title>", t)
        if ti and dsc.lower().startswith(html_lib.unescape(ti.group(1)).lower()[:20]):
            failures.append(f"{p}: description repeats the title's opening")
        if dsc in seen:
            failures.append(f"{p}: description duplicates {seen[dsc]}")
        seen[dsc] = p
        body_text = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", t)))
        # Run 123: the pattern captures the comma after a figure ("$5, expiring" -> "$5,"),
        # which made any description with a comma straight after a number impossible to pass.
        for num in {n.rstrip(",") for n in re.findall(r"\$?\d[\d,]*(?:\.\d+)?", dsc)}:
            if num not in body_text:
                failures.append(f"{p}: description number {num} is not visible in the page body")
    # feed parses
    try:
        root = ET.parse(os.path.join(S, "feed.xml")).getroot()
        if root.tag != "rss" or root.find("channel/item") is None:
            failures.append("feed.xml: no items")
    except Exception as e:
        failures.append(f"feed.xml: does not parse: {e}")
    # pricing.json parses and its as_of matches the dataset
    pj = json.load(open(os.path.join(S, "pricing.json"), encoding="utf-8"))
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
        print(f"rendered {len(written)} files in a scratch dir, site/ untouched")
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
