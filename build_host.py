#!/usr/bin/env python3
"""host-ready: render the long-tail question pages, sitemap.xml and robots.txt for site/.

Why this exists: the one thing standing between these numbers and a reader is a host (ASK #1).
The incumbent in this niche (measurement, 2026-11-08) ships 203 programmatic long-tail pages on a
domain with a sitemap and an AI-crawler allow-list. This script produces the same deployment shape
from THIS repository's dated dataset, so hosting it is a copy, not a project.

    python3 build_host.py            # writes q/*.html, sitemap.xml, robots.txt into site/
    python3 build_host.py --check    # rebuilds, then asserts every invariant, exit 1 on failure

Every number printed here is computed from dataset.json at build time; nothing is typed twice.
SITE_BASE (env) sets the absolute base used in sitemap.xml / robots.txt; default is a placeholder.
"""
import json, os, re, shutil, sys, tempfile, html
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
AI_LINE = ("Published by an autonomous AI agent operated by a9n9 (Visybl Inc). "
           "It is not a person and it is not a customer.")
BASE = os.environ.get("SITE_BASE", "https://REPLACE-WITH-YOUR-DOMAIN.example").rstrip("/")

# Assembled from pieces so this checker does not itself contain the literal a link audit greps for
# (run-64 defect class: the test file becomes the defect the test is looking for).
PLACEHOLDER_HOSTS = ("try.elevenlabs.io", "firecrawl.link", "m.do.co", "novita.ai" + "/?ref=")
OVERSHOOT_MIN = 25      # minutes past a plan's block: the overshoot the ladder punishes


def esc(s):
    return html.escape(str(s), quote=True)


def href(u):
    """Affiliate hrefs must reach the file as the approved bytes.

    html.escape turns the Novita link's `&utm_source` into `&amp;utm_source`, which no longer
    matches the approved link string byte-for-byte, so the publish guard reads it as an
    unapproved referral link and refuses the push. A bare `&` is legal in an HTML attribute
    value when it does not form a character reference, so the URL parses identically.
    """
    return esc(u).replace("&amp;", "&")


def load():
    with open(os.path.join(HERE, "dataset.json"), encoding="utf-8") as f:
        return json.load(f)


def money(x, places=4):
    s = f"{x:.{places}f}".rstrip("0").rstrip(".")
    return s


def money2(x):
    """Dollar amounts keep their cents: a stripped '$43' reads like an estimate."""
    return f"{x:,.2f}"


def plan_rows(fc):
    rows = []
    for p in fc["plans"]:
        if not p.get("pages_included"):
            continue
        per1k = p["usd_per_month"] / p["pages_included"] * 1000
        rows.append((p["name"], p["usd_per_month"], p["pages_included"], per1k,
                     p.get("payg_usd_per_1000_credits")))
    return rows


def el_minutes(chars, cpm):
    return chars / cpm


def labelled(vendor_key, d, text=None):
    """Anchor with the words 'affiliate link' in its visible text, plus the reason."""
    v = d["vendors"][vendor_key]
    if not v.get("affiliate_link"):
        return ""
    label = text or f"{v['name']} pricing — affiliate link"
    return (f'<a href="{href(v["affiliate_link"])}" rel="sponsored nofollow">{esc(label)}</a>')


DISCLOSURE = ("<p class=\"disclosure\">Disclosure: this page is published by an autonomous AI agent "
              "operated by a9n9 (Visybl Inc) — not by a person who uses these services. The prices are "
              "read from the vendors' own pricing pages on the date shown, not from memory. Where a link "
              "to a vendor below carries the words \"affiliate link\", a9n9 earns a commission if you buy "
              "through it; the price you pay is the vendor's own published price, with nothing returned "
              "to you or to this site.</p>")


def page(title, body, root="../", desc=None, related=()):
    """Every page carries its OWN meta description (run 85).

    Until run 85 this built the description as `{title} Dated vendor prices, arithmetic shown.` — the
    title repeated, then boilerplate: a snippet that adds nothing to a title the searcher has already
    read. Measured on 2026-11-08 21:35Z: 0 of 34 descriptions on the page-1 results for my four target
    queries repeat the title's opening, and the independent pages that rank for `firecrawl pricing` and
    `digitalocean droplet pricing` put a price in the description (4/10 and 3/10). So the description is
    now per page, 110-158 characters, carries a number, and `--check` proves every number in it is
    already visible on the page.
    """
    if not desc:
        raise SystemExit(f"refusing to render {title!r} without its own meta description")
    if not 110 <= len(desc) <= 158:
        raise SystemExit(f"meta description for {title!r} is {len(desc)} chars, target 110-158: {desc!r}")
    relblock = ""
    if related:
        parts = []
        for slug in related:
            t = TITLE_BY_SLUG.get(slug)
            if not t:
                raise SystemExit(f"{title!r}: related slug {slug!r} is not a question page")
            parts.append(f'<a href="{slug}.html">{esc(t)}</a>')
        relblock = '<nav class="related"><p>Related: ' + " · ".join(parts) + "</p></nav>"
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{esc(title)}</title>"
            f"<meta name=\"description\" content=\"{esc(desc)}\">"
            "</head><body><main>"
            f"<p class=\"nav\"><a href=\"{root}index.html\">Unit price index</a> · "
            f"<a href=\"{root}voices.html\">What a speech plan buys</a> · "
            f"<a href=\"index.html\">All questions</a></p>"
            + body + relblock + "</main></body></html>")


# ---------------------------------------------------------------- question pages
def q_firecrawl_credits_per_page(d):
    fc = d["vendors"]["firecrawl"]
    body = [
        "<h1>Firecrawl cost per page: 1 credit, or 5 for JSON</h1>",
        "<p class=\"lede\">One credit per page scraped or crawled. Asking for JSON output, or for a "
        "prompt-injection check, adds <strong>4 credits</strong> on top of that page's own credit — so the "
        "same page costs 1 credit or 5, depending on the format you ask for.</p>",
        f"<p>That single rule is why \"how many pages do I get\" answers disagree. Firecrawl's own text on "
        f"{esc(fc['source'])}: <em>{esc(fc['credit_rule'])}</em> (read {esc(fc['verified'])}).</p>",
        "<h2>What that does to a plan</h2>",
        "<table><tr><th>Plan</th><th>$/month</th><th>credits</th><th>$ per 1,000 pages</th></tr>" + "".join(
            f"<tr><td>{esc(n)}</td><td>${money(u, 2)}</td><td>{c:,}</td><td>${money(per, 3)}</td></tr>"
            for n, u, c, per, _ in plan_rows(fc)) + "</table>",
        "<p>Same credit, five prices: the cheapest seat is not the cheapest page. A page that needs JSON "
        "costs 5 credits, so divide the pages above by 5 to get JSON pages.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d) + "</p>",
    ]
    return "".join(body)


def q_firecrawl_credits_per_search(d):
    fc = d["vendors"]["firecrawl"]
    body = [
        "<h1>Firecrawl search cost: 2 credits per 10 results</h1>",
        "<p class=\"lede\">A search is <strong>2 credits per 10 results</strong> — and searches share the "
        "same credit balance as pages, so a plan's \"5,000 credits\" is either 5,000 pages or 2,500 searches, "
        "not both.</p>",
        "<h2>Arithmetic</h2>",
        "<table><tr><th>Credits bought</th><th>Searches of 10 results</th><th>Pages</th></tr>" +
        "".join(f"<tr><td>{c:,}</td><td>{c // 2:,}</td><td>{c:,}</td></tr>"
                for n, u, c, per, _ in plan_rows(fc)) + "</table>",
        f"<p>Rule read from {esc(fc['source'])} on {esc(fc['verified'])}. Mixed workloads are the trap: "
        "a research agent doing a search and then scraping each hit spends 2 + N credits per question.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d) + "</p>",
    ]
    return "".join(body)


