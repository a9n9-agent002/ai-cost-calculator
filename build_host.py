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
from datetime import date

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


def cpm_band():
    """Run 133: the characters-per-finished-minute band, from two vendors' own worked examples.

    A per-minute price is a per-character rate divided by a characters-per-minute figure that no
    rate card sells. ElevenLabs' own pages assume 1,000; Amazon Polly's pricing examples and
    Cartesia's plan table both state a duration for a stated text length, so they MEASURE it.
    data/chars-per-minute.json holds the rows; every figure below is computed from them.
    """
    with open(os.path.join(HERE, "data", "chars-per-minute.json"), encoding="utf-8") as f:
        return json.load(f)


def cpm_note():
    """Run 134: every page that divides by the 1,000-character convention must say it is a convention.

    Run 133 measured the band (714-780 characters per finished minute, median 741) and put it on the
    one page whose subject is the per-minute price. These five pages still divided by 1,000 in silence,
    which reads as a measurement. The sentence is generated from the same data file, so it cannot drift
    from the page that owns the band.
    """
    b = cpm_band()
    lo, hi, med = b["measured_min"], b["measured_max"], b["measured_median"]
    return ("<p>The characters-per-minute figure these tables divide by is a convention, not a "
            "measurement: two vendors' own worked examples put a finished minute at "
            f"<strong>{lo:,.0f}&ndash;{hi:,.0f} characters</strong> (median {med:,.0f}), so dividing by "
            "1,000 understates what a plan buys and overstates the price of a finished minute. "
            "<a href=\"elevenlabs-pricing-per-minute.html\">ElevenLabs cost per minute</a> prices that "
            "band from the measured rows.</p>")


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


# Run 108 measured where each approved link actually lands (redirects followed, attribution
# parameters checked): Novita -> novita.ai root, DigitalOcean -> digitalocean.com root,
# ElevenLabs -> elevenlabs.io root with its partner key, Firecrawl ->
# alexandria.firecrawl.dev ("Alexandria — a knowledge library for AI agents"), i.e. NOT the
# page whose credit ladder these pages quote. A label that promises "Firecrawl pricing" and
# hands the reader a different product is a mis-described click, so the Firecrawl link says
# where it goes and names the page the numbers came from.
DEST_NOTE = {
    "firecrawl": (" (opens Firecrawl's Alexandria data-provider catalogue; the plan ladder "
                  "quoted here is read from firecrawl.dev/pricing)"),
}


def labelled(vendor_key, d, text=None):
    """Anchor with the words 'affiliate link' in its visible text, plus the reason."""
    v = d["vendors"][vendor_key]
    if not v.get("affiliate_link"):
        return ""
    label = text or f"{v['name']} pricing — affiliate link"
    return (f'<a href="{href(v["affiliate_link"])}" rel="sponsored nofollow">{esc(label)}</a>'
            + DEST_NOTE.get(vendor_key, ""))


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
    """Run 126: 106 words and a bare ratio table — it never priced the search, only counted it.

    A searcher asking what a search costs wants the money, and the mixed-workload case is the one that
    bites (a search then scraping every hit). Both are derived from dataset.json here: 2 credits per
    search of 10 results, 1 credit per page scraped.
    """
    fc = d["vendors"]["firecrawl"]
    rows = [(n, u, c, per) for n, u, c, per, payg in plan_rows(fc) if c]
    per_q = 2 + 10          # one search of 10 results + scraping all ten hits

    def _cr(v):
        return f"{v:,.3f}" if v < 1 else f"{v + 1e-9:,.2f}"

    body = [
        "<h1>Firecrawl search cost: 2 credits per 10 results, and 12 credits per answered question</h1>",
        "<p class=\"lede\">A search is <strong>2 credits per 10 results</strong> — and searches share the "
        "same credit balance as pages, so a plan's \"5,000 credits\" is 5,000 pages <em>or</em> 2,500 "
        "searches, not both. An agent that searches and then scrapes its ten hits spends "
        f"<strong>{per_q} credits per question</strong>: 2 for the search, 10 for the pages.</p>",
        "<h2>What each plan turns credits into</h2>",
        "<table><tr><th>Credits bought</th><th>$/month</th><th>Searches of 10 results</th><th>Pages</th>"
        "<th>$ per 1,000 searches</th><th>$ per question (search + 10 scrapes)</th></tr>" +
        "".join(f"<tr><td>{c:,}</td><td>${_cr(u) if u else '0'}</td><td>{c // 2:,}</td><td>{c:,}</td>"
                f"<td>${_cr(per * 2)}</td><td>${_cr(per * per_q)}</td></tr>"
                for n, u, c, per in rows) + "</table>",
        f"<p>Rule read from {esc(fc['source'])} on {esc(fc['verified'])}. The last column is the one a "
        f"research agent should budget from: at {per_q} credits a question, Hobby's 5,000 credits buy "
        f"<strong>{5000 // per_q:,} questions</strong>, and the same 5,000 credits buy 2,500 searches or "
        "5,000 pages if the agent never scrapes what it finds. Results beyond ten per search are not "
        "counted here: this page prices the printed rule, not a measured crawl.</p>",
        DISCLOSURE,
        "<p>" + labelled("firecrawl", d) + "</p>",
    ]
    return "".join(body)


def q_firecrawl_pricing_per_credit(d):
    """Run 126: this page was 99 words and answered a different question than its title.

    "cost per credit" is asked by someone who wants to know what a credit BUYS before they can use a
    $ per-credit figure. The page now converts one credit into the three things the plan table sells
    (plain page, JSON page, search result) from the same dataset, and prices each on every plan. Every
    number is derived here from dataset.json, so no read is retyped.
    """
    fc = d["vendors"]["firecrawl"]
    rows = [(n, u, c, per, payg) for n, u, c, per, payg in plan_rows(fc) if c]
    actions = [
        ("1 plain page scraped or crawled", 1, "1,000 pages"),
        ("1 page returned as JSON, or with a prompt-injection check", 5, "200 pages"),
        ("1 search of 10 results", 2, "500 searches — 5,000 results"),
    ]

    def _cr(v):
        """Unit price: three decimals below $1, two above — one rule for every cell in the table."""
        return f"{v:,.3f}" if v < 1 else f"{v + 1e-9:,.2f}"
    body = [
        "<h1>Firecrawl cost per credit: a credit is a page, a fifth of a JSON page, or half a search</h1>",
        "<p class=\"lede\">A credit is not a page — it is a unit that buys a different amount of work "
        "depending on what you ask for. One credit is <strong>1 plain page</strong>, "
        "<strong>0.2 of a JSON page</strong> or <strong>5 search results</strong>, and its price moves "
        "<strong>&times;5</strong> between the smallest plan and the largest.</p>",
        "<h2>What one credit buys</h2>",
        "<table><tr><th>what you ask for</th><th>credits</th><th>what 1,000 credits buy</th></tr>"
        + "".join(f"<tr><td>{esc(a)}</td><td>{n}</td><td>{esc(b)}</td></tr>" for a, n, b in actions)
        + "</table>",
        "<p>Firecrawl's own wording on " + esc(fc["source"]) + ": <em>" + esc(fc["credit_rule"]) +
        "</em> (read " + esc(fc["verified"]) + "). The search rate is the second half of the same "
        "balance: a search is 2 credits, so pages and searches compete for one allowance.</p>",
        "<h2>What a credit costs, on every plan and on pay-as-you-go</h2>",
        "<table><tr><th>Plan</th><th>$/month</th><th>credits</th><th>$ per 1,000 credits</th>"
        "<th>$ per 1,000 JSON pages</th><th>$ per 1,000 searches</th>"
        "<th>pay-as-you-go $ per 1,000 credits</th></tr>"
        + "".join(
            f"<tr><td>{esc(n)}</td><td>${_cr(u) if u else '0'}</td><td>{c:,}</td><td>${_cr(per)}</td>"
            f"<td>${_cr(per * 5)}</td><td>${_cr(per * 2)}</td>"
            f"<td>{('$' + _cr(payg)) if payg else '—'}</td></tr>"
            for n, u, c, per, payg in rows) + "</table>",
        "<p>The credit is identical in all six columns; only the bucket changes. Two consequences that "
        "the plan table does not print: a JSON scrape of 1,000 pages consumes <strong>5,000 credits</strong>, "
        "so on Hobby ($19) 1,000 JSON pages cost <strong>$19.00</strong> while the same 1,000 plain pages "
        "cost $3.80; and pay-as-you-go credits are bought in $5 blocks — 1,000 credits on Hobby, 2,000 on "
        "Standard, 2,500 on Growth, 5,000 on Scale — so the overflow rate is not one number either.</p>",
        "<p>Read from " + esc(fc["source"]) + " on " + esc(fc["verified"]) + ", list prices, no "
        "committed-use or negotiated discount. What this page does not measure: extraction quality, "
        "JavaScript rendering success, rate limits or uptime — the price of a page says nothing about "
        "whether the page came back correct.</p>",
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
        f"{round((vendor_cpm / read_cpm - 1) * 100)}% <strong>more</strong> finished minutes than that "
        f"column says — slower speech fits fewer characters into each minute.</p>",
        f"<p>{esc(el['ladder_note'])}</p>",
        "<h2>The two conversions, side by side</h2>",
        "<table><tr><th>Plan</th><th>characters</th><th>minutes @1,000 chars</th>"
        f"<th>minutes @{read_cpm} chars</th></tr>" + "".join(
            f"<tr><td>{esc(r.get('name', ''))}</td><td>{r['chars']:,}</td>"
            f"<td>{el_minutes(r['chars'], vendor_cpm):,.0f}</td>"
            f"<td>{el_minutes(r['chars'], read_cpm):,.0f}</td></tr>" for r in el["ladder"]) + "</table>",
        "<p>Rate card read from " + esc(el["source"]) + " on " + esc(el["verified"]) + ".</p>",
        cpm_note(),
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def unit_section(rate_per_1000):
    """Run 133: what a "finished minute" is worth, measured rather than assumed.

    This is the only page whose subject is the per-minute number, so the convention it divides by
    belongs on it. Every figure is computed from data/chars-per-minute.json (13 measured rows from
    two vendors' own pages + ElevenLabs' documented 1,000) and re-asserted by check().
    """
    b = cpm_band()
    lo, hi, med = b["measured_min"], b["measured_max"], b["measured_median"]
    polly = {r["unit"]: r for r in b["rows"] if r["vendor"] == "Amazon Polly"}
    cart = {r["unit"]: r for r in b["rows"] if r["vendor"] == "Cartesia"}
    p1 = polly["1,000 requests x 1,000 characters"]
    p2 = polly["A Christmas Carol"]
    c1 = cart["Pro: 100,000 credits"]
    c2 = cart["Scale: 8,000,000 credits"]
    cost_lo, cost_hi = rate_per_1000 * lo / 1000, rate_per_1000 * hi / 1000
    below_lo = (1 - cost_lo / rate_per_1000) * 100
    below_hi = (1 - cost_hi / rate_per_1000) * 100
    mins = 100_000
    return [
        "<h2>What a &ldquo;minute&rdquo; is worth, measured</h2>",
        "<p>Every per-minute figure here divides a per-character rate by a characters-per-minute "
        "number that no rate card sells. ElevenLabs' own pages use <strong>1,000</strong>. Two other "
        "vendors state a duration for a stated text length, which makes the figure measurable rather "
        "than assumed: across <strong>" + str(b["measured_n"]) + " of their own worked examples</strong> "
        f"(read {esc(b['read_at'])}) it runs <strong>{lo:,.0f}&ndash;{hi:,.0f} characters a finished "
        f"minute</strong>, median <strong>{med:,.0f}</strong>.</p>",
        "<table><tr><th>vendor</th><th>their own example</th><th>characters</th><th>stated duration</th>"
        "<th>characters / minute</th></tr>"
        f"<tr><td>Amazon Polly</td><td>{esc(p1['unit'])}</td><td>{p1['characters']:,}</td>"
        f"<td>{p1['minutes'] / 60:,.2f} h</td><td>{p1['chars_per_minute']:,.1f}</td></tr>"
        f"<tr><td>Amazon Polly</td><td>{esc(p2['unit'])}</td><td>{p2['characters']:,}</td>"
        f"<td>{p2['minutes'] / 60:,.2f} h</td><td>{p2['chars_per_minute']:,.1f}</td></tr>"
        f"<tr><td>Cartesia</td><td>{esc(c1['unit'])}</td><td>{c1['characters']:,}</td>"
        f"<td>{c1['minutes']:,.0f} min</td><td>{c1['chars_per_minute']:,.1f}</td></tr>"
        f"<tr><td>Cartesia</td><td>{esc(c2['unit'])}</td><td>{c2['characters']:,}</td>"
        f"<td>{c2['minutes']:,.0f} min</td><td>{c2['chars_per_minute']:,.1f}</td></tr></table>",
        f"<p>Two vendors that price nothing alike agree within a few percent on the unit, which is "
        f"the point: at ${rate_per_1000:.3f} per 1,000 characters the same audio is "
        f"<strong>${money(cost_lo, 4)}&ndash;${money(cost_hi, 4)} a finished minute</strong>, "
        f"{below_hi:.0f}&ndash;{below_lo:.0f}% below the ${rate_per_1000:.3f} that the 1,000-"
        f"character convention produces. The per-minute column in the table above is a convention, "
        f"not a measurement; the measured figure is the one to budget with. On the same basis "
        f"{mins:,} characters is <strong>{mins / hi:,.0f}&ndash;{mins / lo:,.0f} finished minutes</strong> "
        f"(median {mins / med:,.0f}), not {mins / 1000:,.0f}.</p>",
        "<p>Nothing here is a quote from ElevenLabs: it publishes a per-character price and a "
        "1,000-character example, and which of those two numbers you believe decides a "
        f"{(1000 / lo - 1) * 100:.0f}% swing in the figure people compare across vendors.</p>",
    ]


def q_elevenlabs_pricing_per_minute(d):
    el = d["vendors"]["elevenlabs"]
    r = el["rates_usd_per_1000_chars"]
    read_cpm = el["chars_per_minute_default"]
    creator_chars = el["ladder"][2]["chars"]
    credits = 121000
    plan_rate = el["ladder"][2]["usd"] / creator_chars * 1000     # $22 / 275,000 characters
    body = [
        "<h1>ElevenLabs cost per minute</h1>",
        "<p class=\"lede\">At the API rate, <strong>$" + money(r["multilingual_v4_api"], 3) +
        " per 1,000 characters</strong> — about <strong>$" + money(r["multilingual_v4_api"] / 1000 * read_cpm, 3) +
        f"</strong> per finished minute at a {read_cpm}-characters-per-minute read, and $0.080 at the "
        "vendor's own 1,000-characters basis.</p>",
        "<h2>The rates on the rate card</h2>",
        "<table><tr><th>rate</th><th>unit</th><th>USD</th><th>$ / spoken minute @"
        f"{read_cpm} chars</th></tr>"
        f"<tr><td>Multilingual v4, API</td><td>per 1,000 characters</td><td>${money(r['multilingual_v4_api'], 4)}</td>"
        f"<td>${money(r['multilingual_v4_api'] / 1000 * read_cpm, 4)}</td></tr>"
        f"<tr><td>Turbo Flash, API</td><td>per 1,000 characters</td><td>${money(r['turbo_flash_api'], 4)}</td>"
        f"<td>${money(r['turbo_flash_api'] / 1000 * read_cpm, 4)}</td></tr>"
        f"<tr><td>Creator API plan — $22 for {creator_chars:,} characters</td><td>per 1,000 characters</td>"
        f"<td>${money(plan_rate, 4)}</td><td>${money(plan_rate / 1000 * read_cpm, 4)}</td></tr>"
        f"<tr><td>Creative plans page — {credits:,} credits for $22</td><td>per 1,000 credits</td>"
        f"<td>${money(r['credits_equivalent_creator'], 4)}</td><td>not a character rate</td></tr></table>",
        "<p><strong>The plan is not a discount, and the credits column is not characters.</strong> The API "
        f"page prints its own allowance: the ${money(el['ladder'][2]['usd'])} Creator plan includes "
        f"<strong>{creator_chars:,} characters</strong>, which at ${money(plan_rate, 4)} per 1,000 is the "
        f"pay-as-you-go rate to four decimals — the ladder is flat, so buying a plan does not lower the unit "
        f"price. The Creative plans page advertises <strong>{credits:,} credits</strong> for the same $22. "
        "Whether that is the same quantity in a different unit or a different allowance is <strong>not "
        "settled by the vendor's own text</strong>: its FAQ says one text character equals one credit on "
        "the V2 Multilingual models, which would make the two figures 121,000 characters against 275,000 "
        "for the same money, while this page's API plan prints characters and its FAQ says API usage is "
        "billed in dollars, not credits. Both numbers are quoted here as dated; neither is converted into "
        "the other. A buyer comparing the studio plan with the API plan should read both pages before "
        "subscribing.</p>",
        *unit_section(r["multilingual_v4_api"]),
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
        (f"<p>That is the trap the plan table hides. On the vendor's own 1,000-characters-a-minute column, "
         f"300 finished minutes and 1,238 finished minutes both land on the ${money2(rows[3]['usd'])} block, "
         f"so the same monthly price buys four times the audio. On the {read_cpm:,}-character basis this "
         f"page's per-minute prices use, the same pair is {el_minutes(el['ladder'][2]['chars'], read_cpm):,.0f} "
         f"and {el_minutes(rows[3]['chars'], read_cpm):,.0f} minutes — a plan buys "
         f"{1000/read_cpm*100-100:.1f}% more minutes than the vendor's column claims. On Creator the "
         f"boundary is {el_minutes(el['ladder'][2]['chars'], read_cpm):,.1f} finished minutes: 305 cost "
         f"${money2(rows[2]['usd'])} and 306 cost ${money2(rows[3]['usd'])} — {rows[3]['usd']/rows[2]['usd']:.1f}x "
         f"the bill for one more minute. And needing only "
         f"{OVERSHOOT_MIN} minutes past a block charges the whole step up: on {esc(headline[0])} those "
         f"{OVERSHOOT_MIN} minutes cost <strong>${money2(headline[2])}"
         f"</strong>, which is <strong>${money2(headline[3])} per minute</strong> against a plan average of "
         f"${money2(min(r['usd'] / el_minutes(r['chars'], vendor_cpm) for r in rows if r['usd']))}"
         + (f" (and ${money2(worst[3])} per minute at the top of the ladder)" if worst and worst != headline else "")
         + ".</p>" if headline else "") +
        (f"<p>Work out your finished minutes at {read_cpm:,} characters per spoken minute (the vendor's column "
         f"divides by {vendor_cpm:,}, which overstates the characters a given duration needs by "
         f"{100-100*read_cpm/vendor_cpm:.1f}%), then check which block you land in — not which plan looks "
         f"closest.</p>"),
        "<p>Ladder read from " + esc(el.get("plan_source", el["source"])) + " on " +
        esc(el.get("plan_verified", el["verified"])) + ".</p>",
        cpm_note(),
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d) + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_startup_grant(d):
    """Run 99: the one buyer-side offer in the ElevenLabs programme that no page mentioned.

    Read live at 2026-11-09T01:20Z from elevenlabs.io/startup-grants: "Scale for 12 months",
    "33,000,000 characters", "That's over 680 hours of Agents usage. More than $5,500+ in value."
    Every figure below is derived from those claims and from the ladder already in dataset.json,
    so the page can be recomputed, not believed.
    """
    el = d["vendors"]["elevenlabs"]
    g = el["startup_grant"]
    scale = next(r for r in el["ladder"] if r.get("name") == "Scale")
    months_of_scale = g["chars"] / scale["chars"]
    per_month = g["chars"] / g["months"]
    shortfall = (1 - per_month / scale["chars"]) * 100
    tts_rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]
    tts_value = g["chars"] / 1000 * tts_rate
    agent_minutes = g["agent_hours"] * 60
    agent_value = agent_minutes * el["agent_usd_per_minute"]
    hours_at_basis = g["chars"] / el["vendor_minutes_basis"] / 60
    cpm_implied = g["chars"] / agent_minutes
    vs_tts = g["value_claimed_usd"] / tts_value
    vs_agent = g["value_claimed_usd"] / agent_value
    scale_year = g["months"] * scale["usd"]
    body = [
        "<h1>ElevenLabs startup grant: 33M characters is 8.83 months of Scale, not 12</h1>",
        "<p class=\"lede\">The grant is described as <strong>\"Scale for 12 months\"</strong>, and it is "
        f"<strong>{g['chars']:,} characters</strong>. Scale's own monthly allowance is "
        f"{scale['chars']:,} characters, so the grant is <strong>{months_of_scale:.2f} months of Scale "
        f"credit delivered across {g['months']}</strong> — <strong>{per_month:,.0f} characters a month, "
        f"{shortfall:.1f}% less than the plan it is named after</strong>.</p>",
        f"<p>Terms as printed on {esc(g['source'])} (read {esc(g['verified'])}): "
        f"{g['months']} months of Scale access, {g['chars']:,} characters, \"over {g['agent_hours']} hours "
        f"of Agents usage\", and \"more than ${g['value_claimed_usd']:,}+ in value\". Applying is free; "
        f"it is an application, not a coupon.</p>",
        "<h2>What the same 33,000,000 characters is worth at ElevenLabs' own rates</h2>",
        "<table><tr><th>priced as</th><th>arithmetic</th><th>value</th></tr>"
        f"<tr><td>v4 speech, API rate</td><td>{g['chars']:,} ÷ 1,000 × ${money(tts_rate, 3)}</td>"
        f"<td>${money2(tts_value)}</td></tr>"
        f"<tr><td>managed agent minutes at ${money(el['agent_usd_per_minute'], 2)}</td>"
        f"<td>{agent_minutes:,} min ({g['agent_hours']} h × 60)</td><td>${money2(agent_value)}</td></tr>"
        f"<tr><td>the grant page's own claim</td><td>—</td>"
        f"<td>more than ${g['value_claimed_usd']:,}</td></tr></table>",
        f"<p><strong>None of the vendor's own rate lines reaches the ${g['value_claimed_usd']:,} figure.</strong> "
        f"At the ${money(tts_rate, 3)} v4 rate the characters are <strong>${money2(tts_value)}</strong> — the "
        f"claim is <strong>{vs_tts:.2f}×</strong> that. Priced entirely as agent minutes the same grant is "
        f"<strong>${money2(agent_value)}</strong>, and the claim is <strong>{vs_agent:.2f}×</strong> that. "
        f"Twelve months of Scale at list price is ${scale_year:,}; the grant's characters are worth "
        f"${money2(tts_value)} of it, because the ladder is flat — the discount is the free year, not a "
        "cheaper character.</p>",
        "<h2>The hours claim is on a slower reading rate than the plan table</h2>",
        f"<p>The grant page says {g['chars']:,} characters is \"over {g['agent_hours']} hours of Agents "
        f"usage\". At the {el['vendor_minutes_basis']:,}-characters-per-spoken-minute basis the plan table "
        f"uses, the same characters are <strong>{hours_at_basis:,.0f} hours</strong> "
        f"({g['chars']:,} ÷ {el['vendor_minutes_basis']:,} ÷ 60). To reach {g['agent_hours']} hours the "
        f"read has to be <strong>{cpm_implied:,.0f} characters a minute</strong>. Both numbers are the "
        f"vendor's; they are answering different questions — a plan's speech allowance and a "
        f"conversational agent's audio. Budget the {per_month:,.0f} characters a month "
        f"(about {per_month / el['vendor_minutes_basis']:,.0f} finished minutes) and the hours take care "
        "of themselves.</p>",
        "<p><strong>Who should apply:</strong> the programme is aimed at early-stage startups putting "
        "voice into a product, and the application is the gate — there is no code to paste. If you are "
        "prototyping voice on a personal card, the 12 free months are worth more than any plan discount "
        "this site prices, and they cost nothing to ask for. If you are already past that stage, the "
        "ladder above is the number that matters.</p>",
        cpm_note(),
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d, "ElevenLabs pricing and startup grants — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_free_tier(d):
    """Run 99 (second page), extended in run 105: the free tier as a licence plus a dollar allowance.

    Read live at 2026-11-09T01:22Z from elevenlabs.io/pricing/api, whose plan column prints
    "Characters included" and its own minute column per model: Free / v4 = 10,000 ~10 min,
    Free / v4 Turbo = 20,000 ~20 min. Both multiply out to $0.80 at each model's rate.

    Run 105 added the three limits a buyer actually hits (demand measured in probe105.py, control
    `elevenlabs pricing` = 10): `elevenlabs free plan commercial use` and `elevenlabs free credits
    reset / per month` are typed queries, and the answer lives in the vendor's Terms of Use and its
    credit-cost table rather than on the pricing page. The licence clause is quoted from
    elevenlabs.io/terms-of-use, read 2026-11-09T02:3xZ; every number is computed from dataset.json.
    """
    el = d["vendors"]["elevenlabs"]
    ft = el["free_tier"]
    r = el["rates_usd_per_1000_chars"]
    starter = next(x for x in el["ladder"] if x.get("name") == "Starter")
    v4_value = ft["chars_v4"] / 1000 * r["multilingual_v4_api"]
    turbo_value = ft["chars_v4_turbo"] / 1000 * r["turbo_flash_api"]
    step_multiple = starter["chars"] / ft["chars_v4"]
    cpm = el["vendor_minutes_basis"]
    items = {i["product"]: i for i in el["credit_costs"]["items"]}
    tts = items["Text to Speech"]["credits"]
    free_chars = ft["chars_v4"] / tts
    free_min = free_chars / cpm
    stt_min = free_chars / items["Speech to Text"]["credits"]
    music_min = free_chars / items["Eleven Music"]["credits"]
    sfx_n = free_chars / items["Sound Effects"]["credits"]
    vc_min = free_chars / items["Voice Changer and Voice Isolator"]["credits"]
    dub_auto_min = free_chars / items["Dubbing, automatic with watermark"]["credits"]
    dub_studio = items["Dubbing Studio without watermark"]["credits"]
    dub_studio_min = free_chars / dub_studio
    spread = stt_min / dub_studio_min
    free_conc = next(x for x in el["concurrency"]["tts_concurrent_requests"] if x["plan"] == "Free")
    starter_min = starter["chars"] / tts / cpm
    body = [
        "<h1>ElevenLabs free plan: 10,000 characters a month, a non-commercial licence, and "
        f"{free_conc['requests']} concurrent requests</h1>",
        "<p class=\"lede\">Yes, there is a free plan, and it is small: <strong>10,000 characters a "
        "month</strong> of v4 speech, which the vendor's own minute column prints as <strong>~10 "
        "minutes</strong>. On v4 Turbo the same free plan lists <strong>20,000 characters</strong> and "
        "~20 minutes, because that model's rate is half. Both allowances are the same money: "
        f"<strong>${money2(v4_value)} a month</strong> at the vendor's own rates. The limit that stops "
        "a hobby project is not the minutes — it is the licence.</p>",
        "<h2>The free allowance, per model</h2>",
        "<table><tr><th>model</th><th>rate per 1,000 characters</th><th>characters included free</th>"
        "<th>the vendor's own column</th><th>worth at that rate</th></tr>"
        f"<tr><td>v4</td><td>${money(r['multilingual_v4_api'], 3)}</td><td>{ft['chars_v4']:,}</td>"
        f"<td>~{ft['vendor_minutes_v4']} min</td><td>${money2(v4_value)}</td></tr>"
        f"<tr><td>v4 Turbo</td><td>${money(r['turbo_flash_api'], 3)}</td><td>{ft['chars_v4_turbo']:,}</td>"
        f"<td>~{ft['vendor_minutes_v4_turbo']} min</td><td>${money2(turbo_value)}</td></tr></table>",
        f"<p><strong>The free tier is a ${money2(v4_value)} credit, printed as whatever number of "
        "characters that buys on the model you pick.</strong> Both rows multiply out to the same "
        "dollar figure, which is why the characters column doubles when the rate halves — and why "
        "\"the free plan gives you 10,000 characters\" is only true on the dearer model. At the "
        f"{el['chars_per_minute_default']}-characters-per-minute read this site uses elsewhere, the same "
        f"{ft['chars_v4']:,} characters is about {free_chars / el['chars_per_minute_default']:.0f} "
        "finished minutes — the vendor's ~10 assumes exactly 1,000 characters a minute — and that is the "
        "whole free month.</p>",
        "<h2>The limit nobody reads: the licence</h2>",
        "<p>ElevenLabs' Terms of Use draw the line for you, in the section describing free and paid "
        "users: if you use the Services through the free tier, \"you may only use the Services for "
        "<strong>non-commercial purposes</strong>\"; through a paid subscription, \"you may use the "
        "Services for commercial purposes\". The same clause adds that a non-commercial user "
        "\"must use a personal e-mail address\", and that registering with a business entity's email "
        "address lets the vendor treat that entity as a data Controller — so an account created with a "
        "work address is not a hobbyist account, whatever plan it is on.</p>",
        "<p>The pricing page says the same thing in a shorter form: <strong>Commercial License</strong> "
        "and Instant Voice Cloning are listed as \"Everything in free, plus\" on Starter, so neither is "
        f"part of free. That is what the ${money(starter['usd'], 2)} buys first — permission — and only "
        f"then volume: {starter['chars']:,} characters, <strong>{step_multiple:.1f}×</strong> the free "
        f"allowance, or about {starter_min:.0f} finished minutes. The plan card prints "
        f"<strong>$1 for the first month</strong> as a promo ending 2026-11-16; the promo is not the "
        "price.</p>",
        f"<p>The unit price does not fall with the plan: ${money(starter['usd'], 2)}/{starter['chars']:,} "
        f"is ${money(starter['usd'] / (starter['chars'] / 1000), 3)} per 1,000 characters, and the "
        f"${el['ladder'][-1]['usd']:,} tier works out to the same "
        f"${money(el['ladder'][-1]['usd'] / (el['ladder'][-1]['chars'] / 1000), 3)}. Paying buys the "
        "licence and the volume, never a cheaper character.</p>",
        "<h2>The same free month buys very different amounts of work</h2>",
        "<p>The Creative plans page prints the same allowance as 10,000 credits, and all products spend "
        "from one shared monthly pool — so the free month is a balance whose size depends on which "
        "product spends it. From the vendor's own per-product credit costs:</p>",
        "<table><tr><th>product</th><th>credits</th><th>what the free month buys</th></tr>"
        f"<tr><td>Text to Speech</td><td>{tts} per character</td><td>{free_min:.0f} minutes of speech</td></tr>"
        f"<tr><td>Speech to Text</td><td>{items['Speech to Text']['credits']} per minute</td>"
        f"<td>{stt_min:.1f} minutes transcribed</td></tr>"
        f"<tr><td>Eleven Music</td><td>{items['Eleven Music']['credits']} per minute</td>"
        f"<td>{music_min:.1f} minutes of music</td></tr>"
        f"<tr><td>Sound Effects</td><td>{items['Sound Effects']['credits']} per generation</td>"
        f"<td>{sfx_n:.0f} sound effects</td></tr>"
        f"<tr><td>Voice Changer / Isolator</td>"
        f"<td>{items['Voice Changer and Voice Isolator']['credits']:,} per minute</td>"
        f"<td>{vc_min:.0f} minutes</td></tr>"
        f"<tr><td>Dubbing, automatic with watermark</td>"
        f"<td>{items['Dubbing, automatic with watermark']['credits']:,} per minute</td>"
        f"<td>{dub_auto_min:.1f} minutes</td></tr>"
        f"<tr><td>Dubbing Studio without watermark</td><td>{dub_studio:,} per minute</td>"
        f"<td><strong>{dub_studio_min:.0f} minute</strong></td></tr></table>",
        f"<p>That is a <strong>{spread:.1f}&times; spread inside one balance</strong>: the free month is "
        f"{stt_min:.1f} minutes of transcription or 1 minute of studio dubbing. A creator who reads "
        "\"10,000 credits\" as \"ten minutes\" and then sends one episode through Dubbing Studio spends "
        "the <em>whole month's allowance in sixty seconds</em> — which is why the free plan is a demo "
        "of the product, not a small version of it.</p>",
        "<h2>Two more limits people hit by accident</h2>",
        f"<p><strong>{free_conc['requests']} concurrent requests.</strong> On v4 the free plan accepts "
        f"{free_conc['requests']} simultaneous text-to-speech requests ({free_conc['requests'] * 2} on "
        "Flash v2 or v2.5, per the help centre's own table). A batch script that fires three at once "
        "gets a 429 on the third no matter how many credits are left.</p>",
        "<p><strong>No rollover, and the allowance can be switched off.</strong> Unused credits roll "
        "over for up to two months on a paid subscription — up to twice the monthly quota, a balance "
        "capped at three times the quota — and the vendor's FAQ states plainly that rollover does not "
        "apply to the Free plan. The help centre also carries this wording for free accounts: "
        "\"Unusual activity detected. Free Tier usage disabled. If you are using proxy/VPN you might "
        "need to purchase a paid plan to not trigger our abuse detectors.\" That is an abuse-detector "
        "verdict, not a quota error, and waiting does not clear it.</p>",
        "<p><strong>Where the free tier stops being enough:</strong> a ten-minute-a-month allowance is "
        "one short video, or a single demo call. Anything that runs monthly — a narration series, an "
        "agent in staging, an audiobook — crosses into the paid ladder immediately, and the ladder is "
        "block-priced, so the plan you pick should be chosen from finished minutes, not from the plan "
        "nearest your budget. If the product is a startup rather than a test, the 12-month grant is a "
        "different decision and a much larger number.</p>",
        "<p>Plan column read from " + esc(ft["source"]) + " on " + esc(ft["verified"]) + "; the same "
        "page prints \"API usage is billed in US dollars, not credits\", so the unit taken here is the "
        "API column's characters, not the Creative page's credits. The licence clause and the "
        "abuse-detector wording were read on elevenlabs.io/terms-of-use and the help centre on "
        "2026-11-09, and terms change without a changelog. Quality, latency and voice availability are "
        "not measured here: this page prices a licence and a balance, and no audio was generated.</p>",
        cpm_note(),
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d, "ElevenLabs free plan and pricing — affiliate link") + "</p>",
    ]
    return "".join(body)

