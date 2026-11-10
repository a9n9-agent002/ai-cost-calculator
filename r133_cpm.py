#!/usr/bin/env python3
"""Run 133: derive the characters-per-finished-minute band from two vendors' own worked examples.

Both pages were read live on 2026-11-09 ~20:05Z:
  * https://aws.amazon.com/polly/pricing/  — the "Pricing Examples" table states a speech duration
    for each text length, so every row is a chars/minute measurement (no assumption needed).
  * https://cartesia.ai/pricing          — the plan comparison prints "Minutes included monthly" next
    to each tier's credit allowance, and the calculator prints "133 Text to Speech minutes / month"
    for Pro's 100K credits.
ElevenLabs is the third data point and it is not a measurement: its API page prices 1,000 characters
and its plan cards assume ~10 minutes per 10,000 credits, i.e. exactly 1,000 characters a minute.
"""
import json

# (label, characters, stated duration in seconds)
POLLY = [
    ("1,000 requests x 1,000 characters", 1_000_000, 23 * 3600 + 8 * 60),
    ("2016 Amazon Shareholders Letter", 1_300, 100),
    ("average email message", 3_100, 240),
    ("typical news article", 6_500, 9 * 60),
    ("A Christmas Carol", 165_000, 3 * 3600 + 50 * 60),
    ("Adventures of Huckleberry Finn", 600_000, 13 * 3600 + 50 * 60),
    ("animated video, 25 phrases", 2_500, 210),
    ("conversational app, 30k chars/user", 30_000, 42 * 60),
    ("storytelling with highlighted text", 10_000, 13 * 60),
]
CARTESIA = [
    ("Free: 20,000 credits", 20_000, "~27"),
    ("Pro: 100,000 credits", 100_000, "~133"),
    ("Startup: 1,250,000 credits", 1_250_000, "~1,667"),
    ("Scale: 8,000,000 credits", 8_000_000, "~10,667"),
]

rows = []
for label, chars, secs in POLLY:
    rows.append({"vendor": "Amazon Polly", "unit": label, "characters": chars,
                 "minutes": round(secs / 60, 4), "chars_per_minute": round(chars / (secs / 60), 2),
                 "source": "https://aws.amazon.com/polly/pricing/", "kind": "measured"})
for label, chars, mins in CARTESIA:
    m = float(mins.replace("~", "").replace(",", ""))
    rows.append({"vendor": "Cartesia", "unit": label, "characters": chars, "minutes": m,
                 "chars_per_minute": round(chars / m, 2),
                 "source": "https://cartesia.ai/pricing", "kind": "measured"})
rows.append({"vendor": "ElevenLabs", "unit": "plan cards / API page", "characters": 10_000,
             "minutes": 10.0, "chars_per_minute": 1000.0,
             "source": "https://elevenlabs.io/pricing/api", "kind": "documented convention"})

measured = [r["chars_per_minute"] for r in rows if r["kind"] == "measured"]
measured.sort()
median = (measured[len(measured) // 2 - 1] + measured[len(measured) // 2]) / 2 if len(measured) % 2 == 0 else measured[len(measured) // 2]

out = {
    "read_at": "2026-11-09T20:05Z",
    "note": ("A per-minute price is a per-1,000-character price divided by the characters per spoken "
             "minute. Only the rate is on the rate card; the characters-per-minute figure is either a "
             "vendor convention or a measurement. These are the two vendors whose own pages state a "
             "duration for a stated text length."),
    "rows": rows,
    "measured_min": measured[0],
    "measured_max": measured[-1],
    "measured_median": round(median, 2),
    "measured_n": len(measured),
    "elevenlabs_basis": 1000,
    "site_basis": 900,
}
with open("data/chars-per-minute.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
    f.write("\n")
print(json.dumps({k: out[k] for k in ("measured_min", "measured_max", "measured_median", "measured_n")}, indent=1))
print("polly rows", sum(1 for r in rows if r["vendor"] == "Amazon Polly"),
      "cartesia rows", sum(1 for r in rows if r["vendor"] == "Cartesia"))
rate = 0.08
for cpm in (out["measured_min"], out["measured_median"], 900, 1000):
    print(f"cpm {cpm:7.2f} -> $/min ${rate * cpm / 1000:.4f}   (x{rate / (rate * cpm / 1000):.2f} to the 1,000 basis)")
print("100,000 chars at measured median =", round(100_000 / out["measured_median"], 1), "finished minutes")