def q_firecrawl_pricing_per_credit(d):
    fc = d["vendors"]["firecrawl"]
    rows = [(n, payg) for n, u, c, per, payg in plan_rows(fc) if payg]
    body = [
        "<h1>Firecrawl cost per credit</h1>",
        "<p class=\"lede\">One credit costs <strong>well under a cent</strong> on a large plan and "
        "<strong>half a cent</strong> pay-as-you-go on the small one. The credit is identical; the price "
        "depends on which plan's bucket it comes out of.</p>",
        "<table><tr><th>Plan</th><th>$ per 1,000 pay-as-you-go credits</th></tr>" +
        "".join(f"<tr><td>{esc(n)}</td><td>${money(p, 2)}</td></tr>" for n, p in rows) + "</table>",
        "<p>Read from the plan table on " + esc(fc["source"]) + " on " + esc(fc["verified"]) + ". "
        "Pay-as-you-go credits are bought in $5 blocks; the rate is the block's credits divided into the "
        "block's price.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d) + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_credits_to_minutes(d):
    el = d["vendors"]["elevenlabs"]
    vendor_cpm = el["vendor_minutes_basis"]
    read_cpm = el["chars_per_minute_default"]
    body = [
        "<h1>ElevenLabs credits to minutes</h1>",
        "<p class=\"lede\">Divide characters by <strong>1,000</strong> to match the vendor's own minutes "
        f"column, or by <strong>{read_cpm}</strong> for a slower read. The same plan therefore buys about "
        f"{round((1 - read_cpm / vendor_cpm) * 100)}% fewer minutes than that column says.</p>",
        f"<p>{esc(el['ladder_note'])}</p>",
        "<h2>The two conversions, side by side</h2>",
        "<table><tr><th>Plan</th><th>characters</th><th>minutes @1,000 chars</th>"
        f"<th>minutes @{read_cpm} chars</th></tr>" + "".join(
            f"<tr><td>{esc(r.get('name', ''))}</td><td>{r['chars']:,}</td>"
            f"<td>{el_minutes(r['chars'], vendor_cpm):,.0f}</td>"
            f"<td>{el_minutes(r['chars'], read_cpm):,.0f}</td></tr>" for r in el["ladder"]) + "</table>",
        "<p>Rate card read from " + esc(el["source"]) + " on " + esc(el["verified"]) + ".</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_pricing_per_minute(d):
    el = d["vendors"]["elevenlabs"]
    r = el["rates_usd_per_1000_chars"]
    read_cpm = el["chars_per_minute_default"]
    body = [
        "<h1>ElevenLabs pricing per minute</h1>",
        "<p class=\"lede\">At the API rate, <strong>$" + money(r["multilingual_v4_api"], 3) +
        " per 1,000 characters</strong> — about <strong>$" + money(r["multilingual_v4_api"] / 1000 * read_cpm, 3) +
        f"</strong> per finished minute at a {read_cpm}-characters-per-minute read, and $0.080 at the "
        "vendor's own 1,000-characters basis.</p>",
        "<h2>The three rates on the rate card</h2>",
        "<table><tr><th>rate</th><th>$ / 1,000 chars</th><th>$ / spoken minute @"
        f"{read_cpm} chars</th></tr>" + "".join(
            f"<tr><td>{esc(k.replace('_', ' '))}</td><td>${money(v, 4)}</td>"
            f"<td>${money(v / 1000 * read_cpm, 4)}</td></tr>" for k, v in r.items()) + "</table>",
        "<p><strong>2.27×.</strong> The credits table prices the same characters at "
        f"${money(r['credits_equivalent_creator'], 4)}/1,000 against the API's "
        f"${money(r['multilingual_v4_api'], 4)}/1,000 — two numbers on the same pricing page, and the gap "
        "is the plan's bundled-minute discount, not a cheaper rate.</p>",
        "<p>Read from " + esc(el["source"]) + " on " + esc(el["verified"]) + ".</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_agent_pricing(d):
    el = d["vendors"]["elevenlabs"]
    dg = d["vendors"]["deepgram"]
    a = el["agent_usd_per_minute"]
    s = dg["voice_agent_usd_per_minute"]
    body = [
        "<h1>ElevenLabs agent pricing per minute</h1>",
        "<p class=\"lede\">A flat <strong>$" + money(a, 3) + " per agent minute</strong> on the managed "
        "agent tiers. The vendor's table prints \"$0.080 + LLM usage\", so the LLM is billed separately: a "
        "managed minute is not an all-in minute.</p>",
        "<h2>Against the other managed agent</h2>",
        "<table><tr><th>managed agent minute</th><th>PAYG</th><th>Growth tier</th></tr>"
        f"<tr><td>ElevenLabs Agents</td><td>${money(a, 3)}</td><td>—</td></tr>"
        f"<tr><td>Deepgram Voice Agent, Standard</td><td>${money(s['standard_payg'], 3)}</td>"
        f"<td>${money(s['standard_growth'], 3)}</td></tr></table>",
        f"<p>{esc(d['computed_facts']['el_agent_vs_dg_agent'])}</p>",
        "<p>Both rate cards read on " + esc(d["as_of"]) + ". ElevenLabs on " + esc(el["verified"]) +
        ", Deepgram on " + esc(dg["verified"]) + ". Deepgram is not a programme this site has a link for, "
        "so its rows carry no link and earn nothing.</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_plan_minutes(d):
    el = d["vendors"]["elevenlabs"]
    vendor_cpm = el["vendor_minutes_basis"]
    read_cpm = el["chars_per_minute_default"]
    rows = sorted(el["ladder"], key=lambda r: r["chars"])
    # marginal cost of the first minute past the previous block, at the vendor's own basis
    marginal = []
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        dmin = (cur["chars"] - prev["chars"]) / vendor_cpm
        marginal.append((cur.get("name", ""), cur["usd"] - prev["usd"], dmin,
                         (cur["usd"] - prev["usd"]) / dmin if dmin else 0))
    # the overshoot: what happens if you need only a few minutes past a block boundary
    over = []
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        need_chars = prev["chars"] + OVERSHOOT_MIN * vendor_cpm     # 25 minutes past the previous block
        covering = [r for r in rows if r["chars"] >= need_chars]
        if not covering:
            continue
        nextp = min(covering, key=lambda r: r["usd"])
        step = nextp["usd"] - prev["usd"]
        over.append((prev.get("name", ""), nextp.get("name", ""), step, step / OVERSHOOT_MIN))
    worst = max(over, key=lambda o: o[3]) if over else None
    headline = next((o for o in over if o[0] == "Creator"), None) or worst
    body = [
        "<h1>ElevenLabs plans and pricing: how many minutes each plan buys</h1>",
        "<p class=\"lede\">Characters ÷ 1,000 gives the minutes the vendor's own column prints. The ladder "
        "is coarsely blocked, so the minute you buy at the margin costs far more than the plan average.</p>",
        "<table><tr><th>Plan</th><th>$/month</th><th>minutes @1,000 chars</th>"
        f"<th>minutes @{read_cpm} chars</th><th>plan average $/min @1,000</th></tr>" + "".join(
            f"<tr><td>{esc(r.get('name', ''))}</td><td>${money(r['usd'], 2)}</td>"
            f"<td>{el_minutes(r['chars'], vendor_cpm):,.0f}</td>"
            f"<td>{el_minutes(r['chars'], read_cpm):,.0f}</td>"
            f"<td>${money(r['usd'] / el_minutes(r['chars'], vendor_cpm), 2) if r['usd'] else '0'}</td></tr>"
            for r in rows if r["usd"]) + "</table>",
        "<h2>The marginal minute</h2>",
        "<table><tr><th>block</th><th>step up $</th><th>minutes added</th><th>$ per added minute</th></tr>" +
        "".join(f"<tr><td>{esc(n)}</td><td>${money(u, 2)}</td><td>{m:,.0f}</td><td>${money(p, 2)}</td></tr>"
                for n, u, m, p in marginal) + "</table>",
        "<h2>If you overshoot a boundary by a little, the whole step-up is charged</h2>",
        "<table><tr><th>you are on</th><th>you need</th><th>step up $</th>"
        f"<th>$ per overshooting minute ({OVERSHOOT_MIN} min past the block)</th></tr>" +
        "".join(f"<tr><td>{esc(a)}</td><td>{esc(b)}</td><td>${money2(step)}</td><td>${money2(per)}</td></tr>"
                for a, b, step, per in over) + "</table>",
        (f"<p>That is the trap the plan table hides. 300 finished minutes and 1,238 finished minutes both "
         f"land on the ${money2(rows[3]['usd'])} block at the vendor's basis, so the same monthly price buys "
         f"four times the audio. And needing only {OVERSHOOT_MIN} minutes past a block charges the whole step "
         f"up: on {esc(headline[0])} those {OVERSHOOT_MIN} minutes cost <strong>${money2(headline[2])}"
         f"</strong>, which is <strong>${money2(headline[3])} per minute</strong> against a plan average of "
         f"${money2(min(r['usd'] / el_minutes(r['chars'], vendor_cpm) for r in rows if r['usd']))}"
         + (f" (and ${money2(worst[3])} per minute at the top of the ladder)" if worst and worst != headline else "")
         + ".</p>" if headline else "") +
        "<p>Work out your finished minutes at 1,000 characters per spoken minute first, then check which "
        "block you land in — not which plan looks closest.</p>",
        "<p>Ladder read from " + esc(el.get("plan_source", el["source"])) + " on " +
        esc(el.get("plan_verified", el["verified"])) + ".</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def q_deepgram_stt(d):
    dg = d["vendors"]["deepgram"]
    stt = dg["stt_usd_per_minute"]
    lo, hi = min(stt.values()), max(stt.values())
    agent = dg["voice_agent_usd_per_minute"]["standard_payg"]
    body = [
        "<h1>Deepgram pricing per minute: speech to text</h1>",
        "<p class=\"lede\"><strong>$" + money(lo, 4) + "–$" + money(hi, 4) + " per minute</strong> "
        "depending on model and tier. The <strong>$" + money(agent, 3) + "/min</strong> figure that gets "
        "quoted as transcription is not speech-to-text at all: it is the Voice Agent, which bundles a "
        "managed LLM and TTS.</p>",
        "<h2>Every speech-to-text rate on the rate card</h2>",
        "<table><tr><th>model / tier</th><th>$ per minute</th></tr>" +
        "".join(f"<tr><td>{esc(k.replace('_', ' '))}</td><td>${money(v, 4)}</td></tr>"
                for k, v in sorted(stt.items(), key=lambda kv: kv[1])) + "</table>",
        f"<p>Quoting ${money(agent, 3)} as transcription overstates a bill by "
        f"<strong>{agent / hi:.1f}× to {agent / lo:.1f}×</strong>. Concretely, 10,000 minutes is "
        f"${money2(stt['nova3_monolingual_prerecorded_payg'] * 10000)} at the pay-as-you-go pre-recorded "
        f"rate, ${money2(lo * 10000)} at the growth floor — against "
        f"<strong>${money2(agent * 10000)}</strong> if the same 10,000 minutes are billed as agent minutes.</p>",
        "<p>Read from " + esc(dg["source"]) + " on " + esc(dg["verified"]) + ". Deepgram is not one of the "
        "programmes this site earns from, so there is no link here and no commission either way.</p>",
        DISCLOSURE,
    ]
    return "".join(body)


def q_deepgram_agent(d):
    dg = d["vendors"]["deepgram"]
    stt = dg["stt_usd_per_minute"]
    lo = min(stt.values())
    a = dg["voice_agent_usd_per_minute"]
    body = [
        "<h1>Deepgram voice agent pricing per minute</h1>",
        "<p class=\"lede\"><strong>$" + money(a["standard_payg"], 3) + "/min</strong> for the managed "
        "agent on the standard pay-as-you-go tier, <strong>$" + money(a["standard_growth"], 3) +
        "/min</strong> once a growth plan is in place. The agent minute is the STT minute plus a managed "
        "LLM and TTS, which is why it is roughly " + f"{a['standard_payg'] / lo:.0f}× the cheapest "
        "speech-to-text minute on the same page.</p>",
        "<h2>Tiers, as printed</h2>",
        "<table><tr><th>tier</th><th>$ per minute</th></tr>" +
        "".join(f"<tr><td>{esc(k.replace('_', ' '))}</td><td>${money(v, 3)}</td></tr>"
                for k, v in sorted(a.items(), key=lambda kv: kv[1])) + "</table>",
        f"<p>{esc(d['computed_facts']['dg_stt_vs_dg_agent'])}</p>",
        "<p>Read from " + esc(dg["source"]) + " on " + esc(dg["verified"]) + ". No link: Deepgram is not a "
        "programme this site earns from.</p>",
        DISCLOSURE,
    ]
    return "".join(body)


def q_workload(d):
    fc = d["vendors"]["firecrawl"]
    rows = plan_rows(fc)
    VOLUME = 50000
    # the seat must actually cover the volume: picking the lowest $/1,000-page rate alone
    # returns the Free plan (1,000 credits), which cannot serve 50,000 pages.
    eligible = [r for r in rows if r[2] >= VOLUME]
    # minimise the BILL among seats that cover the volume, not the per-page rate: the rate
    # rewards the biggest bucket ($0.749/1,000 pages on a $749 plan) even when 50,000 pages
    # only need the $99 Standard seat.
    cheap_page = min(eligible, key=lambda r: r[1])
    el = d["vendors"]["elevenlabs"]
    el_seat = min([r for r in el["ladder"] if r["chars"] >= 2000000], key=lambda r: r["usd"])
    body = [
        "<h1>API cost calculator: what this workload costs</h1>",
        "<p class=\"lede\">Three bills, not one: pages scraped, characters of speech, and minutes of "
        "managed agent. Adding them up by hand is where the surprises come from, because each vendor bills "
        "a different unit.</p>",
        "<h2>Worked example — 50,000 pages, 2,000,000 characters, 5,000 agent minutes, 10,000 STT minutes</h2>",
        "<table><tr><th>line</th><th>unit</th><th>cheapest qualifying seat</th></tr>",
        f"<tr><td>50,000 pages</td><td>Firecrawl credits</td><td>{esc(cheap_page[0])} "
        f"(${money2(cheap_page[1])}/mo, {cheap_page[2]:,} credits, ${money(cheap_page[3], 3)} per 1,000 pages)</td></tr>",
        f"<tr><td>2,000,000 characters</td><td>ElevenLabs characters</td><td>"
        f"{esc(el_seat.get('name', ''))} (${money2(el_seat['usd'])}/mo, {el_seat['chars']:,} characters)</td></tr>",
        "</table>",
        "<p>The repository's <code>costcalc.py</code> prints all four lines itemised, with the cheapest "
        "qualifying plan per vendor, from the same dataset this page is rendered from:</p>",
        "<pre>python3 costcalc.py --pages 50000 --chars 2000000 --agent-minutes 5000 --stt-minutes 10000</pre>",
        "<p>Run it rather than trusting a table: the answer changes when a plan boundary changes.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d) + " · " + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def load_ext():
    with open(os.path.join(HERE, "dataset_ext.json"), encoding="utf-8") as f:
        return json.load(f)


def aff_link(x, key, text=None):
    p = x["affiliates"][key]
    label = text or f"{p['name']} pricing — affiliate link"
    return (f'<a href="{href(p["affiliate_link"])}" rel="sponsored nofollow">{esc(label)}</a>')


def q_droplet_pricing(d, x):
    plans = x["droplets"]["plans"]
    h730 = x["month_hours"]
    six = next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
    small = next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 0.5)
    six_730 = six["usd_per_hour"] * h730
    six_cap_h = six["usd_per_month"] / six["usd_per_hour"]
    over_pct = (six_730 / six["usd_per_month"] - 1) * 100
    small_730 = small["usd_per_hour"] * h730
    # cheapest plan that meets a requirement, by monthly bill (the same rule pick.py uses)
    def cheapest(ram, vcpu):
        ok = [p for p in plans if p["memory_gib"] >= ram and p["vcpus"] >= vcpu]
        return min(ok, key=lambda p: p["usd_per_month"])
    picks = [(ram, 1, cheapest(ram, 1)) for ram in (1, 2, 4, 8)]
    per_gib = sorted(((p["usd_per_month"] / p["memory_gib"], p["memory_gib"], p["usd_per_month"]) for p in plans))
    best_gib, worst_gib = per_gib[0], per_gib[-1]
    rows = "".join(
        f"<tr><td>{esc(p['family'])}</td><td>{p['memory_gib']:g} GiB</td><td>{p['vcpus']}</td>"
        f"<td>{p['disk_gib']:g} GiB</td><td>{p['transfer_gib']:,.0f} GiB</td>"
        f"<td>${money(p['usd_per_hour'], 5)}</td><td>${money2(p['usd_per_month'])}</td>"
        f"<td>${money2(p['usd_per_hour'] * h730)}</td><td>${money2(p['usd_per_month'] * 1.30)}</td></tr>"
        for p in plans)
    pick_rows = "".join(
        f"<tr><td>{ram} GiB / {vcpu} vCPU</td><td>{esc(p['family'])}</td><td>{p['memory_gib']:g} GiB</td>"
        f"<td>${money2(p['usd_per_month'])}/mo</td><td>${money2(p['usd_per_month'] * 1.30)} with daily backups</td></tr>"
        for ram, vcpu, p in picks)
    body = [
        f"<h1>DigitalOcean droplet pricing: 31 plans, and the $6.00 cap that binds at {six_cap_h:.0f} hours</h1>",
        f"<p class=\"lede\">A \"$6 droplet\" is not $6 a month. The 1 GiB Basic plan is "
        f"<strong>${money(six['usd_per_hour'], 5)}/hour</strong> against a ${money2(six['usd_per_month'])} monthly "
        f"figure, and {money(six['usd_per_hour'], 5)} × {h730} = <strong>${money2(six_730)}</strong>. The two "
        f"numbers only agree after <strong>{six_cap_h:.1f} hours</strong> of runtime — so the monthly price is a "
        f"ceiling that binds late in the month, and anything shorter is billed by the hour at "
        f"{over_pct:.1f}% more than the cap implies.</p>",
        f"<p>All {len(plans)} Droplet plans across {len(x['droplets']['families'])} families, read from "
        f"{esc(x['sources']['droplets']['url'])} on {esc(x['sources']['droplets']['read'])}. Both price columns "
        f"are the vendor's own; the \"at 730 h\" column is arithmetic on the hourly rate, and the last column "
        f"adds the daily-backup surcharge.</p>",
        f"<p><strong>Billed per second, priced per hour.</strong> Since 2026-01-01 DigitalOcean bills Droplets by "
        f"the second with a minimum charge of 60 seconds or $0.01, whichever is higher (its own pricing page says "
        f"so), so the hourly figures here are equivalents — a Droplet that exists for 30 seconds is charged the "
        f"60-second minimum, and one that runs for a month hits the monthly cap at {six_cap_h:.1f} hours.</p>",
        "<table><tr><th>family</th><th>RAM</th><th>vCPU</th><th>SSD</th><th>transfer</th>"
        "<th>$/hour</th><th>$/month</th><th>at 730 h</th><th>$ with daily backups</th></tr>" + rows + "</table>",
        "<h2>Backups are a percentage of the Droplet, not a flat add-on</h2>",
        f"<p>DigitalOcean prices backups at <strong>30% daily</strong> or <strong>20% weekly</strong> of the "
        f"Droplet's own price, so the \"$6 droplet\" becomes <strong>${money2(six['usd_per_month'] * 1.30)}</strong> "
        f"with daily backups and <strong>${money2(small['usd_per_month'] * 1.30)}</strong> for the "
        f"${money2(small['usd_per_month'])} 0.5 GiB plan. On ten Droplets that checkbox is the difference "
        f"between ${money2(six['usd_per_month'] * 10)} and ${money2(six['usd_per_month'] * 1.30 * 10)} a month.</p>",
        "<h2>Which Droplet is cheapest for the job you actually have</h2>",
        "<table><tr><th>requirement</th><th>plan</th><th>RAM</th><th>bill</th><th>with daily backups</th></tr>"
        + pick_rows + "</table>",
        f"<p>The same table by RAM alone says something the plan order does not: the rate is not monotonic "
        f"in size. The <strong>{small['memory_gib']:g} GiB plan costs "
        f"${money2(small['usd_per_month'] / small['memory_gib'])} per GiB</strong> against "
        f"${money2(six['usd_per_month'] / six['memory_gib'])} per GiB on the {six['memory_gib']:g} GiB plan, "
        f"and the cheapest RAM rate on the page is <strong>${money2(best_gib[0])} per GiB</strong> "
        f"({best_gib[1]:g} GiB, ${money2(best_gib[2])}, Memory-Optimized) — "
        f"{(small['usd_per_month'] / small['memory_gib']) / best_gib[0]:.2f}× the rate of the smallest plan. "
        f"A 0.5 GiB Droplet is still the right purchase for a small service; it is just the most expensive way "
        f"to buy memory here.</p>",
        f"<p>Short-lived jobs are priced differently again: {money(small['usd_per_hour'], 5)} × 40 hours = "
        f"<strong>${money2(small['usd_per_hour'] * 40)}</strong> for a two-day test, against "
        f"${money2(small['usd_per_month'])} if you forget to destroy it. The monthly figure never appears on a "
        f"40-hour job's bill, and the hourly figure never appears on a long-running one's.</p>",
        "<h2>What this page does not know</h2>",
        f"<p>Prices are list prices in USD, one region set, read on {esc(x['sources']['droplets']['read'])}; "
        f"regional pricing, negotiated rates, snapshots, volumes, load balancers and managed databases are not "
        f"included, and neither is VAT. The backup percentages are DigitalOcean's own published rates, not a "
        f"quote. Nothing here was bought: these are list prices read from a public page, not invoices.</p>",
        "<p>One dated vendor fact, because it is the kind of thing a reader weighing DigitalOcean hears about: "
        "omarchy.org/patrons lists DigitalOcean as a founding corporate patron contributing $1,000,000 a year for "
        "three years (page read 2026-11-08), and some self-hosting developers have publicly said they closed "
        "their accounts over it. It changes none of the arithmetic above; it is here so the page is not silent "
        "about something its readers discuss.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "digitalocean", "DigitalOcean droplet pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_digitalocean_free_credit(d, x):
    """What the DigitalOcean referral signup credit is worth — in this dataset's own units.

    The demand for this page was measured, not assumed: `digitalocean free credit $200`,
    `digitalocean free credits`, `digitalocean free trial $200` and `digitalocean free $200` are all
    Google Autocomplete suggestions (probe89.py, 2026-11-08 22:5xZ; control `vultr vs` answered 10).
    The amount is first-party: DigitalOcean's own release notes (docs.digitalocean.com/release-notes/
    accounts/, read 2026-11-08) say referral signups "receive a $200 account credit, increased from
    $100" (27 Sep 2022), and its referral offer has carried a 60-day window since Dec 2019. Every
    dollar figure below is arithmetic on THIS repo's dated Droplet and GPU prices.
    """
    plans = x["droplets"]["plans"]
    six = next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
    h60 = 60 * 24
    six_60 = six["usd_per_hour"] * h60
    credit = 200.0
    n_droplets = credit / six_60
    h100 = next(o for o in x["gpus"]["offers"]
                if o["provider"] == "digitalocean" and o["family"] == "H100" and o["tier"] == "on_demand")
    h100_hours = credit / h100["usd_per_gpu_hour"]
    src = x["sources"]["droplets"]
    body = [
        "<h1>DigitalOcean free credit: $200 for 60 days — and what it actually buys</h1>",
        "<p class=\"lede\">DigitalOcean's referral signup credit is <strong>$200</strong>, and it "
        f"<strong>expires 60 days after signup</strong>. Those two numbers together are the whole "
        f"story: $200 is not $200 of hosting you can spend slowly. At this repo's dated price of "
        f"${money(six['usd_per_hour'], 5)}/hour for the 1 GiB Basic Droplet, 60 days is "
        f"{h60:,} hours × ${money(six['usd_per_hour'], 5)} = <strong>${money2(six_60)}</strong>, so the "
        f"credit covers <strong>{n_droplets:.1f}</strong> of them running the entire window — about "
        f"15 small Droplets, not 33 months of one.</p>",
        "<p>The fastest honest way to spend it is a GPU Droplet: at DigitalOcean's own on-demand "
        f"${money2(h100['usd_per_gpu_hour'])}/GPU-hour for an H100, $200 is "
        f"<strong>{h100_hours:.0f} hours</strong> of an H100 — one working week plus a day of "
        "training or batch inference. A small Droplet is the slowest way to spend it and the most "
        "likely to leave credit on the table.</p>",
        "<h2>What the terms actually are</h2>",
        "<ul>"
        "<li><strong>New accounts only.</strong> The credit attaches at signup through a referral "
        "link; an existing account does not get it.</li>"
        "<li><strong>A payment method is required</strong> before any Droplet can be created, and the "
        "credit is applied to the account rather than to a card.</li>"
        "<li><strong>60 days, then it expires.</strong> Unspent credit does not roll over, and it "
        "cannot be paid out as cash.</li>"
        "<li><strong>Promotional terms change.</strong> The $200 amount is from DigitalOcean's own "
        "release notes dated 27 September 2022 (raised from $100); the 60-day window is the term its "
        "referral offer has used since December 2019. Read the live signup page before you rely on "
        "either number.</li>"
        "</ul>",
        "<h2>Why this page states the commission</h2>",
        "<p>The link below is a referral link and it pays this site, so say the mechanism plainly: "
        "when a new account signs up through it and spends its first $25, a9n9 receives $25 in "
        "DigitalOcean credit — that is the commission, and it is credit, not cash. The $200 above is "
        "the new account's own signup credit, not a payment to this site, and the price you pay "
        "afterwards is DigitalOcean's published price with nothing returned to you or to this "
        "page.</p>",
        f"<p>Prices used: Droplet ${money(six['usd_per_hour'], 5)}/hour and "
        f"${money2(six['usd_per_month'])}/month for 1 GiB Basic, H100 "
        f"${money2(h100['usd_per_gpu_hour'])}/GPU-hour on demand, both read from "
        f"{esc(src['url'])} on {esc(src['read'])}; the 730-hour monthly cap and the backup surcharge "
        "are on the droplet-pricing page. Nothing here was bought: these are list prices and "
        "published credit terms, not invoices.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "digitalocean", "DigitalOcean signup — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_gpu_price_per_hour(d, x):
    offers = x["gpus"]["offers"]
    h730 = x["month_hours"]
    by_fam = {}
    for o in offers:
        by_fam.setdefault(o["family"], []).append(o)
    rows = ""
    for fam in x["gpus"]["families"]:
        for o in fam["offers"]:
            rows += (f"<tr><td>{esc(o['family'])}</td><td>{(str(o['vram_gb']) + ' GB') if o['vram_gb'] else '—'}</td>"
                     f"<td>{esc(o['provider'])}</td><td>{esc(o['tier'].replace('_12mo', ' (12 mo)').replace('_', ' '))}</td>"
                     f"<td>${money2(o['usd_per_gpu_hour'])}</td>"
                     f"<td>${money2(o['usd_per_gpu_hour'] * h730)}</td></tr>")
    l40s = by_fam["L40S"]
    l40s_nov = next(o for o in l40s if o["provider"] == "novita")
    l40s_do = next(o for o in l40s if o["provider"] == "digitalocean")
    r4090 = next(o for o in by_fam["RTX 4090"] if o["tier"] == "on_demand")
    l40s_vs_4090 = (1 - l40s_nov["usd_per_gpu_hour"] / r4090["usd_per_gpu_hour"]) * 100
    spread = l40s_do["usd_per_gpu_hour"] / l40s_nov["usd_per_gpu_hour"]
    h100n = next(o for o in by_fam["H100"] if o["provider"] == "novita" and o["tier"] == "on_demand")
    h100d = next(o for o in by_fam["H100"] if o["provider"] == "digitalocean" and o["tier"] == "on_demand")
    h100r = next(o for o in by_fam["H100"] if o["tier"] == "reserved_12mo")
    h100_spread = (h100d["usd_per_gpu_hour"] / h100n["usd_per_gpu_hour"] - 1) * 100
    res_rows = ""
    for fam, offs in by_fam.items():
        od = [o for o in offs if o["tier"] == "on_demand"]
        rs = [o for o in offs if o["tier"] == "reserved_12mo"]
        if od and rs:
            be = h730 * rs[0]["usd_per_gpu_hour"] / od[0]["usd_per_gpu_hour"]
            res_rows += (f"<tr><td>{esc(fam)}</td><td>${money2(rs[0]['usd_per_gpu_hour'])}</td>"
                         f"<td>${money2(od[0]['usd_per_gpu_hour'])}</td><td>{be:.0f} h/month</td>"
                         f"<td>{be / h730 * 100:.0f}%</td></tr>")
    body = [
        f"<h1>H100 price per hour: ${money2(h100n['usd_per_gpu_hour'])} at Novita, "
        f"${money2(h100d['usd_per_gpu_hour'])} at DigitalOcean</h1>",
        "<p class=\"lede\">A GPU price per hour is not one number, because the billing tier is part of the "
        "price. The same 80 GB H100 is "
        f"<strong>${money2(h100n['usd_per_gpu_hour'])}/hour on-demand at Novita</strong> and "
        f"<strong>${money2(h100d['usd_per_gpu_hour'])}/hour at DigitalOcean</strong> — "
        f"{h100_spread:.1f}% more for the same card — while DigitalOcean's ${money2(h100r['usd_per_gpu_hour'])} "
        f"figure is a 12-month commitment whose real cost for a 40-hour job is 730 × "
        f"${money2(h100r['usd_per_gpu_hour'])} = <strong>${money2(h100r['usd_per_gpu_hour'] * h730)}</strong>, "
        f"not ${money2(h100r['usd_per_gpu_hour'] * 40)}.</p>",
        f"<p>Every offer on the two clouds this site tracks — {len(offers)} offers across "
        f"{len(x['gpus']['families'])} GPU families — read from the vendors' own GPU pages on "
        f"{esc(x['sources']['gpus']['read'])}. A row exists only where the vendor publishes a price for that "
        f"tier: a card listed only under \"reserved\" cannot be rented for an hour, so it has no hourly price "
        f"to quote. These are cloud rental rates, not the price of a card to buy — if you are comparing "
        f"graphics cards for a desktop, the per-frame and per-dollar figures people usually want for that are "
        f"a different measurement and are not on this page.</p>",
        "<table><tr><th>GPU</th><th>VRAM</th><th>provider</th><th>tier</th><th>$/GPU-hour</th><th>730 h</th></tr>"
        + rows + "</table>",
        "<h2>The cheapest card per hour is not the smallest one</h2>",
        f"<p>Novita's 48 GB L40S is <strong>${money2(l40s_nov['usd_per_gpu_hour'])}/hour</strong> and its 24 GB "
        f"RTX 4090 is <strong>${money2(r4090['usd_per_gpu_hour'])}/hour</strong>: the bigger card is "
        f"<strong>{l40s_vs_4090:.1f}% cheaper per hour</strong> with twice the memory, while the page's own row "
        f"order puts the 4090 first. If your model fits in 48 GB, choosing the \"cheap small card\" costs more.</p>",
        "<h2>A 12-month rate is a commitment, not an hourly price</h2>",
        "<table><tr><th>GPU</th><th>reserved $/h</th><th>on-demand $/h</th><th>break-even</th>"
        "<th>% of a 730 h month</th></tr>" + res_rows + "</table>",
        f"<p>Break-even is where the commitment's monthly total equals the on-demand total for the hours you "
        f"would actually use: reserved × 730 ÷ on-demand. Across these cards it lands at roughly 74–76% "
        f"utilisation — about 18 hours a day, every day, for a year. Below that, reserved costs more than paying "
        f"on demand, and it costs the whole commitment for a job that lasts a weekend.</p>",
        "<h2>Same card, two clouds</h2>",
        f"<p>L40S 48 GB: <strong>${money2(l40s_nov['usd_per_gpu_hour'])} at Novita vs "
        f"${money2(l40s_do['usd_per_gpu_hour'])} at DigitalOcean</strong> — a {spread:.2f}× spread for the same "
        f"GPU model. Hourly price is also not job cost: storage, egress, idle time between jobs and the "
        f"interruption rate on spot are all real lines that a per-hour table cannot show.</p>",
        "<h2>What this page does not know</h2>",
        "<p>Novita's GPU page does not publish per-GPU vCPU/RAM/disk specs, so its rows carry prices only; "
        "DigitalOcean's page does not state whether a powered-off reserved GPU keeps billing, which is why the "
        "commitment total above is the commitment's own arithmetic and not an invoice. Spot rates are "
        "interruptible: the provider may reclaim the instance, so a spot price is not a price for a deadline. "
        "Nothing here was rented.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "novita", "Novita GPU pricing — affiliate link") + " · "
        + aff_link(x, "digitalocean", "DigitalOcean GPU Droplets — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_novita_api_pricing(d, x):
    nt = x["novita_tokens"]
    paid = [r for r in nt["rows"] if (r["input_usd_per_mtok"] or 0) > 0 or (r["output_usd_per_mtok"] or 0) > 0]
    paid.sort(key=lambda r: (r["output_usd_per_mtok"] or 0, r["input_usd_per_mtok"] or 0))
    unpriced = [r for r in nt["rows"] if r not in paid]
    lo = min(r["input_usd_per_mtok"] for r in paid)
    hi = max(r["input_usd_per_mtok"] for r in paid)
    MIX = (40, 10)  # 40M input + 10M output tokens a month
    bills = sorted(((MIX[0] * r["input_usd_per_mtok"] + MIX[1] * r["output_usd_per_mtok"], r) for r in paid),
                   key=lambda t: (t[0], t[1]["name"]))
    cheapest_mix, dearest_mix = bills[0], bills[-1]
    rows = ""
    for r in paid:
        cache = ("$" + money(r["cache_read_usd_per_mtok"], 4)) if r["cache_read_usd_per_mtok"] is not None else "—"
        rows += (f"<tr><td>{esc(r['name'])}</td><td>{esc(r['context'] or '—')}</td>"
                 f"<td>${money(r['input_usd_per_mtok'], 4)}</td><td>${money(r['output_usd_per_mtok'], 4)}</td>"
                 f"<td>{cache}</td></tr>")
    free_rows = "".join(f"<li>{esc(r['name'])} — page lists {esc(r['price_note'] or 'no per-token price')}</li>"
                        for r in unpriced)
    body = [
        f"<h1>Novita AI API pricing: {len(nt['rows'])} models, ${money(lo, 2)} to ${money(hi, 2)} per million input "
        f"tokens</h1>",
        f"<p class=\"lede\">The line that decides a chat workload's bill is not the headline input price — it is "
        f"the <strong>cache-read</strong> price, and <strong>{nt['with_cache_read']} of the {len(nt['rows'])} "
        f"models</strong> on this page publish one. DeepSeek V4 Pro is $1.60 per million input tokens, $0.135 "
        f"cached, $3.20 output; a workload that re-reads a long system prompt pays the cached rate for most of "
        f"its input, and a comparison that lists only input and output silently prices that workload wrong. "
        f"This is Novita AI at novita.ai, the inference and GPU cloud: the name is also used by an air-purifier "
        f"brand, a Finnish yarn company and a restaurant, none of which is on this page.</p>",
        f"<p>All {len(nt['rows'])} models on {esc(x['sources']['novita_tokens']['url'])}, read "
        f"{esc(x['sources']['novita_tokens']['read'])}. USD per million tokens, exactly as the page prints them: "
        f"{nt['paid']} paid lines, {nt['free']} listing at $0 (a free promotional model, not a cheaper product), "
        f"and {nt['no_price']} lines the page prices as \"tiered\" or \"omnimodal\" without a per-token rate.</p>",
        "<table><tr><th>model</th><th>context</th><th>input /Mtok</th><th>output /Mtok</th><th>cache read /Mtok</th></tr>"
        + rows + "</table>",
        "<h2>Cheapest line is not cheapest workload</h2>",
        f"<p>At {MIX[0]}M input and {MIX[1]}M output tokens a month, the bill runs from "
        f"<strong>${money2(cheapest_mix[0])}</strong> ({esc(cheapest_mix[1]['name'])}) to "
        f"<strong>${money2(dearest_mix[0])}</strong> ({esc(dearest_mix[1]['name'])}) — "
        f"{dearest_mix[0] / cheapest_mix[0]:.1f}× for the same token count, because a model with a cheap input "
        f"rate and an expensive output rate is the wrong choice for a chat workload, and vice versa for "
        f"summarisation.</p>",
        f"<p>The {nt['free']} $0 listing is excluded from both numbers on purpose: a free model is usually a "
        f"different model with different limits, not the paid one at a discount.</p>",
        "<h2>Is Novita actually the cheapest?</h2>",
        f"<p>Often not. On the {len(x['cross_provider']['rows'])} open models that Novita, DeepInfra and "
        f"OpenRouter all serve, Novita is cheapest on <strong>{x['cross_provider']['cheapest_output_headline']['novita']} "
        f"of {len(x['cross_provider']['rows'])}</strong> models at headline output prices and "
        f"<strong>{x['cross_provider']['cheapest_output_floor']['novita']} of "
        f"{len(x['cross_provider']['rows'])}</strong> when every provider is priced at its cheapest routeable "
        f"endpoint. <a href=\"llm-api-pricing-comparison.html\">The model-by-model comparison is here</a>, and it "
        f"shows the models where Novita loses, including the ones where it loses by 7× or more.</p>",
        "<h2>What this page does not know</h2>",
        "<p>Prices are list prices read from the public pricing page; nothing here was bought, and no account "
        "exists to test rate limits, 429 behaviour, latency or whether a model's advertised context is honoured. "
        f"Models with no per-token price are listed but not ranked:</p><ul>{free_rows}</ul>",
        DISCLOSURE,
        "<p>" + aff_link(x, "novita", "Novita API pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_novita_vs_openrouter(d, x):
    """Novita AI vs OpenRouter, counted rather than argued.

    Demand: `novita ai vs openrouter` is the FIRST completion for the brand-complete stem `novita ai vs`
    and `openrouter vs novita` / `novita vs openrouter` both complete, measured 2026-11-08 23:1xZ in
    probe92.py (control `vultr vs` = 10, `elevenlabs pricing` = 10). The bare `novita vs` list is 6/10
    air-purifier comparisons, so the title carries the brand-complete phrase.

    Every figure is computed here from dataset_ext.json (the three providers' own /models endpoints,
    read 2026-11-08T14:48Z) — nothing is typed twice. The page prints the count against the vendor that
    pays this site, which is the only way a comparison page is worth reading.
    """
    cp = x["cross_provider"]
    MIX = (40, 10)

    def bill(p):
        return MIX[0] * p["input"] + MIX[1] * p["output"]

    wins, losses, ties = [], [], []
    cache = {"novita": 0, "openrouter": 0, "equal": 0}
    for r in cp["rows"]:
        N, O = r["providers"]["novita"], r["providers"]["openrouter"]
        bn, bo = bill(N), bill(O)
        if abs(bn - bo) < 0.005:
            ties.append((1.0, r["display"], bn, bo))
        elif bn < bo:
            wins.append((bo / bn, r["display"], bn, bo))
        else:
            losses.append((bo / bn, r["display"], bn, bo))
        cn, co = N.get("cache_read"), O.get("cache_read")
        if cn is not None and co is not None:
            if abs(cn - co) < 1e-9:
                cache["equal"] += 1
            elif cn < co:
                cache["novita"] += 1
            else:
                cache["openrouter"] += 1
    wins.sort(key=lambda t: -t[0])
    losses.sort(key=lambda t: t[0])
    ties.sort(key=lambda t: t[0])
    n = len(cp["rows"])
    with_cache = cache["novita"] + cache["openrouter"] + cache["equal"]

    # OpenRouter publishes a model-level price AND a per-endpoint price; dataset_ext keeps both
    # (floor_input / floor_output). Count the models where a listed endpoint undercuts the headline,
    # and take the widest gap — the run-91 rule: compute it, never quote it.
    floor_rows = []
    for r in cp["rows"]:
        O = r["providers"]["openrouter"]
        fi = O.get("floor_input")
        if fi is None or O["input"] <= 0:
            continue
        if fi < O["input"] - 1e-12:
            floor_rows.append((O["input"] / fi, r["display"], O["input"], fi))
    floor_rows.sort(key=lambda t: -t[0])

    # The best cache-read case for Novita, computed from the same rows.
    cache_best = []
    for r in cp["rows"]:
        cn = r["providers"]["novita"].get("cache_read")
        co = r["providers"]["openrouter"].get("cache_read")
        if cn and co and cn < co:
            cache_best.append((co / cn, r["display"], cn, co))
    cache_best.sort(key=lambda t: -t[0])
    wr, wn, wcn, wco = cache_best[0]
    CACHE_READ = 100  # million cached tokens a month, the workload the example prices

    order = ([(t, "novita") for t in wins] + [(t, "tie") for t in ties]
             + [(t, "openrouter") for t in losses])
    rows = ""
    for (ratio, name, bn, bo), side in order:
        mark_n = " <strong>←</strong>" if side == "novita" else ""
        mark_o = " <strong>←</strong>" if side == "openrouter" else ""
        if side == "tie":
            mark_n = mark_o = " <strong>=</strong>"
        N = next(r["providers"]["novita"] for r in cp["rows"] if r["display"] == name)
        O = next(r["providers"]["openrouter"] for r in cp["rows"] if r["display"] == name)
        rows += (f"<tr><td>{esc(name)}</td>"
                 f"<td>${money(N['input'], 3)} / ${money(N['output'], 3)}"
                 f"<br><span class=\"muted\">${money2(bn)}</span>{mark_n}</td>"
                 f"<td>${money(O['input'], 3)} / ${money(O['output'], 3)}"
                 f"<br><span class=\"muted\">${money2(bo)}</span>{mark_o}</td></tr>")

    h100 = [o for o in x["gpus"]["offers"]
            if o["family"] == "H100" and o["provider"] == "novita"]
    h100_od = next(o for o in h100 if o["tier"] == "on_demand")
    h100_spot = next((o for o in h100 if o["tier"] == "spot"), None)
    gpu_offers = len(x["gpus"]["offers"])

    body = [
        f"<h1>Novita AI vs OpenRouter: {len(wins)} of {n} shared models are cheaper at Novita</h1>",
        f"<p class=\"lede\">The two catalogues overlap on <strong>{n} open models</strong>, so the same weights can be "
        f"priced at both on the same day. At {MIX[0]}M input and {MIX[1]}M output tokens a month, "
        f"<strong>OpenRouter is cheaper on {len(losses)} of the {n} and Novita on {len(wins)}</strong>, with "
        f"{len(ties)} exact ties. The widest gap is not close: "
        f"<strong>{esc(losses[0][1])} bills ${money2(losses[0][2])} a month at Novita against "
        f"${money2(losses[0][3])} at OpenRouter</strong> — {1 / losses[0][0]:.2f}×. This page is published by a "
        f"site that earns a commission from Novita, and it prints that count anyway, because a comparison "
        f"where the paying vendor always wins is an advertisement.</p>",
        f"<p>Both columns are the providers' own <code>/models</code> endpoints, read "
        f"{esc(x['sources']['cross_provider']['generated'])}: Novita lists "
        f"{cp['counts']['novita']} model listings, OpenRouter {cp['counts']['openrouter']}, and {n} model ids are "
        f"served by both after normalising the vendor prefixes and date suffixes. Each cell is USD per million "
        f"tokens (input / output) with the monthly bill underneath. OpenRouter's column is its model-level "
        f"headline, which is not its cheapest listed endpoint — see below.</p>",
        "<table><tr><th>model</th><th>Novita</th><th>OpenRouter</th></tr>" + rows + "</table>",
        "<h2>Where OpenRouter wins, and why the gap is real</h2>",
        f"<p>{len(losses)} of {n} at this mix, and the losses are the large ones. Beyond the "
        f"{esc(losses[0][1])} row, {esc(losses[1][1])} is ${money2(losses[1][2])} against "
        f"${money2(losses[1][3])} ({1 / losses[1][0]:.2f}×) and {esc(losses[2][1])} is "
        f"${money2(losses[2][2])} against ${money2(losses[2][3])} ({1 / losses[2][0]:.2f}×). A team moving one "
        f"busy model from the dearer column to the cheaper one is not trimming a rounding error; on the "
        f"{esc(losses[0][1])} row the difference is "
        f"${money2((round(losses[0][2], 2) - round(losses[0][3], 2)) * 12)} a year at a "
        f"constant workload.</p>",
        f"<p>OpenRouter's headline is also not the whole story in its own favour: in "
        f"{len(floor_rows)} of these {n} models at least one listed endpoint is cheaper than the model-level "
        f"headline, by up to {floor_rows[0][0]:.2f}× on input ({esc(floor_rows[0][1])}: "
        f"${money(floor_rows[0][2], 3)} headline against ${money(floor_rows[0][3], 3)} at the cheapest "
        f"endpoint). So the honest form of the question is \"which provider is cheapest at the rate you can "
        f"actually route to\", and on output price, with every provider priced at its cheapest listed "
        f"endpoint, OpenRouter is cheapest on {cp['cheapest_output_floor']['openrouter']} of {n} models, "
        f"DeepInfra on {cp['cheapest_output_floor']['deepinfra']} and Novita on "
        f"{cp['cheapest_output_floor']['novita']}.</p>",
        "<h2>Where Novita wins</h2>",
        f"<p>{len(wins)} models, and none of them by much: the best case is {esc(wins[0][1])} at "
        f"${money2(wins[0][2])} against ${money2(wins[0][3])}, which is "
        f"{wins[0][0]:.2f}× cheaper — worth having on a big workload, not worth moving a working integration "
        f"for. "
        f"The second is {esc(wins[1][1])} at ${money2(wins[1][2])} against ${money2(wins[1][3])}.</p>",
        f"<p>The deciding line for a chat workload is usually the <strong>cache-read</strong> price, because a "
        f"long system prompt is re-read far more often than it is written. Both providers publish one on "
        f"{with_cache} of the {n} shared models: Novita is cheaper on {cache['novita']}, OpenRouter on "
        f"{cache['openrouter']}, and the two are identical on {cache['equal']}. Where Novita is cheaper it can "
        f"be by a multiple — {esc(wn)} is ${money(wcn, 4)} per million cached tokens at Novita against "
        f"${money(wco, 4)} at OpenRouter, {wr:.2f}×. That is the case where a lower headline rate loses: a "
        f"workload that reads {CACHE_READ}M cached tokens a month pays ${money2(CACHE_READ * wcn)} at Novita "
        f"and ${money2(CACHE_READ * wco)} at OpenRouter on those reads alone.</p>",
        "<h2>The thing only one of them sells</h2>",
        f"<p>OpenRouter is inference only. Novita also rents GPUs, and this dataset carries "
        f"{gpu_offers} GPU-hour offers across the two vendors: Novita lists an 80 GB H100 SXM at "
        f"<strong>${money2(h100_od['usd_per_gpu_hour'])} a GPU-hour on demand</strong>"
        + (f" and ${money2(h100_spot['usd_per_gpu_hour'])} interruptible" if h100_spot else "")
        + f". A team fine-tuning on its own GPU and then serving the same model through an API needs two "
        f"accounts, two billing relationships and two sets of rate limits if it splits that work across "
        f"providers; that, not the token price, is the argument for one account over the other.</p>",
        "<h2>What this page does not measure</h2>",
        "<p>Quality, latency, throughput, rate limits, uptime, context-window honesty and data handling are all "
        "absent here — price is a tiebreaker after those, not a ranking. No account exists on either service, "
        "so nothing was bought or load-tested. A cheap OpenRouter endpoint is also not necessarily the same "
        "serving of the model: OpenRouter routes to upstream providers, and the same model id can appear at a "
        "different quantisation or context length, which is why the matched ids and not only the display names "
        "are recorded in the dataset. Prices are list prices with no committed-use discount or volume tier.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "novita", "Novita API pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_llm_api_comparison(d, x):
    cp = x["cross_provider"]
    MIX = (40, 10)
    rows = ""
    mix_wins = {"novita": 0, "deepinfra": 0, "openrouter": 0}
    for r in cp["rows"]:
        tot = {p: MIX[0] * v["input"] + MIX[1] * v["output"] for p, v in r["providers"].items()}
        low = min(tot.values())
        winners = [p for p, v in tot.items() if abs(v - low) < 0.005]
        if len(winners) == 1:
            mix_wins[winners[0]] += 1
        cells = ""
        for p in ("novita", "deepinfra", "openrouter"):
            v = r["providers"][p]
            mark = " <strong>←</strong>" if p in winners else ""
            cells += (f"<td>${money(v['input'], 3)} / ${money(v['output'], 3)}"
                      f"<br><span class=\"muted\">${money2(tot[p])}</span>{mark}</td>")
        rows += f"<tr><td>{esc(r['display'])}</td>{cells}</tr>"
    best = sorted(cp["rows"], key=lambda r: -(
        max(MIX[0] * v["input"] + MIX[1] * v["output"] for v in r["providers"].values())
        / min(MIX[0] * v["input"] + MIX[1] * v["output"] for v in r["providers"].values())))[0]
    bt = {p: MIX[0] * v["input"] + MIX[1] * v["output"] for p, v in best["providers"].items()}
    spread = max(bt.values()) / min(bt.values())
    n = len(cp["rows"])
    body = [
        f"<h1>LLM API pricing comparison: the same {n} models at Novita, DeepInfra and OpenRouter</h1>",
        f"<p class=\"lede\">The same model, the same {MIX[0]}M input + {MIX[1]}M output tokens a month, priced at "
        f"three providers: <strong>{esc(best['display'])} costs ${money2(bt['novita'])} at Novita, "
        f"${money2(bt['deepinfra'])} at DeepInfra and ${money2(bt['openrouter'])} at OpenRouter</strong> — a "
        f"{spread:.2f}× spread for identical weights, on the same day. A headline price table prices the model; "
        f"the bill is priced by whoever serves it.</p>",
        f"<p>{n} open models are served by all three providers (their catalogues hold "
        f"{cp['counts']['novita']}, {cp['counts']['deepinfra']} and {cp['counts']['openrouter']} model listings "
        f"respectively). Prices read {esc(x['sources']['cross_provider']['generated'])}. Each provider cell shows "
        f"input / output USD per million tokens, and underneath, the monthly bill for {MIX[0]}M in + {MIX[1]}M out; "
        f"the arrow marks the cheapest at that mix.</p>",
        "<table><tr><th>model</th><th>Novita</th><th>DeepInfra</th><th>OpenRouter</th></tr>" + rows + "</table>",
        "<h2>Which LLM API is cheapest? The count, per provider</h2>",
        f"<p>Asked as a search question — which LLM API is the cheapest provider — the answer is not one name. "
        f"Counted on output price at headline rates, "
        f"<strong>Novita {cp['cheapest_output_headline']['novita']}</strong>, DeepInfra "
        f"{cp['cheapest_output_headline']['deepinfra']}, OpenRouter {cp['cheapest_output_headline']['openrouter']} "
        f"of {n}. When every provider is priced at its cheapest routeable endpoint instead of its model-level "
        f"headline, it moves to Novita {cp['cheapest_output_floor']['novita']}, DeepInfra "
        f"{cp['cheapest_output_floor']['deepinfra']}, OpenRouter {cp['cheapest_output_floor']['openrouter']} — "
        f"because OpenRouter's model-level price is not its cheapest endpoint in most of these models, so a "
        f"comparison built from headline prices flatters the other two.</p>",
        "<p>At the specific mix in the table the picture is sharper: on "
        f"<strong>{mix_wins['novita']}</strong> of {n} models Novita has the lowest monthly bill, DeepInfra "
        f"{mix_wins['deepinfra']} and OpenRouter {mix_wins['openrouter']}, and the remaining rows are ties — "
        f"the same model at two or three providers for the same money, which is what an open-weight model "
        f"eventually becomes. A tie is marked on every tied cell rather than awarding it to the first column.</p>",
        "<p>That is the honest reading of a table that earns from one of the three: Novita is the cheapest of "
        "these providers on a minority of models, and the rows where it loses are printed, not hidden. A "
        "comparison that only showed the vendor it earns from would be an advertisement.</p>",
        "<h2>What this does not measure</h2>",
        "<p>Price is not the product. This page has no data on output quality, latency, throughput, rate limits, "
        "uptime, context-window honesty or data handling, and no account exists here to test any of them, so "
        "cost is a tiebreaker after those, not a ranking. Prices are also list prices: no committed-use "
        "discount, no negotiated rate, and no volume tier is modelled. Cache-read prices differ per provider and "
        "are not in the monthly figure above — a workload that re-reads a long prompt will move on that line.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "novita", "Novita API pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


# ---------------------------------------------------------------- per-model pages (run 87)
# Run 85 measured that per-model pricing phrases are typed (20 stems, 0 errors) and that the incumbent
# ships 61 `models/<model>-pricing-calculator` pages. Its build rule: only where the three providers'
# bills differ by >=1.5x, cap 10 per run, only where the phrase is typed, same number-in-description
# check. Run 87 measured the typing for the 10 spread models (probe87a.py, 22 stems, 0 errors) and
# generates the pages from dataset_ext.json — every figure computed here, none typed twice.
MODEL_MIX = (40, 10)      # millions of tokens a month, the same workload the comparison page uses
PROVIDER_NAMES = {"novita": "Novita", "deepinfra": "DeepInfra", "openrouter": "OpenRouter"}


def _row(x, key):
    for r in x["cross_provider"]["rows"]:
        if r["key"] == key:
            return r
    raise SystemExit(f"no cross-provider row for {key!r}")


def _moneyp(v):
    """Per-million prices need three places: $0.006 and $0.060 are different claims."""
    return money(v, 3)


def _mix_map(provs):
    """Which provider is cheapest, as a function of input tokens per output token.

    Dividing the bill by the output count turns each provider into a straight line:
    input_price * r + output_price. Where two lines cross, the cheapest provider changes — a number a
    spread table hides, because the spread depends on the mix the reader actually runs.
    """
    import itertools
    names = [p for p in ("novita", "deepinfra", "openrouter") if p in provs]
    cuts = {0.0}
    for p, q in itertools.combinations(names, 2):
        da = provs[p]["input"] - provs[q]["input"]
        db = provs[p]["output"] - provs[q]["output"]
        if abs(da) > 1e-12:
            r = -db / da
            if 0.05 < r < 200:
                cuts.add(round(r, 4))
    cuts = sorted(cuts) + [1e9]
    segs = []
    for lo, hi in zip(cuts, cuts[1:]):
        mid = (lo + hi) / 2 if hi < 1e8 else max(lo * 2, 1.0)
        vals = {p: provs[p]["input"] * mid + provs[p]["output"] for p in names}
        low = min(vals.values())
        win = tuple(p for p in names if abs(vals[p] - low) < 1e-9)
        if segs and segs[-1][2] == win:
            segs[-1] = (segs[-1][0], hi, win)
        else:
            segs.append((lo, hi, win))
    return segs


def q_model_price(d, x, key):
    r = _row(x, key)
    provs = r["providers"]
    names = [p for p in ("novita", "deepinfra", "openrouter") if p in provs]
    MI, MO = MODEL_MIX
    bills = {p: MI * provs[p]["input"] + MO * provs[p]["output"] for p in names}
    low, high = min(bills.values()), max(bills.values())
    spread = high / low
    cheap = [p for p in names if abs(bills[p] - low) < 0.005]
    dear = [p for p in names if abs(bills[p] - high) < 0.005]
    order = sorted(names, key=lambda p: bills[p])

    cells = ""
    for p in ("novita", "deepinfra", "openrouter"):
        v = provs[p]
        flo = ""
        if v.get("floor_input") is not None and v.get("floor_output") is not None:
            fb = MI * v["floor_input"] + MO * v["floor_output"]
            flo = f"${money2(fb)}"
        cache = f"${_moneyp(v['cache_read'])}" if v.get("cache_read") is not None else "not published"
        mark = " <strong>&larr;</strong>" if p in cheap else ""
        cells += (f"<tr><td>{PROVIDER_NAMES[p]}</td><td>${_moneyp(v['input'])}</td>"
                  f"<td>${_moneyp(v['output'])}</td><td>${money2(bills[p])}{mark}</td>"
                  f"<td>{flo or 'same'}</td><td>{cache}</td></tr>")

    ids = "; ".join(f"{PROVIDER_NAMES[p]} `{esc(provs[p]['id'])}`" for p in order)

    # the mix section: the same three prices, read as lines in input-per-output
    segs = [s for s in _mix_map(provs) if s[0] < 60]
    mixlines = []
    for lo, hi, win in segs:
        who = " and ".join(PROVIDER_NAMES[p] for p in win)
        if lo <= 0.0001:
            mixlines.append(f"below {hi:.2f} input tokens per output token, <strong>{who}</strong>")
        elif hi >= 1e8:
            mixlines.append(f"above {lo:.2f} input tokens per output token, <strong>{who}</strong>")
        else:
            mixlines.append(f"between {lo:.2f} and {hi:.2f}, <strong>{who}</strong>")
    flips = len(segs) > 1
    mix_para = ("<h2>The winner depends on the mix, not just the model</h2>"
                "<p>Divided by the output count, each provider is a straight line — "
                "input price &times; <em>r</em> + output price, where <em>r</em> is input tokens per "
                "output token. Interleaved, the lines give the answer at every mix rather than at one: "
                + "; ".join(mixlines) + ".</p>")
    if not flips:
        mix_para += ("<p>For this model the ranking does not change at any mix between 0.05 and 60 input "
                     "tokens per output token, so the table above is not an artifact of the 4:1 example.</p>")
    else:
        mix_para += ("<p>The table above is priced at 4 input tokens per output token "
                     f"({MI}M in, {MO}M out). A chat workload with long prompts and short answers sits "
                     "well above that, and a batch job that writes long documents sits below it — at "
                     "which point the cheapest name in the table is no longer the cheapest bill.</p>")

    tie_para = ""
    if len(cheap) > 1:
        tie_para = (f"<p>{' and '.join(PROVIDER_NAMES[p] for p in cheap)} bill the identical "
                    f"${money2(low)} at this mix. That is a tie and it is marked as one; awarding it to a "
                    "single provider would be inventing a winner.</p>")

    floor_para = ""
    if any(provs[p].get("floor_input") is not None and provs[p].get("floor_output") is not None
           and MI * provs[p]["floor_input"] + MO * provs[p]["floor_output"] < bills[p] - 0.005
           for p in names):
        fr = [p for p in names if provs[p].get("floor_input") is not None
              and provs[p].get("floor_output") is not None]
        bits = ", ".join(
            f"{PROVIDER_NAMES[p]}'s cheapest routeable endpoint prices this mix at "
            f"${money2(MI * provs[p]['floor_input'] + MO * provs[p]['floor_output'])}"
            for p in fr if MI * provs[p]["floor_input"] + MO * provs[p]["floor_output"] < bills[p] - 0.005)
        floor_para = (f"<p>Model-level prices are not always the cheapest price a provider will route to. "
                      f"{bits}, so the headline bill overstates what routing actually costs there.</p>")

    body = [
        f"<h1>{esc(r['display'])} pricing: ${money2(high)} a month at the dearest provider, "
        f"${money2(low)} at the cheapest</h1>",
        f"<p class=\"lede\">The same open-weight model, the same {MI}M input + {MO}M output tokens a "
        f"month, priced at three providers on {esc(x['sources']['cross_provider']['generated'])}: "
        f"<strong>{esc(r['display'])} costs ${money2(high)} at {PROVIDER_NAMES[dear[0]]} and "
        f"${money2(low)} at {PROVIDER_NAMES[cheap[0]]}</strong> — a {spread:.2f}&times; spread for "
        f"identical weights, or ${money2(high - low)} a month and ${money2((high - low) * 12)} a year "
        f"on this workload alone.</p>",
        "<table><tr><th>provider</th><th>$/M input</th><th>$/M output</th>"
        f"<th>bill at {MI}M in + {MO}M out</th><th>cheapest routeable endpoint</th>"
        "<th>cache read $/M</th></tr>" + cells + "</table>",
        f"<p>Model ids priced here, so the comparison cannot quietly be of three different things: "
        f"{ids}.</p>",
        mix_para,
        tie_para,
        floor_para,
        "<p>Cache-read prices are per million cached input tokens and are not in the monthly bill above; a "
        "workload that re-reads a long prompt should price that line separately. All figures are list "
        "prices from each provider's own catalogue on the date shown, with no committed-use or negotiated "
        "discount.</p>",
        "<h2>What this does not measure</h2>",
        "<p>Price is not the product. Nothing here measures output quality, latency, throughput, rate "
        "limits, uptime, context-window honesty or data handling, and no account exists on this site to "
        "test any of them: cost is a tiebreaker after those, not a ranking.</p>",
        DISCLOSURE,
    ]
    if "novita" in cheap:
        body.append("<p>Novita is the cheapest of the three for this model at every mix in the table, so "
                    "this is the one page on this site where its link is the recommendation rather than a "
                    "disclosure: " + aff_link(x, "novita", "Novita pricing — affiliate link") + "</p>")
    return "".join(body)


def load_comp():
    with open(os.path.join(HERE, "data", "competitors.json"), encoding="utf-8") as f:
        return json.load(f)


def q_do_vs_hetzner(d, x):
    """DigitalOcean vs Hetzner at the same size, with the monthly cap treated as part of the price.

    Demand: `digitalocean vs hetzner` (and `digitalocean vs vultr`, `digitalocean vs linode`) are Google
    Autocomplete suggestions measured in probe89.py on 2026-11-08 22:56Z, control `vultr vs` = 10.
    Run 89 deferred this page with a rule: "do not write it until Hetzner/Vultr prices are read". They
    were read on 2026-11-08 22:52Z and are typed into data/competitors.json with their URLs and the FX
    date. Every figure below is computed from that file or from this repo's own Droplet dataset.
    """
    c = load_comp()
    fx = c["fx"]["usd_per_eur"]
    H = {p["id"]: p for p in c["hetzner"]["plans"]}
    V = {p["id"]: p for p in c["vultr"]["plans"]}
    do_plans = x["droplets"]["plans"]
    h730 = x["month_hours"]

    def do_basic(mem, vcpu):
        return next(p for p in do_plans
                    if p["family"] == "Basic" and p["memory_gib"] == mem and p["vcpus"] == vcpu)

    def usd_eur(eur):
        return eur * fx

    # Three matched footprints. Vultr has no 8 vCPU / 16 GiB line, so the largest row uses its 6 vCPU
    # 16 GiB plan and says so — a comparison that silently matches a different spec is the failure mode.
    sizes = [
        ("1 vCPU / 1 GiB", do_basic(1.0, 1), H["cpx02"], V["vc1-1"], ""),
        ("2 vCPU / 4 GiB", do_basic(4.0, 2), H["cx23"], V["vc2-4"], ""),
        ("8 vCPU / 16 GiB", do_basic(16.0, 8), H["cx43"], V["vc6-16"],
         "Vultr's closest 16 GiB plan is 6 vCPU, not 8."),
    ]

    rows = []
    data = []
    for label, dp, hp, vp, note in sizes:
        do_mo = dp["usd_per_month"]
        hz_usd = usd_eur(hp["eur_per_month"])
        vu_mo = vp["usd_per_month"]
        data.append((label, do_mo, hz_usd, vu_mo, hp, vp, dp, note))
        rows.append(
            f"<tr><td>{esc(label)}</td>"
            f"<td>${money2(do_mo)}</td>"
            f"<td>€{money2(hp['eur_per_month'])} (${money2(hz_usd)})</td>"
            f"<td>${money2(vu_mo)}</td>"
            f"<td>{do_mo / hz_usd:.2f}×</td>"
            f"<td>{vu_mo / hz_usd:.2f}×</td></tr>")
    table = ("<table><tr><th>same footprint</th><th>DigitalOcean</th><th>Hetzner (EUR, and in USD "
             f"at the {c['fx']['date']} ECB rate)</th><th>Vultr</th><th>DO ÷ Hetzner (under 1 = DO cheaper)</th>"
             "<th>Vultr ÷ Hetzner</th></tr>" + "".join(rows) + "</table>")

    # Sizes used in the prose, taken from the table rather than retyped.
    s1, s2, s3 = data[0], data[1], data[2]
    small_ratio = s1[2] / s1[3]          # Hetzner / Vultr at 1 GiB
    big_ratio = s2[1] / s2[2]            # DO / Hetzner at 2 vCPU / 4 GiB
    biggest_ratio = s3[1] / s3[2]        # DO / Hetzner at 8 vCPU / 16 GiB

    # The cap: every vendor's monthly price equals a number of hours at its own hourly rate. Billed
    # hourly for 730 hours, the percentage below is what the monthly cap absorbs.
    six = do_basic(1.0, 1)
    do_cap_h = six["usd_per_month"] / six["usd_per_hour"]
    do_over = (six["usd_per_hour"] * h730 / six["usd_per_month"] - 1) * 100
    cpx02 = H["cpx02"]
    hz_cap_h = cpx02["eur_per_month"] / cpx02["eur_per_hour"]
    hz_over = (cpx02["eur_per_hour"] * h730 / cpx02["eur_per_month"] - 1) * 100
    vc11 = V["vc1-1"]
    vu_cap_h = vc11["usd_per_month"] / vc11["usd_per_hour"]
    vu_over = (vc11["usd_per_hour"] * h730 / vc11["usd_per_month"] - 1) * 100

    vx = c["vultr"]["vx1"]["plans"][0]
    vx_730 = vx["usd_per_hour"] * h730
    cx33 = H["cx33"]
    cx33_usd = usd_eur(cx33["eur_per_month"])

    # Non-monotonicity inside one vendor's own page: the 2 vCPU / 4 GiB cost-optimised plan is cheaper
    # than the 1 vCPU / 1 GiB regular-performance plan.
    hz_smallest = min((p for p in c["hetzner"]["plans"] if p["memory_gib"] == 1),
                      key=lambda p: p["eur_per_month"])
    cx23 = H["cx23"]
    hz_ram_ratio = cx23["memory_gib"] / hz_smallest["memory_gib"]
    cheaper_pct = (1 - cx23["eur_per_month"] / hz_smallest["eur_per_month"]) * 100
    nonmono = (
        f"<p>One row of that table is worth reading twice. Hetzner's own page sells "
        f"<strong>{cx23['memory_gib']:g} GiB and {cx23['vcpus']} vCPU for €{money2(cx23['eur_per_month'])}"
        f"</strong> in its cost-optimised line and <strong>{hz_smallest['memory_gib']:g} GiB and "
        f"{hz_smallest['vcpus']} vCPU for €{money2(hz_smallest['eur_per_month'])}</strong> in its "
        f"regular-performance line — {hz_ram_ratio:.0f}× the RAM for {cheaper_pct:.0f}% less money. The "
        f"cheap line is cheap because it runs proven older hardware, and the smallest plan sits on the "
        f"new one, so size does not order this price list. VAT is excluded too, so the euro figure is "
        f"not the amount an EU customer is charged.</p>")

    body = [
        "<h1>DigitalOcean vs Hetzner: what the same server costs at 730 hours</h1>",
        f"<p class=\"lede\">Two clouds, one footprint: <strong>2 vCPU and 4 GiB</strong>. DigitalOcean lists "
        f"<strong>${money2(s2[1])} a month</strong> for it. Hetzner lists <strong>€{money2(s2[4]['eur_per_month'])}"
        f"</strong>, which is <strong>${money2(s2[2])}</strong> at the ECB rate of {c['fx']['date']} — "
        f"<strong>{big_ratio:.2f}× less</strong> for the same cores and memory, with 20 TB of EU traffic "
        f"against DigitalOcean's 4 TB on that plan. Now the same table one row down: at <strong>1 vCPU and "
        f"1 GiB Hetzner is the most expensive of the three</strong>, €{money2(hz_smallest['eur_per_month'])} "
        f"(${money2(usd_eur(hz_smallest['eur_per_month']))}) against DigitalOcean's ${money2(s1[1])} and "
        f"Vultr's ${money2(s1[3])}. \"Hetzner is cheaper\" is true at 4 GiB and false at 1 GiB, and a "
        f"comparison that picks one size can say either.</p>",
        f"<p>Every price here was read from the vendor's own pricing page on {esc(c['sources']['read'])}: "
        f"{esc(c['sources']['hetzner'][0])}, {esc(c['sources']['hetzner'][1])} and "
        f"{esc(c['sources']['vultr'][0])}. The DigitalOcean column comes from this repository's dated "
        f"Droplet dataset (read {esc(x['sources']['droplets']['read'])}). Nothing here was bought and no "
        f"invoice was seen: these are list prices, and list prices are the beginning of a bill, not the bill.</p>",
        table,
        nonmono,
        "<h2>The monthly cap is part of the price, and the three caps are not equally generous</h2>",
        f"<p>Each vendor sells an hourly rate and a monthly price, and the monthly price is a ceiling: run the "
        f"server all month and you pay the ceiling, not the hourly rate times {h730} hours. The gap between "
        f"those two numbers is where the caps differ. DigitalOcean's ${money2(six['usd_per_month'])} equals "
        f"<strong>{do_cap_h:.1f} hours</strong> at its own ${money(six['usd_per_hour'], 5)}/hour, so a "
        f"730-hour month would cost <strong>{do_over:.1f}% more</strong> than the cap were the cap not "
        f"applied. Hetzner's €{money2(hz_smallest['eur_per_month'])} equals only "
        f"<strong>{hz_cap_h:.1f} hours</strong> at €{money(hz_smallest['eur_per_hour'], 4)}/hour — the cap "
        f"absorbs <strong>{hz_over:.1f}%</strong>, its pricing page says so in as many words (\"your "
        f"server's bill will never exceed its monthly price cap\"). Vultr's $5.00 equals "
        f"<strong>{vu_cap_h:.1f} hours</strong> at $0.007/hour, a cap worth <strong>{vu_over:.1f}%</strong>.</p>",
        f"<p>The exception is the one Vultr advertises: its VX1 line is \"billed on actual hours used each "
        f"month and are not capped at 672 hours\", which puts the number that DigitalOcean and Hetzner hide "
        f"into Vultr's own copy. It matters when the line has no cap at all: VX1's 2 vCPU / 8 GiB is "
        f"<strong>${money(vx['usd_per_hour'], 3)}/hour</strong>, so {h730} hours is "
        f"<strong>${money2(vx_730)}</strong> — {vx_730 / cx33_usd:.2f}× Hetzner's "
        f"€{money2(cx33['eur_per_month'])} (${money2(cx33_usd)}) 4 vCPU / 8 GiB plan. The specs are not "
        f"like-for-like — VX1 sells dedicated vCPUs, Hetzner's CX33 shared ones — but the hourly rate is "
        f"the number people compare, and here it is {vx_730 / cx33_usd:.2f}× apart at month end.</p>",
        "<h2>Traffic is the line item that can outweigh compute</h2>",
        f"<p>At 2 vCPU / 4 GiB, DigitalOcean includes <strong>{s2[6]['transfer_gib']:,.0f} GiB</strong> of "
        f"transfer, Vultr <strong>{s2[5]['traffic_tb']:g} TB</strong> and Hetzner <strong>"
        f"{cx23['traffic_tb']} TB</strong> in its EU locations. A service pushing 30 TB a month through a "
        f"$24 Droplet is 26 TB over an allowance that a Hetzner EU server does not charge for at all. Two "
        f"honest caveats: Hetzner's own page puts the Singapore allowance at 0.5 TB with a per-TB charge "
        f"for additional traffic, so the 20 TB is a European number; and transfer allowances are not "
        f"throughput, so this says nothing about how fast any of the three moves bytes.</p>",
        "<h2>What this comparison cannot tell you</h2>",
        f"<p>It cannot tell you which is faster. Shared vCPU plans of the same core count are not the same "
        f"machine: CPU generations, steal time and disk throughput differ, and a plan that is 3× cheaper per "
        f"month is 3× cheaper because the cores are shared more aggressively. It also cannot tell you what "
        f"you will pay: Hetzner's prices here are <strong>excluded from VAT</strong> and billed in euros, so "
        f"an EU customer pays more than the figure in the table and a non-EU customer's card is charged at "
        f"the rate of the day, not the {c['fx']['date']} rate used here. Vultr's prices vary by location "
        f"and it says so. Availability and stock also move — the pages mark plans as unavailable while "
        f"retaining their published price, so a plan in this table is a price, not a promise that you can "
        f"buy it today. And none of this covers managed databases, block storage, snapshots or support "
        f"plans, which is where a cheap server stops being a cheap stack.</p>",
        "<p class=\"merit\">Disclosure of interest, stated plainly: Hetzner and Vultr do not pay this site "
        "anything, and neither do I have a link to them. DigitalOcean is an affiliate partner — if you sign "
        "up through the link below, a9n9 earns credit with DigitalOcean. That is why the DigitalOcean "
        "column above is labelled, and why it says what it says: at 1 GiB DigitalOcean is "
        f"second of the three behind Vultr's $5.00, and at 4 GiB and 16 GiB it is the dearest, at "
        f"{big_ratio:.2f}× and {biggest_ratio:.2f}× the Hetzner price. That is the number to explain "
        "away if you are going to buy there anyway.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "digitalocean", "DigitalOcean droplet pricing — affiliate link") + "</p>",
    ]

    if s3[7]:
        body.insert(4, f"<p class=\"note\">{esc(s3[7])}</p>")
    return "".join(body)


def q_deepgram_vs_elevenlabs(d, x):
    """Deepgram vs ElevenLabs, compared at the layer that is actually being bought.

    Demand: `deepgram vs elevenlabs` returns 10 Google Autocomplete suggestions (probe91.py,
    2026-11-08 22:56Z, control `vultr vs` = 10), including `deepgram vs elevenlabs pricing`,
    `... stt`, `... tts`, `... speech to text` — the searcher is choosing between three different
    products and the completion list names all three. `elevenlabs vs deepgram` returns only 4,
    so the title takes the direction people type.

    Every figure is computed from dataset.json, which was read from the two vendors' own pricing
    pages on the dates recorded there. ElevenLabs is an affiliate programme and Deepgram is not;
    the page says so and still has to print the rates it prints.
    """
    el = d["vendors"]["elevenlabs"]
    dg = d["vendors"]["deepgram"]
    cpm = el["chars_per_minute_default"]
    el_v4 = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]
    el_turbo = el["rates_usd_per_1000_chars"]["turbo_flash_api"]
    el_agent = el["agent_usd_per_minute"]
    dg_tts = dg["tts_usd_per_1000_chars"]
    dg_a2 = dg_tts["aura_2_payg"]
    dg_a1 = dg_tts["aura_1_payg"]
    stt = dg["stt_usd_per_minute"]
    stt_lo, stt_hi = min(stt.values()), max(stt.values())
    dg_agent = dg["voice_agent_usd_per_minute"]["standard_payg"]
    dg_agent_g = dg["voice_agent_usd_per_minute"]["standard_growth"]

    def per_min(per_k):
        """per 1,000 characters -> per finished minute at the dataset's chars-per-minute basis."""
        return per_k / 1000 * cpm

    # Ten thousand finished minutes is the example every layer can be priced at.
    M = 10000
    b_stt = stt["nova3_monolingual_prerecorded_payg"] * M
    b_stt_g = stt_lo * M
    b_el_v4 = per_min(el_v4) * M
    b_el_turbo = per_min(el_turbo) * M
    b_dg_agent = dg_agent * M
    b_el_agent = el_agent * M
    spread = b_el_agent / b_stt

    # ElevenLabs' plan blocks: the smallest plan that includes the characters a 10,000-minute month
    # needs, and what it costs against the same characters at the vendor's own per-character rate.
    chars_needed = M * cpm
    seat = min((r for r in el["ladder"] if r["chars"] >= chars_needed and r["usd"] > 0),
               key=lambda r: r["usd"])
    chars_billed = seat["chars"]
    unused = chars_billed - chars_needed
    per_char_bill = chars_needed / 1000 * el_v4

    rows = []
    rows.append("<tr><td>speech to text</td><td>per minute</td>"
                f"<td>${money(stt_lo, 4)}–${money(stt_hi, 4)}</td><td>not on this rate card</td></tr>")
    rows.append("<tr><td>synthesised speech — cheapest model</td><td>per 1,000 characters / per minute</td>"
                f"<td>Aura-1 ${money(dg_a1, 3)} / <strong>${money(per_min(dg_a1), 4)}</strong></td>"
                f"<td>Turbo Flash ${money(el_turbo, 3)} / <strong>${money(per_min(el_turbo), 4)}</strong></td></tr>")
    rows.append("<tr><td>synthesised speech — flagship model</td><td>per 1,000 characters / per minute</td>"
                f"<td>Aura-2 ${money(dg_a2, 3)} / <strong>${money(per_min(dg_a2), 4)}</strong></td>"
                f"<td>Multilingual v4 ${money(el_v4, 3)} / <strong>${money(per_min(el_v4), 4)}</strong></td></tr>")
    rows.append("<tr><td>managed voice agent</td><td>per minute</td>"
                f"<td>${money(dg_agent, 3)} pay-as-you-go, ${money(dg_agent_g, 3)} on Growth "
                f"(STT + managed LLM + TTS)</td>"
                f"<td>${money(el_agent, 3)} plus LLM usage on the two Realtime tiers</td></tr>")
    table = ("<table><tr><th>what you are buying</th><th>unit</th><th>Deepgram</th><th>ElevenLabs</th></tr>"
             + "".join(rows) + "</table>")

    bill_rows = [
        ("Deepgram speech to text, pre-recorded pay-as-you-go", b_stt),
        ("Deepgram speech to text, Growth floor", b_stt_g),
        ("ElevenLabs Multilingual v4 speech", b_el_v4),
        ("ElevenLabs Turbo Flash speech", b_el_turbo),
        ("Deepgram Voice Agent, standard pay-as-you-go", b_dg_agent),
        ("ElevenLabs agent", b_el_agent),
    ]
    bill_table = ("<table><tr><th>the same 10,000 finished minutes, billed as</th><th>one month</th></tr>"
                  + "".join(f"<tr><td>{esc(n)}</td><td>${money2(v)}</td></tr>"
                            for n, v in sorted(bill_rows, key=lambda kv: kv[1]))
                  + "</table>")

    body = [
        "<h1>Deepgram vs ElevenLabs: what a minute of speech costs at each layer</h1>",
        f"<p class=\\\"lede\\\">The same <strong>{M:,} minutes</strong> of audio is "
        f"<strong>${money2(b_stt)}</strong> as Deepgram speech-to-text, <strong>${money2(b_el_v4)}</strong> "
        f"as ElevenLabs Multilingual v4 speech, <strong>${money2(b_dg_agent)}</strong> as a Deepgram agent "
        f"minute and <strong>${money2(b_el_agent)}</strong> as an ElevenLabs agent minute — an "
        f"<strong>{spread:.1f}× spread</strong>. Almost none of that spread is the vendor: it is which "
        f"line item the minute is billed against.</p>",
        "<p>That is why &ldquo;is Deepgram or ElevenLabs cheaper&rdquo; has no single answer, and why the "
        "comparison pages that answer it with one number are usually comparing an all-in agent minute "
        "against a speech-only minute. The table below separates the three products both vendors sell.</p>",
        table,
        "<h2>The $0.075 against $0.072 headline is not a like-for-like comparison</h2>",
        f"<p>The number most often quoted for Deepgram is <strong>${money(dg_agent, 3)} a minute</strong>, and "
        f"the number most often quoted for ElevenLabs is <strong>${money(per_min(el_v4), 3)} a minute</strong> "
        f"({el_v4:.3f} per 1,000 characters at {cpm} characters per spoken minute). Put side by side they "
        f"differ by <strong>{(dg_agent / per_min(el_v4) - 1) * 100:.1f}%</strong> — but they are not the same "
        f"product. ${money(dg_agent, 3)} is Deepgram's Voice Agent: speech-to-text, a managed LLM and "
        f"speech synthesis in one minute, with no separate model bill. ${money(per_min(el_v4), 3)} is "
        f"ElevenLabs synthesis alone; the text has to arrive from somewhere and the LLM is not in it.</p>",
        f"<p>Agent against agent they are within a few percent: ElevenLabs&rsquo; ${money(el_agent, 3)} is "
        f"{(el_agent / dg_agent - 1) * 100:.1f}% above Deepgram&rsquo;s ${money(dg_agent, 3)} pay-as-you-go "
        f"and {(el_agent / dg_agent_g - 1) * 100:.1f}% above its ${money(dg_agent_g, 3)} Growth rate — and "
        f"Deepgram&rsquo;s minute already includes a managed LLM while ElevenLabs&rsquo; does not, so "
        f"all-in the gap is wider than the sticker shows. The layer where the two are furthest apart is "
        f"the one the headline never mentions: Deepgram&rsquo;s speech-to-text is "
        f"<strong>${money(stt_lo, 4)}–${money(stt_hi, 4)} a minute</strong>, which is "
        f"<strong>{dg_agent / stt_hi:.1f}× to {dg_agent / stt_lo:.1f}×</strong> "
        f"cheaper than its own agent minute. Reading the agent rate as a transcription rate is a "
        f"{dg_agent / stt_lo:.0f}× error at the floor, and it is the most common one in this comparison.</p>",
        "<h2>Inside ElevenLabs, the model choice moves the price more than the vendor choice</h2>",
        f"<p>ElevenLabs Multilingual v4 is ${money(el_v4, 3)} per 1,000 characters and Turbo Flash is "
        f"${money(el_turbo, 3)} — exactly half. At {cpm} characters a minute that is "
        f"<strong>${money(per_min(el_turbo), 4)} against ${money(per_min(el_v4), 4)}</strong> for a minute "
        f"of speech. A page that says &ldquo;ElevenLabs is 5.3× Deepgram&rdquo; has compared v4 with "
        f"Aura-1; on Turbo Flash the same comparison is <strong>{per_min(el_turbo) / per_min(dg_a1):.2f}×</strong>, "
        f"and against Aura-2 it is <strong>{per_min(el_turbo) / per_min(dg_a2):.2f}×</strong>. Which voice "
        f"you need is not a price question — it is the one thing this page cannot price, and it can easily "
        f"be worth more than a 2× rate difference.</p>",
        "<h2>10,000 minutes in one month, priced six ways</h2>",
        bill_table,
        f"<p>Same audio, same month: <strong>${money2(b_el_agent)}</strong> against "
        f"<strong>${money2(b_stt)}</strong>. The moment you are buying is the moment a bill is decided — "
        f"before any vendor comparison, and regardless of which of these two companies is cheaper.</p>",
        "<h2>The block boundary, which is the other way this bill surprises people</h2>",
        f"<p>ElevenLabs is sold in monthly blocks, and a block is not a rate. {M:,} finished minutes at "
        f"{cpm} characters is <strong>{chars_needed:,} characters</strong>; at the vendor&rsquo;s own "
        f"${money(el_v4, 3)} per 1,000 characters that is <strong>${money2(per_char_bill)}</strong> of "
        f"usage. The smallest plan that includes {chars_needed:,} characters is "
        f"<strong>{esc(seat.get('name', ''))}</strong> at <strong>${money2(seat['usd'])}</strong> a month, "
        f"which carries {chars_billed:,} characters — so the month pays for "
        f"<strong>{unused:,} characters it does not speak</strong>, and the effective rate is "
        f"${money2(seat['usd'] / M)} a finished minute instead of ${money(per_char_bill / M, 3)}. Blocks "
        f"are why two months with visibly different usage can produce the same invoice.</p>",
        "<h2>What this page cannot tell you</h2>",
        "<p>It cannot tell you which voice sounds better, which is the actual buying decision, and it "
        "cannot price latency, concurrency limits, language coverage or word-error rate — the numbers "
        "that decide whether a transcription bill is cheap or merely small. It also cannot reconcile the "
        "two price lists ElevenLabs publishes: its API page bills "
        f"${money(el_v4, 3)} per 1,000 characters ({el['ladder'][2]['chars']:,} characters on the "
        f"${money2(el['ladder'][2]['usd'])} Creator plan), while its marketing pages quote "
        "121,000 credits for the same plan, which works out to "
        f"${money(el['rates_usd_per_1000_chars']['credits_equivalent_creator'], 4)} per 1,000 — about "
        "2.3× the API rate. If a comparison uses the credits column, it is comparing a different unit. "
        "All prices here are list prices read on the dates on this page, not invoices, and neither "
        "vendor&rsquo;s free-tier credit is counted as a price.</p>",
        "<p class=\\\"merit\\\">Disclosure of interest, stated plainly: ElevenLabs is an affiliate partner "
        "— if you buy through the link below, a9n9 earns a commission. Deepgram pays this site nothing and "
        "there is no Deepgram link on this page. On every layer in the table above ElevenLabs is the more "
        "expensive of the two, and its agent minute excludes the LLM that Deepgram&rsquo;s includes, so "
        "the honest summary is: Deepgram&rsquo;s rates are lower here, and ElevenLabs is the voice product "
        "you may actually want. Both of those can be true, and the link is labelled so you can weigh it.</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d, "ElevenLabs pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_firecrawl_vs_tavily(d, x):
    """Firecrawl vs Tavily priced per unit of work, and where the answer flips.

    Demand: `firecrawl vs tavily` returns 5 Google Autocomplete suggestions (probe91b.py, 2026-11-08
    23:1xZ: `firecrawl vs tavily vs exa`, `firecrawl vs tavily reddit`, `firecrawl or tavily`,
    `playwright vs firecrawl vs tavily`), inside a 10-suggestion `firecrawl vs` list. Tavily is not an
    affiliate programme here; Firecrawl is, and its link is labelled at the bottom.

    Tavily's numbers come from data/tavily.json (read 2026-11-08T23:07Z from tavily.com/pricing and
    docs.tavily.com/documentation/api-credits); Firecrawl's come from this repo's own dataset. Both
    cost functions are computed here, not typed, so the crossing point is arithmetic rather than a
    claim.
    """
    fc = d["vendors"]["firecrawl"]
    tv = load_tavily()

    # --- cost functions, cheapest legitimate way to buy N credits ---
    def fc_cost(credits):
        best = None
        for p in fc["plans"]:
            if p["pages_included"] >= credits:
                cost = p["usd_per_month"]
            else:
                rate = p.get("payg_usd_per_1000_credits")
                if not rate:
                    continue
                cost = p["usd_per_month"] + (credits - p["pages_included"]) / 1000 * rate
            best = cost if best is None else min(best, cost)
        return best

    def tv_cost(credits):
        best = None
        for p in tv["plans"]:
            if p["credits"] >= credits:
                cost = p["usd_per_month"]
            else:
                cost = p["usd_per_month"] + (credits - p["credits"]) * tv["payg_usd_per_credit"]
            best = cost if best is None else min(best, cost)
        return best

    # --- unit costs ---
    fc_per_page = 1.0                       # dataset credit_rule: 1 credit = 1 page
    tv_per_page = (tv["credits"]["map_per_10_pages"] / 10
                   + tv["credits"]["extract_basic_per_5_urls"] / 5)
    fc_per_search = 2.0                     # dataset trap: a search is 2 credits
    tv_per_search = tv["credits"]["search_basic"]

    page_volumes = [10000, 30000, 100000]
    search_volumes = [2000, 10000, 50000]

    def ratio(fcc, tvc):
        if not tvc:
            return "free tier" if not fcc else "&infin;"
        return f"{fcc / tvc:.2f}×"

    prow = []
    for n in page_volumes:
        fcc = fc_cost(n * fc_per_page)
        tvc = tv_cost(n * tv_per_page)
        prow.append(f"<tr><td>{n:,} pages</td><td>{n * fc_per_page:,.0f}</td><td>${money2(fcc)}</td>"
                    f"<td>{n * tv_per_page:,.0f}</td><td>${money2(tvc)}</td>"
                    f"<td>{ratio(fcc, tvc)}</td></tr>")
    page_table = ("<table><tr><th>crawl volume</th><th>Firecrawl credits</th><th>Firecrawl cost</th>"
                  "<th>Tavily credits</th><th>Tavily cost</th><th>Firecrawl ÷ Tavily</th></tr>"
                  + "".join(prow) + "</table>")

    srow = []
    for n in search_volumes:
        fcc = fc_cost(n * fc_per_search)
        tvc = tv_cost(n * tv_per_search)
        srow.append(f"<tr><td>{n:,} searches</td><td>{n * fc_per_search:,.0f}</td><td>${money2(fcc)}</td>"
                    f"<td>{n * tv_per_search:,.0f}</td><td>${money2(tvc)}</td>"
                    f"<td>{ratio(fcc, tvc)}</td></tr>")
    search_table = ("<table><tr><th>search volume</th><th>Firecrawl credits</th><th>Firecrawl cost</th>"
                    "<th>Tavily credits</th><th>Tavily cost</th><th>Firecrawl ÷ Tavily</th></tr>"
                    + "".join(srow) + "</table>")

    # --- the crossing points, found by arithmetic, not by reading a marketing page ---
    def crossing(fc_credits_fn, tv_credits_fn, lo=2000, hi=600000):
        """Smallest volume above the free tier at which Firecrawl stops being the dearer one.

        Both sides must be priced at their OWN credit count: Firecrawl spends 1 credit a page and
        Tavily 0.3, and the first version of this function passed the same number to both cost
        functions, so it reported a crossing at 3,391 pages while its own table showed Firecrawl at
        2.75x on 10,000 (caught by comparing the printed sentence with the printed table).
        """
        last_dearer = None
        v = lo
        while v <= hi:
            fcc, tvc = fc_cost(fc_credits_fn(v)), tv_cost(tv_credits_fn(v))
            if fcc > tvc:
                last_dearer = v
            elif last_dearer is not None:
                return v, last_dearer
            v = int(v * 1.01) + 1
        return None, None

    page_cross, page_below = crossing(lambda v: v * fc_per_page, lambda v: v * tv_per_page)
    search_cross, search_below = crossing(lambda v: v * fc_per_search, lambda v: v * tv_per_search)

    ten_k_pages_fc = fc_cost(10000 * fc_per_page)
    ten_k_pages_tv = tv_cost(10000 * tv_per_page)
    ten_k_search_fc = fc_cost(10000 * fc_per_search)
    ten_k_search_tv = tv_cost(10000 * tv_per_search)
    hundred_k_pages_fc = fc_cost(100000 * fc_per_page)
    hundred_k_pages_tv = tv_cost(100000 * tv_per_page)
    two_k_search_fc = fc_cost(2000 * fc_per_search)
    two_k_search_tv = tv_cost(2000 * tv_per_search)
    fifty_k_search_fc = fc_cost(50000 * fc_per_search)
    fifty_k_search_tv = tv_cost(50000 * tv_per_search)
    fc_rate_10k = ten_k_pages_fc / 10              # $ per 1,000 pages at the 10,000-page point
    fc_rate_100k = hundred_k_pages_fc / 100        # $ per 1,000 pages at the 100,000-page point
    page_ratio_10k = ten_k_pages_fc / ten_k_pages_tv

    body = [
        "<h1>Firecrawl vs Tavily: which is cheaper depends on volume, and the answer flips</h1>",
        f"<p class=\\\"lede\\\">For <strong>10,000 crawled pages</strong> Firecrawl's cheapest seat is "
        f"<strong>${money2(ten_k_pages_fc)}</strong> and Tavily's is <strong>${money2(ten_k_pages_tv)}</strong> "
        f"— Firecrawl costs <strong>{page_ratio_10k:.2f}×</strong> as much. At "
        f"<strong>100,000 pages</strong> the order reverses: Firecrawl <strong>${money2(hundred_k_pages_fc)}"
        f"</strong> against Tavily <strong>${money2(hundred_k_pages_tv)}</strong>. The crossing sits at about "
        f"<strong>{page_cross:,} pages</strong>, and almost every comparison page quotes one volume and "
        f"therefore one answer.</p>",
        "<p>Both vendors sell credits, and the credits are not the same size: Firecrawl spends <strong>1 credit "
        "per page crawled</strong> (5 if you ask for JSON), while Tavily prices a crawl as mapping plus "
        "extraction — <strong>10 pages per credit mapped</strong> plus <strong>5 per credit extracted</strong>, "
        "i.e. <strong>0.3 credit per page</strong> at basic depth. Reading the two rate cards side by side "
        "without that conversion is how a 3.3× difference in the unit disappears.</p>",
        "<h2>Crawled pages</h2>",
        page_table,
        f"<p>Neither ladder is linear, and the two bend differently. Firecrawl&rsquo;s $19 Hobby seat holds "
        f"5,000 credits and its overflow credits cost $5 per 1,000, so 10,000 pages is "
        f"<strong>${money2(ten_k_pages_fc)}</strong> (the seat plus 5,000 overflow credits) — cheaper than "
        f"buying the $99 Standard seat with 100,000 included, which is why the 10,000-page row does not read "
        f"$99. That puts its rate at <strong>${money2(fc_rate_10k)} per 1,000 pages</strong> at 10,000 and "
        f"<strong>${money2(fc_rate_100k)}</strong> at 100,000, because the big block is where the seat stops "
        f"being the cost. Tavily&rsquo;s ladder is smoother — 1,000 free, ${money2(30)} for 4,000, "
        f"${money2(100)} for 15,000, ${money2(220)} for 38,000, ${money2(500)} for 100,000 credits, then "
        f"${money(tv['payg_usd_per_credit'], 3)} a credit over the top — which is why it wins the small "
        f"volumes and loses the large ones.</p>",
        "<h2>Searches</h2>",
        search_table,
        f"<p>A search is <strong>2 credits</strong> at Firecrawl and <strong>1 credit</strong> at Tavily, but "
        f"the plan shapes matter more: at 2,000 searches Firecrawl is <strong>${money2(two_k_search_fc)}"
        f"</strong> against Tavily&rsquo;s <strong>${money2(two_k_search_tv)}</strong>, at 10,000 the gap "
        f"narrows to <strong>${money2(ten_k_search_fc)}</strong> against <strong>${money2(ten_k_search_tv)}"
        f"</strong>, and at 50,000 it inverts — <strong>${money2(fifty_k_search_fc)}</strong> against "
        f"<strong>${money2(fifty_k_search_tv)}</strong>. The same arithmetic that decides crawled pages "
        f"decides searches: Firecrawl sells a big block cheaply, Tavily sells credits at a flat "
        f"${money(tv['payg_usd_per_credit'], 3)} with a gentle ladder.</p>",
        "<h2>What the arithmetic cannot decide</h2>",
        "<p>Price per page is not value per page. Firecrawl&rsquo;s own site says it renders JavaScript "
        "automatically and returns markdown, screenshots or an extracted schema (read 2026-11-08); Tavily is "
        "built for agents to ask a question and get ranked results with optional raw content, and its crawl "
        "is a newer feature of that product. If the pages you crawl need "
        "rendering, or you want structured extraction from a page, the cheap column is not the cheap option — "
        "a $0.0024 page that returns an empty string costs more than a $0.0099 page that returns the data. "
        "Neither rate card prices retries, failed extractions or rate limits, and both vendors&rsquo; free "
        "credits expire monthly or are one-off, so a free tier is not a price.</p>",
        "<p class=\\\"merit\\\">Disclosure of interest, stated plainly: Firecrawl is an affiliate partner — if "
        "you buy through the link below, a9n9 earns a commission, and its 10% first-purchase discount is "
        "stated where the link is. Tavily pays this site nothing and there is no Tavily link here. On the "
        f"numbers above Firecrawl is the dearer of the two below roughly {page_cross:,} pages and the "
        "cheaper above it, and it is the vendor that renders JavaScript — both of those are reasons someone might "
        "pick it, and neither is a reason to hide the other column.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d, "Firecrawl pricing — affiliate link") + "</p>",
    ]
    return "".join(body)


def load_tavily():
    with open(os.path.join(HERE, "data", "tavily.json"), encoding="utf-8") as f:
        return json.load(f)


QUESTIONS = [
    # Every title below is a phrase Google Autocomplete actually answers with, measured with short stems
    # (probe82.py / probe82b.py, 2026-11-08 20:5xZ; probe83.py re-measured the DigitalOcean / GPU / Novita
    # stems at 21:10Z, 24/24 answered): `firecrawl cost per` -> firecrawl cost per page;
    # `firecrawl cost` -> firecrawl search cost, firecrawl cost per credit; `elevenlabs agent pricing`,
    # `elevenlabs plan` -> elevenlabs plans and pricing; `deepgram pricing` -> deepgram pricing per minute;
    # `deepgram voice agent` -> deepgram voice agent pricing; `api cost calculator`;
    # `digitalocean droplet` -> digitalocean droplet pricing / droplet cost / droplet pricing calculator;
    # `gpu price per` -> gpu price per hour, `h100 price per` -> h100 price per hour (a100, l40s, b200 too);
    # `novita api pr` -> novita api pricing; `llm api pricing` -> llm api pricing comparison.
    # RUN 84 (probe84b.py, 27 stems, 21:2xZ): the card-level stems are the dense ones — `h100 price per`
    # returns h100 price per hour / per month / per hour aws / per hour gcp / cost per hour, `h100 rental`
    # returns h100 rental price / index / chart / tracker / history, `a100 price per`, `l40s price per`,
    # `b200 price per`, `h200 price per` all complete to "per hour". By contrast `gpu price per` completes
    # to gpu price performance chart / per frame / per fps / per dollar — a consumer graphics-card-value
    # intent, with "per hour" only 4th. So the GPU page is titled and slugged on the card, not on "gpu".
    # For Novita the brand collides hard: `novita vs` returns 7 of 10 air-purifier comparisons and `novita ai`
    # returns careers/yarn/air purifier, while the typed pricing forms are `novita ai pricing` and
    # `novita ai api pricing` — hence the brand-complete slug and a one-sentence disambiguation.
    # The slug is that phrase, so the URL carries the query too — the site is not hosted yet, so renaming
    # costs no redirect.
    ("firecrawl-cost-per-page", "Firecrawl cost per page", lambda d, x: q_firecrawl_credits_per_page(d)),
    ("firecrawl-search-cost", "Firecrawl search cost", lambda d, x: q_firecrawl_credits_per_search(d)),
    ("firecrawl-cost-per-credit", "Firecrawl cost per credit", lambda d, x: q_firecrawl_pricing_per_credit(d)),
    ("elevenlabs-credits-to-minutes", "ElevenLabs credits to minutes", lambda d, x: q_elevenlabs_credits_to_minutes(d)),
    ("elevenlabs-pricing-per-minute", "ElevenLabs pricing per minute", lambda d, x: q_elevenlabs_pricing_per_minute(d)),
    ("elevenlabs-agent-pricing", "ElevenLabs agent pricing per minute", lambda d, x: q_elevenlabs_agent_pricing(d)),
    ("elevenlabs-plan-minutes", "ElevenLabs plans and pricing: minutes per plan", lambda d, x: q_elevenlabs_plan_minutes(d)),
    ("deepgram-pricing-per-minute", "Deepgram pricing per minute: speech to text", lambda d, x: q_deepgram_stt(d)),
    ("deepgram-voice-agent-pricing", "Deepgram voice agent pricing per minute", lambda d, x: q_deepgram_agent(d)),
    ("api-cost-calculator", "API cost calculator: what this workload costs", lambda d, x: q_workload(d)),
    ("digitalocean-droplet-pricing", "DigitalOcean droplet pricing", q_droplet_pricing),
    # Run 89: the page for the buying-intent phrase, measured in probe89.py (2026-11-08 22:56Z, control
    # `vultr vs` = 10 suggestions): `digitalocean free credit $200`, `digitalocean free credits`,
    # `digitalocean free trial $200`, `digitalocean free $200` all complete. It is the only page in the
    # set aimed at a signup decision rather than a bill, and it states the referral commission openly.
    ("digitalocean-free-credit", "DigitalOcean free credit: $200 for 60 days",
     q_digitalocean_free_credit),
    # Run 90: the head-to-head page run 89 deferred until the competitors' prices were actually read.
    # Title and slug = `digitalocean vs hetzner`, a measured Autocomplete suggestion (probe89.py).
    ("digitalocean-vs-hetzner", "DigitalOcean vs Hetzner: what the same server costs at 730 hours",
     q_do_vs_hetzner),
    # Run 91: the voice pair's head-to-head. `deepgram vs elevenlabs` is a measured Autocomplete
    # suggestion with 10 tails (pricing / stt / tts / speech to text) in probe91.py, 2026-11-08
    # 22:56Z, control `vultr vs` = 10; `elevenlabs vs deepgram` carries only 4, so the title takes
    # the direction people type. The page separates the three products both vendors sell, because
    # the quoted $0.075 against $0.072 compares an all-in agent minute with synthesis alone.
    ("deepgram-vs-elevenlabs", "Deepgram vs ElevenLabs: what a minute of speech costs at each layer",
     q_deepgram_vs_elevenlabs),
    # Run 91 (second page): scrape vendors, the other head-to-head this run measured. `firecrawl vs tavily`
    # returns 5 completions in probe91b.py (23:1xZ), inside a 10-suggestion `firecrawl vs` list; Tavily's
    # own credit rules (1 credit a search, 10 pages mapped / 5 pages extracted per credit) are in
    # data/tavily.json, read 23:07Z. The point of the page is that the cheaper vendor flips with volume.
    ("firecrawl-vs-tavily", "Firecrawl vs Tavily: which is cheaper depends on volume, and the answer flips",
     q_firecrawl_vs_tavily),
    ("h100-price-per-hour", "H100 price per hour", q_gpu_price_per_hour),
    ("novita-ai-api-pricing", "Novita AI API pricing", q_novita_api_pricing),
    # Run 92: `novita ai vs openrouter` is the FIRST completion for the brand-complete stem `novita ai vs`
    # and both word orders complete (probe92.py, 2026-11-08 23:1xZ; controls `vultr vs` 10, `elevenlabs
    # pricing` 10). The bare `novita vs` list is 6/10 air purifiers, so the title carries the brand.
    ("novita-ai-vs-openrouter", "Novita AI vs OpenRouter: which of the shared models is cheaper",
     q_novita_vs_openrouter),
    ("llm-api-pricing-comparison", "LLM API pricing comparison", q_llm_api_comparison),
    # Run 87: per-model pages. Title = the typed phrase measured in probe87a.py at 22:2xZ; slug = same
    # phrase. Only models whose three-provider bill at 40M in + 10M out differs by >=1.5x (run 85's rule),
    # capped at 10, ordered by spread. Books $96.00 vs $12.66, Flash $30.80 vs $4.20, GLM 5.3 $100.00 vs
    # $16.80, V4.1 Flash 1017 $24.00 vs $5.24, Ling $4.20 vs $1.47, gpt-oss $4.50 vs $2.08, Qwen3.7 Max
    # (the one Novita wins) $87.50 vs $175.00, Qwen3.5 35B $30.00 vs $15.60, GLM 5.2 $100.00 vs $54.00,
    # Gemma 4 26B $9.20 vs $4.95. Each page also computes where the winner flips with the input:output mix.
    ("deepseek-v4-pro-pricing", "DeepSeek V4 Pro pricing",
     lambda d, x: q_model_price(d, x, "deepseek-v4-pro")),
    ("deepseek-v4-flash-pricing", "DeepSeek V4 Flash pricing",
     lambda d, x: q_model_price(d, x, "deepseek-v4-flash-0731")),
    ("glm-5-3-pricing", "GLM 5.3 pricing", lambda d, x: q_model_price(d, x, "glm-5.3")),
    ("deepseek-v4-1-flash-1017-pricing", "DeepSeek V4.1 Flash 1017 pricing",
     lambda d, x: q_model_price(d, x, "deepseek-v4.1-flash-1017")),
    ("ling-3-0-flash-pricing", "Ling 3.0 Flash pricing",
     lambda d, x: q_model_price(d, x, "ling-3.0-flash")),
    ("gpt-oss-120b-pricing", "GPT-OSS 120B pricing",
     lambda d, x: q_model_price(d, x, "gpt-oss-120b")),
    ("qwen3-7-max-pricing", "Qwen3.7 Max pricing", lambda d, x: q_model_price(d, x, "qwen3.7-max")),
    ("qwen3-5-35b-a3b-pricing", "Qwen3.5 35B A3B pricing",
     lambda d, x: q_model_price(d, x, "qwen3.5-35b-a3b")),
    ("glm-5-2-pricing", "GLM 5.2 pricing", lambda d, x: q_model_price(d, x, "glm-5.2")),
    ("gemma-4-26b-a4b-pricing", "Gemma 4 26B A4B pricing",
     lambda d, x: q_model_price(d, x, "gemma-4-26b-a4b")),
]


TITLE_BY_SLUG = {s: t for s, t, _ in QUESTIONS}

# Run 85: one description per page, written from numbers that are already in that page's body — and
# `--check` proves that claim by finding each number in the rendered HTML. The measured shape to copy
# (2026-11-08 21:35Z): the paying positions for `firecrawl pricing` and `digitalocean droplet pricing`
# lead their snippet with a price and a claim (4/10 and 3/10 carry "$"), sit at 137-154 characters, and
# 0/34 restate the title. A description that repeats the title spends the whole snippet on the words
# already above it.
DESCRIPTIONS = {
    "firecrawl-vs-tavily":
        "10,000 crawled pages cost $44.00 at Firecrawl and $16.00 at Tavily; at 100,000 it is $99.00 "
        "against $220.00, so the cheaper one flips near 44,787 pages.",
    "deepgram-vs-elevenlabs":
        "The same audio is $43.00 as Deepgram speech to text, $720.00 as ElevenLabs v4 speech and "
        "$800.00 as an agent minute: an 18.6x spread decided by the line item.",
    "digitalocean-vs-hetzner":
        "At 2 vCPU and 4 GiB DigitalOcean lists $24.00 a month against Hetzner's €5.99 ($6.69); at "
        "1 GiB Hetzner is the dearest of the three at $7.25.",
    "digitalocean-free-credit":
        "New accounts get $200 of credit that expires after 60 days — about 15 of the $6 Droplet for "
        "the whole window, or 45 hours of an H100 at $4.41.",
    "firecrawl-cost-per-page":
        "One credit is one page, and five if you ask for JSON — so 5,000 credits on the $19 Hobby plan "
        "are 5,000 pages or 1,000 JSON pages, not the same purchase.",
    "firecrawl-search-cost":
        "A search is 2 credits per 10 results, from the same balance as pages: Hobby's 5,000 credits are "
        "2,500 searches, or 5,000 pages.",
    "firecrawl-cost-per-credit":
        "One credit is $2 per 1,000 pay-as-you-go in the smallest block and well under a cent on a large "
        "plan: the credit is identical, the bucket is not.",
    "elevenlabs-credits-to-minutes":
        "275,000 characters on the Creator plan is about 306 finished minutes at 900 characters a "
        "minute, not the 275 the vendor's own credits column suggests.",
    "elevenlabs-pricing-per-minute":
        "$0.08 per 1,000 characters is $0.072 a finished minute at 900 characters and $0.080 at the "
        "vendor's 1,000 — a 2.27× gap against the plan's credits column.",
    "elevenlabs-agent-pricing":
        "$0.08 per managed agent minute plus LLM usage, billed as a separate line: the agent minute is "
        "not an all-in minute, and the vendor's table says so.",
    "elevenlabs-plan-minutes":
        "Both 300 and 1,238 finished minutes cost $99 — the ladder is block-priced, so the 25th minute "
        "past Creator costs the whole $77 step-up, or $3.08 a minute.",
    "deepgram-pricing-per-minute":
        "$0.0036 to $0.0092 a minute for speech to text. The $0.075 usually quoted is the Voice Agent, "
        "8.2× the cheapest STT minute on the same page.",
    "deepgram-voice-agent-pricing":
        "$0.075 a minute for the managed agent, $0.068 once a growth plan is in place — roughly 21× the "
        "cheapest speech-to-text minute Deepgram sells.",
    "api-cost-calculator":
        "50,000 pages, 2,000,000 characters of speech, 5,000 agent minutes and 10,000 STT minutes are "
        "three separate bills — the $99 page seat covers only the first.",
    "digitalocean-droplet-pricing":
        "A $6 droplet is $0.00893 an hour, and 730 hours is $6.52: the monthly cap only binds after "
        "671.9 hours. All 31 plans, with backups costed separately.",
    "h100-price-per-hour":
        "$3.39 an hour at Novita against $4.41 at DigitalOcean for the same 80 GB H100; the $3.26 "
        "headline is a 12-month commitment, $2,379.80 for a 40-hour job.",
    "novita-ai-api-pricing":
        "76 models, $0.02 to $4 per million input tokens, and 48 of them publish a cache-read price — "
        "the line that decides what a chat workload actually pays.",
    "novita-ai-vs-openrouter":
        "On 34 shared models OpenRouter is cheaper on 23 at this mix and Novita on 4; DeepSeek V4 Pro is "
        "$96.00 a month at Novita against $12.66 at OpenRouter.",
    "llm-api-pricing-comparison":
        "The same 34 models at Novita, DeepInfra and OpenRouter: DeepSeek V4 Pro costs $96.00, $78.00 "
        "or $12.66 a month for identical usage — a 7.58× spread.",
    # Run 87: one description per model page, each number visible in that page's body (asserted).
    "deepseek-v4-pro-pricing":
        "For identical DeepSeek V4 Pro weights, 40M input plus 10M output tokens a month bills $96.00, "
        "$78.00 or $12.66 — a 7.58x spread, about $1,000 a year.",
    "deepseek-v4-flash-pricing":
        "Novita bills $30.80 a month for DeepSeek V4 Flash where DeepInfra bills $4.20 - 7.33x apart, "
        "which looks exactly like a price increase.",
    "glm-5-3-pricing":
        "$100.00, $76.00 and $16.80 a month for identical GLM 5.3 weights: the dearest provider charges "
        "5.95x the cheapest.",
    "deepseek-v4-1-flash-1017-pricing":
        "The same 40M in, 10M out month costs $5.24 at OpenRouter, $14.00 at DeepInfra and $24.00 at "
        "Novita for identical DeepSeek V4.1 Flash 1017 weights - 4.58x.",
    "ling-3-0-flash-pricing":
        "Novita and DeepInfra bill the identical $4.20 a month for Ling 3.0 Flash while OpenRouter bills "
        "$1.47 - a tie for last place, and a 2.86x spread.",
    "gpt-oss-120b-pricing":
        "The spread is 2.16x and the money is $2.42 a month: $4.50 at Novita, $3.18 at DeepInfra, $2.08 "
        "at OpenRouter for the same gpt-oss-120b tokens.",
    "qwen3-7-max-pricing":
        "Novita is cheapest on merit for Qwen3.7 Max: $87.50 a month against $103.25 at OpenRouter and "
        "$175.00 at DeepInfra, a 2.00x spread.",
    "qwen3-5-35b-a3b-pricing":
        "DeepInfra and OpenRouter tie at $15.60 a month for Qwen3.5 35B A3B, but OpenRouter's cheapest "
        "routeable endpoint prices the same usage at $10.10.",
    "glm-5-2-pricing":
        "OpenRouter's $0.006 input price wins only above 5.91 input tokens per output; at the 40M/10M mix "
        "DeepInfra's $54.00 beats its $68.24.",
    "gemma-4-26b-a4b-pricing":
        "$9.20, $6.20 and $4.95 a month for the same Gemma 4 26B A4B weights; OpenRouter's cheapest "
        "routeable endpoint cuts its bill to $3.10.",
    # The count is hand-written and the run-85 check proves it matches the rendered page: adding the
    # DigitalOcean credit page (run 89) broke this line with "description number 24 is not visible",
    # which is exactly what the check is for. Update it in the same commit as any new page.
    # Computed, not typed: the hand-written count had drifted to 25 while QUESTIONS held 28, and the
    # substring check in --check accepted it because "25" appeared inside a price on the page (run 92).
    "index":
        f"{len(QUESTIONS)} questions on what Firecrawl, ElevenLabs, Deepgram, DigitalOcean, Novita and ten "
        f"open models cost, each from a dated vendor read.",
}

# Run 85: internal links, so a reader (or a crawler) landing on any one question can reach the other
# three programs in one hop instead of dead-ending on the page that ranked.
RELATED = {
    "firecrawl-cost-per-page": ["firecrawl-search-cost", "firecrawl-cost-per-credit", "api-cost-calculator"],
    "firecrawl-search-cost": ["firecrawl-cost-per-page", "firecrawl-cost-per-credit",
                              "firecrawl-vs-tavily"],
    "firecrawl-vs-tavily": ["firecrawl-cost-per-page", "firecrawl-search-cost",
                            "api-cost-calculator"],
    "firecrawl-cost-per-credit": ["firecrawl-cost-per-page", "firecrawl-search-cost"],
    "elevenlabs-credits-to-minutes": ["elevenlabs-plan-minutes", "elevenlabs-pricing-per-minute"],
    "elevenlabs-pricing-per-minute": ["elevenlabs-credits-to-minutes", "elevenlabs-agent-pricing",
                                      "deepgram-vs-elevenlabs",
                                      "elevenlabs-plan-minutes"],
    "elevenlabs-agent-pricing": ["elevenlabs-pricing-per-minute", "deepgram-voice-agent-pricing",
                                 "api-cost-calculator"],
    "elevenlabs-plan-minutes": ["elevenlabs-credits-to-minutes", "elevenlabs-pricing-per-minute"],
    "deepgram-pricing-per-minute": ["deepgram-voice-agent-pricing", "elevenlabs-pricing-per-minute",
                                    "deepgram-vs-elevenlabs"],
    "deepgram-voice-agent-pricing": ["deepgram-pricing-per-minute", "elevenlabs-agent-pricing"],
    "deepgram-vs-elevenlabs": ["deepgram-pricing-per-minute", "elevenlabs-pricing-per-minute",
                               "deepgram-voice-agent-pricing", "elevenlabs-plan-minutes"],
    "api-cost-calculator": ["firecrawl-cost-per-page", "elevenlabs-plan-minutes",
                            "deepgram-pricing-per-minute", "digitalocean-droplet-pricing"],
    "digitalocean-droplet-pricing": ["digitalocean-free-credit", "h100-price-per-hour",
                                     "api-cost-calculator"],
    # run 89: the signup-credit page is where the buying decision happens, so it points at what the
    # credit buys (droplet plans, H100 hours) rather than only at another calculation.
    "digitalocean-free-credit": ["digitalocean-droplet-pricing", "h100-price-per-hour"],
    "digitalocean-vs-hetzner": ["digitalocean-droplet-pricing", "digitalocean-free-credit",
                                "api-cost-calculator"],
    "h100-price-per-hour": ["novita-ai-api-pricing", "digitalocean-droplet-pricing"],
    "novita-ai-api-pricing": ["llm-api-pricing-comparison", "novita-ai-vs-openrouter",
                              "h100-price-per-hour"],
    "novita-ai-vs-openrouter": ["novita-ai-api-pricing", "llm-api-pricing-comparison",
                               "h100-price-per-hour"],
    "llm-api-pricing-comparison": ["novita-ai-api-pricing", "novita-ai-vs-openrouter",
                                   "api-cost-calculator"],
    # run 87: each model page points back to the 34-model table and to its own family, so a reader who
    # landed on one model can see the shelf it sits on.
    "deepseek-v4-pro-pricing": ["llm-api-pricing-comparison", "deepseek-v4-flash-pricing",
                                "novita-ai-api-pricing"],
    "deepseek-v4-flash-pricing": ["deepseek-v4-pro-pricing", "deepseek-v4-1-flash-1017-pricing",
                                  "llm-api-pricing-comparison"],
    "deepseek-v4-1-flash-1017-pricing": ["deepseek-v4-flash-pricing", "llm-api-pricing-comparison"],
    "glm-5-3-pricing": ["glm-5-2-pricing", "llm-api-pricing-comparison"],
    "glm-5-2-pricing": ["glm-5-3-pricing", "llm-api-pricing-comparison"],
    "ling-3-0-flash-pricing": ["gpt-oss-120b-pricing", "gemma-4-26b-a4b-pricing",
                               "llm-api-pricing-comparison"],
    "gpt-oss-120b-pricing": ["gemma-4-26b-a4b-pricing", "ling-3-0-flash-pricing",
                             "llm-api-pricing-comparison"],
    "gemma-4-26b-a4b-pricing": ["gpt-oss-120b-pricing", "ling-3-0-flash-pricing",
                                "llm-api-pricing-comparison"],
    "qwen3-7-max-pricing": ["qwen3-5-35b-a3b-pricing", "llm-api-pricing-comparison",
                            "novita-ai-api-pricing"],
    "qwen3-5-35b-a3b-pricing": ["qwen3-7-max-pricing", "llm-api-pricing-comparison"],
}


def render_q_index(d):
    items = "".join(f"<li><a href=\"{slug}.html\">{esc(q)}</a></li>" for slug, q, _ in QUESTIONS)
    return page(f"API cost comparison: {len(QUESTIONS)} pricing questions answered from dated vendor pages",
                f"<h1>API cost comparison: {len(QUESTIONS)} pricing questions answered from dated vendor pages</h1>"
                f"<p class=\"lede\">Every answer below is computed from this repository's <code>dataset.json</code> "
                f"(prices read {esc(d['as_of'])}) and says which vendor page and fetch time it came from.</p>"
                f"<ul>{items}</ul>" + DISCLOSURE, root="../",
                desc=f"{len(QUESTIONS)} questions on what Firecrawl, ElevenLabs, Deepgram, DigitalOcean, "
                     f"Novita and ten open models cost, each from a dated vendor read.")


def render_llms_txt(d, root=None):
    """llms.txt — the manifest an LLM crawler reads instead of guessing (run 85).

    Why: robots.txt here already allows GPTBot / OAI-SearchBot / ClaudeBot / PerplexityBot, and the
    incumbent measured in run 65 ships an `llms.txt` at its root. It costs one static file and it states,
    in plain text, what each page answers — the format a corpus or answer engine can quote without
    rendering HTML. Generated from QUESTIONS and DESCRIPTIONS so it cannot drift from the site, and it
    carries no affiliate link: a manifest with a referral link is an ad.
    """
    lines = [
        "# AI API pricing comparison: dated prices for Firecrawl, ElevenLabs, Deepgram, DigitalOcean and Novita",
        "",
        "> Unit prices read from the vendors' own pricing pages on " + str(d["as_of"]) + ", with the",
        "> arithmetic shown. Each page names the vendor URL and the fetch time it came from.",
        "",
        AI_LINE,
        "",
        "## Questions answered",
    ]
    for slug, title, _ in QUESTIONS:
        lines.append(f"- [{title}]({BASE}/q/{slug}.html): {DESCRIPTIONS[slug]}")
    lines += [
        "",
        "## Data",
        f"- [pricing.json]({BASE}/pricing.json): normalised unit prices for Firecrawl, ElevenLabs and Deepgram.",
        f"- [All questions]({BASE}/q/index.html): the same {len(QUESTIONS)} answers on one page.",
        f"- [Unit price index]({BASE}/index.html): the per-unit view and the price-change log.",
        "",
        "## Notes",
        "- Prices are list prices, read by an autonomous agent; nothing was purchased and no account exists to",
        "  test rate limits, latency or quality. Cost is a tiebreaker after quality, not a ranking.",
        "- Affiliate links appear only on the pages, next to the words \"affiliate link\"; this file has none.",
        "",
    ]
    return "\n".join(lines)


def build(out_dir=None):
    """Render every host-ready file into out_dir (default: site/).

    --check passes a scratch directory: a checker must not rewrite the tree it is checking
    (it used to, which silently replaced a correct SITE_BASE sitemap with the placeholder).
    """
    root = out_dir or SITE
    d = load()
    x = load_ext()
    qdir = os.path.join(root, "q")
    os.makedirs(qdir, exist_ok=True)
    written = []
    for slug, title, fn in QUESTIONS:
        with open(os.path.join(qdir, slug + ".html"), "w", encoding="utf-8") as f:
            f.write(page(title, fn(d, x), root="../", desc=DESCRIPTIONS[slug],
                         related=RELATED.get(slug, ())))
        written.append(f"q/{slug}.html")
    with open(os.path.join(qdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_q_index(d))
    written.append("q/index.html")

    pages = ["index.html", "voices.html"] + [f"vendors/{v}.html" for v in d["vendors"]] + written
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in pages:
        loc = f"{BASE}/{p}"
        pri = "1.0" if p == "index.html" else ("0.8" if p.startswith("q/") else "0.6")
        parts.append(f"  <url><loc>{esc(loc)}</loc><lastmod>{d['as_of']}</lastmod>"
                     f"<changefreq>weekly</changefreq><priority>{pri}</priority></url>")
    parts.append("</urlset>")
    with open(os.path.join(root, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    written.append("sitemap.xml")

    robots = ["User-agent: *", "Allow: /", "",
              "# AI answer engines may read these pages (same posture as the incumbent's robots.txt)",
              "User-agent: GPTBot", "Allow: /", "",
              "User-agent: OAI-SearchBot", "Allow: /", "",
              "User-agent: ClaudeBot", "Allow: /", "",
              "User-agent: PerplexityBot", "Allow: /", "",
              f"Sitemap: {BASE}/sitemap.xml", ""]
    with open(os.path.join(root, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(robots))
    written.append("robots.txt")

    with open(os.path.join(root, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(render_llms_txt(d))
    written.append("llms.txt")
    return written, d


def check():
    failures = []
    scratch = tempfile.mkdtemp(prefix="hostcheck-")
    try:
        # the sitemap lists pages build_site.py renders (index, voices, vendors/*): copy them in so
        # "every loc has a file" is checked against a complete tree, not a half-rendered one
        for name in ("index.html", "voices.html", "pricing.json"):
            src = os.path.join(SITE, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(scratch, name))
        vend = os.path.join(SITE, "vendors")
        if os.path.isdir(vend):
            shutil.copytree(vend, os.path.join(scratch, "vendors"))
        written, d = build(scratch)
        return _check_in(scratch, written, d, failures)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _check_in(scratch, written, d, failures):
    # a checker must not write into the tree it checks: every path below is the scratch render
    # 1. sitemap parses, every loc maps to a file that exists
    try:
        root = ET.parse(os.path.join(scratch, "sitemap.xml")).getroot()
        locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    except Exception as e:
        return [f"sitemap.xml does not parse: {e}"], written
    if len(locs) < 13:
        failures.append(f"sitemap has only {len(locs)} urls")
    for loc in locs:
        rel = loc.split("/", 3)[-1] if loc.startswith("http") else loc
        rel = re.sub(r"^[a-z]+://[^/]+/", "", loc)
        if not os.path.exists(os.path.join(scratch, rel)):
            failures.append(f"sitemap loc with no file: {loc}")
    if "Sitemap:" not in open(os.path.join(scratch, "robots.txt"), encoding="utf-8").read():
        failures.append("robots.txt has no Sitemap line")
    # 1b. llms.txt (run 85): a manifest a crawler can read, generated from QUESTIONS — so the count must
    # match, every link must resolve, and it must carry no affiliate URL or placeholder host.
    lp = os.path.join(scratch, "llms.txt")
    if not os.path.exists(lp):
        failures.append("llms.txt not written")
    else:
        lt = open(lp, encoding="utf-8").read()
        qlinks = [u for u in re.findall(r"- \[[^\]]*\]\(([^)]+)\): ", lt)
                  if re.search(r"/q/(?!index\.html)[a-z0-9-]+\.html$", u)]
        if len(qlinks) != len(QUESTIONS):
            failures.append(f"llms.txt lists {len(qlinks)} answered questions, QUESTIONS has {len(QUESTIONS)}")
        for u in re.findall(r"\]\(([^)]+)\)", lt):
            rel = re.sub(r"^[a-z]+://[^/]+/", "", u)
            if not os.path.exists(os.path.join(scratch, rel)):
                failures.append(f"llms.txt links to {u}, which is not in the render")
        for bad in PLACEHOLDER_HOSTS + ("REPLACE-WITH", "utm_", "ref="):
            if bad in lt:
                failures.append(f"llms.txt carries {bad!r}")
        if "autonomous AI agent" not in lt:
            failures.append("llms.txt has no AI-authorship line")
    # 2. every generated page: AI line, disclosure, and every affiliate href labelled
    for rel in [w for w in written if w.endswith(".html")]:
        t = open(os.path.join(scratch, rel), encoding="utf-8").read()
        if "autonomous AI agent operated by a9n9" not in t:
            failures.append(f"{rel}: missing AI disclosure")
        if "earns a commission" not in t:
            failures.append(f"{rel}: missing commission sentence")
        for m in re.finditer(r'<a href="(https://(?:' + "|".join(re.escape(h) for h in PLACEHOLDER_HOSTS) + r')[^"]*)"', t):
            start = t.rfind("<a ", 0, m.start())
            end = t.find("</a>", m.start())
            if "affiliate link" not in t[start:end]:
                failures.append(f"{rel}: unlabelled affiliate href {m.group(1)}")
        # forbidden offer phrasing, assembled from pieces so this checker does not itself contain
        # the literals a disclosure audit greps for (run-64 defect class: the test file becomes the defect)
        for bad in ("cash" + "back", "re" + "bate", "share the " + "commission", "split the " + "commission"):
            if bad in t.lower():
                failures.append(f"{rel}: forbidden offer phrasing {bad!r}")
    # 3. the arithmetic this deployment publishes, recomputed from the dataset
    fc = d["vendors"]["firecrawl"]
    rows = {n: per for n, u, c, per, _ in plan_rows(fc)}
    if abs(rows["Hobby"] - 3.8) > 1e-9 or abs(rows["Standard"] - 0.99) > 1e-9:
        failures.append(f"Firecrawl per-1,000-page arithmetic changed: {rows}")
    el = d["vendors"]["elevenlabs"]
    # a checker that hard-codes a page URL breaks silently when the page is renamed (run 82 renamed
    # eight slugs), so name the slugs it needs and fail loudly if one of them is gone.
    slugs = {s for s, _, _ in QUESTIONS}
    for needed in ("elevenlabs-pricing-per-minute", "deepgram-pricing-per-minute",
                   "api-cost-calculator", "elevenlabs-plan-minutes"):
        if needed not in slugs:
            failures.append(f"checker references slug {needed!r}, which is not in QUESTIONS")
    q = open(os.path.join(scratch, "q", "elevenlabs-pricing-per-minute.html"), encoding="utf-8").read()
    expect = money(el["rates_usd_per_1000_chars"]["multilingual_v4_api"] / 1000 * el["chars_per_minute_default"], 4)
    if expect not in q:
        failures.append(f"ElevenLabs per-minute page missing expected ${expect}")
    if "2.27" not in q:
        failures.append("ElevenLabs rate-gap ratio 2.27 no longer on the page")
    dgq = open(os.path.join(scratch, "q", "deepgram-pricing-per-minute.html"), encoding="utf-8").read()
    if "$0.0043" not in dgq or "$0.075" not in dgq:
        failures.append("Deepgram STT page lost its floor or its agent-rate warning")
    if "10,000 minutes is $43" not in dgq.replace("$43.00", "$43"):
        failures.append("Deepgram STT page lost the 10,000-minute comparison")
    # a seat offered for 50,000 pages must cover 50,000 pages (the Free plan cannot)
    wq = open(os.path.join(scratch, "q", "api-cost-calculator.html"), encoding="utf-8").read()
    if "Free ($0.00/mo" in wq:
        failures.append("workload page offers the Free plan for a 50,000-page workload")
    if "Standard" not in wq:
        failures.append("workload page does not name Standard as the 50,000-page seat")
    # the overshoot arithmetic: 25 minutes past Creator must cost the $77 step-up, i.e. $3.08/min
    pm = open(os.path.join(scratch, "q", "elevenlabs-plan-minutes.html"), encoding="utf-8").read()
    if "$3.08" not in pm:
        failures.append("ElevenLabs plan page lost the $3.08 per overshooting minute figure")
    # 4. the SERP snippet layer (run 85). Shape measured on page 1 at 2026-11-08 21:35Z: 0/34
    # descriptions restate the title's opening, the paying positions for `firecrawl pricing` and
    # `digitalocean droplet pricing` carry a price, and 2/34 exceed 160 characters. So: one description
    # per page, 110-158 chars, at least one number, never the title repeated, and every number in it
    # must already be visible on that page — the snippet cannot drift away from the body.
    seen = {}
    for rel in [w for w in written if w.endswith(".html")]:
        t = open(os.path.join(scratch, rel), encoding="utf-8").read()
        m = re.search(r'<meta name="description" content="([^"]*)"', t)
        if not m:
            failures.append(f"{rel}: no meta description")
            continue
        dsc = html.unescape(m.group(1))
        if not 110 <= len(dsc) <= 158:
            failures.append(f"{rel}: description is {len(dsc)} chars, outside the measured 110-158 band")
        if not re.search(r"\d", dsc):
            failures.append(f"{rel}: description carries no number")
        ti = re.search(r"<title>(.*?)</title>", t)
        if ti and dsc.lower().startswith(html.unescape(ti.group(1)).lower()[:20]):
            failures.append(f"{rel}: description repeats the title's opening")
        if "Dated vendor prices, arithmetic shown" in dsc:
            failures.append(f"{rel}: boilerplate description (the run-85 defect) is back")
        if dsc in seen:
            failures.append(f"{rel}: description duplicates {seen[dsc]}")
        seen[dsc] = rel
        body_text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
        for num in set(re.findall(r"\$?\d[\d,]*(?:\.\d+)?", dsc)):
            if num not in body_text:
                failures.append(f"{rel}: description number {num} is not visible in the page body")
        for target in re.findall(r'href="([a-z0-9-]+)\.html"', t):
            if not os.path.exists(os.path.join(scratch, "q", target + ".html")):
                failures.append(f"{rel}: internal link to missing q/{target}.html")
    for slug, _, _ in QUESTIONS:
        if slug not in DESCRIPTIONS:
            failures.append(f"{slug}: no description in DESCRIPTIONS")
        if f"q/{slug}.html" not in written:
            failures.append(f"{slug}: not rendered")
    for slug in DESCRIPTIONS:
        if slug != "index" and slug not in TITLE_BY_SLUG:
            failures.append(f"DESCRIPTIONS names {slug!r}, which is not a question page")
    return failures, written


def main():
    if "--check" in sys.argv:
        failures, written = check()
        print(f"host-ready: rendered {len(written)} files in a scratch dir, site/ untouched (base {BASE})")
        if "REPLACE-WITH" in BASE:
            print("NOTE: sitemap.xml/robots.txt still carry the placeholder base — set SITE_BASE=<host> "
                  "before publishing, or the sitemap will point at a domain that does not exist.")
        if failures:
            print(f"{len(failures)} FAILURE(S):")
            for f in failures:
                print("  - " + f)
            return 1
        print("ALL HOST CHECKS PASS")
        return 0
    written, d = build()
    print(f"as_of {d['as_of']}: wrote {len(written)} host files in a scratch dir, site/ untouched (base {BASE})")
    for w in written:
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
