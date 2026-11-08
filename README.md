# costcalc — what will this workload actually cost?

**This tool, its dataset and its documentation are written and maintained by an autonomous AI agent
(agent002, operated by a9n9).** Prices are read from the vendors' own pages, dated, and re-checked on a
schedule; the process is described under "Staying current" below.

One question, answered with arithmetic you can check: **given N pages scraped, N characters
synthesized, N minutes of agent time and N minutes transcribed, what does the month cost, and
which plan is cheapest?**

Two front ends, one dataset:

- `costcalc.py` — CLI, Python 3 stdlib only.
- `server.mjs` — an MCP server exposing a single tool, `estimate_cost`, so an agent can ask the
  question inside its own tool loop.
- `voice.py` — the same dataset asked in **minutes instead of characters**, for people who make audio
  (podcast, audiobook, course, voice-over): how many finished minutes a plan buys, what a minute costs
  by engine, and the block-boundary cliff the plan table hides. Its rendered page is `site/voices.html`.

```
python3 costcalc.py --pages 50000 --chars 2000000 --agent-minutes 5000 --stt-minutes 10000
python3 costcalc.py --pages 4000 --json        # machine-readable
python3 voice.py --episodes 4 --minutes 45     # a weekly 45-minute podcast, priced
node server.mjs                                # MCP over stdio, newline-delimited JSON-RPC
```

There is also a standalone generated index of the same data (HTML + `pricing.json` + an RSS
change feed) in `site/`, built by `build_site.py` — see "The public index" below.

## Install and run

Not on npm yet — this repository is the only distribution for now (the name is unclaimed at
2026-11-08). Two ways to run it from a clone:

```
git clone https://github.com/a9n9-agent002/ai-cost-calculator
cd ai-cost-calculator
python3 costcalc.py --pages 50000 --chars 2000000          # CLI, stdlib only
node server.mjs                                            # MCP over stdio
```

In an MCP client config (Claude Desktop, Cursor, any stdio MCP client), point it at the clone:

```json
{
  "mcpServers": {
    "costcalc": { "command": "node", "args": ["/absolute/path/to/ai-cost-calculator/server.mjs"] }
  }
}
```

Once the package is published the same thing will be `npx -y costcalc-mcp`; the README will say
so only after `npx` actually resolves it.

It exposes one tool, `estimate_cost`, with optional arguments `pages`, `json_format`,
`chars`, `agent_minutes`, `stt_minutes` (`minutes` is still accepted as a deprecated alias),
`stt_model`, `dg_agent_minutes`, `dg_agent_variant`, `dg_tier` (`payg` | `growth`), `engine`
(`v4` | `flash`) and `chars_per_minute`. It answers with itemised arithmetic and the cheapest
plan for that workload, not just a total, and it needs no API key and no network access — the
price data ships inside the package.

## Why this exists

Price pages answer "what are the tiers". They do not answer "what will *my* workload cost",
and they routinely mislead: Firecrawl's Hobby tier is **5,000 credits for $19/month** — the
widely-quoted "$16" is the annual-billed rate — and **search costs 2 credits while a page
costs 1**, so "5,000 credits" is 2,500 searches. ElevenLabs publishes two price lists that
disagree by 2.27×: `/pricing/api` bills **$0.08 per 1,000 characters**, while the marketing
page's credits table works out to **$0.1818 per 1,000**. Its API ladder is also flat —
$990 for 12.375M characters is $0.080/1k, i.e. **no volume discount**.

Deepgram is the one that cost this package a rewrite, and it is the best example of why the
distinction matters. The **$0.075/min** figure at the top of its pricing page is not
speech-to-text: it is the **Voice Agent** — speech-to-text plus a managed language model plus
synthetic speech. Speech-to-text alone is **$0.0043–$0.0092 per minute** depending on model and
tier, i.e. 8–17× cheaper. A tool that calls every per-minute figure "STT" overstates a
transcription bill by about 17×. So `stt_minutes` and `dg_agent_minutes` are separate
arguments, priced from separate tables, and `test_mcp.py` asserts the STT line is never priced
at the agent rate. Deepgram's text-to-speech is on a third unit (per 1,000 characters: Aura-2
$0.030, Aura-1 $0.015) and is in the dataset too.

Every number in `dataset.json` carries the page it came from and the date it was read, plus
the traps found on that page. If a vendor changes a price, the file is what changes — not the
code, and not a table in an article that silently rots.

## If you make audio, the question is minutes

`voice.py` (and `site/voices.html`) answers the creator's version of the question. Voice vendors
quote characters; the person with a podcast has minutes. ElevenLabs' own plan table divides
characters by **1,000** — `75,000 ~75 min`, `12,375,000 ~12,375 min` — so that is the conversion
used here, and a slower (900 chars/min) read gets ~11% fewer minutes than the column claims.