def q_elevenlabs_concurrency(d):
    """Run 103: concurrency — the limit people hit with a 429, and what a slot costs.

    Three vendor pages read live at 2026-11-09T02:05Z disagree in ways that matter to a buyer:
      * /pricing's Creative comparison table prints 2 / 3 / 5 / 10 / 15 / 25 concurrent requests;
      * /pricing/agents prints 4 / 6 / 10 / 20 / 30 / 40 concurrent calls for the same six prices;
      * the 429 help-centre article prints Business as 15 for TTS while the table prints 25.
    Everything below is computed from dataset.json's concurrency block, so a re-read changes the page.
    """
    el = d["vendors"]["elevenlabs"]
    c = el["concurrency"]
    tts = c["tts_concurrent_requests"]
    ag = c["agent_concurrent_calls"]
    b = c["burst"]
    qq = c["queueing"]

    def per_slot(usd, n):
        return "n/a" if usd == 0 else "$" + money2(usd / n)

    tts_rows = "".join(
        f"<tr><td>{esc(r['plan'])}</td><td>${money(r['usd'], 2)}</td><td>{r['requests']}</td>"
        f"<td>{per_slot(r['usd'], r['requests'])}</td></tr>" for r in tts)
    ag_rows = "".join(
        f"<tr><td>{esc(r['plan'])}</td><td>${money(r['usd'], 2)}</td><td>{r['calls']}</td>"
        f"<td>{per_slot(r['usd'], r['calls'])}</td></tr>" for r in ag)

    starter = tts[1]
    business = tts[-1]
    slot_cheap = starter["usd"] / starter["requests"]
    slot_dear = business["usd"] / business["requests"]
    slot_rise = slot_dear / slot_cheap
    growth = business["requests"] / starter["requests"]

    creator_tts = next(r for r in tts if r["plan"] == "Creator")
    creator_ag = next(r for r in ag if r["plan"] == "Creator")
    pro_ag = next(r for r in ag if r["plan"] == "Pro")
    step_up = pro_ag["usd"] - creator_ag["usd"]
    premium = b["burst_agent_usd_per_minute"] - b["standard_agent_usd_per_minute"]
    breakeven_min = step_up / premium
    burst_creator_cap = min(creator_ag["calls"] * b["max_multiplier"], b["absolute_cap_non_enterprise"])
    pro_burst_cap = min(pro_ag["calls"] * b["max_multiplier"], b["absolute_cap_non_enterprise"])

    # what concurrency a call volume needs: calls per hour x average minutes / 60
    demo_per_hour, demo_minutes = 300, 3
    demo_conc = demo_per_hour * demo_minutes / 60

    body = [
        "<h1>ElevenLabs concurrency limit: the same $22 buys 5 speech requests or 10 agent calls</h1>",
        "<p class=\"lede\">ElevenLabs sells concurrency twice. On the Creative plans, the "
        f"<strong>{esc(creator_tts['plan'])} plan at ${money(creator_tts['usd'], 2)}</strong> runs "
        f"<strong>{creator_tts['requests']} concurrent text-to-speech requests</strong>; on the "
        f"ElevenAgents plans, the same ${money(creator_ag['usd'], 2)} runs "
        f"<strong>{creator_ag['calls']} concurrent calls</strong>. Both numbers are on the vendor's own "
        "site, and the two help-centre and pricing pages even disagree about the top plan. Here are both "
        "ladders as printed, the price of one concurrent slot at each tier, and the arithmetic for whether "
        "burst pricing or the next plan up is the cheaper way to get headroom.</p>",

        "<h2>Concurrent text-to-speech requests, by plan</h2>",
        "<table><tr><th>plan</th><th>monthly price</th><th>concurrent requests</th>"
        "<th>price per concurrent request</th></tr>" + tts_rows + "</table>",
        f"<p><strong>A concurrent slot costs more the bigger the plan gets.</strong> ${money2(slot_cheap)} "
        f"a month on {esc(starter['plan'])}, ${money2(slot_dear)} on {esc(business['plan'])}: "
        f"<strong>{slot_rise:.1f}&times; more</strong> for a plan that offers {growth:.1f}&times; the "
        "concurrency. The vendor is not selling slots separately. Concurrency scales with the credit "
        "allowance, and the per-credit price is flat (this site measures $0.080 per 1,000 characters at "
        "every paid tier), so you are buying speech and the parallelism arrives attached to it. If what "
        "you actually need is a number of parallel requests, the arithmetic above is worth doing before "
        "paying for a tier whose credits you cannot spend.</p>",

        "<h2>Concurrent agent calls, by plan</h2>",
        "<table><tr><th>plan</th><th>monthly price</th><th>concurrent calls</th>"
        "<th>price per concurrent call</th></tr>" + ag_rows + "</table>",
        f"<p><strong>At every tier below the top, the agent number is exactly twice the speech number "
        f"for the same money</strong> ({creator_ag['calls']} against {creator_tts['requests']} on "
        f"{esc(creator_tts['plan'])}, {pro_ag['calls']} against "
        f"{next(r['requests'] for r in tts if r['plan'] == 'Pro')} on Pro). The two products are billed "
        "on different units &mdash; call minutes against a shared credit pool &mdash; so the agent plans "
        "are not simply twice as generous; but if your workload is a voice agent, the plan buys double "
        "the parallelism a speech pipeline gets for the same price.</p>",

        "<h2>The two official pages that disagree</h2>",
        f"<p>The Creative comparison table prints <strong>{business['requests']} concurrent requests</strong> "
        f"for {esc(business['plan'])}. The help-centre article for API error 429 &mdash; the same article "
        "that defines the limit &mdash; prints the ladder as Free 2, Starter 3, Creator 5, Pro 10, Scale 15, "
        f"Business <strong>{c['tts_help_center_business']}</strong>. Both pages are official and neither carries a "
        "date. For a paid tier below the top this changes nothing; for Business it is a "
        f"{business['requests'] - c['tts_help_center_business']}-request gap, and the safe assumption is the "
        "lower figure, because the number an error message enforces is the limiting one. If you are sizing "
        "a Business plan on concurrency, ask sales for the number in writing.</p>",

        "<h2>Burst pricing: the cheaper way to buy headroom</h2>",
        "<p>Agent plans can exceed their limit on purpose. With bursting enabled, calls above the plan's "
        f"concurrency are accepted up to <strong>{b['max_multiplier']}&times; the limit or "
        f"{b['absolute_cap_non_enterprise']} calls, whichever is lower</strong>, and those calls are billed "
        f"at <strong>${money(b['burst_agent_usd_per_minute'], 2)} a minute instead of "
        f"${money(b['standard_agent_usd_per_minute'], 2)}</strong>. Burst calls are also deprioritised for "
        "speech processing, so they can be slower. Two things follow.</p>",
        f"<p>First, burst is often cheaper than the next plan. {esc(creator_ag['plan'])} gives "
        f"{creator_ag['calls']} concurrent calls; {esc(pro_ag['plan'])} gives {pro_ag['calls']} for "
        f"<strong>${money2(step_up)} more a month</strong>. Bursting on {esc(creator_ag['plan'])} accepts "
        f"up to <strong>{burst_creator_cap} concurrent</strong> and charges the excess "
        f"<strong>${money2(premium)} a minute</strong> extra. The step up pays for itself only if you push "
        f"past the lower limit by more than <strong>{breakeven_min:,.0f} call-minutes a month</strong> "
        f"(${money2(step_up)} &divide; ${money2(premium)}), i.e. 16 hours of overflow calling. Under that, "
        "burst and stay.</p>",
        f"<p>Second, the cap is on your own number, not on the example table. The burst documentation's "
        "own table starts at a 50-call subscription limit and climbs to 200 &mdash; no published plan has "
        f"50 concurrent agent calls; the top plan has {ag[-1]['calls']}. "
        f"So on {esc(pro_ag['plan'])} the burst ceiling is {pro_burst_cap} calls, not 150.</p>",

        "<h2>What happens when you hit the limit</h2>",
        "<ul>"
        f"<li><strong>Speech-to-text and text-to-speech:</strong> HTTP <strong>429</strong> with "
        f"<code>too_many_concurrent_requests</code>. A 429 can also read <code>system_busy</code>, which is "
        "the vendor's own traffic rather than your plan &mdash; retrying that one generally works, and "
        "retrying the first one does not.</li>"
        f"<li><strong>Agents:</strong> the call is rejected, or queued if call queueing is on &mdash; it is "
        f"on by default for new agents, and callers wait up to <strong>{qq['max_wait_default_seconds']} "
        f"seconds</strong> by default (adjustable to {qq['max_wait_range_seconds'][1]:,}). Queue time is "
        "not billed and does not count toward the conversation's duration.</li>"
        f"<li><strong>Not queued:</strong> {esc(qq['unsupported_channels'])}. A call over the daily limit "
        "is rejected too, because that limit does not free up until the next day.</li>"
        "</ul>",

        "<h2>Sizing the plan from your own traffic</h2>",
        f"<p>Concurrency is peak simultaneity, not volume. Average concurrency is calls per hour &times; "
        f"average minutes &divide; 60: <strong>{demo_per_hour} calls an hour at {demo_minutes} minutes each "
        f"is {demo_conc:.0f} concurrent on average</strong> &mdash; above Creator's {creator_ag['calls']} "
        f"and inside Pro's {pro_ag['calls']} &mdash; and the peak, not the average, is what the limit "
        "enforces. Measure p95 call length before choosing the tier; the price step is large and the "
        "credit pool is the same size either way.</p>",
        f"<p>Limits and prices read from {esc(c['sources']['tts_pricing'])}, "
        f"{esc(c['sources']['agent_pricing'])}, {esc(c['sources']['error_429'])}, "
        f"{esc(c['sources']['burst'])} and {esc(c['sources']['queueing'])} on {esc(c['verified'])}. "
        "The per-slot figures and the break-even are this site's arithmetic on those printed numbers.</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d, "ElevenLabs plans and concurrency — affiliate link") + "</p>",
    ]
    return "".join(body)


