// End-to-end: treat the installed bin as a third-party server (the npx path) and drive it.
// Run:  cd tests && node e2e.mjs "$(npm root -g)/costcalc-mcp/server.mjs"
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const SERVER = process.argv[2];
if (!SERVER) { console.log("usage: node e2e.mjs <path to installed server.mjs>"); process.exit(2); }
const t = new StdioClientTransport({ command: "node", args: [SERVER], env: { ...process.env } });
const c = new Client({ name: "e2e", version: "1.0.0" }, { capabilities: {} });
let ok = 0, fail = 0;
const check = (n, cond, extra = "") => { cond ? ok++ : fail++; console.log(`${cond ? "PASS" : "FAIL"} ${n}${extra ? " — " + extra : ""}`); };

try {
  await c.connect(t);
  const { tools } = await c.listTools();
  check("installed bin speaks MCP", tools.length === 1, tools[0]?.name);
  const r = await c.callTool({ name: "estimate_cost", arguments: { pages: 2500, chars: 500000, stt_minutes: 1000 } });
  const txt = r.content[0].text;
  console.log(txt.split("\n").slice(0, 7).join("\n"));
  check("prices and read dates ship with the package (no network)", /2026-11-08/.test(txt), txt.split("\n")[0]);
  check("affiliate disclosure present", /affiliate link/.test(txt) && /earns a commission/.test(txt));
  check("AI author footer present", /autonomous AI agent operated by a9n9/.test(txt));
  await c.close();
} catch (e) { console.log("FATAL", e.message); fail++; }
console.log(`\nE2E ${ok} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
