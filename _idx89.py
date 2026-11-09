import importlib.util, sys, re
spec = importlib.util.spec_from_file_location("bh", "build_host.py")
bh = importlib.util.module_from_spec(spec)
sys.argv = ["build_host.py"]
spec.loader.exec_module(bh)
print("QUESTIONS:", len(bh.QUESTIONS))
d = bh.load(); x = bh.load_ext()
t = bh.render_q_index(d)
print(re.search(r"<title>(.*?)</title>", t).group(1))
print(re.search(r"<h1>(.*?)</h1>", t).group(1))
print("desc:", re.search(r'name="description" content="([^"]*)"', t).group(1))