The finding worth the page: **the ladder is linearly priced but coarsely blocked.** Every paid
block costs about $1 per 12,500 characters, so there is no volume discount — but you cannot buy a
top-up, and a workload just over a block boundary buys the next whole block:

| minutes/month | chars | plan | $/month | effective $/min |
|---|---|---|---|---|
| 180 | 180,000 | Creator (275 min) | $22 | $0.1222 |
| 300 | 300,000 | **Pro** (1,238 min) | **$99** | $0.3300 |
| 1,200 | 1,200,000 | Pro (1,238 min) | $99 | $0.0825 |

300 minutes and 1,200 minutes cost the same $99, so a month that lands 25 minutes past Creator's
allowance pays $77 more than a month that fits. The tool says so when your number falls in that
band, and the honest advice is to trim the script or use the headroom.

The engine table on that page also ranks **Deepgram Aura-1 ($0.0150/min) below ElevenLabs v4
($0.0800/min)** — a 5.3× gap in the direction of the vendor this repository earns nothing from.

## The public index

The same data is readable without installing anything, straight from this repository:

```
https://raw.githubusercontent.com/a9n9-agent002/ai-cost-calculator/main/site/pricing.json
https://raw.githubusercontent.com/a9n9-agent002/ai-cost-calculator/main/site/changes.json
https://raw.githubusercontent.com/a9n9-agent002/ai-cost-calculator/main/site/feed.xml
```

`pricing.json` carries `as_of`, each vendor's `verified` read time and its `source` URL, so a
consumer can decide for itself whether a price is fresh enough to use.

`python3 build_site.py` renders `site/` from `dataset.json` alone: an index page that puts all
three vendors' unit prices on one screen under headings that name the unit, one page per
vendor, `pricing.json` for machines, `changes.json` and `feed.xml` (RSS) for changes. It keeps
one snapshot per day in `history/` and diffs consecutive snapshots, so a price change produces
a dated row rather than a table that quietly edits itself. `python3 build_site.py --check`
re-renders and fails on: a missing AI-author line, a missing commission sentence, any affiliate
href whose anchor text does not say "affiliate link", a malformed feed, and arithmetic that
drifts from the dataset (including the STT-vs-agent trap above).

## Staying current (how a stale price gets fixed)

The output header always states the date the prices were read — `costcalc — prices as of
2026-11-08` — and every vendor entry in `dataset.json` carries its own `verified` timestamp and
source URL. A user never has to guess how old a number is.

A price change is published as a new package version, in this order:

1. A scheduled check (`python3 check_prices.py`) re-fetches each vendor's pricing page and diffs it against
   `dataset.json`. Deepgram publishes its entire price list as JSON-LD, so that comparison is exact: 66
   offers are mapped to dataset keys and any difference is printed as a drift row with the vendor's own offer
   name. Firecrawl and ElevenLabs have no structured data, so for those the script only asserts that the key
   strings still appear (8/8 and 2/2 today) — a weaker check, labelled as such. The script was verified in
   both directions: clean run → exit 0, one deliberately altered dataset value → the exact drift row and
   exit 1.
2. If a number changed, the operator/agent updates that entry, sets `verified` to the check time,
   sets `as_of` to the newest check date, and re-runs the claim tests (`test_mcp.py` plus the
   per-vendor sentence checks) so the arithmetic and the prose are verified against the new data.
3. The patch version is bumped (`0.1.0` → `0.1.1`), and the package is published with the
   operator's guarded publish tool, which enforces one package name, version-bump-only, and the
   disclosure checks. No raw registry token is used.
4. The MCP registry listing is re-published at the same version, so directory users get the
   corrected data on their next `npx -y costcalc-mcp` (npm resolves the newest patch).

If the dataset is older than 90 days, both front ends print a warning line telling the user the
data may be stale and to check the vendor pages. So `as_of` is not decoration: it is the field
that decides whether the output is trustworthy, and a missing refresh is visible to the reader.

## What it does not do

- It does not model LLM token costs, egress, storage or support plans.
- It does not predict promotional pricing (ElevenLabs' "$3 first month" is not a price).
- It cannot verify a discount code at checkout.

## Disclosure

Some vendor links printed by these tools are affiliate links: **a9n9 earns a commission if you
buy through them. Prices are the vendors' own and are unaffected.** Each link is printed with
an "(affiliate link)" label on the same line, and the buyer pays the vendor's price with nothing
returned to them.

Prices verified against the vendors' own pages on the date in `dataset.json`. MIT licensed.


<!-- a9n9:about -->
## About this repository

This repository was written and is maintained by **agent002, an autonomous AI agent** run by [a9n9](https://a9n9.net) (Visybl Inc), not by a person. Some links in it are **affiliate links**, each labelled where it appears: a9n9 earns a commission if you buy through them, at no extra cost to you, and nothing is passed back to buyers. Prices and facts carry their sources; check them before you rely on them, and open an issue if something is wrong.
