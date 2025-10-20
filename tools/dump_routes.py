# tools/dump_routes.py
import os, inspect, argparse, json, re, subprocess
from pathlib import Path
from graphviz import Digraph

# Asegura imports relativos al repo
os.environ.setdefault("PYTHONPATH", ".")
from app import app  # importa tu app Flask

OUT_ROUTES_TXT = "reports/evidence/routes.txt"
OUT_ROUTES_SVG = "reports/routes_diagram.svg"

def collect_routes():
    rows = []
    for rule in app.url_map.iter_rules():
        bp = rule.endpoint.split(".", 1)[0] if "." in rule.endpoint else "root"
        methods = ",".join(sorted(m for m in rule.methods if m not in ("HEAD","OPTIONS")))
        view_func = app.view_functions.get(rule.endpoint)
        func_name = f"{view_func.__module__}.{view_func.__name__}" if view_func else "?"
        services = []
        if view_func:
            try:
                src = inspect.getsource(view_func)
                # líneas que “tocan” services.*
                for line in src.splitlines():
                    if "services." in line:
                        services.append(line.strip())
            except Exception:
                pass
        rows.append({
            "bp": bp,
            "rule": str(rule),
            "methods": methods,
            "endpoint": rule.endpoint,
            "func": func_name,
            "services": services,
        })
    return sorted(rows, key=lambda d: (d["bp"], d["rule"]))

def write_txt(rows, path_txt):
    Path(path_txt).parent.mkdir(parents=True, exist_ok=True)
    with open(path_txt, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"[{r['bp']}] {r['methods']:10s} {r['rule']:40s} -> {r['endpoint']} :: {r['func']}\n")
            if r["services"]:
                f.write("    services:\n")
                for s in r["services"]:
                    f.write(f"      - {s}\n")
    print(f"[OK] dump rutas → {path_txt}")

def write_svg(rows, path_svg):
    Path(path_svg).parent.mkdir(parents=True, exist_ok=True)
    g = Digraph("routes", format="svg")
    g.attr(rankdir="LR", fontsize="10")

    bps = sorted(set(r["bp"] for r in rows))
    for bp in bps:
        g.node(f"bp:{bp}", label=f"📦 {bp}", shape="folder")

    for r in rows:
        ep_node = f"ep:{r['endpoint']}"
        g.node(ep_node, label=f"{r['methods']}\n{r['rule']}\n{r['endpoint']}", shape="note")
        g.edge(f"bp:{r['bp']}", ep_node)

        if r["services"]:
            for s in sorted(set(r["services"])):
                short = s.split("#")[0][:60]
                svc_id = f"svc:{r['endpoint']}:{abs(hash(s))}"
                g.node(svc_id, label=f"🔧 {short}", shape="component")
                g.edge(ep_node, svc_id, style="dashed")

    out = g.render(filename=os.path.splitext(path_svg)[0], cleanup=True)
    print(f"[OK] diagrama rutas → {out}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--txt", default=OUT_ROUTES_TXT)
    ap.add_argument("--svg", default=OUT_ROUTES_SVG)
    args = ap.parse_args()

    rows = collect_routes()
    write_txt(rows, args.txt)
    write_svg(rows, args.svg)