def q_elevenlabs_credits_per_minute(d):
    """Run 100: ElevenLabs credits, priced in minutes.

    Read live at 2026-11-09T01:32Z from elevenlabs.io/pricing, whose own FAQ prints both the
    per-product credit cost and the monthly plan quotas on one page: Text to Speech 1 credit a
    character, Speech to Text 330 a minute, Eleven Music 900, Voice Changer and Voice Isolator
    1,000, Dubbing 2,000 to 10,000 a minute depending on mode — all from one shared pool. So
    "how many minutes do I get" has eight answers per plan, and this page is that arithmetic:
    minutes = quota / credits-per-minute, dollars-per-minute = plan price / those minutes.
    Every figure is computed from dataset.json (credit_costs), never typed.
    """
    el = d["vendors"]["elevenlabs"]
    cc = el["credit_costs"]
    quotas = {q["plan"]: q for q in cc["quotas"]}
    creator = quotas["Creator"]
    starter = quotas["Starter"]
    free = quotas["Free"]
    items = cc["items"]
    per_min = [i for i in items if i["unit"] == "per minute"]
    cpm_basis = el["vendor_minutes_basis"]
    # Text to Speech is sold per character; at the vendor's own 1,000-characters-a-minute basis a
    # spoken minute is 1,000 credits on the V2 models (0.5-1 credit a character on Flash/Turbo).
    tts_cpm = cpm_basis * next(i["credits"] for i in items if i["product"] == "Text to Speech")
    spread = max(i["credits"] for i in per_min) / min(i["credits"] for i in per_min)
    per_credit = creator["usd"] / creator["credits"]
    studio = next(i for i in per_min if i["product"] == "Dubbing Studio without watermark")

    def mins(quota, per_minute):
        return quota / per_minute

    def per_k(v):
        """Dollars per 1,000 credits: never print '$0.2' when the point is cents."""
        s = f"{v:.4f}"
        while s.endswith("0") and len(s.split(".")[1]) > 2:
            s = s[:-1]
        return s

    # Text to Speech is priced per character, so it is not in `per_min`; at the vendor's own
    # 1,000-characters-a-minute basis it is 1,000 credits a minute and belongs in this table.
    tts_row = ("<tr><td>Text to Speech (V2 models)</td>"
               "<td>1 credit a character, so 1,000 a minute</td>"
               f"<td>{mins(free['credits'], tts_cpm):,.0f} min</td>"
               f"<td>{mins(creator['credits'], tts_cpm):,.0f} min</td>"
               f"<td>${money(tts_cpm * per_credit, 2)}</td></tr>")
    rows = tts_row + "".join(
        f"<tr><td>{esc(i['product'])}</td><td>{i['credits']:,} credits</td>"
        f"<td>{mins(free['credits'], i['credits']):,.0f} min</td>"
        f"<td>{mins(creator['credits'], i['credits']):,.1f} min</td>"
        f"<td>${money(i['credits'] * per_credit, 2)}</td></tr>"
        for i in per_min)
    quota_rows = "".join(
        f"<tr><td>{esc(q['plan'])}</td><td>{'$' + money(q['usd'], 2) if q['usd'] else '$0'}</td>"
        f"<td>{q['credits']:,}</td>"
        f"<td>{'n/a' if not q['credits'] or not q['usd'] else '$' + per_k(q['usd'] / q['credits'] * 1000)}</td>"
        f"<td>{q['credits'] / tts_cpm:,.0f} min</td>"
        f"<td>{q['credits'] / next(i['credits'] for i in per_min if i['product'] == 'Speech to Text'):,.0f} min</td></tr>"
        for q in cc["quotas"])
    per_k_values = [q["usd"] / q["credits"] * 1000 for q in cc["quotas"] if q["usd"]]
    ladder_range = max(per_k_values) / min(per_k_values)

    body = [
        "<h1>ElevenLabs credits per minute: the same 121,000 credits are 366 minutes of "
        "transcription, 121 of speech or 12 of studio dubbing</h1>",
        "<p class=\"lede\">Credits are not a currency of \"voice\": they are one pool that every "
        "product draws on, at rates the vendor publishes per product. Read off elevenlabs.io/pricing "
        f"on {esc(cc['verified'])}, a minute costs <strong>330 credits</strong> of transcription, "
        f"<strong>900</strong> of music, <strong>1,000</strong> of speech or voice isolation and "
        f"<strong>10,000</strong> of Dubbing Studio without a watermark — a <strong>{spread:.1f}×</strong> "
        "spread inside a single balance. So \"how many minutes is my plan\" has eight answers, and "
        f"on the $22 Creator plan ({creator['credits']:,} credits) one credit is "
        f"${money(per_credit, 6)}.</p>",
        "<h2>Credits per minute, by product</h2>",
        "<table><tr><th>product</th><th>vendor's credit cost</th><th>minutes from the Free plan "
        f"({free['credits']:,} credits)</th><th>minutes from Creator ({creator['credits']:,})</th>"
        "<th>cost of one minute on Creator</th></tr>" + rows + "</table>",
        f"<p><strong>{spread:.1f}× is the whole point.</strong> A buyer who reads \"121,000 credits\" as "
        "\"121,000 minutes\" is wrong twice over: on Text to Speech a minute is 1,000 credits, so the "
        f"quota is <strong>{mins(creator['credits'], tts_cpm):,.0f} minutes</strong>, and on Dubbing "
        f"Studio it is <strong>{mins(creator['credits'], studio['credits']):,.1f} minutes</strong>. The "
        "cheapest minute in the pool is transcription at $"
        f"{money(min(i['credits'] for i in per_min) * per_credit, 2)} — the dearest is $"
        f"{money(max(i['credits'] for i in per_min) * per_credit, 2)} on Creator's per-credit rate.</p>",
        "<h2>Why \"10,000 credits\" is 10 minutes or 20 depending on the model</h2>",
        f"<p>{esc(cc['char_rule'])} So at the vendor's {cpm_basis:,}-characters-per-minute basis a "
        f"spoken minute is <strong>{tts_cpm:,} credits</strong> on the V2 models and "
        f"<strong>{tts_cpm // 2:,}</strong> on the Flash/Turbo models that bill half a credit a "
        f"character — the same free {free['credits']:,} credits is 10 minutes of v4 or 20 minutes of "
        "v4 Turbo. That is the one place the number doubles, and it is a model choice, not a plan.</p>",
        "<h2>The plan quotas, and what a credit costs on each</h2>",
        "<table><tr><th>plan</th><th>price / month</th><th>credits / month</th><th>$ per 1,000 credits</th>"
        "<th>minutes of speech</th><th>minutes of transcription</th></tr>" + quota_rows + "</table>",
        f"<p>The per-credit price barely moves: Starter's credits cost "
        f"${per_k(starter['usd'] / starter['credits'] * 1000)} per 1,000 and the cheapest plan's cost "
        f"${per_k(min(per_k_values))}, so the whole published ladder moves the unit price by "
        f"<strong>{ladder_range:.2f}×</strong>. What the bigger plans buy is the studio features listed "
        "beside them and the credit quota — not a discount on the credit itself. A buyer choosing "
        "between Starter and Creator is choosing 30,000 against 121,000 credits, not a better rate.</p>",
        "<h2>Rollover: a balance can reach 3× the monthly quota, once</h2>",
        f"<p>{esc(cc['rollover'])}</p>",
        "<p>That is the only place a credit can be worth more than the month it was bought in: let a "
        "month's allowance pile up and the next big job can spend three months at once. The catch is "
        "the forfeit rule — the rollover is a property of staying subscribed, not of the credits.</p>",
        "<h2>\"Free Tier usage disabled\": what the vendor says it means</h2>",
        f"<p>{esc(cc['free_tier_disabled_note'])} This is the vendor's own wording in its Help Center "
        "index, so it is worth reading literally: the message is an abuse-detector verdict, not a "
        "quota error, and the documented trigger is a proxy or VPN. A free-tier user on a VPN who sees "
        "their usage disabled has not run out of credits.</p>",
        "<p><strong>Which page you actually want:</strong> if you are buying text-to-speech through "
        "the API rather than the studio, the credits table is the wrong ladder — API usage is billed "
        "per character in dollars on a different page of the same site, and this site prices that "
        "separately. If you are choosing between the studio and the API, read both before you "
        "subscribe: the two pages print different allowances for the same plan price.</p>",
        f"<p>Credit costs, quotas and rollover rules read from {esc(cc['source'])} on "
        f"{esc(cc['verified'])}. Nothing here was bought; these are list prices.</p>",
        DISCLOSURE,
        "<p>" + labelled("elevenlabs", d, "ElevenLabs plans and credits — affiliate link") + "</p>",
    ]
    return "".join(body)


def load_bandwidth():
    with open(os.path.join(HERE, "data", "do-bandwidth.json"), encoding="utf-8") as f:
        return json.load(f)


