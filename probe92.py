#!/usr/bin/env python3
"""Run 92: does anyone type a Novita-x-OpenRouter comparison? Google Autocomplete, anonymous.

Controls first (`vultr vs`, `elevenlabs pricing`) so an empty list is a real empty, not a
blocked instrument. Writes probe92_autocomplete.json next to the other probe files.
"""
import json, urllib.parse, urllib.request, time

URL = "https://suggestqueries.google.com/complete/search"
STEMS = [
    "novita vs",
    "novita ai vs",
    "novita ai vs openrouter",
    "openrouter vs novita",
    "novita vs openrouter",
    "deepinfra vs novita",
    "novita ai alternative",
    "novita pricing",
    "novita ai pricing",
    # controls
    "vultr vs",
    "elevenlabs pricing",
]


def ask(q):
    p = urllib.parse.urlencode({"client": "firefox", "hl": "en", "gl": "us", "q": q})
    req = urllib.request.Request(URL + "?" + p, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))[1]


out = {"measured": time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime()), "instrument": "Google Autocomplete"}
for s in STEMS:
    try:
        out[s] = ask(s)
    except Exception as e:  # noqa: BLE001 - instrument must report its own failure
        out[s] = {"error": f"{type(e).__name__}: {e}"}
    print(f"{s!r}: {len(out[s]) if isinstance(out[s], list) else out[s]}")
    if isinstance(out[s], list):
        for t in out[s]:
            print("    ", t)
    time.sleep(0.4)

with open("probe92_autocomplete.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("wrote probe92_autocomplete.json")
