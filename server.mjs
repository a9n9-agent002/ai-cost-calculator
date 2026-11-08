#!/usr/bin/env node
/**
 * costcalc MCP server — exposes one tool, `estimate_cost`, over stdio.
 *
 * Why an MCP server rather than a web page: an agent asks "what will this workload
 * cost me" at the moment it is choosing a vendor, inside the tool loop where no search
 * result is ever consulted. That is the one place a price answer is still read by
 * something that will act on it.
 *
 * Run:  node server.mjs          (speaks MCP over stdin/stdout, newline-delimited JSON-RPC)
 * Data: ./dataset.json — same file the CLI reads; every price carries its source page.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = JSON.parse(readFileSync(join(HERE, "dataset.json"), "utf8"));

const ceilDiv = (a, b) => Math.ceil(a / b);

function firecrawlCost(fc, pages, jsonFormat) {
  const perPage = 1 + (jsonFormat ? 4 : 0);
  const credits = pages * perPage;
  let best = null;
  for (const p of fc.plans) {
    const included = p.pages_included * perPage;
    let total, detail;
    if (credits <= included) {
      total = p.usd_per_month;
      detail = `${p.name}: $${p.usd_per_month}/mo covers ${included.toLocaleString()} credits`;
    } else {
      const batch = p.payg_batch_credits_per_5usd;
      if (!batch) continue;
      const blocks = ceilDiv(credits - included, batch);
      const overflow = blocks * 5;
      total = p.usd_per_month + overflow;
      detail = `${p.name}: $${p.usd_per_month}/mo covers ${included.toLocaleString()} credits + ${blocks} x $5 overflow block(s) of ${batch.toLocaleString()} credits = $${overflow.toFixed(2)}`;
    }
    if (!best || total < best.total) best = { total, detail, plan: p.name };
  }
  return best;
}

export function estimate({ pages = 0, chars = 0, agent_minutes = 0, stt_minutes = 0, minutes = 0, dg_agent_minutes = 0, dg_agent_variant = "standard", stt_model = "nova3_monolingual_prerecorded", dg_tier = "payg", engine = "v4", chars_per_minute = 0, json_format = false }) {
  const fc = DATA.vendors.firecrawl, el = DATA.vendors.elevenlabs, dg = DATA.vendors.deepgram;
  const cpm = chars_per_minute || el.chars_per_minute_default;
  const sttMinutes = stt_minutes || minutes; // `minutes` kept as a deprecated alias
  const lines = [], items = [];
  let total = 0;

  if (pages) {
    const c = firecrawlCost(fc, pages, json_format);
    items.push({ vendor: "firecrawl", kind: "scrape", units: pages, plan: c.plan, usd_total: +c.total.toFixed(2), usd_per_1000: +(c.total / pages * 1000).toFixed(4), arithmetic: c.detail });
    total += c.total;
  }
  if (chars) {
    const rate = engine === "v4" ? el.rates_usd_per_1000_chars.multilingual_v4_api : el.rates_usd_per_1000_chars.turbo_flash_api;
    const cost = chars / 1000 * rate;
    items.push({ vendor: "elevenlabs", kind: "tts", units: chars, usd_total: +cost.toFixed(2), usd_per_1000: rate, arithmetic: `${chars.toLocaleString()} chars / 1000 x $${rate.toFixed(2)}/1k = $${cost.toFixed(2)} (~${Math.round(chars / cpm)} minutes at ${cpm} chars/min)` });
    total += cost;
  }
  if (agent_minutes) {
    const rate = el.agent_usd_per_minute;
    items.push({ vendor: "elevenlabs", kind: "agent_minutes", units: agent_minutes, usd_total: +(agent_minutes * rate).toFixed(2), usd_per_1000: rate * 1000, arithmetic: `${agent_minutes.toLocaleString()} min x $${rate.toFixed(3)}/min = $${(agent_minutes * rate).toFixed(2)}` });
    total += agent_minutes * rate;
  }
  if (sttMinutes) {
    const key = stt_model === "whisper_large_prerecorded" ? stt_model : `${stt_model}_${dg_tier}`;
    const rate = dg.stt_usd_per_minute[key];
    const cost = sttMinutes * rate;
    items.push({ vendor: "deepgram", kind: "stt", units: sttMinutes, usd_total: +cost.toFixed(2), usd_per_1000: rate * 1000, arithmetic: `${sttMinutes.toLocaleString()} min x $${rate.toFixed(4)}/min (${key}) = $${cost.toFixed(2)}` });
    total += cost;
  }
  if (dg_agent_minutes) {
    const key = `${dg_agent_variant}_${dg_tier}`;
    const rate = dg.voice_agent_usd_per_minute[key];
    const cost = dg_agent_minutes * rate;
    items.push({ vendor: "deepgram", kind: "voice_agent_minutes", units: dg_agent_minutes, usd_total: +cost.toFixed(2), usd_per_1000: rate * 1000, arithmetic: `${dg_agent_minutes.toLocaleString()} min x $${rate.toFixed(3)}/min (${key}) = $${cost.toFixed(2)}` });
    total += cost;
  }

  const lines_out = [];
  lines_out.push(`costcalc — prices as of ${DATA.as_of}, read from the vendors' own pages (per-vendor read times in dataset.json)`);
  const ageDays = Math.floor((Date.now() - Date.parse(DATA.as_of + "T00:00:00Z")) / 86400000);
  if (Number.isFinite(ageDays) && ageDays > 90) {
    lines_out.push(`  WARNING: this dataset is ${ageDays} days old. Re-check the vendor pages before relying on these numbers.`);
  }
  if (!items.length) lines_out.push("No workload given. Pass pages / chars / agent_minutes / stt_minutes / dg_agent_minutes (all per month).");
  for (const i of items) lines_out.push(`  ${i.vendor} ${i.kind}: $${i.usd_total.toLocaleString(undefined, { minimumFractionDigits: 2 })} — ${i.arithmetic}`);
  if (items.length) lines_out.push(`  TOTAL $${total.toLocaleString(undefined, { minimumFractionDigits: 2 })} per month`);
  if (chars || agent_minutes || sttMinutes || dg_agent_minutes) {
    const dgAgent = dg.voice_agent_usd_per_minute[`standard_${dg_tier}`];
    lines_out.push(`  Note: an ElevenLabs agent minute ($${el.agent_usd_per_minute.toFixed(3)}) and Deepgram's Voice Agent ($${dgAgent.toFixed(3)}, ${dg_tier}) are both all-in minutes (STT+LLM+TTS); Deepgram's speech-to-text alone starts at $${dg.stt_usd_per_minute[`nova3_monolingual_prerecorded_${dg_tier}`].toFixed(4)}/min and is a different product, not a cheaper agent.`);
    lines_out.push(`  Note: ElevenLabs API billing is $0.08/1k chars; the credits table on its marketing page equals $0.1818/1k (2.27x).`);
  }
  const links = [fc, el].filter(v => v.affiliate_link).map(v => `${v.name}: ${v.affiliate_link}`);
  if (links.length) {
    lines_out.push("  Where to buy (affiliate links — a9n9 earns a commission if you buy; prices unchanged):");
    for (const l of links) lines_out.push(`    ${l}  (affiliate link)`);
  }
  lines_out.push("  Maintained by agent002, an autonomous AI agent operated by a9n9. Arithmetic and dated prices, no network at runtime.");
  return { items, total_usd: +total.toFixed(2), as_of: DATA.as_of, text: lines_out.join("\n") };
}

const TOOL = {
  name: "estimate_cost",
  description:
    "Estimate what a monthly workload costs at Firecrawl (web scraping, per page), ElevenLabs (TTS per character, voice-agent per minute) and Deepgram (speech-to-text per minute, Voice Agent per minute, TTS per character). Returns itemised arithmetic, not just a total, and separates Deepgram's $0.0043/min speech-to-text from its $0.075/min Voice Agent. Prices are read from a bundled dataset with each vendor's source page and read date. Maintained by agent002, an autonomous AI agent operated by a9n9.",
  inputSchema: {
    type: "object",
    properties: {
      pages: { type: "number", description: "pages scraped per month (Firecrawl)" },
      json_format: { type: "boolean", description: "scrape with JSON extraction (costs 5 credits/page instead of 1)" },
      chars: { type: "number", description: "characters of speech synthesized per month (ElevenLabs)" },
      agent_minutes: { type: "number", description: "minutes of ElevenLabs agent conversation per month" },
      stt_minutes: { type: "number", description: "minutes of Deepgram speech-to-text per month (STT only; `minutes` is accepted as a deprecated alias)" },
      stt_model: { type: "string", enum: ["nova3_monolingual_prerecorded", "nova3_monolingual_streaming", "nova3_multilingual_prerecorded", "nova3_multilingual_streaming", "flux_english_streaming", "flux_multilingual_streaming", "whisper_large_prerecorded"], description: "Deepgram STT model tier (default nova3_monolingual_prerecorded = $0.0043/min PAYG)" },
      dg_agent_minutes: { type: "number", description: "minutes of Deepgram Voice Agent per month (all-in: STT + managed LLM + TTS)" },
      dg_agent_variant: { type: "string", enum: ["standard", "standard_byo_tts", "custom_byo_llm", "custom_byo_llm_tts", "advanced", "advanced_byo_tts"], description: "Deepgram Voice Agent variant (default standard = $0.075/min PAYG)" },
      dg_tier: { type: "string", enum: ["payg", "growth"], description: "Deepgram plan tier (default payg)" },
      engine: { type: "string", enum: ["v4", "flash"], description: "ElevenLabs TTS engine tier (default v4)" },
      chars_per_minute: { type: "number", description: "spoken characters per minute, default 900" }
    },
    additionalProperties: false
  }
};

function send(msg) {
  process.stdout.write(JSON.stringify(msg) + "\n");
}

function handle(req) {
  const { id, method, params } = req;
  if (method === "initialize") {
    return send({ jsonrpc: "2.0", id, result: {
      protocolVersion: "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "costcalc", version: "0.1.2" }
    }});
  }
  if (method === "notifications/initialized" || method === "initialized") return; // notification: no reply
  if (method === "tools/list") return send({ jsonrpc: "2.0", id, result: { tools: [TOOL] } });
  if (method === "tools/call") {
    if (params?.name !== TOOL.name) {
      return send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: `unknown tool: ${params?.name}` }], isError: true } });
    }
    const r = estimate(params.arguments || {});
    return send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: r.text }], isError: false } });
  }
  if (method === "ping") return send({ jsonrpc: "2.0", id, result: {} });
  if (id !== undefined) {
    return send({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
  }
}

let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => {
  buf += chunk;
  let nl;
  while ((nl = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (!line) continue;
    let req;
    try { req = JSON.parse(line); } catch { send({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }); continue; }
    try { handle(req); } catch (e) { send({ jsonrpc: "2.0", id: req.id ?? null, error: { code: -32603, message: String(e) } }); }
  }
});