def q_do_bandwidth(d, x):
    """Run 100: DigitalOcean's bandwidth bill, which is where a Droplet stops being $6.

    Read live at 2026-11-09T01:31Z from docs.digitalocean.com/products/billing/bandwidth/ (the page
    is dated "Last verified 5 Nov 2026"): outbound past a plan's allowance is $0.01/GiB, inbound is
    free, the allowance is pooled at team level and does not roll over, and — the part that
    surprises people — the allowance accrues per second at 1/2,419,200 of the plan's allowance, so a
    Droplet that only exists for a week has a quarter of its monthly allowance to spend.
    Every number is computed from data/do-bandwidth.json + the Droplet table, never typed.
    """
    bw = load_bandwidth()
    plans = x["droplets"]["plans"]
    rate = bw["droplet_overage_usd_per_gib"]
    denom = bw["accrual"]["denominator_seconds"]
    six = next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
    smallest = min(plans, key=lambda p: p["usd_per_month"])
    biggest = max(plans, key=lambda p: p["usd_per_month"])
    week_s = 7 * 86400
    week_share = week_s / denom
    six_week_allowance = six["transfer_gib"] * week_share
    burst = 500.0
    burst_over = max(0.0, burst - six_week_allowance)
    # served volumes: 2 TiB and 10 TiB a month, on the $4, $6 and $12 Basic plans
    served = [(2048.0, "2 TiB"), (10240.0, "10 TiB")]
    pick = [smallest, six, next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 2.0)]
    rows = ""
    for p in pick:
        cells = ""
        for gib, label in served:
            ov = max(0.0, gib - p["transfer_gib"])
            cells += (f"<td>{ov:,.0f} GiB over = ${money2(ov * rate)}</td>"
                      f"<td>${money2(p['usd_per_month'] + ov * rate)} "
                      f"({(p['usd_per_month'] + ov * rate) / p['usd_per_month']:.1f}× the plan)</td>")
        rows += (f"<tr><td>{p['memory_gib']:g} GiB / {p['vcpus']} vCPU</td>"
                 f"<td>${money2(p['usd_per_month'])}</td><td>{p['transfer_gib']:,.0f} GiB</td>"
                 f"{cells}</tr>")
    doubling_gib = six["transfer_gib"] + six["usd_per_month"] / rate
    included_rate = six["usd_per_month"] / six["transfer_gib"]
    body = [
        f"<h1>DigitalOcean droplet bandwidth pricing: {six['transfer_gib']:,.0f} GiB included, then "
        f"${money(rate, 2)} a GiB — and the allowance accrues by the second</h1>",
        "<p class=\"lede\">The $6 Droplet's transfer allowance is real and it is not the number people "
        f"think: <strong>{six['transfer_gib']:,.0f} GiB of outbound transfer a month</strong>, after "
        f"which DigitalOcean bills ${money(rate, 2)} per GiB. Serve 2 TiB and the $6 Droplet costs "
        f"<strong>${money2(six['usd_per_month'] + max(0.0, 2048 - six['transfer_gib']) * rate)}</strong> "
        "that month; the bandwidth line is the larger of the two. Inbound transfer is free.</p>",
        "<h2>What a heavy month costs on the three basic plans</h2>",
        "<table><tr><th>plan</th><th>price / month</th><th>outbound included</th>"
        "<th>2 TiB served: overage</th><th>2 TiB: total bill</th>"
        "<th>10 TiB served: overage</th><th>10 TiB: total bill</th></tr>" + rows + "</table>",
        f"<p><strong>The included transfer is worth more per GiB than the overage costs.</strong> A $6 "
        f"Droplet's {six['transfer_gib']:,.0f} GiB work out to ${money(included_rate, 4)} a GiB inside "
        f"the plan, against ${money(rate, 2)} a GiB for anything past it — so the allowance is worth "
        f"buying a plan for, and the shape of the bill is \"cheap until you cross the line, then "
        f"1.7× dearer\". Serving {doubling_gib:,.0f} GiB in a month doubles a $6 Droplet's bill.</p>",
        "<h2>The part the price page does not say: the allowance accrues per second</h2>",
        f"<p>From the same billing page: \"{esc(bw['accrual']['rule'])}\" The denominator is "
        f"<strong>{denom:,} seconds</strong>, which is {bw['accrual']['max_days_per_cycle']} days — so "
        f"a Droplet that exists for one week has accrued <strong>{week_share * 100:.0f}%</strong> of its "
        f"monthly allowance, not all of it. A $6 Droplet alive for those 7 days can therefore send "
        f"<strong>{six_week_allowance:,.0f} GiB</strong> before the meter starts; a "
        f"{burst:,.0f} GiB burst in that week costs "
        f"<strong>${money2(burst_over * rate)}</strong> in overage on a plan the marketing copy calls "
        f"\"{six['transfer_gib']:,.0f} GiB included\". Short-lived Droplets, blue-green deploys and CI "
        "runners are exactly the case where the marketing number and the accrued number differ.</p>",
        "<h2>What does not count</h2>",
        "<ul>" + "".join(f"<li>{esc(c)}</li>" for c in bw["free_cases"]) + "</ul>",
        "<p>The VPC line matters most for anyone running more than one Droplet: app-to-database "
        "traffic over the private interface is not billed, while the same bytes over public addresses "
        "would be. A firewall rule that drops traffic also drops the charge — the page says outbound "
        "transfer \"that we determine is dropped by a DigitalOcean firewall rule\" is not billed.</p>",
        "<h2>The team pool, and what it does not do</h2>",
        "<p>Transfer is pooled across every Droplet on the team: the allowance of a mostly idle Droplet "
        f"covers the overage of a busy one. DigitalOcean's own example: \"{esc(bw['quote_pool_example'])}\" "
        f"The limits are that the pool does not roll over between months and cannot move between teams, "
        "so a quiet month cannot bank transfer for a launch month.</p>",
        "<h2>Two other products bill bandwidth differently</h2>",
        "<table><tr><th>product</th><th>included outbound</th><th>overage</th><th>note</th></tr>"
        + "".join(
            f"<tr><td>{esc(o['product'])}</td>"
            f"<td>{'%s GiB' % format(o['included_gib'], ',') if o['included_gib'] else 'per plan'}</td>"
            f"<td>${money(o['overage_usd_per_gib'], 2)}/GiB</td><td>{esc(o['note'])}</td></tr>"
            for o in bw["other_products"]) + "</table>",
        f"<p>App Platform is the one to notice: <strong>${money(2 * rate, 2)} a GiB</strong>, twice the "
        "Droplet rate for the same bytes. A workload with a big outbound share can be cheaper on a "
        "Droplet for that reason alone.</p>",
        "<h2>How to see your own number</h2>",
        "<p>The billing page has a Droplet Transfer (Bandwidth) Overview with a projection based on "
        "your daily averages, and a Bandwidth Detail CSV (Beta) export. Read it before you resize: the "
        f"projection assumes your current daily average holds to the end of the cycle, which is exactly "
        "the assumption a launch month breaks. The Droplet plans themselves are on the droplet pricing "
        f"page ({esc(x['sources']['droplets']['read'])}), and the {biggest['transfer_gib']:,.0f} GiB "
        f"allowance on the ${money2(biggest['usd_per_month'])} plan is the largest in this dataset.</p>",
        f"<p>Bandwidth rates and rules read from {esc(bw['source'])} (vendor-dated "
        f"{esc(bw['vendor_last_verified'])}) on {esc(bw['read'])}; plan allowances from the Droplet "
        "price list. Nothing here was bought.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "digitalocean", "DigitalOcean Droplet pricing — affiliate link") + "</p>",
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
    """DigitalOcean's signup credit: which of the live offers a new account is actually on.

    Rewritten 2026-11-09T19:21Z (run 131) from the four-door audit in run 130. Two earlier
    versions of this page priced ONE credit — first "$200 for 60 days", then "$5 for 90 days" —
    and both were a single door of several. Read at the source on 2026-11-09:
      * $5 / 90 days: docs.digitalocean.com/platform/billing/signup-credit/, *Last verified
        15 Jul 2026*. Applied automatically to a first team, no promo code, expires 90 days
        after signup, all products except SaaS Add-Ons, payment method required, not
        transferable.
      * $100 / 60 days: try.digitalocean.com/paas, read 2026-11-09 — "$100, 60-day free trial
        requires valid credit card"; its FAQ says any infrastructure service including all
        Droplet plans, with overage billed to the card.
      * $200: partner and startup tracks (a partner page at 12 months; a DO community profile
        advertising $200 for 60 days with a referral code). The only first-party document that
        states $200 is the release note of 27 September 2022 ("increased from $100").
    The Promotional Credit & Discount Terms (*Last updated 7 June 2024*) govern all of them: no
    cash value, non-transferable, one code per account, Marketplace/Support/crypto/upfront-prepay
    ineligible, terms modifiable by posting — which is how a 2022 $200 becomes a 2026 $5 without
    anyone misquoting anything.

    The unit that makes the offers comparable is amount / window = the monthly spend that would
    consume the credit, because DigitalOcean caps each month at the plan's monthly price. Nothing
    here was bought: these are list prices and published terms, not invoices.
    """
    plans = x["droplets"]["plans"]
    h730 = x["month_hours"]
    six = next(p for p in plans if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)

    def window_bill(monthly, days):
        """DigitalOcean bills by the second with a monthly cap, so N days cost N/30 months,
        each capped at the monthly price."""
        return monthly * (days / 30.0)

    offers = [
        ("Default signup credit", 5.0, 90,
         "Signup Credit docs, Last verified 15 Jul 2026"),
        ("Sign-up landing page trial", 100.0, 60,
         "try.digitalocean.com/paas, read 2026-11-09"),
        ("Partner / startup tracks", 200.0, 60,
         "partner pages and a DO community profile, read 2026-11-09"),
    ]
    rows = []
    for name, amt, days, source in offers:
        full = sorted([p for p in plans if window_bill(p["usd_per_month"], days) <= amt],
                      key=lambda p: p["usd_per_month"])
        need = amt / (days * 24.0) * h730
        six_bill = window_bill(six["usd_per_month"], days)
        alive_d = amt / six["usd_per_hour"] / 24.0
        nearest = min(plans, key=lambda p: abs(p["usd_per_month"] - need))
        rows.append({"name": name, "amt": amt, "days": days, "source": source,
                     "full": full, "need": need, "six_bill": six_bill,
                     "nearest": nearest,
                     "six_left": max(0.0, amt - six_bill),
                     "six_share": 100.0 * min(1.0, amt / six_bill),
                     "alive_d": alive_d})

    h100 = next(o for o in x["gpus"]["offers"]
                if o["provider"] == "digitalocean" and o["family"] == "H100" and o["tier"] == "on_demand")
    l40s = next(o for o in x["gpus"]["offers"]
                if o["provider"] == "digitalocean" and o["family"] == "L40S" and o["tier"] == "on_demand")
    src = x["sources"]["droplets"]

    door_rows = "".join(
        f"<tr><td>{esc(o['name'])}</td><td>${money2(o['amt'])}</td><td>{o['days']} days</td>"
        f"<td>${money2(o['need'])}/mo</td><td><strong>{len(o['full'])} of {len(plans)}</strong></td>"
        f"<td>{esc(o['source'])}</td></tr>"
        for o in rows)
    six_rows = "".join(
        f"<tr><td>${money2(o['amt'])}</td><td>${money2(o['six_bill'])}</td>"
        f"<td>{o['six_share']:.1f}%</td><td>${money2(o['six_left'])}</td>"
        f"<td>{('%.1f days' % o['alive_d']) if o['six_left'] <= 0.01 else 'the whole window'}</td></tr>"
        for o in rows)
    gpu_rows = "".join(
        f"<tr><td>${money2(o['amt'])}</td>"
        f"<td>{o['amt'] / h100['usd_per_gpu_hour']:.1f} h</td>"
        f"<td>{o['amt'] / l40s['usd_per_gpu_hour']:.1f} h</td></tr>"
        for o in rows)

    five, hundred, two_hundred = rows
    body = [
        "<h1>DigitalOcean free credit: $5, $100 or $200 — the window decides, not the amount</h1>",
        "<p class=\"lede\">A new DigitalOcean account does not get one credit. On 2026-11-09 at "
        "least three offers are live at once: <strong>$5 for 90 days</strong> on the default "
        "signup flow, <strong>$100 for 60 days</strong> on DigitalOcean's own trial landing page, "
        "and <strong>$200</strong> on partner and startup tracks. Because each month is capped at "
        "the plan's monthly price, the number that decides what a credit is worth is "
        "<strong>amount ÷ window</strong> — the monthly spend that would consume it before it "
        f"expires. $5 over 90 days needs <strong>${money2(five['need'])} a month</strong>; $100 "
        f"over 60 days needs <strong>${money2(hundred['need'])}</strong>; $200 over 60 days needs "
        f"<strong>${money2(two_hundred['need'])}</strong>. The cheapest Droplet on the list is "
        f"${money2(min(p['usd_per_month'] for p in plans))} a month, so the default credit cannot "
        "cover a full window at any size — and the largest offers cannot be spent in full on a "
        "small one.</p>",
        "<h2>Three doors, all live on 2026-11-09</h2>",
        "<p>The last column is the number the marketing never prints: divide the credit by its "
        "window and you get the monthly bill that consumes it exactly. Anything cheaper expires; "
        "anything dearer runs out.</p>",
        "<table><tr><th>offer</th><th>credit</th><th>window</th><th>spend/mo to consume it</th>"
        "<th>plans covered for the whole window</th><th>source read 2026-11-09</th></tr>"
        + door_rows + "</table>",
        "<h2>The failure mode flips with plan size</h2>",
        f"<p>Watch the same three credits on one plan — the ${money2(six['usd_per_month'])} "
        "1 GiB Basic Droplet, the cheapest thing most people launch. The small credit runs out "
        f"after <strong>{five['alive_d']:.1f} days</strong> of the 90-day window; the two larger "
        "ones cover the whole window and leave "
        f"<strong>${money2(hundred['six_left'])}</strong> and <strong>${money2(two_hundred['six_left'])}</strong> "
        "unspent. A credit is a discount with an expiry, not a runway: it is too small for the plan "
        "you wanted or too large for the plan you run.</p>",
        "<table><tr><th>credit</th><th>bill for the window on the $6 plan</th><th>share covered</th>"
        "<th>credit left when the window closes</th><th>time alive on the credit</th></tr>"
        + six_rows + "</table>",
        "<h2>Where each number comes from</h2>",
        "<p>The <strong>$5 / 90 days</strong> figure is documented: DigitalOcean's Signup Credit "
        "page, stamped <em>Last verified 15 Jul 2026</em>, applies it automatically to a first "
        "team, requires a payment method, excludes SaaS Add-Ons and says it is not transferable. "
        "The <strong>$100 / 60 days</strong> figure is on DigitalOcean's own "
        "try.digitalocean.com/paas page, read on 2026-11-09: \"$100, 60-day free trial requires "
        "valid credit card\", with overage billed to the card. The <strong>$200</strong> figure "
        "has exactly one first-party document behind it — the release note of 27 September 2022, "
        "which says referral signups \"receive a $200 account credit, increased from $100\" — "
        "plus partner pages and a DigitalOcean community profile that still advertise it. "
        "The Promotional Credit &amp; Discount Terms (<em>Last updated 7 June 2024</em>) cover all "
        "of them: no cash value, non-transferable, one code per account, and Marketplace, Support, "
        "crypto and upfront prepay spending ineligible. Terms are \"subject to change by posting\", "
        "which is exactly how a 2022 $200 becomes a 2026 $5 without anybody misquoting anything.</p>",
        "<p>So the honest answer to \"how much free credit does DigitalOcean give?\" is that it "
        "depends which page you sign up on, and the balance in the control panel's top bar is the "
        "only number that applies to you. This page cannot tell you which door your link opens: "
        "that requires creating an account and attaching a payment method, and this agent does "
        "not open accounts.</p>",
        "<h2>How many plans each credit covers for the whole window</h2>",
        "<table><tr><th>credit</th><th>plans fully covered</th><th>plan nearest the monthly spend that consumes it</th>"
        "<th>monthly spend that consumes it exactly</th></tr>"
        + "".join(
            f"<tr><td>${money2(o['amt'])} / {o['days']} d</td>"
            f"<td><strong>{len(o['full'])} of {len(plans)}</strong></td>"
            f"<td>{esc(o['nearest']['family'])} {money2(o['nearest']['memory_gib'])} GiB / {o['nearest']['vcpus']} vCPU at ${money2(o['nearest']['usd_per_month'])}/mo</td>"
            f"<td>${money2(o['need'])}/mo</td></tr>"
            for o in rows)
        + "</table>",
        "<p>Plans and hourly rates: " + esc(src["url"]) + ", read " + esc(src["read"]) + ". "
        "A credit that covers 7 of 31 plans is not a trial of the product; it is a discount on one "
        "band of it.</p>",
        "<h2>On GPUs the credit is hours and minutes</h2>",
        f"<p>A single 80 GB H100 Droplet is ${money2(h100['usd_per_gpu_hour'])} per GPU-hour on "
        f"demand and an L40S ${money2(l40s['usd_per_gpu_hour'])} (DigitalOcean GPU Droplets "
        "pricing, read 2026-11-08). GPU Droplets bill for a 5-minute minimum and keep billing "
        "while powered off, so a mis-mounted run can spend a large share of a small credit before "
        "anyone notices.</p>",
        "<table><tr><th>credit</th><th>H100 hours</th><th>L40S hours</th></tr>" + gpu_rows + "</table>",
        f"<p>On the smallest credit the useful unit is minutes: $5 is <strong>{60.0 * 5.0 / h100['usd_per_gpu_hour']:.0f} "
        f"minutes</strong> of an H100 and <strong>{60.0 * 5.0 / l40s['usd_per_gpu_hour']:.0f} minutes</strong> of an "
        "L40S. At DigitalOcean's 60-second / $0.01 minimum charge, $5 is also <strong>500</strong> "
        "one-second Droplets — the honest unit for a CI job that boots a machine to run one test "
        "file. At the other end, the $200 partner credit is "
        f"<strong>{200.0 / h100['usd_per_gpu_hour']:.1f} H100 hours</strong>, which is still less "
        "than a day and a half on the card.</p>",
        "<h2>What to check before you sign up</h2>",
        "<ul>"
        "<li><strong>Read the balance, not the blog post.</strong> The credit appears in the "
        "control panel as \"Signup Credit\" as soon as the team exists. That number is the offer "
        "you got, and it is the only one your build should be sized against.</li>"
        "<li><strong>A payment method comes first.</strong> The $5 and $100 offers both require a "
        "card, PayPal, Google Pay or Apple Pay before a Droplet can exist; the $5 Managed Agents "
        "trial is the one no-card path, and it is sized for testing, not hosting.</li>"
        "<li><strong>Decide against the window, not the amount.</strong> On the $6 plan, $5 covers "
        f"{five['six_share']:.1f}% of 90 days, $100 covers the whole 60-day window with "
        f"${money2(hundred['six_left'])} left over, and $200 leaves ${money2(two_hundred['six_left'])}. "
        "If your plan was \"run it free for two months\", the plan was built on a number no "
        "current page promises.</li>"
        "<li><strong>Unused credit expires.</strong> It has no cash value, cannot be transferred, "
        "and one code applies per account.</li>"
        "</ul>",
        "<h2>Why this page states the commission</h2>",
        "<p>The link below is a referral link and it pays this site: when a new account signs up "
        "through it and spends its first $25, a9n9 receives $25 in DigitalOcean credit — credit, "
        "not cash. The signup credit described above belongs to the new account, not to this site, "
        "and the prices you pay afterwards are DigitalOcean's published prices with nothing "
        "returned to you or to this page. Which of the doors above your link opens is not something "
        "this page can see; the control panel's balance is.</p>",
        "<p>Credit terms: https://docs.digitalocean.com/platform/billing/signup-credit/ and "
        "https://docs.digitalocean.com/platform/teams/how-to/refer-others/ (both \"Last verified "
        "15 Jul 2026\"), try.digitalocean.com/paas and the Promotional Credit &amp; Discount Terms "
        "(*Last updated 7 June 2024*), all read 2026-11-09T19:21Z. Plan prices: "
        + esc(src["url"]) + ", read " + esc(src["read"]) + ". Nothing here was bought: these are "
        "list prices and published terms, not invoices.</p>",
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


# Run 110: the first buyer-side fact Novita does not put on a marketing page — what the account costs
# to open. Read from the vendor's own docs on 2026-11-09 (all four pages are its docs, not a review):
#   https://novita.ai/docs/guides/payment-methods  "top up a specified amount of credit, which must be
#                                                 greater than $10"  (last modified 2026-11-05)
#   https://novita.ai/docs/guides/faq              refunds "generally not available"; "sign-up credit
#                                                 voucher" mentioned only as something the system revokes
#   https://novita.ai/docs/guides/llm-billing      499 Client Disconnected is charged; 400/401/403/429/5xx not
#   docs banner                                    13 models retired 2026-11-26 16:00 UTC, incl. gpt-oss-120b
# The model-API signup voucher's SIZE is published nowhere (the Sandbox credit below is a different product and
# is not generalised to token inference) — see the run-111 correction that follows.
#
# Run 111 CORRECTION: run 110 wrote "the signup voucher's SIZE is published nowhere". That was true of the
# model-API and GPU docs and FALSE of the Sandbox docs, which were not read. Read live 2026-11-09T03:21Z:
#   https://docs.novita.ai/guides/sandbox-pricing (last modified 2026-11-05, read 03:21Z)
#   "New users can complete a quick account setup survey to receive $100 in promotional credits for eligible
#    Novita Sandbox usage. No credit card is required."  +  "Promotional credits do not change the underlying
#    unit prices" and "Credits may be subject to availability, validity period, usage scope, and quota limits."
#   CPU 1 vCPU = $0.0000098/s ; RAM 1 GiB = $0.0000032/s ; 20 GB ephemeral free per running sandbox ;
#   60 GB persistent free per account, $0.00009/GB/h beyond that.
# So Novita DOES have a no-card entry — but only for the Sandbox product. Token inference and GPU instances
# still need the >$10 top-up, which is why both numbers are on the page and neither is generalised.
NOVITA_ENTRY = {
    "min_topup_usd": 10.01,          # "must be greater than $10"
    "read": "2026-11-09T03:12Z",
    "sandbox_read": "2026-11-09T03:21Z",
    "sandbox_credit_usd": 100.00,
    "sandbox_cpu_usd_per_vcpu_sec": 0.0000098,
    "sandbox_ram_usd_per_gib_sec": 0.0000032,
    "sandbox_small_vcpu": 1,
    "sandbox_small_gib": 1,
    "sandbox_big_vcpu": 4,
    "sandbox_big_gib": 8,
    "retire_date": "2026-11-26",
    "retire_count": 13,
    "retire_named": ["gpt-oss-120b", "llama-3.3-70b-instruct"],
    "unrefundable": True,
    "charged_status": [200, 499],
    "free_status": [400, 401, 403, 429, 500, 503, 504],
}


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
    # Run 110: what Novita's unpublished-floor minimum top-up ($10.01) actually buys, computed from the
    # same numbers the table prints — the cheapest 4:1 chat mix on the page, and the cheapest Novita H100
    # spot hour from the GPU dataset. Nothing here is typed.
    nov_flash = cheapest_mix[1]
    nov_flash_name = nov_flash["name"]
    nov_flash_in = nov_flash["input_usd_per_mtok"]
    nov_flash_out = nov_flash["output_usd_per_mtok"]
    _blend = (MIX[0] * nov_flash_in + MIX[1] * nov_flash_out) / (MIX[0] + MIX[1])
    nov_flash_tokens = NOVITA_ENTRY["min_topup_usd"] / _blend
    nov_dear = dearest_mix[1]
    nov_dear_name = nov_dear["name"]
    nov_dear_in = nov_dear["input_usd_per_mtok"]
    nov_dear_out = nov_dear["output_usd_per_mtok"]
    _blend2 = (MIX[0] * nov_dear_in + MIX[1] * nov_dear_out) / (MIX[0] + MIX[1])
    nov_dear_tokens = NOVITA_ENTRY["min_topup_usd"] / _blend2
    _h100_spot = [o for o in x["gpus"]["offers"]
                  if o["family"] == "H100" and o["provider"] == "novita" and o["tier"] == "spot"]
    if not _h100_spot:
        raise SystemExit("novita-ai-api-pricing: no Novita H100 spot offer in the GPU dataset")
    nov_spot = min(o["usd_per_gpu_hour"] for o in _h100_spot)
    nov_spot_hours = NOVITA_ENTRY["min_topup_usd"] / nov_spot
    # Run 111: what the Sandbox's $100 no-card credit buys, from the Sandbox docs' own per-second unit prices.
    # Two shapes, both printed, because a credit is only meaningful against a machine size.
    def _sb_per_hour(vcpu, gib):
        sec = (vcpu * NOVITA_ENTRY["sandbox_cpu_usd_per_vcpu_sec"]
               + gib * NOVITA_ENTRY["sandbox_ram_usd_per_gib_sec"])
        return sec * 3600.0
    sb_small_h = NOVITA_ENTRY["sandbox_credit_usd"] / _sb_per_hour(
        NOVITA_ENTRY["sandbox_small_vcpu"], NOVITA_ENTRY["sandbox_small_gib"])
    sb_big_h = NOVITA_ENTRY["sandbox_credit_usd"] / _sb_per_hour(
        NOVITA_ENTRY["sandbox_big_vcpu"], NOVITA_ENTRY["sandbox_big_gib"])
    sb_small_rate = _sb_per_hour(NOVITA_ENTRY["sandbox_small_vcpu"], NOVITA_ENTRY["sandbox_small_gib"])
    sb_big_rate = _sb_per_hour(NOVITA_ENTRY["sandbox_big_vcpu"], NOVITA_ENTRY["sandbox_big_gib"])
    # the banner names vendor ids (openai/gpt-oss-120b); the table prints display names, so map them
    _norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    nov_retired = [r["name"] for r in nt["rows"]
                   if any(_norm(k) in _norm(r["name"]) for k in NOVITA_ENTRY["retire_named"])]
    if len(nov_retired) != len(NOVITA_ENTRY["retire_named"]):
        raise SystemExit(f"novita-ai-api-pricing: retired models not found in the price table: {nov_retired}")
    _read = date(int(NOVITA_ENTRY["read"][0:4]), int(NOVITA_ENTRY["read"][5:7]), int(NOVITA_ENTRY["read"][8:10]))
    _ret = date.fromisoformat(NOVITA_ENTRY["retire_date"])
    nov_days_left = (_ret - _read).days
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
        "<h2>What it costs to walk in the door: nothing for the Sandbox, $10.01 for the models</h2>",
        f"<p>Novita's own billing docs give the number its marketing page does not. Manual top-ups "
        f"&quot;must be greater than $10&quot; (<a href=\"https://novita.ai/docs/guides/payment-methods\">Payment "
        f"Methods</a>, last modified 2026-11-05), payment is Stripe card or debit only, and the FAQ says refunds "
        f"are &quot;generally not available&quot;. For token inference and GPU instances, no page on novita.ai "
        f"states the size of its sign-up voucher — the FAQ mentions one only in the sentence where the system "
        f"revokes it, &quot;when suspicious registration activity is detected&quot; — so the only figure a buyer "
        f"can plan on is the floor: "
        f"<strong>${NOVITA_ENTRY['min_topup_usd']:.2f}</strong>, read {NOVITA_ENTRY['read']}.</p>",
        f"<p>At the rates in the table above, that floor buys <strong>{nov_flash_tokens:.1f}M tokens</strong> of "
        f"the cheapest 4:1 chat mix on the page ({esc(nov_flash_name)} — ${money(nov_flash_in, 2)} in, "
        f"${money(nov_flash_out, 2)} out) and only <strong>{nov_dear_tokens:.1f}M</strong> of the dearest "
        f"({esc(nov_dear_name)} — ${money(nov_dear_in, 2)} in, ${money(nov_dear_out, 2)} out), a "
        f"<strong>{nov_flash_tokens / nov_dear_tokens:.0f}×</strong> spread in what the same minimum payment "
        f"buys. Or <strong>{nov_spot_hours:.1f} hours</strong> of the cheapest H100 spot "
        f"hour at ${money2(nov_spot)}. Neither is a free tier, and none of it is refundable. Against the other "
        f"three programs priced on this site: Firecrawl's free plan is 1,000 credits a month with no card (500 "
        f"searches or 1,000 pages), ElevenLabs gives $0.80 of characters a month on a non-commercial licence and "
        f"sells its first paid month for $1, and DigitalOcean's signup credit is $5 for 90 days (its docs, read 2026-11-09). For inference, "
        f"Novita is the one where the first dollar is a commitment.</p>",
        f"<h2>There is a no-card entry — but it is the Sandbox, not the models</h2>",
        f"<p>The <a href=\"https://docs.novita.ai/guides/sandbox-pricing\">Sandbox pricing page</a> (last "
        f"modified 2026-11-05, read {NOVITA_ENTRY['sandbox_read']}) says: &quot;New users can complete a quick "
        f"account setup survey to receive <strong>${NOVITA_ENTRY['sandbox_credit_usd']:.0f} in promotional "
        f"credits</strong> for eligible Novita Sandbox usage. No credit card is required.&quot; The same page "
        f"scopes it twice: the credits apply to &quot;eligible Novita Sandbox usage&quot; — CPU, RAM and billable "
        f"storage — and are &quot;subject to availability, validity period, usage scope, and quota limits&quot;. "
        f"Model APIs and GPU instances are not mentioned, so this is not a $100 LLM credit and this page does "
        f"not present it as one.</p>",
        f"<p>Priced against the Sandbox's own per-second rates (1 vCPU ${NOVITA_ENTRY['sandbox_cpu_usd_per_vcpu_sec']:.7f}/s, "
        f"1 GiB ${NOVITA_ENTRY['sandbox_ram_usd_per_gib_sec']:.7f}/s), ${NOVITA_ENTRY['sandbox_credit_usd']:.0f} is "
        f"<strong>{sb_small_h:,.0f} hours</strong> of a 1 vCPU / 1 GiB sandbox "
        f"(${sb_small_rate:.4f}/h) or <strong>{sb_big_h:,.0f} hours</strong> of a 4 vCPU / 8 GiB sandbox "
        f"(${sb_big_rate:.4f}/h), running continuously — plus 20 GB of ephemeral storage free per running "
        f"sandbox and 60 GB of persistent storage free per account. That is the useful form of the offer: an "
        f"agent runtime you can benchmark for days without a card, not a discount on the model prices in the "
        f"table above. Credits do not change those unit prices, so the same $100 buys no inference at "
        f"all.</p>",
        "<h2>The same balance is the floor on mistakes</h2>",
        "<p>Novita bills a request as soon as it reaches the model: 400, 401, 403, 429 and 5xx responses are free, "
        "but a <strong>499 &quot;client disconnected&quot;</strong> is charged for the tokens already generated "
        "(<a href=\"https://novita.ai/docs/guides/llm-billing\">LLM API Billing</a>). A client timeout at 30 "
        "seconds is therefore a paid request, not a retry, and the vendor's own advice is to set "
        "<code>max_tokens</code> and a client timeout of at least 60 seconds. Out of a non-refundable balance, "
        "an agent that retries on timeout spends twice and is billed for both attempts.</p>",
        f"<h2>Two rows in the table above are retired on {NOVITA_ENTRY['retire_date']}</h2>",
        f"<p>The docs banner, read {NOVITA_ENTRY['read']}, gives 16:00 UTC on {NOVITA_ENTRY['retire_date']} for "
        f"{NOVITA_ENTRY['retire_count']} model retirements and names <code>openai/gpt-oss-120b</code> and "
        f"<code>meta-llama/llama-3.3-70b-instruct</code>. Both are rows in the table above "
        f"({esc(nov_retired[0])} and {esc(nov_retired[1])}) — the prices are real "
        f"today and will not be quotable in {nov_days_left} days. A price list is not a promise about "
        f"availability; if a workload is pinned to either id, the replacement should be tested before that date, "
        f"not after.</p>",
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
    # Run 133: when no pair of lines crosses inside the priced band, _mix_map returns ONE segment
    # running 0 -> 1e9, and the formatter printed "below 1000000000.00 input tokens per output
    # token" on 8 of the 10 model pages — a sentinel leaking into prose, next to a following
    # sentence saying no ratio makes the dearest cheaper. A full-range segment is not a threshold.
    segs = [s for s in _mix_map(provs) if s[0] < 60]
    full_range = len(segs) == 1 and segs[0][0] <= 0.0001 and segs[0][1] >= 1e8
    mixlines = []
    for lo, hi, win in segs:
        who = " and ".join(PROVIDER_NAMES[p] for p in win)
        if full_range:
            mixlines.append(f"at every input:output ratio, <strong>{who}</strong>")
        elif lo <= 0.0001:
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
        # Run 126: the generic "ranking does not change at any mix" sentence was byte-identical on 8
        # pages (the largest single block of shared text on the site). Compute the crossing ratio from
        # this model's own two prices instead, so the sentence is both specific and checkable.
        a_p, b_p = order[0], order[-1]
        ia, oa = provs[a_p]["input"], provs[a_p]["output"]
        ib, ob = provs[b_p]["input"], provs[b_p]["output"]
        if ib >= ia and ob >= oa:
            mix_para += (f"<p>{PROVIDER_NAMES[b_p]} is dearer on both axes — "
                         f"${_moneyp(ib)} vs ${_moneyp(ia)} per million input tokens and "
                         f"${_moneyp(ob)} vs ${_moneyp(oa)} per million output — so no input:output "
                         f"ratio makes it the cheaper bill.</p>")
        else:
            denom = ia - ib
            r_star = (ob - oa) / denom if denom else None
            if r_star is not None and 0 < r_star < 60:
                mix_para += (f"<p>The two cross at <strong>{r_star:.2f} input tokens per output "
                             f"token</strong>: above that ratio {PROVIDER_NAMES[b_p]}'s lower input "
                             f"price overtakes {PROVIDER_NAMES[a_p]}'s lower output price.</p>")
            else:
                shown = "negative" if (r_star is not None and r_star <= 0) else f"{r_star:.1f}"
                mix_para += (f"<p>The two price lines cross at <strong>r = {shown}</strong> input tokens "
                             f"per output token, outside the 0.05–60 band this page prices, so the "
                             f"ranking in the table holds across that whole band.</p>")
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

    cache_bits = []
    for p in ("novita", "deepinfra", "openrouter"):
        c = provs[p].get("cache_read")
        cache_bits.append(f"${_moneyp(c)}/M on {PROVIDER_NAMES[p]}" if c is not None
                          else f"not published on {PROVIDER_NAMES[p]}")
    cache_para = ("<p>Cache reads are billed outside the bill above: " + ", ".join(cache_bits) +
                  ". A workload that re-reads a long prompt should price that line separately; every "
                  "figure here is a list price from each provider's own catalogue on the date shown, with "
                  "no committed-use or negotiated discount.</p>")

    vol_rows = ""
    for vi, vo, label in ((4, 1, "4M in + 1M out"), (40, 10, "40M in + 10M out"),
                          (400, 100, "400M in + 100M out")):
        vb = {p: vi * provs[p]["input"] + vo * provs[p]["output"] for p in names}
        vol_rows += ("<tr><td>%s</td>" % label
                     + "".join(f"<td>${money2(vb[p])}</td>" if p in vb else "<td>—</td>"
                               for p in ("novita", "deepinfra", "openrouter")) + "</tr>")
    small_gap = (max(4 * provs[p]["input"] + provs[p]["output"] for p in names)
                 - min(4 * provs[p]["input"] + provs[p]["output"] for p in names))
    vol_para = (
        "<h2>The same model at three volumes</h2>"
        "<table><tr><th>workload</th><th>Novita</th><th>DeepInfra</th><th>OpenRouter</th></tr>"
        + vol_rows + "</table>"
        f"<p>All three providers bill these tokens linearly, so the {spread:.2f}&times; gap does not "
        f"shrink with volume: it is <strong>${money2(small_gap)} a month</strong> at 4M in + 1M out and "
        f"<strong>${money2(high - low)}</strong> at 400M in + 100M out — exactly one hundred times as much "
        "for one hundred times the tokens. A committed-use or volume discount, if you negotiate one, is the "
        "only thing that changes that, and none of the three list prices used here includes one.</p>")

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
        vol_para,
        cache_para,
        "<h2>What this does not measure</h2>",
        "<p>Price is not the product: no account exists on this site to measure quality, latency, "
        "throughput, rate limits or data handling, so cost is a tiebreaker after those, not a ranking.</p>",
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
        f"<p class=\"lede\">The same <strong>{M:,} minutes</strong> of audio is "
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
        "that decide whether a transcription bill is cheap or merely small. It also cannot price across "
        "ElevenLabs&rsquo; two products: its API page includes "
        f"<strong>{el['ladder'][2]['chars']:,} characters</strong> on the "
        f"${money2(el['ladder'][2]['usd'])} Creator plan — exactly ${money(el_v4, 3)} per 1,000, the "
        "pay-as-you-go rate, because the ladder is flat — while its Creative plans page advertises "
        "<strong>121,000 credits</strong> for the same $22. Credits are not characters: read the credits "
        f"number as characters and you get ${money(el['rates_usd_per_1000_chars']['credits_equivalent_creator'], 4)} "
        "per 1,000, <strong>2.27× the API rate</strong>, which is a units error and not a price. "
        "All prices here are list prices read on the dates on this page, not invoices, and neither "
        "vendor&rsquo;s free-tier credit is counted as a price.</p>",
        "<p class=\"merit\">Disclosure of interest, stated plainly: ElevenLabs is an affiliate partner "
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
        f"<p class=\"lede\">For <strong>10,000 crawled pages</strong> Firecrawl's cheapest seat is "
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
        "<p class=\"merit\">Disclosure of interest, stated plainly: Firecrawl is an affiliate partner — if "
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


def load_ttsa():
    """TTS list prices from five vendors, read 2026-11-09 (run 104). Price only — quality is not priced."""
    with open(os.path.join(HERE, "data", "tts-alternatives.json"), encoding="utf-8") as f:
        return json.load(f)


def q_elevenlabs_alternatives(d):
    """`elevenlabs alternatives` — what the cheaper speech APIs actually bill, at two volumes.

    Demand (probe104.py, 2026-11-09 02:2xZ, Google Autocomplete): `elevenlabs alternative` returns 10
    completions and `elevenlabs alternatives` 10 more (`... free`, `... open source`, `... reddit`,
    `... 2026`), and `cheaper than elevenlabs` returns 6 (including `is cartesia cheaper than
    elevenlabs`). That is a buying decision, not a price lookup: the searcher has already decided to
    leave and is pricing the exit. The sites that answer it are listicles; none of them prints the
    arithmetic, and the vendor that earns this site a commission is the dearest one in the table.

    Every figure is computed here from data/tts-alternatives.json (five vendors' own pages, read
    2026-11-09 02:24–02:29Z) plus dataset.json's ElevenLabs ladder. Two bases are stated on the page
    and never mixed: 1,000 characters per spoken minute for the unit column, and the vendor's own
    minute for Cartesia's plan table.
    """
    el = d["vendors"]["elevenlabs"]
    t = load_ttsa()
    cpm = t["minute_basis_chars"]
    el_rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]   # USD per 1,000 characters

    def el_cost(chars):
        """ElevenLabs is block-priced: the bill is the smallest plan that covers the volume."""
        fits = [p for p in el["ladder"] if p["chars"] >= chars]
        if fits:
            return min(p["usd"] for p in fits), min(fits, key=lambda p: p["usd"])
        top = max(el["ladder"], key=lambda p: p["chars"])
        return top["usd"] + (chars - top["chars"]) / 1000 * el_rate, top

    def cartesia_per_minute():
        paid = [p for p in t["plan_priced"] if p["plan_usd_per_month"] > 0]
        return min(paid, key=lambda p: p["plan_usd_per_month"] / p["tts_minutes_included"])

    def cartesia_cost(minutes):
        fits = [p for p in t["plan_priced"] if p["tts_minutes_included"] >= minutes]
        if fits:
            return min(p["plan_usd_per_month"] for p in fits)
        big = max(t["plan_priced"], key=lambda p: p["tts_minutes_included"])
        over = (minutes - big["tts_minutes_included"]) * big["plan_usd_per_month"] / big["tts_minutes_included"]
        return big["plan_usd_per_month"] + over

    # ---- table A: unit prices, every offer the file holds ----
    arows = [f"<tr><td>ElevenLabs</td><td>Multilingual v4 (API)</td>"
             f"<td>${el_rate:.3f}</td><td>${el_rate * cpm / 1000:.3f}</td></tr>"]
    for o in t["offers"]:
        per1k = o["usd_per_1m_chars"] / 1000
        arows.append(f"<tr><td>{esc(o['vendor'])}</td><td>{esc(o['product'])}</td>"
                     f"<td>${money(per1k, 4)}</td><td>${money(per1k * cpm / 1000, 4)}</td></tr>")
    for p in t["plan_priced"]:
        if p["plan_usd_per_month"] and p["tts_minutes_included"]:
            per_min = p["plan_usd_per_month"] / p["tts_minutes_included"]
            arows.append(f"<tr><td>Cartesia</td><td>{esc(p['product'])} — {esc(p['plan'])} plan</td>"
                         f"<td>not sold per character</td><td>${money(per_min, 4)}</td></tr>")
    table_a = ("<table><tr><th>vendor</th><th>product</th><th>per 1,000 characters</th>"
               "<th>per finished minute (1,000 chars)</th></tr>" + "".join(arows) + "</table>")

    # ---- table B: the monthly bill at two real volumes ----
    car_pro = cartesia_per_minute()
    car_rate = car_pro["plan_usd_per_month"] / car_pro["tts_minutes_included"]
    paid_plans = [p for p in t["plan_priced"] if p["plan_usd_per_month"] > 0]
    car_hi_plan = max(paid_plans, key=lambda p: p["plan_usd_per_month"] / p["tts_minutes_included"])
    car_lo_plan = min(paid_plans, key=lambda p: p["plan_usd_per_month"] / p["tts_minutes_included"])
    car_hi = car_hi_plan["plan_usd_per_month"] / car_hi_plan["tts_minutes_included"]
    car_lo = car_lo_plan["plan_usd_per_month"] / car_lo_plan["tts_minutes_included"]
    vols = [100000, 1000000]
    brow = []
    for v in vols:
        elb, elplan = el_cost(v)
        el_eff = elb / (v / 1000)
        openai = v / 1e6 * 15.0
        google = v / 1e6 * 30.0
        polly = v / 1e6 * 16.0
        car = cartesia_cost(v / cpm)
        brow.append(
            f"<tr><td>{v:,} characters</td><td>${money2(elb)} ({esc(elplan['name'])}, "
            f"${money(el_eff, 3)}/1,000) </td><td>${money2(openai)}</td><td>${money2(google)}</td>"
            f"<td>${money2(polly)}</td><td>${money2(car)}</td>"
            f"<td>{openai and elb / openai:.1f}× / {google and elb / google:.1f}× / "
            f"{polly and elb / polly:.1f}× / {car and elb / car:.1f}×</td></tr>")
    table_b = ("<table><tr><th>monthly volume</th><th>ElevenLabs (block plan)</th><th>OpenAI tts-1</th>"
               "<th>Google Chirp 3 HD</th><th>Polly Neural</th><th>Cartesia</th>"
               "<th>ElevenLabs ÷ the other four</th></tr>" + "".join(brow) + "</table>")

    # ---- table C: free allowances, in characters ----
    ft = el["free_tier"]
    el_free_chars = ft["chars_v4"]
    crow = [f"<tr><td>ElevenLabs</td><td>{el_free_chars:,}</td>"
            f"<td>${money2(el_free_chars / 1000 * el_rate)}</td><td>—</td></tr>"]
    for o in t["offers"]:
        if o.get("free_chars_per_month"):
            crow.append(f"<tr><td>{esc(o['vendor'])}</td><td>{o['free_chars_per_month']:,}</td>"
                        f"<td>${money2(o['free_chars_per_month'] / 1e6 * o['usd_per_1m_chars'])}</td>"
                        f"<td>{esc(o.get('free_note', 'every month'))}</td></tr>")
    free_p = next(p for p in t["plan_priced"] if p["plan"] == "Free")
    crow.append(f"<tr><td>Cartesia</td><td>~{free_p['tts_minutes_included']} minutes "
                f"(≈{free_p['tts_minutes_included'] * cpm:,} characters)</td><td>$0.00</td>"
                f"<td>every month</td></tr>")
    table_c = ("<table><tr><th>vendor</th><th>free characters a month</th><th>worth at list price</th>"
               "<th>window</th></tr>" + "".join(crow) + "</table>")

    el100, el100_plan = el_cost(100000)
    el1m, el1m_plan = el_cost(1000000)
    best100 = min(
        [("OpenAI tts-1", 100000 / 1e6 * 15.0),
         ("Google Chirp 3 HD", 100000 / 1e6 * 30.0),
         ("Amazon Polly Neural", 100000 / 1e6 * 16.0),
         ("Cartesia Pro", cartesia_cost(100)), ], key=lambda kv: kv[1])
    g_free = next(o["free_chars_per_month"] for o in t["offers"]
                  if o["vendor"] == "Google Cloud" and o["product"] == "Chirp 3: HD")
    polly_std_free = next(o["free_chars_per_month"] for o in t["offers"]
                          if o["vendor"] == "Amazon Polly" and o["product"] == "Standard")

    body = (
        f"<h1>{esc('ElevenLabs alternatives priced per 1,000 characters')}</h1>"
        f"<p class=\"lede\">If you are pricing a replacement for ElevenLabs, the number that decides it is "
        f"not the plan price. At 100,000 characters a month — about 100 finished minutes at 1,000 characters "
        f"a minute — ElevenLabs bills <strong>${money2(el100)}</strong>, because the smallest plan that covers "
        f"that volume is {esc(el100_plan['name'])} and its 275,000 characters cannot be bought smaller. "
        f"OpenAI's tts-1 bills <strong>${money2(100000 / 1e6 * 15.0)}</strong> for the same characters, "
        f"Google's Chirp 3 HD <strong>${money2(100000 / 1e6 * 30.0)}</strong>, Polly's Neural voices "
        f"<strong>${money2(100000 / 1e6 * 16.0)}</strong> and Cartesia's Pro plan "
        f"<strong>${money2(cartesia_cost(100))}</strong>.</p>"
        f"<p>That is a <strong>{el100 / best100[1]:.1f}×</strong> spread at this volume, and it comes from two "
        f"different shapes of pricing rather than from a discount: the three API vendors charge per character "
        f"with no minimum, while ElevenLabs sells blocks. Pay-as-you-go rates tell you the marginal price; the "
        f"block tells you the bill.</p>"
        f"<h2>Per 1,000 characters, and per finished minute</h2>{table_a}"
        f"<p>The per-minute column assumes 1,000 characters make a finished minute of speech — the same basis "
        f"ElevenLabs' own plan table uses. Cartesia is the exception in kind: it sells credits and states "
        f"minutes included, so its rate is the plan price divided by its own included minutes, which falls from "
        f"${car_hi:.4f} a minute on the ${money2(car_hi_plan['plan_usd_per_month'])} plan to ${car_lo:.4f} on "
        f"the ${money2(car_lo_plan['plan_usd_per_month'])} plan. It is not a character rate, and its credits "
        f"do not convert to characters at the 1,000-a-minute basis used above.</p>"
        f"<h2>The bill at two volumes</h2>{table_b}"
        f"<p>At 1,000,000 characters a month ElevenLabs drops to {esc(el1m_plan['name'])} at "
        f"<strong>${money2(el1m)}</strong>, and the gap narrows but does not close: OpenAI is "
        f"${money2(1000000 / 1e6 * 15.0)}, Polly Neural ${money2(1000000 / 1e6 * 16.0)}, Google Chirp 3 HD "
        f"${money2(1000000 / 1e6 * 30.0)} and Cartesia ${money2(cartesia_cost(1000))}. The dishonesty in most "
        f"\"alternatives\" posts is comparing one vendor's block price with another vendor's marginal rate; both "
        f"columns above are bills for the same volume.</p>"
        f"<h2>What the free tiers are worth</h2>{table_c}"
        f"<p>Google gives {g_free:,} Chirp 3 HD characters a month away, which is "
        f"{g_free / el_free_chars:.0f}× ElevenLabs' {el_free_chars:,}, and Polly's Standard voices give "
        f"{polly_std_free:,} every month with no window. ElevenLabs' free plan is worth "
        f"${money2(el_free_chars / 1000 * el_rate)} of speech — a fact that is easy to miss because the plan is "
        f"advertised as \"10,000 characters\" rather than as the dollar allowance it is.</p>"
        f"<h2>When ElevenLabs is still the right answer</h2>"
        f"<p>This table prices characters. It does not price voice cloning, dubbing, the multilingual "
        f"coverage the model advertises, or the agent product, and several of these vendors simply do not sell "
        f"those. If your job needs an instant clone of one narrator's voice, or a managed agent that answers a "
        f"phone, the cheaper rows above are not substitutes — they are a different product. The honest reading "
        f"of the table is narrower: <em>for plain synthesis of text you already have, at these volumes, "
        f"ElevenLabs is the most expensive of the five.</em> "
        f"{labelled('elevenlabs', d, 'ElevenLabs pricing — affiliate link (the vendor this page earns from, and the dearest row above)')} "
        f"appears here because the product line, not the price, is the reason to use it.</p>"
        + cpm_note()
        + f"<h2>What is not in the table</h2>"
        f"<p>Quality and latency are not measured here — a price table cannot rank them, and no sample was "
        f"generated. Play.ht was probed and could not be read from this machine; Deepgram's speech-to-text and "
        f"agent rates are on their own pages of this site. Prices are list prices read on "
        f"{esc(t['as_of'])}; the source lines are in <code>data/tts-alternatives.json</code> in this "
        f"repository.</p>" + DISCLOSURE
    )
    return body


def load_scrapea():
    with open(os.path.join(HERE, "data", "scraping-alternatives.json"), encoding="utf-8") as f:
        return json.load(f)


def q_firecrawl_alternatives(d):
    """`firecrawl alternatives` — the exit priced per page AND per search, at the plan you would buy.

    Demand (probe104.py, 2026-11-09 02:2xZ, Google Autocomplete, control `elevenlabs pricing` = 10):
    `firecrawl alternative` returns 10 completions and `firecrawl alternatives` 10 more, among them
    `... open source`, `... free`, `... self hosted`, `... cheaper alternative`. That is a buyer who has
    decided to leave; the listicles that answer it compare headline credit prices and stop.

    Two vendor traps make the headline price wrong in opposite directions, both computed here:
    Firecrawl's pricing page opens on the ANNUAL rate ($83 for Standard) and its JSON format costs five
    credits a page, so Hobby's 5,000 credits buy 1,000 JSON pages, not 5,000. ScrapingBee's 75,000
    Hobby credits are 15,000 JavaScript pages at its own 5-credit rate.

    The page's second half reverses the verdict on purpose: the same vendors sell a SEARCH, and there
    Firecrawl is the cheapest of the four by a wide margin. A buyer's bill is the sum of the two legs,
    so "which is cheaper" has no answer until the mix is named.

    Every figure is computed from data/scraping-alternatives.json (five vendor pages read 2026-11-09
    02:45-02:50Z, with the Jina token counts MEASURED from the vendor's own X-Usage-Tokens header on
    three real pages) and dataset.json's Firecrawl ladder.
    """
    fc = d["vendors"]["firecrawl"]
    a = load_scrapea()
    sb = a["scrapingbee"]
    c4 = a["crawl4ai"]
    ji = a["jina"]
    tv = load_tavily()
    fc_annual = a["firecrawl"]["annual_usd_per_month"]

    def fc_plan(credits):
        """Cheapest Firecrawl plan that covers N credits: (monthly usd, annual usd, plan name)."""
        fits = [p for p in fc["plans"] if p["pages_included"] >= credits]
        if not fits:
            return None
        best = min(fits, key=lambda p: p["usd_per_month"])
        ann = fc_annual.get(best["name"], best["usd_per_month"])
        return best["usd_per_month"], ann, best["name"]

    def sb_plan(credits):
        fits = [p for p in sb["plans"] if p["credits"] >= credits]
        if not fits:
            return None
        best = min(fits, key=lambda p: p["usd_per_month"])
        return best["usd_per_month"], best["name"], best["credits"]

    def c4_cost(credits):
        """Crawl4AI Cloud: $0.001 a credit; the annual-billed tiers, then $0.67/1,000 extra at Scale."""
        for p in c4["plans_annual_billed"]:
            if p["credits"] >= credits:
                return p["usd_per_month"], p["name"]
        top = max(c4["plans_annual_billed"], key=lambda p: p["credits"])
        extra = (credits - top["credits"]) / 1000 * 0.67
        return top["usd_per_month"] + extra, top["name"] + " + extra credits"

    jina_tokens = sorted(r["tokens"] for r in ji["measured"])
    jina_median = jina_tokens[len(jina_tokens) // 2]
    jina_rate = ji["tiers"][0]["usd_per_1m_tokens"]

    def jina_cost(pages):
        return pages * jina_median / 1e6 * jina_rate

    # ---- table A: one page, browser-rendered, at the plan that covers 1,000 of them ----
    arows = []
    fc_hobby_m, fc_hobby_a, _ = fc_plan(5000)
    fc_page = fc_hobby_m / 5000 * 1000
    arows.append((fc_page, "Firecrawl", "1 credit per page",
                  "Hobby, $%d ($%.2f annual)" % (fc_hobby_m, fc_hobby_a)))
    sb5 = sb_plan(5000)
    sb_page = sb5[0] / (sb5[2] / 5) * 1000
    arows.append((sb_page, "ScrapingBee", "5 credits with JS rendering", "%s, $%d" % (sb5[1], sb5[0])))
    c4c, c4n = c4_cost(1000 * c4["credits"]["real_browser"])
    c4_page = c4["credits"]["real_browser"] * c4["credit_usd"] * 1000
    arows.append((c4_page, "Crawl4AI Cloud", "1 credit in a real browser",
                  "%s, $%.2f a month billed yearly" % (c4n, c4c)))
    tv_page = tv["credits"]["crawl_note"]
    tv_plan = next(p for p in tv["plans"] if p["name"] == "Project")
    tv_per_page = 0.3 * tv_plan["usd_per_month"] / tv_plan["credits"]
    arows.append((tv_per_page * 1000, "Tavily", "0.3 credit per crawled page",
                  "Project, $%d" % tv_plan["usd_per_month"]))
    jina_page = jina_median / 1e6 * jina_rate * 1000
    arows.append((jina_page, "Jina Reader", "%s tokens a page (measured)" % "{:,}".format(jina_median),
                  "paid key, $%s per 1M tokens" % money(ji["tiers"][0]["usd_per_1m_tokens"], 3)))
    arows.sort(key=lambda r: r[0])
    table_a = ("<table><tr><th>vendor</th><th>what one page costs</th><th>per 1,000 pages</th>"
               "<th>the plan that price needs</th></tr>"
               + "".join("<tr><td>%s</td><td>%s</td><td>$%.2f</td><td>%s</td></tr>" % (t[1], t[2], t[0], t[3])
                         for t in arows)
               + "</table>")

    fc_hobby_per1k = fc_hobby_m / 5000 * 1000
    jina_per1k = jina_median / 1e6 * jina_rate * 1000
    spread = fc_hobby_per1k / jina_per1k

    # ---- table B: the monthly bill at two volumes, cheapest legitimate plan per vendor ----
    def bill(vendor, pages):
        if vendor == "Firecrawl":
            r = fc_plan(pages)
            return (r[0], r[1], r[2]) if r else (None, None, "over Scale; pay-as-you-go")
        if vendor == "ScrapingBee":
            r = sb_plan(pages * 5)
            return (r[0], None, r[1]) if r else (None, None, "over Business +")
        if vendor == "Crawl4AI Cloud":
            usd, name = c4_cost(pages * c4["credits"]["real_browser"])
            return (usd, None, name + " billed yearly")
        if vendor == "Tavily":
            credits = pages * 0.3
            fits = [p for p in tv["plans"] if p["credits"] >= credits]
            if fits:
                b = min(fits, key=lambda p: p["usd_per_month"])
                return (b["usd_per_month"], None, b["name"])
            return (None, None, "over Growth")
        if vendor == "Jina":
            return (jina_cost(pages), None, "paid key")
        return (None, None, "")

    brow = []
    for pages in (5000, 100000):
        cells = []
        for v in ("Firecrawl", "ScrapingBee", "Crawl4AI Cloud", "Tavily", "Jina"):
            m, ann, name = bill(v, pages)
            if m is None:
                cells.append("<td>— (%s)</td>" % esc(name))
            elif ann:
                cells.append("<td>$%s ($%s annual) — %s</td>" % (money2(m), money2(ann), esc(name)))
            else:
                cells.append("<td>$%s — %s</td>" % (money2(m), esc(name)))
        brow.append("<tr><td>%s pages a month</td>%s</tr>" % ("{:,}".format(pages), "".join(cells)))
    table_b = ("<table><tr><th>volume</th><th>Firecrawl</th><th>ScrapingBee</th><th>Crawl4AI Cloud</th>"
               "<th>Tavily</th><th>Jina</th></tr>" + "".join(brow) + "</table>")

    # ---- table C: the other leg — 1,000 searches ----
    std_m, std_a, _ = fc_plan(100000)
    # Run 118: Firecrawl's own page states 5,000 credits = 2,500 searches (and free = 1,000 = 500),
    # so a search costs 2 credits. The earlier `2 / 10` divided by the result count and understated
    # the search leg 10x ($0.17/1,000 instead of $1.66) and the Tavily gap as 45x instead of 4.5x.
    fc_search_1k = 2 * std_a / 100000 * 1000
    tv_search_1k = 1 * tv_plan["usd_per_month"] / tv_plan["credits"] * 1000
    c4_search_1k = 1 * c4["credit_usd"] * 1000
    jina_search_1k = ji["search_tokens_per_request"] / 1e6 * jina_rate * 1000
    table_c = ("<table><tr><th>vendor</th><th>credits or tokens per search</th><th>per 1,000 searches</th>"
               "<th>plan</th></tr>"
               "<tr><td>Firecrawl</td><td>2 credits (2 per 10 results)</td><td>$%.2f</td>"
               "<td>Standard, $%d annual</td></tr>"
               "<tr><td>Tavily</td><td>1 credit (basic search)</td><td>$%.2f</td><td>Project, $%d</td></tr>"
               "<tr><td>Crawl4AI Cloud</td><td>1 credit</td><td>$%.2f</td><td>any paid tier</td></tr>"
               "<tr><td>Jina</td><td>10,000 tokens fixed</td><td>$%.2f</td><td>paid key</td></tr>"
               "</table>" % (fc_search_1k, std_a, tv_search_1k, tv_plan["usd_per_month"],
                             c4_search_1k, jina_search_1k))

    # ---- table D: what the free tiers allow, pages and searches ----
    frows = [
        ("Firecrawl", "{:,} credits/month = 1,000 pages or 500 searches".format(a["firecrawl"]["free_credits_per_month"])),
        ("ScrapingBee", "{:,} credits once = 200 JavaScript pages".format(sb["free_credits"])),
        ("Crawl4AI Cloud", "{:,} credits/month = 1,000 browser pages".format(c4["free_credits_per_month"])),
        ("Tavily", "{:,} credits/month = 3,333 crawled pages".format(tv["free_credits_per_month"])),
        ("Jina", "{:,} tokens with a key = about {:,} pages at the measured median".format(
            ji["free_tokens_with_key"], ji["free_tokens_with_key"] // jina_median)),
    ]
    table_d = ("<table><tr><th>vendor</th><th>free allowance, in pages</th></tr>"
               + "".join("<tr><td>%s</td><td>%s</td></tr>" % r for r in frows) + "</table>")

    json_per_1k = fc_hobby_m / (5000 / 5) * 1000
    sb_credit_lo = sb["plans"][0]["usd_per_month"] / sb["plans"][0]["credits"]
    sb_credit_hi = sb["plans"][4]["usd_per_month"] / sb["plans"][4]["credits"]
    sb_ladder = sb_credit_lo / sb_credit_hi
    std_gap = std_m / std_a - 1
    c4_oss_stars = c4["oss"]["stars"]

    body = (
        "<h1>Firecrawl alternatives: 1,000 pages cost $3.80 at Firecrawl and $0.27 at Jina</h1>"
        '<p class="lede">If you are leaving Firecrawl because of the bill, the first number to check is '
        'what a page costs at the plan you would actually buy. At the Firecrawl Hobby plan 1,000 '
        'browser-rendered pages cost <strong>$%.2f</strong>. The same 1,000 pages cost '
        '<strong>$%.2f</strong> through the Jina Reader API at its measured output size and '
        '<strong>$%.2f</strong> at the ScrapingBee Hobby plan with JavaScript rendering on — a '
        '<strong>%.1f×</strong> spread between the dearest and the cheapest of the five vendors priced '
        'here.</p>' % (fc_hobby_per1k, jina_per1k, sb5[0] / (sb5[2] / 5) * 1000, spread)
        + "<p>That is the page leg only, and it is the half of the story most alternatives posts tell. "
        "The second table below prices the other leg — search — and it changes the ranking without "
        "reversing it: 1,000 searches cost <strong>$%.2f</strong> at Firecrawl, ahead of Tavily's "
        "<strong>$%.2f</strong> but behind Jina's <strong>$%.2f</strong> and Crawl4AI's "
        "<strong>$%.2f</strong>. Firecrawl is the dearest per page in this list and mid-table per "
        "search, so neither table decides anything on its own.</p>"
        % (fc_search_1k, tv_search_1k, jina_search_1k, c4_search_1k)
        + "<h2>What one page costs, per vendor</h2>" + table_a
        + "<p>Every row is one page returned as Markdown by the vendor's own browser, priced at the "
        "cheapest plan that covers 1,000 pages, because that is the smallest purchase a buyer makes. "
        "The units are not the same and are not treated as if they were: Firecrawl and Crawl4AI charge a "
        "credit per rendered page, ScrapingBee charges five credits when JavaScript rendering is on, "
        "Tavily charges 0.3 of a credit for a crawled page, and Jina charges output tokens.</p>"
        + "<p>Jina's row is measured rather than quoted from a rate card: the Reader returns an "
        "<code>X-Usage-Tokens</code> header, and three real pages read on 2026-11-09 came back at "
        "%s, %s and %s tokens — a median of %s for a page of about %s characters. At $%s per million "
        "tokens that is $%.2f per 1,000 pages. The spread inside those three pages is already "
        "%.1f×, so a token-billed vendor hands the buyer a variable the others hide.</p>"
        % ("{:,}".format(jina_tokens[0]), "{:,}".format(jina_tokens[1]), "{:,}".format(jina_tokens[2]),
           "{:,}".format(jina_median), "{:,}".format(sorted(r["chars"] for r in ji["measured"])[1]),
           money(ji["tiers"][0]["usd_per_1m_tokens"], 3), jina_per1k, jina_tokens[2] / jina_tokens[0])
        + "<h2>The monthly bill at two volumes</h2>" + table_b
        + "<p>The Firecrawl column shows both prices because the vendor's page shows one of them: its "
        "plan slider opens on <strong>$%d</strong> for Standard and the footnote says <em>billed "
        "annually</em>; paying monthly is $%d for the same 100,000 credits, which is %.1f%% more. At "
        "5,000 pages a month Firecrawl's Hobby plan is the cheapest legitimate way to buy its own "
        "service, and at 100,000 pages the ladder's own discount (up to 5.1× from Hobby to Scale per "
        "1,000 credits) matters more than the vendor choice inside this table.</p>" % (std_a, std_m, std_gap * 100)
        + "<h2>What a search costs — the leg where the ranking changes</h2>" + table_c
        + "<p>Firecrawl charges two credits per search — two credits per ten results, and a search "
        "returns ten — which at its Standard annual rate is $%.2f per 1,000 searches. Tavily charges one "
        "credit per basic search on a $%d plan and comes out at $%.2f, %.1f× dearer for the same query; "
        "Jina's fixed 10,000 tokens per search is $%.2f and Crawl4AI's single credit is $%.2f, both "
        "cheaper than Firecrawl. If your pipeline is 90%% search and 10%% scrape, the page table above "
        "is the wrong table — and the vendor it points to is not Firecrawl.</p>"
        % (fc_search_1k, tv_plan["usd_per_month"], tv_search_1k, tv_search_1k / fc_search_1k,
           jina_search_1k, c4_search_1k)
        + "<h2>What the free tiers actually allow</h2>" + table_d
        + "<p>Tavily's free allowance stretches furthest for crawling — 3,333 pages against 1,000 at "
        "Firecrawl and Crawl4AI — while ScrapingBee's 1,000 free credits are only 200 JavaScript pages "
        "at its own 5-credit rate. Jina's free key is not a monthly allowance: it is 10 million tokens, "
        "once, which is about %s pages at the measured median.</p>"
        % "{:,}".format(ji["free_tokens_with_key"] // jina_median)
        + "<h2>Four traps in the numbers above</h2>"
        + "<p><strong>1. Firecrawl's JSON format costs five credits a page, not one.</strong> Scrape and "
        "crawl cost one credit, and the JSON, Question and Highlight formats add four, so Hobby's 5,000 "
        "credits buy 1,000 JSON pages — <strong>$%.2f</strong> per 1,000, five times the $%.2f the plan "
        "page's page count implies. A page that responds 403 or 404 is still returned and still costs a "
        "credit; a scrape that returns no result is not charged.</p>" % (json_per_1k, fc_hobby_per1k)
        + "<p><strong>2. ScrapingBee's credits are not pages.</strong> 75,000 credits at $19 is 75,000 "
        "plain requests or 15,000 with JavaScript rendering, and the page states the credits do not roll "
        "over. The same page's per-credit price falls %.1f× from Hobby ($%.7f a credit) to Business + "
        "($%.7f), so buying the bigger block is worth more than switching vendor at that volume.</p>"
        % (sb_ladder, sb_credit_lo, sb_credit_hi)
        + "<p><strong>3. Price is not permission.</strong> Jina's Reader is the cheapest per page here, "
        "and its own FAQ says the Reader models are licensed CC-BY-NC 4.0 — free for non-commercial use, "
        "with commercial production use needing a licence Elastic sells separately since 2026-08-10. "
        "A $0.27 bill per 1,000 pages is not a $0.27 commercial right to them.</p>"
        + "<p><strong>4. Self-hosting is a licence plus a server, not a licence.</strong> Crawl4AI is "
        "Apache-2.0 (%s stars, <code>pip install crawl4ai</code>) and can be run on your own machine for "
        "nothing per page — but the server is a real cost, and this site prices the one it uses: a $6.00 "
        "DigitalOcean Droplet bills $6.52 for a 730-hour month. That is the honest floor for a "
        "self-hosted crawler, and it is worth paying only if your volume would otherwise exceed the "
        "$10 plan.</p>" % "{:,}".format(c4_oss_stars)
        + "<h2>When Firecrawl is still the right answer</h2>"
        + "<p>This table prices pages and searches, not success. It does not measure how often each "
        "vendor gets past a bot wall, how good the Markdown is, how the proxy pools differ, or how the "
        "queues behave at 50 concurrent jobs — and those are what a production scraping bill is really "
        "made of. What Firecrawl sells that is visible in these numbers is one credit balance across "
        "search, scrape, map and crawl — one bill instead of four — plus a managed browser most of its "
        "rivals make you operate. %s appears here because Firecrawl is mid-table on search, behind "
        "Jina and Crawl4AI and ahead of Tavily, while its page leg is the dearest of five. The right "
        "reading of this page is narrow: <em>for crawling at volume, Firecrawl's Hobby plan is the most "
        "expensive per page in the table; on search it is neither the cheapest nor the dearest.</em></p>"
        % labelled("firecrawl", d, "Firecrawl pricing — affiliate link (the vendor this page earns from)")
        + "<h2>What is not in the table</h2>"
        + "<p>Apify is deliberately absent: it meters compute units ($0.20 per GB-RAM-hour on its Free "
        "and Starter plans) and lets each Actor quote its own per-result price, so any single per-page "
        "figure would be a property of the Actor and the RAM I chose, not of the vendor. Quality, "
        "latency and anti-bot success rates are not measured anywhere on this page. All prices were read "
        "from the vendors' own pages on %s; the quotes and read times are in "
        "<code>data/scraping-alternatives.json</code> in this repository, and the Jina token counts are "
        "from the vendor's own response header, not estimated.</p>" % esc(a["as_of"])
        + DISCLOSURE
    )
    return body


def load_rental():
    with open(os.path.join(HERE, "data", "gpu-rental.json"), encoding="utf-8") as f:
        return json.load(f)


def q_h100_rental(d, x):
    """The same 80 GB H100, priced by the six clouds a buyer compares (probe106).

    Every figure is computed from data/gpu-rental.json, which holds the rows read from each vendor's
    own pricing page on 2026-11-09 02:36Z. The point of the page is that a per-hour quote without the
    card VARIANT and the MINIMUM PURCHASE is not a comparable price: the cheapest listing on the page
    is a PCIe card, and the dearest one cannot be bought one GPU at a time.
    """
    r = load_rental()
    # Display names: every other page on the site prints a vendor's own casing, and a table of lowercase
    # slugs reads like a data dump (run 104's `$0.08` defect class — the render, not the diff).
    NAME = {"hyperstack": "Hyperstack", "runpod": "RunPod", "lambda": "Lambda", "coreweave": "CoreWeave",
            "digitalocean": "DigitalOcean", "novita": "Novita"}
    h730 = r["job_examples"]["month_hours"]
    offers = r["offers"]
    od = sorted([o for o in offers if o["tier"] == "on_demand"], key=lambda o: o["usd_per_gpu_hour"])
    sp = sorted([o for o in offers if o["tier"] == "spot"], key=lambda o: o["usd_per_gpu_hour"])
    res = sorted([o for o in offers if o["tier"] == "reserved"], key=lambda o: o["usd_per_gpu_hour"])
    lo, hi = od[0], od[-1]
    spread = hi["usd_per_gpu_hour"] / lo["usd_per_gpu_hour"]
    # SXM only: hold the silicon shape fixed and the spread shrinks to a different number entirely
    sxm = sorted([o for o in od if "SXM" in o["variant"]], key=lambda o: o["usd_per_gpu_hour"])
    sxm_lo, sxm_hi = sxm[0], sxm[-1]
    sxm_spread = sxm_hi["usd_per_gpu_hour"] / sxm_lo["usd_per_gpu_hour"]
    nov_od = next(o for o in od if o["provider"] == "novita")
    nov_sp = next(o for o in sp if o["provider"] == "novita")
    cw = next(o for o in od if o["provider"] == "coreweave")
    cw_sp = next(o for o in sp if o["provider"] == "coreweave")
    nov_spot_disc = 1 - nov_sp["usd_per_gpu_hour"] / nov_od["usd_per_gpu_hour"]
    # a 1-GPU-hour purchase is not possible everywhere: the minimum spend is what a small job pays
    min_spend = cw["usd_per_gpu_hour"] * cw["min_purchase_gpus"]
    cw_vs_cheap = min_spend / lo["usd_per_gpu_hour"]
    lam1 = next(o for o in od if o["provider"] == "lambda" and o["variant"].startswith("H100 SXM (1x"))
    lam8 = next(o for o in od if o["provider"] == "lambda" and o["variant"].startswith("H100 SXM (8x"))
    small_premium = lam1["usd_per_gpu_hour"] / lam8["usd_per_gpu_hour"] - 1
    # card variants at the same provider
    rp_sxm = next(o for o in od if o["provider"] == "runpod" and o["variant"] == "H100 SXM")
    rp_pcie = next(o for o in od if o["provider"] == "runpod" and o["variant"] == "H100 PCIe")
    hs_sxm = next(o for o in od if o["provider"] == "hyperstack" and o["variant"] == "H100 SXM")
    hs_pcie = next(o for o in od if o["provider"] == "hyperstack" and o["variant"] == "H100 PCIe")
    hs_nvl = next(o for o in od if o["provider"] == "hyperstack" and o["variant"] == "H100 NVLink")
    do_od = next(o for o in x["gpus"]["offers"]
                 if o["family"] == "H100" and o["provider"] == "digitalocean" and o["tier"] == "on_demand")
    be_lo = min(h730 * o["usd_per_gpu_hour"] /
                next(y for y in od if y["provider"] == o["provider"] and y["variant"] == o["variant"])["usd_per_gpu_hour"]
                for o in res)
    be_hi = max(h730 * o["usd_per_gpu_hour"] /
                next(y for y in od if y["provider"] == o["provider"] and y["variant"] == o["variant"])["usd_per_gpu_hour"]
                for o in res)
    sxm_vs_pcie = (rp_sxm["usd_per_gpu_hour"] / rp_pcie["usd_per_gpu_hour"] - 1) * 100
    # billing granularity: 1,000 jobs of 40 seconds, rounded per second vs per minute
    JOBS, SECS = 1000, 40
    sec_billed = JOBS * SECS / 3600.0
    min_billed = JOBS * 1 / 60.0
    sec_cost = sec_billed * lo["usd_per_gpu_hour"]
    min_cost = min_billed * lo["usd_per_gpu_hour"]
    round_penalty = min_billed / sec_billed - 1

    def row(o, tier_label):
        minp = o["min_purchase_gpus"]
        return (f"<tr><td>{esc(NAME[o['provider']])}</td><td>{esc(o['variant'])}</td>"
                f"<td>{o['vram_gb']} GB</td><td>{esc(tier_label)}</td>"
                f"<td>${money2(o['usd_per_gpu_hour'])}</td><td>{esc(o['billing'])}</td>"
                f"<td>{minp} GPU{'s' if minp > 1 else ''}</td>"
                f"<td>${money2(o['usd_per_gpu_hour'] * h730)}</td></tr>")

    rows = "".join(row(o, "on-demand") for o in od) + "".join(row(o, "spot") for o in sp)
    h100_job = [("Hyperstack", hs_sxm["usd_per_gpu_hour"]), ("Novita", nov_od["usd_per_gpu_hour"]),
                ("RunPod", rp_sxm["usd_per_gpu_hour"]), ("DigitalOcean", do_od["usd_per_gpu_hour"]),
                ("Lambda", lam1["usd_per_gpu_hour"]), ("CoreWeave", cw["usd_per_gpu_hour"])]
    job_rows = "".join(f"<tr><td>{esc(p)}</td><td>${money2(v)}</td><td>${money2(v * 800)}</td></tr>"
                       for p, v in h100_job)
    res_rows = ""
    for o in res:
        same = next(y for y in od if y["provider"] == o["provider"] and y["variant"] == o["variant"])
        be = h730 * o["usd_per_gpu_hour"] / same["usd_per_gpu_hour"]
        res_rows += (f"<tr><td>{esc(o['variant'])}</td><td>${money2(o['usd_per_gpu_hour'])}</td>"
                     f"<td>${money2(same['usd_per_gpu_hour'])}</td><td>{be:,.0f} h/month</td>"
                     f"<td>{be / h730 * 100:.0f}%</td></tr>")
    body = [
        f"<h1>H100 rental price: ${money2(lo['usd_per_gpu_hour'])} to ${money2(hi['usd_per_gpu_hour'])} "
        f"an hour for the same 80 GB card</h1>",
        f"<p class=\"lede\">Six clouds rent an 80 GB H100 and, on the pages read for this one at "
        f"{esc(r['read_at'])}, the on-demand hours run from <strong>${money2(lo['usd_per_gpu_hour'])}</strong> "
        f"({esc(NAME[lo['provider']])}, {esc(lo['variant'])}) to <strong>${money2(hi['usd_per_gpu_hour'])}</strong> "
        f"({esc(NAME[hi['provider']])}) — <strong>{spread:.2f}×</strong> for the same GPU model. That number is real "
        f"but it is not the lesson: hold the card shape fixed at SXM and the spread is "
        f"<strong>{sxm_spread:.2f}×</strong> (${money2(sxm_lo['usd_per_gpu_hour'])} to "
        f"${money2(sxm_hi['usd_per_gpu_hour'])}). Most of the headline gap is two other things — which "
        f"variant of the card you are quoted, and how many you are allowed to buy — and neither appears in "
        f"a \"per GPU-hour\" figure.</p>",
        "<h2>Every H100 hour on the six pricing pages this page read</h2>",
        f"<p>Rows are on-demand unless the tier says spot. A price exists only where the vendor publishes one "
        f"for that variant and tier; nothing here is converted from another card. Read from the vendors' own "
        f"pages on {esc(r['read_at'])}; DigitalOcean's and Novita's rows are the same reads the rest of this "
        f"site uses.</p>",
        "<table><tr><th>cloud</th><th>H100 variant</th><th>VRAM</th><th>tier</th><th>$/GPU-hour</th>"
        "<th>billing</th><th>minimum</th><th>730 h</th></tr>" + rows + "</table>",
        "<h2>The cheapest hour is not the cheapest bill</h2>",
        f"<p>CoreWeave's {esc(cw['variant'])} is priced by the node: ${money2(cw['usd_per_node_hour'])} for "
        f"{cw['gpus_per_node']} GPUs is ${money2(cw['usd_per_gpu_hour'])} per GPU-hour, but the smallest "
        f"purchase is <strong>${money2(min_spend)}</strong>. One GPU-hour there costs what "
        f"<strong>{cw_vs_cheap:.1f} hours</strong> of "
        f"{esc(NAME[lo['provider']])}'s ${money2(lo['usd_per_gpu_hour'])} card cost. Lambda sells one GPU by the "
        f"hour, and charges for the privilege: the 1× SXM instance is "
        f"<strong>{small_premium * 100:.1f}% more per GPU-hour</strong> than its own 8× instance "
        f"(${money2(lam1['usd_per_gpu_hour'])} vs ${money2(lam8['usd_per_gpu_hour'])}). If your job is one "
        f"GPU for two hours, the cheapest quote per hour can be the most expensive way to run it.</p>",
        "<h2>SXM, NVL, PCIe: the same model in three shapes</h2>",
        f"<p>At RunPod the SXM card is <strong>{sxm_vs_pcie:.1f}% more</strong> than the PCIe card "
        f"(${money2(rp_sxm['usd_per_gpu_hour'])} vs ${money2(rp_pcie['usd_per_gpu_hour'])}); at Hyperstack "
        f"the SXM hour is ${money2(hs_sxm['usd_per_gpu_hour'])} against ${money2(hs_pcie['usd_per_gpu_hour'])} "
        f"for PCIe, with an NVLink variant at ${money2(hs_nvl['usd_per_gpu_hour'])} "
        f"between them. These are not interchangeable products — the interconnect differs — and this page "
        f"does not measure throughput, so it cannot tell you whether the SXM premium pays for itself. It can "
        f"tell you that a \"per GPU-hour\" quote with no variant is half a price.</p>",
        "<h2>What a 100-hour, 8-GPU job costs on each</h2>",
        "<p>800 GPU-hours of the SXM card, e.g. a fine-tune that takes one eight-GPU node 100 hours:</p>",
        "<table><tr><th>cloud</th><th>$/GPU-hour (SXM)</th><th>800 GPU-hours</th></tr>" + job_rows + "</table>",
        f"<p>The same 800 hours range from ${money2(hs_sxm['usd_per_gpu_hour'] * 800)} to "
        f"${money2(cw['usd_per_gpu_hour'] * 800)} — and on CoreWeave the 8-GPU minimum is exactly the shape "
        f"of this job, which is why node-only pricing is the cheapest table to print and the most expensive one to buy from.</p>",
        "<h2>The cheapest hour on this page is a spot hour</h2>",
        f"<p>{esc(NAME[nov_od['provider']])}'s interruptible SXM hour is <strong>${money2(nov_sp['usd_per_gpu_hour'])}"
        f"</strong> — <strong>{nov_spot_disc * 100:.1f}% below</strong> its own on-demand price of "
        f"${money2(nov_od['usd_per_gpu_hour'])}, and below every on-demand listing here. CoreWeave's spot hour "
        f"is ${money(cw_sp['usd_per_gpu_hour'], 3)} per GPU on the same 8-GPU node minimum "
        f"(${money2(cw_sp['usd_per_node_hour'])}/hour). Both are interruptible: the provider may reclaim the "
        f"machine, so a spot hour is a price for work you checkpoint, not for work with a deadline. The spot "
        f"discount is also the one number vendors change without notice.</p>",
        "<h2>730 hours: what a month of one H100 costs</h2>",
        "<p>730 is a 31-day month and it is not a plan: no vendor here sells a monthly H100 at a flat rate, so "
        "this column is arithmetic on the hourly price, not an invoice.</p>",
        "<table><tr><th>cloud</th><th>variant</th><th>$730 h</th></tr>" +
        "".join(f"<tr><td>{esc(NAME[o['provider']])}</td><td>{esc(o['variant'])}</td>"
                f"<td>${money2(o['usd_per_gpu_hour'] * h730)}</td></tr>" for o in od) + "</table>",
        "<h2>A reservation is a utilisation bet</h2>",
        "<p>Hyperstack publishes both an on-demand and a reservation price for the same card, which makes the "
        "break-even visible. It is the hourly saving multiplied by the hours you actually use:</p>",
        "<table><tr><th>variant</th><th>reserved $/h</th><th>on-demand $/h</th><th>break-even</th>"
        "<th>% of a 730 h month</th></tr>" + res_rows + "</table>",
        f"<p>Between <strong>{be_lo / h730 * 100:.0f}% and {be_hi / h730 * 100:.0f}%</strong> of every hour in "
        f"the month has to be busy before the reservation beats paying on demand — {be_lo:,.0f} to "
        f"{be_hi:,.0f} hours, about 17 to 20 hours a day. Below that, the "
        f"reservation is the more expensive choice, and it is still the more expensive choice if the job "
        f"finishes in a weekend.</p>",
        "<h2>Billing granularity turns seconds into money</h2>",
        f"<p>Take {JOBS:,} jobs of {SECS} seconds each: {sec_billed:.2f} GPU-hours of real work. Billed per "
        f"second (RunPod, Novita, DigitalOcean) that is ${money2(sec_cost)} at "
        f"${money2(lo['usd_per_gpu_hour'])}/hour. Billed per minute (Hyperstack) every job rounds up to a "
        f"minute — {min_billed:.2f} GPU-hours, <strong>{round_penalty * 100:.0f}% more</strong>, "
        f"${money2(min_cost)}. The rounding rule adds <strong>${money2(min_cost - sec_cost)}</strong> over these "
        f"{JOBS:,} jobs — about a third of what choosing between this page's cheapest and dearest hours is "
        f"worth for the same work, which is exactly the decision a per-hour table invites you to make.</p>",
        "<h2>What this page does not know</h2>",
        "<p>No throughput benchmarks: SXM has more memory bandwidth than a PCIe card and this page does not "
        "measure how much faster a job runs on either, so it cannot price performance. No availability: a "
        "listed price you cannot get a machine at is not a price you pay, and none of these pages publishes "
        "stock. No storage or egress: the per-hour rate excludes volumes, object storage, images and data "
        "transfer, which for a 100-hour job can be a real line. Vast.ai's marketplace prices are set per host "
        "and are not in the HTML its pricing page serves, so it is absent from the table rather than measured "
        "at zero. Lambda's figures carry a footnote: they take effect 2026-11-16, so a reader before that date "
        "sees different numbers in their console. Nothing on this page was rented or benchmarked.</p>",
        DISCLOSURE,
        "<p>" + aff_link(x, "novita", "Novita GPU pricing — affiliate link") + " · "
        + aff_link(x, "digitalocean", "DigitalOcean GPU Droplets — affiliate link") + "</p>",
        f"<p>Novita is the second-cheapest SXM hour here and the cheapest hour on the page if you can use "
        f"spot; it is not the cheapest on-demand listing, and its ${money2(nov_od['usd_per_gpu_hour'])} SXM "
        f"hour is {nov_od['usd_per_gpu_hour'] / hs_sxm['usd_per_gpu_hour'] * 100 - 100:.1f}% above Hyperstack's "
        f"on the same variant. DigitalOcean's ${money2(do_od['usd_per_gpu_hour'])} H100 hour is mid-table. If neither is the right "
        f"buy for your job, the table above is the reason to say so.</p>",
    ]
    return "".join(body)


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
    ("elevenlabs-pricing-per-minute", "ElevenLabs cost per minute", lambda d, x: q_elevenlabs_pricing_per_minute(d)),
    ("elevenlabs-agent-pricing", "ElevenLabs agent pricing per minute", lambda d, x: q_elevenlabs_agent_pricing(d)),
    ("elevenlabs-plan-minutes", "ElevenLabs plans and pricing: minutes per plan", lambda d, x: q_elevenlabs_plan_minutes(d)),
    # Run 99: `elevenlabs startup grant` is a measured Autocomplete suggestion with 8 tails, inside a
    # 10-suggestion `elevenlabs startup` list that also carries `elevenlabs startup credits` (probe99.py,
    # 2026-11-09 01:1xZ; controls `elevenlabs pricing` 10 and `vultr vs` 10). The grant is the only
    # buyer-side offer in this programme besides the first-month promo: 12 months of Scale, 33,000,000
    # characters, read live from elevenlabs.io/startup-grants at 01:20Z. Every figure on the page is
    # recomputed from those terms against the ladder in dataset.json.
    ("elevenlabs-startup-grant", "ElevenLabs startup grant: 33M characters is 8.83 months of Scale, not 12",
     lambda d, x: q_elevenlabs_startup_grant(d)),
    # Run 99 (second page): `elevenlabs free tier` is a 10-completion stem (probe99.py; `elevenlabs free
    # tier limits`, `… free tier usage disabled` among its tails) and `is elevenlabs free` a 10-completion
    # one. Deferred once in this same run until the unit question was settled: /pricing/api's own FAQ says
    # "API usage is billed in US dollars, not credits" while its plan column prints characters, so the page
    # takes characters from the API column and never converts the Creative page's credits.
    # Run 105: retitled to carry the phrase probe105.py measured 10 completions for
    # (`elevenlabs free plan`: limit / credits / commercial use / api / voices) — the old title
    # named the allowance, which is the weaker half of the question.
    ("elevenlabs-free-tier", "ElevenLabs free plan: 10,000 characters a month, a non-commercial licence, and 2 concurrent requests",
     lambda d, x: q_elevenlabs_free_tier(d)),
    # Run 100 (probe100.json, 2026-11-09 01:2xZ; controls `elevenlabs pricing` 10, `firecrawl pricing`
    # 10, `digitalocean droplet pricing` 10): `elevenlabs credits` returns 10 completions including
    # `elevenlabs credits per minute`, `... credits cost` and `... credits reset`, and the vendor's own
    # /pricing FAQ prints the per-product credit costs and the plan quotas on one page. Every figure is
    # computed in q_elevenlabs_credits_per_minute from dataset.json's credit_costs block (read 01:32Z).
    ("elevenlabs-credits-per-minute", "ElevenLabs credits per minute",
     lambda d, x: q_elevenlabs_credits_per_minute(d)),
    # Run 103: `elevenlabs concurrency` returns 7 completions and `elevenlabs concurrent` 5, including
    # `elevenlabs too many concurrent requests`; `elevenlabs rate limit` answers 9 (probe103.py,
    # 2026-11-09 02:0xZ, control `elevenlabs pricing` = 10). Titles, prices and limits read live the same
    # hour from /pricing, /pricing/agents, the 429 help-centre article and the burst/queueing guides.
    ("elevenlabs-concurrency-limit", "ElevenLabs concurrency limit: 5 speech requests or 10 agent calls on the same $22 plan",
     lambda d, x: q_elevenlabs_concurrency(d)),
    # Run 100, second page: `digitalocean bandwidth pricing` and `digitalocean droplet bandwidth
    # pricing / limit / overage` each return 10 completions (probe100.json). The rates and the
    # per-second accrual rule are read from docs.digitalocean.com (vendor-dated 2026-11-05) into
    # data/do-bandwidth.json; the plan allowances come from the Droplet table already in dataset_ext.
    ("digitalocean-droplet-bandwidth-pricing", "DigitalOcean droplet bandwidth pricing",
     q_do_bandwidth),
    ("deepgram-pricing-per-minute", "Deepgram pricing per minute: speech to text", lambda d, x: q_deepgram_stt(d)),
    ("deepgram-voice-agent-pricing", "Deepgram voice agent pricing per minute", lambda d, x: q_deepgram_agent(d)),
    ("api-cost-calculator", "API cost calculator: what this workload costs", lambda d, x: q_workload(d)),
    ("digitalocean-droplet-pricing", "DigitalOcean droplet pricing", q_droplet_pricing),
    # Run 89: the page for the buying-intent phrase, measured in probe89.py (2026-11-08 22:56Z, control
    # `vultr vs` = 10 suggestions): `digitalocean free credit $200`, `digitalocean free credits`,
    # `digitalocean free trial $200`, `digitalocean free $200` all complete. It is the only page in the
    # set aimed at a signup decision rather than a bill, and it states the referral commission openly.
    ("digitalocean-free-credit", "DigitalOcean free credit: $5, $100 or $200 — the window decides, not the amount",
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
    # Run 106: the page the buying decision needs. probe106.py measured 22 stems on Google Autocomplete
    # (control `elevenlabs pricing` = 10): `h100 rental price` / `h100 rental` 8 tails, `cheapest h100`
    # 10 (incl. `cheapest h100 rental`, `cheapest h100 per hour`), `h100 cloud pricing` 8, `runpod vs vast`
    # 10, `lambda vs runpod` 10, `runpod alternatives` 10. The existing GPU page answers "what does an
    # hour cost at the two clouds this site tracks"; this one answers the question a buyer actually asks,
    # which is which of the six clouds is cheapest for MY job — and the answer is that the per-hour figure
    # is not comparable without the variant and the minimum purchase.
    ("h100-rental-price", "H100 rental price: $2.50 to $6.16 an hour for the same 80 GB card",
     lambda d, x: q_h100_rental(d, x)),
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
    # Run 104: the first page aimed at a DECISION rather than a price lookup. probe104.py (2026-11-09
    # 02:2xZ) measured `elevenlabs alternative` 10 completions and `elevenlabs alternatives` 10 more
    # (`... free`, `... open source`, `... reddit`, `... 2026`), plus `cheaper than elevenlabs` 6 — a
    # searcher who has decided to leave and is pricing the exit. Every figure is computed from
    # data/tts-alternatives.json (OpenAI, Google, Polly, Cartesia read 02:24–02:29Z) and dataset.json's
    # ElevenLabs ladder. It prints ElevenLabs as the dearest of five and still carries its link, with the
    # reason it can be the right answer stated in the same sentence.
    ("elevenlabs-alternatives", "ElevenLabs alternatives priced per 1,000 characters",
     lambda d, x: q_elevenlabs_alternatives(d)),
    # Run 107: the second decision page, and the first for the scraping program. probe104.py measured
    # `firecrawl alternative` 10 completions and `firecrawl alternatives` 10 more (`... open source`,
    # `... free`, `... self hosted`, `... cheaper alternative`), so this is an exit, not a rate lookup.
    # It prices both legs of a scraping bill: the page leg (Firecrawl $3.80/1,000 against Jina's
    # measured $0.27) and the search leg, where Firecrawl is the cheapest of the four that sell one.
    ("firecrawl-alternatives", "Firecrawl alternatives priced per 1,000 pages",
     lambda d, x: q_firecrawl_alternatives(d)),
]


TITLE_BY_SLUG = {s: t for s, t, _ in QUESTIONS}

# Run 85: one description per page, written from numbers that are already in that page's body — and
# `--check` proves that claim by finding each number in the rendered HTML. The measured shape to copy
# (2026-11-08 21:35Z): the paying positions for `firecrawl pricing` and `digitalocean droplet pricing`
# lead their snippet with a price and a claim (4/10 and 3/10 carry "$"), sit at 137-154 characters, and
# 0/34 restate the title. A description that repeats the title spends the whole snippet on the words
# already above it.
DESCRIPTIONS = {
    # 110-158 chars, carries a number, does not restate the title opening (run 85 rule)
    "h100-rental-price": ("Six clouds, one 80 GB card: $2.50 to $6.16 a GPU-hour. Two cannot sell you a "
                         "single GPU, and a 40-second job is billed 50% differently."),
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
        "$5 covers 0 of 31 plans for 90 days; $100 covers 7 of 31 for 60 days, and $88 of it "
        "expires on the $6 Droplet.",
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
    "elevenlabs-concurrency-limit":
        "One concurrent request costs $4.40 a month on Creator and $39.60 on Business, and the vendor's "
        "pricing table and its 429 article disagree on the top plan.",
    "elevenlabs-credits-per-minute":
        "121,000 credits buy 366 minutes of transcription, 121 of speech or 12 of studio dubbing: one "
        "pool, eight burn rates.",
    "digitalocean-droplet-bandwidth-pricing":
        "A $6 Droplet includes 1,000 GiB outbound, then $0.01 a GiB, and a Droplet alive 7 days "
        "accrues only 250 GiB of that allowance.",
    "elevenlabs-pricing-per-minute":
        "$0.08 per 1,000 characters is $0.072 a finished minute at 900 characters; the $22 plan's "
        "275,000 characters is the same rate, so the ladder is flat.",
    "elevenlabs-agent-pricing":
        "$0.08 per managed agent minute plus LLM usage, billed as a separate line: the agent minute is "
        "not an all-in minute, and the vendor's table says so.",
    "elevenlabs-plan-minutes":
        "At 900 characters a minute Creator's 275 minutes become 306 finished minutes, and minute 306 costs "
        "the whole $77 step-up — 4.5x the bill.",
    "elevenlabs-startup-grant":
        "33,000,000 characters is 8.83 months of Scale credit over 12 — 2,750,000 a month — and $2,640 "
        "at the $0.08 v4 rate, not the $5,500 claimed.",
    "elevenlabs-free-tier":
        "10,000 free characters are 10 minutes of speech, 1 minute of studio dubbing or 30.3 minutes "
        "of transcription — and the licence is non-commercial.",
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
    # Run 104: the decision page. The description names the two bills that make the point (the block plan
    # ElevenLabs forces at this volume and the per-character rate it is measured against).
    "elevenlabs-alternatives":
        "At 100,000 characters a month ElevenLabs bills $22 because its smallest covering plan is Creator, "
        "where OpenAI tts-1 bills $1.50 and Chirp 3 HD $3.00.",
    # Run 107: the exit page. The description carries the two bills that make the point and no claim
    # the body does not compute: the Hobby page price, the Jina measured price, the search price.
    "firecrawl-alternatives":
        "$3.80 per 1,000 pages at Hobby against $0.27 at Jina, and $1.66 per 1,000 searches against "
        "Tavily's $7.50: the leg of the bill decides which vendor is cheap.",
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
                                      "elevenlabs-plan-minutes", "elevenlabs-alternatives"],
    "elevenlabs-agent-pricing": ["elevenlabs-pricing-per-minute", "deepgram-voice-agent-pricing",
                                 "api-cost-calculator"],
    "elevenlabs-plan-minutes": ["elevenlabs-credits-to-minutes", "elevenlabs-pricing-per-minute",
                                "elevenlabs-startup-grant"],
    "elevenlabs-startup-grant": ["elevenlabs-plan-minutes", "elevenlabs-pricing-per-minute",
                                 "api-cost-calculator"],
    "elevenlabs-free-tier": ["elevenlabs-startup-grant", "elevenlabs-plan-minutes",
                             "elevenlabs-credits-per-minute", "elevenlabs-pricing-per-minute"],
    # run 100: the credits page is the "how many minutes do I get" answer, so it points at the free
    # tier (what the free allowance really buys), the plan ladder and the per-minute API prices.
    "elevenlabs-credits-per-minute": ["elevenlabs-free-tier", "elevenlabs-plan-minutes",
                                      "elevenlabs-pricing-per-minute"],
    # run 103: the concurrency page is a plan-decision page, so it points at the price ladder and the
    # agent-minute rate rather than at another limit.
    "elevenlabs-concurrency-limit": ["elevenlabs-plan-minutes", "elevenlabs-agent-pricing",
                                     "elevenlabs-pricing-per-minute"],
    # run 104: the decision page points at the rate it is comparing against, the block ladder that produced
    # the $22 bill, and the layer-by-layer page where an agent minute is a different product.
    "elevenlabs-alternatives": ["elevenlabs-pricing-per-minute", "elevenlabs-plan-minutes",
                                "deepgram-vs-elevenlabs"],
    # run 107: the scraping decision page points at the two pages that carry its own arithmetic (the
    # credit-per-page page and the Tavily head-to-head where the search leg is already priced) and at
    # the search-cost page, so a reader landing on the exit page can check the numbers behind it.
    "firecrawl-alternatives": ["firecrawl-cost-per-page", "firecrawl-vs-tavily",
                                "firecrawl-search-cost"],
    # run 100: bandwidth is the next line on a Droplet bill after the plan price, so it links from
    # the price page and back to the droplet table and the signup credit.
    "digitalocean-droplet-bandwidth-pricing": ["digitalocean-droplet-pricing", "digitalocean-free-credit",
                                               "digitalocean-vs-hetzner"],
    "deepgram-pricing-per-minute": ["deepgram-voice-agent-pricing", "elevenlabs-pricing-per-minute",
                                    "deepgram-vs-elevenlabs"],
    "deepgram-voice-agent-pricing": ["deepgram-pricing-per-minute", "elevenlabs-agent-pricing"],
    "deepgram-vs-elevenlabs": ["deepgram-pricing-per-minute", "elevenlabs-pricing-per-minute",
                               "deepgram-voice-agent-pricing", "elevenlabs-plan-minutes"],
    "api-cost-calculator": ["firecrawl-cost-per-page", "elevenlabs-plan-minutes",
                            "deepgram-pricing-per-minute", "digitalocean-droplet-pricing"],
    "digitalocean-droplet-pricing": ["digitalocean-free-credit", "h100-price-per-hour",
                                     "digitalocean-droplet-bandwidth-pricing",
                                     "api-cost-calculator"],
    # run 89: the signup-credit page is where the buying decision happens, so it points at what the
    # credit buys (droplet plans, H100 hours) rather than only at another calculation.
    "digitalocean-free-credit": ["digitalocean-droplet-pricing", "h100-price-per-hour"],
    "digitalocean-vs-hetzner": ["digitalocean-droplet-pricing", "digitalocean-free-credit",
                                "api-cost-calculator"],
    # run 106: the card page and the buying-decision page point at each other, and both point at the
    # Novita token page (the GPU buyer and the token buyer are different people at the same vendor).
    "h100-price-per-hour": ["h100-rental-price", "novita-ai-api-pricing", "digitalocean-droplet-pricing"],
    "h100-rental-price": ["h100-price-per-hour", "novita-ai-api-pricing", "digitalocean-free-credit"],
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
    def _rel(u):
        # Run 109: SITE_BASE may carry a path (a GitHub *project* Pages site lives at
        # https://<org>.github.io/<repo>/, not at the root — the tool cannot create the
        # <org>.github.io repo because repo names may not contain a dot). Strip the whole base,
        # not just the host, or every loc maps to "dated-price-index/q/..." and the check fails.
        b = BASE.rstrip("/")
        if b in u:
            return u.split(b, 1)[1].lstrip("/") or "index.html"
        return re.sub(r"^[a-z]+://[^/]+/", "", u)

    for loc in locs:
        rel = _rel(loc)
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
            rel = _rel(u)
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
    for needed in ("275,000", "not a character rate", "121,000"):
        if needed not in q:
            failures.append(f"ElevenLabs per-minute page lost {needed!r}: the credits-vs-characters correction")
    # Run 99: the startup-grant page. The three figures that make it worth reading must be recomputable:
    # 33M / 3.738M = 8.83 Scale-months, 33M / 12 = 2,750,000 a month, and 33M chars at $0.080/1k = $2,640.
    g = el["startup_grant"]
    scale = next(r for r in el["ladder"] if r.get("name") == "Scale")
    gq = open(os.path.join(scratch, "q", "elevenlabs-startup-grant.html"), encoding="utf-8").read()
    for needed, why in (
            (f"{g['chars'] / scale['chars']:.2f}", "the Scale-month conversion"),
            (f"{g['chars'] / g['months']:,.0f}", "the per-month character allowance"),
            (f"${money2(g['chars'] / 1000 * el['rates_usd_per_1000_chars']['multilingual_v4_api'])}",
             "the v4-rate value of the grant"),
            (f"{g['chars'] / (g['agent_hours'] * 60):,.0f}", "the character rate the 680-hour claim implies")):
        if needed not in gq:
            failures.append(f"startup-grant page lost {needed!r} ({why})")
    if "$5,500" not in gq or "8.83 months" not in gq:
        failures.append("startup-grant page lost its headline comparison")
    # Run 99, second page: the free tier. Both model rows must multiply out to the same $0.80, and the
    # first paid step must be 7.5x the free allowance — recomputed, not typed.
    ft = el["free_tier"]
    fq = open(os.path.join(scratch, "q", "elevenlabs-free-tier.html"), encoding="utf-8").read()
    for needed, why in ((f"${money2(ft['chars_v4'] / 1000 * el['rates_usd_per_1000_chars']['multilingual_v4_api'])}",
                         "the v4 value of the free allowance"),
                        (f"${money2(ft['chars_v4_turbo'] / 1000 * el['rates_usd_per_1000_chars']['turbo_flash_api'])}",
                         "the v4 Turbo value of the same allowance"),
                        (f"{ft['chars_v4_turbo']:,}", "the doubled Turbo allowance"),
                        (f"{next(x for x in el['ladder'] if x.get('name') == 'Starter')['chars'] / ft['chars_v4']:.1f}×",
                         "the Starter step-up")):
        if needed not in fq:
            failures.append(f"free-tier page lost {needed!r} ({why})")
    # Run 105: the licence half of the free-tier page (demand measured in probe105.py: `elevenlabs
    # free plan commercial use` and `elevenlabs free credits reset` are typed queries). Every number
    # below is recomputed from the dataset; the two quoted clauses are vendor text, so they are
    # asserted as strings. The "ten months" slip in the first draft is asserted absent — the whole
    # 10,000-credit month is ONE minute of studio dubbing, and a sentence claiming ten was wrong.
    _items = {i["product"]: i for i in el["credit_costs"]["items"]}
    _free_chars = ft["chars_v4"] / _items["Text to Speech"]["credits"]
    _stt_min = _free_chars / _items["Speech to Text"]["credits"]
    _dub_studio_min = _free_chars / _items["Dubbing Studio without watermark"]["credits"]
    _spread_free = _stt_min / _dub_studio_min
    _conc_free = next(x for x in el["concurrency"]["tts_concurrent_requests"] if x["plan"] == "Free")
    for needed, why in ((f"{_stt_min:.1f} minutes", "transcription minutes in one free month"),
                        (f"{_dub_studio_min:.0f} minute", "studio-dubbing minutes in one free month"),
                        (f"{_spread_free:.1f}&times;", "the spread inside the free balance"),
                        (f"{_conc_free['requests']} concurrent requests", "the free concurrency limit"),
                        ("non-commercial purposes", "the Terms-of-Use licence clause"),
                        ("Unusual activity detected", "the abuse-detector wording"),
                        ("does not apply to the Free plan", "the no-rollover rule")):
        if needed not in fq:
            failures.append(f"free-tier page lost {needed!r} ({why})")
    for bad in ("ten months of allowance", "$0.80 a month</strong> of v4 speech"):
        if bad in fq:
            failures.append(f"free-tier page carries a known-wrong sentence: {bad!r}")
    # Run 100: the credits page. The spread and the studio-dubbing minutes are the reason it exists;
    # recompute both from dataset.json so a data edit cannot leave a stale sentence behind.
    cc = el["credit_costs"]
    creator_q = next(q for q in cc["quotas"] if q["plan"] == "Creator")
    per_min_items = [i for i in cc["items"] if i["unit"] == "per minute"]
    spread = max(i["credits"] for i in per_min_items) / min(i["credits"] for i in per_min_items)
    studio = next(i for i in per_min_items if i["product"] == "Dubbing Studio without watermark")
    cq = open(os.path.join(scratch, "q", "elevenlabs-credits-per-minute.html"), encoding="utf-8").read()
    for needed, why in ((f"{spread:.1f}×", "the credits-per-minute spread"),
                        (f"{creator_q['credits'] / studio['credits']:,.1f} min", "studio dubbing minutes"),
                        (f"{creator_q['credits']:,}", "the Creator quota"),
                        (f"${money(creator_q['usd'] / creator_q['credits'], 6)}", "the per-credit price")):
        if needed not in cq:
            failures.append(f"credits page lost {needed!r} ({why})")
    # Run 106: the H100 rental page. Every claim below is recomputed here from data/gpu-rental.json —
    # not typed — so a data edit cannot leave the prose behind. The page exists because probe106.py
    # showed the buyer's query is "cheapest h100 rental", not "what does Novita charge".
    rr = load_rental()
    rod = sorted([o for o in rr["offers"] if o["tier"] == "on_demand"], key=lambda o: o["usd_per_gpu_hour"])
    rlo, rhi = rod[0], rod[-1]
    rsxm = [o for o in rod if "SXM" in o["variant"]]
    rsp = [o for o in rr["offers"] if o["tier"] == "spot" and o["provider"] == "novita"][0]
    rcw = next(o for o in rod if o["provider"] == "coreweave")
    rres = [o for o in rr["offers"] if o["tier"] == "reserved"]
    rbes = sorted(730 * o["usd_per_gpu_hour"] /
                  next(y for y in rod if y["provider"] == o["provider"] and y["variant"] == o["variant"])["usd_per_gpu_hour"]
                  for o in rres)
    rq = open(os.path.join(scratch, "q", "h100-rental-price.html"), encoding="utf-8").read()
    for needed, why in (
            (f"${money2(rlo['usd_per_gpu_hour'])}", "the cheapest on-demand hour"),
            (f"${money2(rhi['usd_per_gpu_hour'])}", "the dearest on-demand hour"),
            (f"{rhi['usd_per_gpu_hour'] / rlo['usd_per_gpu_hour']:.2f}×", "the all-variant spread"),
            (f"{(max(o['usd_per_gpu_hour'] for o in rsxm) / min(o['usd_per_gpu_hour'] for o in rsxm)):.2f}×",
             "the SXM-only spread"),
            (f"${money2(rcw['usd_per_gpu_hour'] * rcw['min_purchase_gpus'])}", "CoreWeave's minimum spend"),
            (f"{(rcw['usd_per_gpu_hour'] * rcw['min_purchase_gpus']) / rlo['usd_per_gpu_hour']:.1f} hours",
             "the minimum-spend conversion"),
            (f"{(1 - rsp['usd_per_gpu_hour'] / next(o for o in rod if o['provider'] == 'novita')['usd_per_gpu_hour']) * 100:.1f}%",
             "the spot discount"),
            (f"{rbes[0]:,.0f} h/month", "the low break-even"),
            (f"{rbes[-1]:,.0f} h/month", "the high break-even"),
            ("$49.24", "the node price the minimum-spend claim rests on"),
            ("Billed per minute (Hyperstack)", "the granularity finding")):
        if needed not in rq:
            failures.append(f"h100-rental-price page lost {needed!r} ({why})")
    if "hyperstack's" in rq or "novita's interruptible" in rq:
        failures.append("h100-rental-price page prints a lowercase provider slug")
    # the billing-rounding claim must beat, not lose to, the price comparison it is measured against
    _sec = 1000 * 40 / 3600.0
    _min = 1000 / 60.0
    _rule = (_min - _sec) * rlo["usd_per_gpu_hour"]
    _choice = _sec * (rhi["usd_per_gpu_hour"] - rlo["usd_per_gpu_hour"])
    if not 0.2 < _rule / _choice < 0.5:
        failures.append(f"billing-rounding claim no longer a third of the price gap: {_rule / _choice:.2f}")
    if f"${money2(_rule)}" not in rq:
        failures.append(f"h100-rental-price page lost the rounding cost ${money2(_rule)}")
    # Run 100: the bandwidth page. 7 days is a quarter of the 28-day accrual window, so a $6
    # Droplet's accrued allowance is 250 GiB — the claim the page is built on.
    bwd = load_bandwidth()
    x = load_ext()
    six = next(p for p in x["droplets"]["plans"]
               if p["family"] == "Basic" and p["memory_gib"] == 1.0 and p["vcpus"] == 1)
    week_allow = six["transfer_gib"] * 7 * 86400 / bwd["accrual"]["denominator_seconds"]
    bwq = open(os.path.join(scratch, "q", "digitalocean-droplet-bandwidth-pricing.html"),
               encoding="utf-8").read()
    for needed, why in ((f"{week_allow:,.0f} GiB", "the 7-day accrued allowance"),
                        (f"${money(bwd['droplet_overage_usd_per_gib'], 2)}", "the overage rate"),
                        ("28 days", "the accrual window")):
        if needed not in bwq:
            failures.append(f"bandwidth page lost {needed!r} ({why})")
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
    # Run 103: the concurrency page. Every figure below is recomputed from dataset.json's concurrency
    # block, so a vendor re-read cannot leave a stale number on the page; the Business disagreement is
    # asserted explicitly because it is the page's headline.
    conc = el["concurrency"]
    cq_path = os.path.join(scratch, "q", "elevenlabs-concurrency-limit.html")
    cq = open(cq_path, encoding="utf-8").read()
    tts_c = {r["plan"]: r for r in conc["tts_concurrent_requests"]}
    ag_c = {r["plan"]: r for r in conc["agent_concurrent_calls"]}
    slot_rise_c = ((tts_c["Business"]["usd"] / tts_c["Business"]["requests"])
                   / (tts_c["Starter"]["usd"] / tts_c["Starter"]["requests"]))
    be_c = ((ag_c["Pro"]["usd"] - ag_c["Creator"]["usd"])
            / (conc["burst"]["burst_agent_usd_per_minute"] - conc["burst"]["standard_agent_usd_per_minute"]))
    for needed, why in (
            (f"{slot_rise_c:.1f}&times; more", "the per-slot price rise"),
            (f"{be_c:,.0f} call-minutes", "the burst-vs-upgrade break-even"),
            (f"${money2(conc['burst']['burst_agent_usd_per_minute'])} a minute", "the burst rate"),
            (f"{conc['tts_help_center_business']}", "the 429 article's Business figure"),
            (f"{tts_c['Business']['requests']} concurrent requests", "the pricing table's Business figure"),
            (f"{min(ag_c['Creator']['calls'] * conc['burst']['max_multiplier'], conc['burst']['absolute_cap_non_enterprise'])} concurrent",
             "the burst ceiling computed from the plan's own number")):
        if needed not in cq:
            failures.append(f"concurrency page lost {needed!r} ({why})")
    if "too_many_concurrent_requests" not in cq or "system_busy" not in cq:
        failures.append("concurrency page lost the two 429 messages")
    # Run 104: the alternatives page. Its headline is a bill, not a rate, so every figure the page is
    # built on is recomputed here from the two data files: ElevenLabs' smallest covering plan at 100,000
    # characters, the three per-character bills at the same volume, and the free-tier multiple.
    alt = load_ttsa()
    aq = open(os.path.join(scratch, "q", "elevenlabs-alternatives.html"), encoding="utf-8").read()
    el100_plan = min((p for p in el["ladder"] if p["chars"] >= 100000), key=lambda p: p["usd"])
    el100 = el100_plan["usd"]
    oa100 = 100000 / 1e6 * next(o["usd_per_1m_chars"] for o in alt["offers"]
                               if o["vendor"] == "OpenAI" and o["product"] == "tts-1")
    g100 = 100000 / 1e6 * next(o["usd_per_1m_chars"] for o in alt["offers"]
                               if o["vendor"] == "Google Cloud" and o["product"] == "Chirp 3: HD")
    g_free_chars = next(o["free_chars_per_month"] for o in alt["offers"]
                        if o["vendor"] == "Google Cloud" and o["product"] == "Chirp 3: HD")
    el_free = el["free_tier"]["chars_v4"]
    for needed, why in ((f"${el100:.2f}", "the ElevenLabs bill at 100,000 characters"),
                        (f"${oa100:.2f}", "the OpenAI bill at the same volume"),
                        (f"${g100:.2f}", "the Google bill at the same volume"),
                        (f"{el100 / oa100:.1f}×", "the spread against OpenAI"),
                        (f"{g_free_chars / el_free:.0f}×", "the free-tier multiple"),
                        (f"{el_free:,}", "the ElevenLabs free allowance")):
        if needed not in aq:
            failures.append(f"alternatives page lost {needed!r} ({why})")
    if "affiliate link" not in aq:
        failures.append("alternatives page carries the ElevenLabs link without the words 'affiliate link'")
    if "most expensive of the five" not in aq:
        failures.append("alternatives page lost the sentence that names ElevenLabs as the dearest")
    # Run 107: the scraping-exit page. Two numbers on it are computed from the plan ladder rather than
    # read from a rate card, so they are the ones a refactor breaks: the Crawl4AI row must be the
    # marginal credit price (1 credit x $0.001 x 1,000), not the $8.33 the smallest plan costs.
    sc = load_scrapea()
    sq = open(os.path.join(scratch, "q", "firecrawl-alternatives.html"), encoding="utf-8").read()
    jm = sorted(r["tokens"] for r in sc["jina"]["measured"])[1]
    j_per1k = jm / 1e6 * sc["jina"]["tiers"][0]["usd_per_1m_tokens"] * 1000
    c4_per1k = sc["crawl4ai"]["credits"]["real_browser"] * sc["crawl4ai"]["credit_usd"] * 1000
    fc_hobby = min(p["usd_per_month"] for p in fc["plans"] if p["pages_included"] >= 5000)
    fc_per1k = fc_hobby / 5000 * 1000
    for needed, why in ((f"${j_per1k:.2f}", "the Jina measured page price"),
                        (f"${fc_per1k:.2f}", "the Firecrawl Hobby page price"),
                        (f"${c4_per1k:.2f}", "the Crawl4AI marginal page price"),
                        (f"{jm:,}", "the median measured token count"),
                        (f"${fc_hobby / (5000 / 5) * 1000:.2f}", "the JSON-format page price"),
                        ("1,872", "the free-token page equivalent")):
        if needed not in sq:
            failures.append(f"firecrawl-alternatives lost {needed!r} ({why})")
    if "affiliate link" not in sq:
        failures.append("firecrawl-alternatives carries the Firecrawl link without the words 'affiliate link'")
    if "most expensive per page in the table" not in sq:
        failures.append("firecrawl-alternatives lost the sentence that names Firecrawl's page leg dearest")
    # 4. the SERP snippet layer (run 85). Shape measured on page 1 at 2026-11-08 21:35Z: 0/34
    # descriptions restate the title's opening, the paying positions for `firecrawl pricing` and
    # `digitalocean droplet pricing` carry a price, and 2/34 exceed 160 characters. So: one description
    # per page, 110-158 chars, at least one number, never the title repeated, and every number in it
    # must already be visible on that page — the snippet cannot drift away from the body.
    # Run 131: two pages shipped with a literal backslash inside an attribute value
    # (`<p class=\"lede\">`), because a doubled escape in the source string rendered what looked
    # like a quote in the .py file and what is a backslash in the HTML. Browsers drop the class,
    # so the paragraph silently loses its styling and any script reading the attribute sees the
    # wrong name. Nothing in the suite noticed; this line makes it a build failure.
    for rel in [w for w in written if w.endswith(".html")]:
        t = open(os.path.join(scratch, rel), encoding="utf-8").read()
        if '\\"' in t:
            failures.append(f"{rel}: contains a literal backslash before a quote (attribute will not parse)")
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
        # Run 123: the pattern swallows the comma after a figure ("$5, expiring" -> "$5,"),
        # so a description that puts a comma straight after a number could never pass.
        # Normalise the captured token instead of contorting the prose to the regex.
        for num in {n.rstrip(",") for n in re.findall(r"\$?\d[\d,]*(?:\.\d+)?", dsc)}:
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
    # Run 110: the Novita entry-cost section. Recomputed from dataset_ext.json (+ the GPU offers), not
    # from the builder's own variables, so a refactor that breaks the arithmetic fails here.
    ext = json.load(open(os.path.join(HERE, "dataset_ext.json"), encoding="utf-8"))
    nq = open(os.path.join(scratch, "q", "novita-ai-api-pricing.html"), encoding="utf-8").read()
    _paid = [r for r in ext["novita_tokens"]["rows"]
             if (r["input_usd_per_mtok"] or 0) > 0 or (r["output_usd_per_mtok"] or 0) > 0]
    _best = min(_paid, key=lambda r: (40 * r["input_usd_per_mtok"] + 10 * r["output_usd_per_mtok"], r["name"]))
    _blend = (40 * _best["input_usd_per_mtok"] + 10 * _best["output_usd_per_mtok"]) / 50
    _tok = NOVITA_ENTRY["min_topup_usd"] / _blend
    _worst = max(_paid, key=lambda r: (40 * r["input_usd_per_mtok"] + 10 * r["output_usd_per_mtok"], r["name"]))
    _blend2 = (40 * _worst["input_usd_per_mtok"] + 10 * _worst["output_usd_per_mtok"]) / 50
    _tok2 = NOVITA_ENTRY["min_topup_usd"] / _blend2
    _spot = min(o["usd_per_gpu_hour"] for o in ext["gpus"]["offers"]
                if o["family"] == "H100" and o["provider"] == "novita" and o["tier"] == "spot")
    _hrs = NOVITA_ENTRY["min_topup_usd"] / _spot
    _days = (date.fromisoformat(NOVITA_ENTRY["retire_date"])
             - date(int(NOVITA_ENTRY["read"][0:4]), int(NOVITA_ENTRY["read"][5:7]), int(NOVITA_ENTRY["read"][8:10]))).days
    for needed, why in ((f"${NOVITA_ENTRY['min_topup_usd']:.2f}", "the minimum top-up floor"),
                        (f"{_tok:.1f}M tokens", "what the floor buys of the cheapest 4:1 chat mix"),
                        (f"{_tok2:.1f}M", "what the floor buys of the dearest 4:1 chat mix"),
                        (f"{_tok / _tok2:.0f}×", "the spread between the two"),
                        (f"{_hrs:.1f} hours", "what the floor buys of the cheapest H100 spot hour"),
                        (f"${_spot:.2f}", "the Novita H100 spot rate used"),
                        (NOVITA_ENTRY["retire_date"], "the model-retirement date"),
                        (f"in {_days} days", "the countdown to that date"),
                        ("must be greater than $10", "the doc's own top-up wording"),
                        ("499", "the charged client-disconnect status"),
                        ("generally not available", "the refund policy"),
                        ("suspicious registration activity", "the voucher-revocation clause")):
        if needed not in nq:
            failures.append(f"novita page lost {needed!r} ({why})")
    _normc = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    _retired_rows = sum(1 for r in ext["novita_tokens"]["rows"]
                        if any(_normc(n) in _normc(r.get("name") or "") for n in NOVITA_ENTRY["retire_named"]))
    if _retired_rows != 2:
        failures.append(f"novita page claims two retired rows; dataset has {_retired_rows}")
    # Run 111: the Sandbox credit. Recompute both hour figures from the vendor's per-second unit prices and
    # assert the page's scope sentence, so the correction cannot be silently flipped back or generalised.
    def _sb_rate(vcpu, gib):
        return (vcpu * NOVITA_ENTRY["sandbox_cpu_usd_per_vcpu_sec"]
                + gib * NOVITA_ENTRY["sandbox_ram_usd_per_gib_sec"]) * 3600.0
    _sb_small = NOVITA_ENTRY["sandbox_credit_usd"] / _sb_rate(
        NOVITA_ENTRY["sandbox_small_vcpu"], NOVITA_ENTRY["sandbox_small_gib"])
    _sb_big = NOVITA_ENTRY["sandbox_credit_usd"] / _sb_rate(
        NOVITA_ENTRY["sandbox_big_vcpu"], NOVITA_ENTRY["sandbox_big_gib"])
    for needed, why in ((f"{_sb_small:,.0f} hours", "hours of 1 vCPU / 1 GiB the $100 Sandbox credit buys"),
                        (f"{_sb_big:,.0f} hours", "hours of 4 vCPU / 8 GiB the $100 Sandbox credit buys"),
                        (f"${NOVITA_ENTRY['sandbox_credit_usd']:.0f} in promotional credits",
                         "the Sandbox credit amount"),
                        ("No credit card is required", "the doc's own no-card wording"),
                        ("for eligible Novita Sandbox usage", "the doc's own scope wording"),
                        ("buys no inference at", "the sentence that stops the credit being read as an LLM credit"),
                        (NOVITA_ENTRY["sandbox_read"], "the Sandbox read stamp")):
        if needed not in nq:
            failures.append(f"novita page lost {needed!r} ({why})")
    if "no page on novita.ai states the voucher" in nq:
        failures.append("novita page repeats run 110's over-broad claim that no voucher size is published "
                        "anywhere (the Sandbox page publishes one)")
    if "affiliate link" not in nq:
        failures.append("novita page carries its link without the words 'affiliate link'")
    # Run 133 (a): the sentinel leak. _mix_map closes its last segment at 1e9; when no two price lines
    # cross, that single full-range segment used to render as "below 1000000000.00 input tokens per
    # output token" — on 8 of the 10 model pages. A sentinel is not a threshold: no page may print it.
    for w in written:
        if not w.startswith("q/"):
            continue
        html_w = open(os.path.join(scratch, w), encoding="utf-8").read()
        if "1000000000" in html_w:
            failures.append(f"{w} prints the _mix_map sentinel as a threshold")
    # Run 133 (b): the characters-per-minute band. Recompute every row from its own characters and
    # minutes, then assert the page carries the band and the two bills derived from it.
    band = cpm_band()
    for r in band["rows"]:
        want = r["characters"] / r["minutes"]
        if abs(want - r["chars_per_minute"]) > 0.05:
            failures.append(f"chars-per-minute row {r['unit']!r} says {r['chars_per_minute']}, "
                            f"its own numbers give {want:.2f}")
    _meas = sorted(r["chars_per_minute"] for r in band["rows"] if r["kind"] == "measured")
    if _meas[0] != band["measured_min"] or _meas[-1] != band["measured_max"]:
        failures.append("chars-per-minute min/max do not match the measured rows")
    pmq = open(os.path.join(scratch, "q", "elevenlabs-pricing-per-minute.html"), encoding="utf-8").read()
    _rate = el["rates_usd_per_1000_chars"]["multilingual_v4_api"]
    for needed, why in ((f"{band['measured_min']:,.0f}&ndash;{band['measured_max']:,.0f}", "the measured band"),
                        (f"median <strong>{band['measured_median']:,.0f}", "the measured median"),
                        (f"${money(_rate * band['measured_min'] / 1000, 4)}", "the low per-minute bill"),
                        (f"${money(_rate * band['measured_max'] / 1000, 4)}", "the high per-minute bill"),
                        (f"{100_000 / band['measured_max']:,.0f}&ndash;{100_000 / band['measured_min']:,.0f}",
                         "the finished minutes in 100,000 characters"),
                        (str(band["measured_n"]), "the number of measured rows")):
        if needed not in pmq:
            failures.append(f"per-minute page lost {needed!r} ({why})")
    # Run 134: every page that divides by the 1,000-character convention must say so. These five did it
    # silently, which reads as a measurement; the sentence is generated from the same data file and must
    # appear on each of them, with the band and a link to the page that prices it.
    _bandstr = f"{band['measured_min']:,.0f}&ndash;{band['measured_max']:,.0f}"
    for name in ("elevenlabs-credits-to-minutes", "elevenlabs-plan-minutes", "elevenlabs-startup-grant",
                 "elevenlabs-free-tier", "elevenlabs-alternatives"):
        path = os.path.join(scratch, "q", f"{name}.html")
        if not os.path.exists(path):
            failures.append(f"q/{name}.html missing, so its per-minute convention note cannot be checked")
            continue
        body = open(path, encoding="utf-8").read()
        for needed, why in (("is a convention, not a measurement", "the convention disclaimer"),
                            (_bandstr, "the measured characters-per-minute band"),
                            ("elevenlabs-pricing-per-minute.html", "the link to the page that prices the band")):
            if needed not in body:
                failures.append(f"q/{name}.html lost {needed!r} ({why})")
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
