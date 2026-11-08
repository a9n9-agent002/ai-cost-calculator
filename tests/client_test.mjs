// Real MCP SDK client against this package's server — does a third-party client accept it?
// Run:  cd tests && npm install && node client_test.mjs ../server.mjs
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const SERVER = process.argv[2] || "../server.mjs";

const t = new StdioClientTransport({ command: "node", args: [SERVER], env: { ...process.env } });
const c = new Client({ name: "real-client-test", version: "1.0.0" }, { capabilities: {} });

let ok = 0, fail = 0;
const check = (name, cond, extra = "") => {
  if (cond) { ok++; console.log(`PASS ${name}${extra ? " — " + extra : ""}`); }
  else { fail++; console.log(`FAIL ${name}${extra ? " — " + extra : ""}`); }
};

try {
  await c.connect(t);
  console.log("connected; serverVersion =", JSON.stringify(c.getServerVersion()));
  ok++;

  const { tools } = await c.listTools();
  check("tools/list returns 1 tool", tools.length === 1, JSON.stringify(tools.map(x => x.name)));
  const tool = tools[0];
  check("tool has name+description+inputSchema", !!(tool.name && tool.description && tool.inputSchema?.properties));
  check("tool description mentions the AI author", /autonomous AI agent/.test(tool.description || ""));
  check("stt_minutes is in the schema", !!tool.inputSchema.properties.stt_minutes);

  const r1 = await c.callTool({ name: "estimate_cost", arguments: { pages: 50000, chars: 2000000, agent_minutes: 5000, stt_minutes: 10000, dg_agent_minutes: 2000 } });
  const txt = r1.content?.[0]?.text ?? "";
  console.log("--- tool text (first 700) ---\n" + txt.slice(0, 700));
  check("callTool returns text content", !!txt, `${txt.length} chars`);
  check("total present and correct ($852.00)", /TOTAL \$852\.00/.test(txt), (txt.match(/TOTAL .*/) || [""])[0]);
  check("STT priced as STT, not as the agent rate", /deepgram stt: \$43\.00/.test(txt));
  check("affiliate link labelled", /affiliate link/.test(txt) && /earns a commission/.test(txt));
  check("AI author footer present", /autonomous AI agent operated by a9n9/.test(txt));

  const r2 = await c.callTool({ name: "estimate_cost", arguments: { pages: 1200000 } });
  const t2 = r2.content?.[0]?.text ?? "";
  check("overflow optimiser: 1.2M pages -> $949", /\$949\.00/.test(t2), (t2.match(/firecrawl scrape: .*/) || [""])[0].slice(0, 120));

  // An agent realistically passes a string number or an unknown field; see how the client/server behave.
  let r3, err3 = null;
  try { r3 = await c.callTool({ name: "estimate_cost", arguments: { pages: "50000" } }); }
  catch (e) { err3 = e; }
  console.log("string-number arg ->", err3 ? "THREW " + err3.message.slice(0, 140) : (r3.content?.[0]?.text || "").split("\n").slice(0, 2).join(" | "));

  let r4, err4 = null;
  try { r4 = await c.callTool({ name: "estimate_cost", arguments: { pages: 1000, bogus_field: 1 } }); }
  catch (e) { err4 = e; }
  console.log("unknown field ->", err4 ? "THREW " + err4.message.slice(0, 140) : (r4.content?.[0]?.text || "").split("\n")[1]);

  // Empty args: does the server give a helpful message rather than crashing?
  const r5 = await c.callTool({ name: "estimate_cost", arguments: {} });
  const t5 = r5.content?.[0]?.text ?? "";
  check("empty args -> guidance, no crash", /No workload given/.test(t5));

  // Deprecated alias still works
  const r6 = await c.callTool({ name: "estimate_cost", arguments: { minutes: 6000 } });
  const t6 = r6.content?.[0]?.text ?? "";
  check("deprecated `minutes` alias still prices STT", /deepgram stt: \$25\.80/.test(t6), (t6.match(/deepgram stt: .*/) || [""])[0]);

  await c.close();
} catch (e) {
  console.log("FATAL", e.message);
  fail++;
}
console.log(`\nCLIENT ${ok} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
