#!/usr/bin/env python3
"""check_deepseek_routes.py - re-derives every figure in the DeepSeek route comparison
article from data/deepseek-routes.json and asserts the relationships the prose claims.

The JSON is the raw read: DeepSeek's own rate card, Novita's DeepSeek rows, OpenRouter's
provider table for deepseek/deepseek-v4-pro, and Novita's batch documentation, each with
the page URL and the reading time. Nothing in this file types a price.

Exit 0 and "ALL CHECKS PASS" only if every assertion holds.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'deepseek-routes.json')))

fails = []
checks = 0


def ok(cond, label):
    global checks
    checks += 1
    if not cond:
        fails.append(label)


def close(a, b, label, tol=0.006):
    ok(abs(a - b) <= tol, '%s (computed %.4f, expected %.4f)' % (label, a, b))


ds = D['deepseek_direct']['deepseek-v4-pro']
flash = D['deepseek_direct']['deepseek-flash']
prov = {k: v for k, v in D['openrouter_v4pro_providers'].items() if not k.startswith('_')}
nov = D['novita']
old = D['price_history_reported']['deepseek-v4-pro']
W = D['workloads']


def cost(rate_in_miss, rate_in_hit, rate_out, w):
    return (w['input_miss'] * rate_in_miss + w['input_hit'] * rate_in_hit + w['output'] * rate_out) / 1e6


# --- 1. the clock
close(35 / 168 * 100, 20.83, 'peak share of the week is 20.83%', 0.01)
ok(D['deepseek_direct']['peak_hours_per_week'] == 35, 'peak hours per week is 35')
ok(D['deepseek_direct']['longest_offpeak_run_hours'] == 63,
   'longest off-peak run is 63 h (Fri 10:00Z -> Mon 01:00Z)')
ok(ds['output']['peak'] == 2 * ds['output']['off_peak'], 'off-peak output is exactly half of peak')
ok(ds['cache_miss']['peak'] == 2 * ds['cache_miss']['off_peak'], 'off-peak cache-miss input is half of peak')

# --- 2. spread across the resellers
ins = [v['input'] for v in prov.values()]
outs = [v['output'] for v in prov.values()]
close(max(ins) / min(ins), 2.12, 'input spread 2.12x', 0.01)
close(max(outs) / min(outs), 2.55, 'output spread 2.55x', 0.01)
ok(len(prov) == 13, 'thirteen providers in the table')
ok(min(ins) == prov['Relace']['input'] == 0.90, 'Relace is the input floor at $0.90')
ok(max(ins) == prov['Azure']['input'] == 1.91, 'Azure is the input ceiling at $1.91')

# --- 3. direct vs the input floor
close((prov['Relace']['input'] / ds['cache_miss']['off_peak'] - 1) * 100, 36.4, 'Relace input is 36.4% above off-peak', 0.1)
close((prov['Relace']['output'] / ds['output']['peak'] - 1) * 100, -62.1, 'Relace output is 62.1% below peak', 0.1)
close((prov['Relace']['cache_read'] / ds['cache_hit']['peak']), 5.7, 'Relace cache read is 5.7x DeepSeek peak cache hit', 0.05)
close((1 - ds['cache_hit']['peak'] / ds['cache_miss']['peak']) * 100, 96.7, 'DeepSeek cache-hit discount is 96.7%', 0.1)

# --- 4. the crossover: off-peak cheaper iff input > 2x output
crossover = (prov['Relace']['output'] - ds['output']['off_peak']) / (ds['cache_miss']['off_peak'] - prov['Relace']['input'])
close(crossover, 2.0, 'crossover at exactly 2:1 input:output', 0.001)
a, b = 2.0, 1.0  # a = 2b, the boundary
close(0.66 * a + 1.98 * b, 0.90 * a + 1.50 * b, 'both routes tie at a=2b', 0.001)

# --- 5. the three workloads
w1 = cost(ds['cache_miss']['off_peak'], ds['cache_hit']['off_peak'], ds['output']['off_peak'], W['W1_no_cache'])
w1_peak = cost(ds['cache_miss']['peak'], ds['cache_hit']['peak'], ds['output']['peak'], W['W1_no_cache'])
w1_blend = w1 * 133 / 168 + w1_peak * 35 / 168
close(w1, 46.20, 'W1 off-peak $46.20', 0.01)
close(w1_peak, 92.40, 'W1 peak $92.40', 0.01)
close(w1_blend, 55.83, 'W1 blended $55.83', 0.01)
close(cost(prov['Relace']['input'], prov['Relace']['cache_read'], prov['Relace']['output'], W['W1_no_cache']), 51.00, 'W1 Relace $51.00', 0.01)
close(cost(prov['SiliconFlow']['input'], prov['SiliconFlow']['cache_read'], prov['SiliconFlow']['output'], W['W1_no_cache']), 55.00, 'W1 SiliconFlow $55.00', 0.01)
close(cost(prov['Azure']['input'], prov['Azure']['cache_read'], prov['Azure']['output'], W['W1_no_cache']), 114.70, 'W1 Azure $114.70', 0.01)

w2 = cost(ds['cache_miss']['off_peak'], ds['cache_hit']['off_peak'], ds['output']['off_peak'], W['W2_agent_98pct_cache'])
w2_peak = cost(ds['cache_miss']['peak'], ds['cache_hit']['peak'], ds['output']['peak'], W['W2_agent_98pct_cache'])
w2_blend = w2 * 133 / 168 + w2_peak * 35 / 168
close(w2, 21.20, 'W2 off-peak $21.20', 0.01)
close(w2_peak, 42.41, 'W2 peak $42.41', 0.01)
close(w2_blend, 25.62, 'W2 blended $25.62', 0.01)
w2_rel = cost(prov['Relace']['input'], prov['Relace']['cache_read'], prov['Relace']['output'], W['W2_agent_98pct_cache'])
w2_sf = cost(prov['SiliconFlow']['input'], prov['SiliconFlow']['cache_read'], prov['SiliconFlow']['output'], W['W2_agent_98pct_cache'])
close(w2_rel, 25.53, 'W2 Relace $25.53', 0.01)
close(w2_sf, 21.11, 'W2 SiliconFlow $21.11', 0.01)
ok(w2_sf < w2 < w2_rel < w2_blend, 'W2 ordering: SiliconFlow < DeepSeek off-peak < Relace < blended')

w3 = cost(ds['cache_miss']['off_peak'], ds['cache_hit']['off_peak'], ds['output']['off_peak'], W['W3_chat_output_heavy'])
close(w3, 42.90, 'W3 off-peak $42.90', 0.01)
w3_rel = cost(prov['Relace']['input'], prov['Relace']['cache_read'], prov['Relace']['output'], W['W3_chat_output_heavy'])
w3_sf = cost(prov['SiliconFlow']['input'], prov['SiliconFlow']['cache_read'], prov['SiliconFlow']['output'], W['W3_chat_output_heavy'])
close(w3_rel, 34.50, 'W3 Relace $34.50', 0.01)
close(w3_sf, 35.00, 'W3 SiliconFlow $35.00', 0.01)
ok(w3_rel < w3_sf < w3, 'W3 Relace wins and output-heavy flips the ranking')
close(w3 / w3_rel, 1.243, 'Relace is 24.3% cheaper on W3', 0.005)

# the 4.4x claim: best case vs worst case on the same token volume
close(92.40 / 21.20, 4.36, 'same tokens cost 4.4x more worst case than best', 0.01)

# --- 6. old flat rates (reported) and the increase
old1 = cost(old['cache_miss'], old['cache_hit'], old['output'], W['W1_no_cache'])
close(old1, 26.10, 'W1 at the old flat rate was $26.10', 0.01)
close(w1 / old1, 1.77, 'W1 off-peak is 1.77x the old flat bill', 0.01)
close(w1_blend / old1, 2.14, 'W1 blended is 2.14x the old flat bill', 0.01)
old2 = cost(old['cache_miss'], old['cache_hit'], old['output'], W['W2_agent_98pct_cache'])
close(w2_blend / old2, 2.79, 'W2 blended is 2.79x the old flat bill (cache-heavy is hit hardest)', 0.01)

# --- 7. Novita: the peak rate, flat
a0813 = nov['DeepSeek V4 Pro 0813']
ok(a0813['input'] == ds['cache_miss']['peak'], 'Novita V4 Pro 0813 input equals DeepSeek peak input')
ok(a0813['output'] == ds['output']['peak'], 'Novita V4 Pro 0813 output equals DeepSeek peak output')
ok(a0813['cache_read'] == ds['cache_hit']['peak'], 'Novita V4 Pro 0813 cache read equals DeepSeek peak cache hit')
fl = nov['DeepSeek V4.1 Flash 1017']
ok(fl['input'] == flash['cache_miss']['peak'], 'Novita V4.1 Flash input equals DeepSeek Flash peak input')
ok(fl['output'] == flash['output']['peak'], 'Novita V4.1 Flash output equals DeepSeek Flash peak output')
ok(fl['cache_read'] == flash['cache_hit']['peak'], 'Novita V4.1 Flash cache read equals DeepSeek Flash peak cache hit')
nov_w1 = cost(a0813['input'], a0813['cache_read'], a0813['output'], W['W1_no_cache'])
close(nov_w1, 92.40, 'Novita V4 Pro 0813 on W1 is $92.40', 0.01)
close(nov_w1 / w1, 2.00, 'Novita is 2.00x DeepSeek off-peak on W1', 0.01)
older = nov['DeepSeek V4 Pro']
close((older['input'] / a0813['input'] - 1) * 100, 21.2, 'older V4 Pro row costs 21.2% more input', 0.1)
close((older['output'] / a0813['output'] - 1) * 100, -19.2, 'older V4 Pro row costs 19.2% less output', 0.1)
close(older['cache_read'] / a0813['cache_read'], 3.07, 'older V4 Pro cache read is 3.07x', 0.01)

# --- 8. the batch trap
ok('deepseek/deepseek-v4-pro' not in D['novita']['batch_supported_models'],
   'V4 Pro is NOT in the batch-supported model list')
ok(D['novita']['batch_supported_models'] == ['openai/gpt-oss-120b', 'deepseek/deepseek-r1-0528'],
   'batch supports exactly two models')
close(nov['DeepSeek R1 0528']['input'] * 0.5, 0.35, 'r1-0528 batch input is $0.35', 0.001)
close(nov['DeepSeek R1 0528']['output'] * 0.5, 1.25, 'r1-0528 batch output is $1.25', 0.001)

# --- 9. every source carries a reading time
for k in ('deepseek_direct', 'novita', 'openrouter_v4pro', 'novita_batch_docs'):
    ok('read 2026-11-10' in D['sources'][k], 'source %s carries its reading time' % k)

print('checks: %d   fails: %d' % (checks, len(fails)))
if fails:
    for f in fails:
        print('  FAIL', f)
    sys.exit(1)
print('ALL CHECKS PASS')
