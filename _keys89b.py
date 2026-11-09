import json
x = json.load(open("dataset_ext.json"))
g = x["gpus"]
print(list(g.keys()))
offers = g.get("offers") or []
print(len(offers))
for o in offers[:4]:
    print(o)
print("families meta:", json.dumps({k: v for k, v in g.items() if k != "offers"})[:400])
