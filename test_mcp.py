#!/usr/bin/env python3
"""Drive server.mjs over real stdio as an MCP client would, and diff it against the CLI."""
import json, subprocess, sys

PROCS = ["node", "server.mjs"]
msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "estimate_cost", "arguments": {"pages": 50000, "chars": 2000000, "agent_minutes": 5000, "stt_minutes": 10000, "dg_agent_minutes": 2000}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "estimate_cost", "arguments": {"pages": 4000}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
]

p = subprocess.run(PROCS, input="\n".join(json.dumps(m) for m in msgs) + "\n",
                   capture_output=True, text=True, timeout=60)
print("exit:", p.returncode)
if p.stderr.strip():
    print("STDERR:", p.stderr.strip()[:2000])
out = [json.loads(l) for l in p.stdout.splitlines() if l.strip()]
print(f"responses: {len(out)} (expected 5: ids 1-5; the notification must NOT be answered)")
for r in out:
    if r.get("id") == 1:
        print("1 initialize ->", r["result"]["serverInfo"], r["result"]["protocolVersion"])
    elif r.get("id") == 2:
        t = r["result"]["tools"]
        print("2 tools/list ->", [x["name"] for x in t], "| required:", t[0]["inputSchema"].get("required"))
    elif r.get("id") == 3:
        print("3 tools/call (full workload) ->")
        print(r["result"]["content"][0]["text"])
    elif r.get("id") == 4:
        print("4 tools/call (4000 pages) ->", r["result"]["content"][0]["text"].splitlines()[1])
    elif r.get("id") == 5:
        print("5 unknown tool -> isError:", r["result"]["isError"], "|", r["result"]["content"][0]["text"])

# cross-check against the CLI for the same workload
cli = subprocess.run([sys.executable, "costcalc.py", "--pages", "50000", "--chars", "2000000",
                      "--agent-minutes", "5000", "--stt-minutes", "10000", "--dg-agent-minutes", "2000", "--json"],
                     capture_output=True, text=True)
d = json.loads(cli.stdout)
print("\nCLI total:", d["total_usd"])
mcp_total = None
for r in out:
    if r.get("id") == 3:
        for line in r["result"]["content"][0]["text"].splitlines():
            if "TOTAL" in line:
                mcp_total = float(line.split("$")[1].replace(",", "").split()[0])
print("MCP total:", mcp_total)
print("MATCH:", mcp_total == d["total_usd"])

# the regression this run exists to prevent: STT must never be priced at the agent rate
stt = next(i for i in d["line_items"] if i["kind"] == "stt")
print(f"STT line: {stt['units']:,} min -> ${stt['usd_total']:.2f} (${stt['usd_per_1000']:.2f}/1k min)")
print("STT priced as STT (not the $0.075/min agent rate):", abs(stt["usd_per_1000"] / 1000 - 0.0043) < 1e-9)

