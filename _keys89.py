import json
x = json.load(open("dataset_ext.json"))
print(list(x.keys()))
print("droplets:", list(x["droplets"].keys()))
print("plan0:", x["droplets"]["plans"][0])
mk = [k for k in x if k not in ("droplets",)]
for k in mk:
    v = x[k]
    print(k, type(v), (list(v.keys())[:8] if isinstance(v, dict) else len(v)))
