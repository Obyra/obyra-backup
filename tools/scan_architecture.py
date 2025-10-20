# tools/scan_architecture.py
import os, re, ast, json, subprocess, sys
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPORTS_DIR = os.path.join(REPO_ROOT, "reports")
EVIDENCE_DIR = os.path.join(REPORTS_DIR, "evidence")
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ---------------------------- helpers ---------------------------------
def rel(p: str) -> str:
    try:
        return os.path.relpath(p, REPO_ROOT).replace("\\", "/")
    except Exception:
        return p

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def git_last_commit(path: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%h %ci %an", "--", path],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
        return out or None
    except Exception:
        return None

def is_legacy_name(name: str) -> bool:
    name = name.lower()
    return any(tok in name for tok in ["_old", "legacy", "_backup", "bak", "deprecated"])

def path_matches_any(path: str, patterns: List[str]) -> bool:
    p = path.lower().replace("\\", "/")
    return any(x in p for x in patterns)

def safe_parse_ast(code: str, path: str):
    try:
        return ast.parse(code, filename=path)
    except Exception:
        return None

def collect_imports(tree: ast.AST) -> List[str]:
    """Return list of imported top-level names (module/package roots)."""
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                root = (n.name or "").split(".")[0]
                if root:
                    mods.append(root)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                mods.append(root)
    return mods

# ---------------------- scan blueprints / models / services ---------------
BP_DEF_RE = re.compile(r"Blueprint\s*\(\s*['\"]([a-zA-Z0-9_\-]+)['\"]\s*,\s*__name__.*?(url_prefix\s*=\s*['\"]([^'\"]+)['\"])?", re.S)
ROUTE_DECOR_RE = re.compile(r"@([a-zA-Z0-9_\.]+)\.route\(\s*['\"]([^'\"]+)['\"]", re.S)

def scan_repo() -> Dict:
    data = {
        "blueprints": [],
        "services": [],
        "models": [],
        "imports_graph": defaultdict(list),  # file -> imports (roots)
        "files": [],
    }

    service_roots = {"services"}  # carpeta principal de servicios
    model_files = set()

    for root, dirs, files in os.walk(REPO_ROOT):
        # excluir carpetas típicas
        low = root.lower()
        if any(x in low for x in ["/.venv", "\\.venv", "/migrations", "\\migrations", "/instance", "\\instance", "/tmp", "\\tmp", "/__pycache__", "\\__pycache__"]):
            continue
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            rpath = rel(fpath)
            data["files"].append(rpath)

            code = read_text(fpath)
            tree = safe_parse_ast(code, fpath)
            if tree:
                data["imports_graph"][rpath] = sorted(set(collect_imports(tree)))

            # -------- blueprints
            # captura definición de Blueprint + url_prefix
            for m in BP_DEF_RE.finditer(code):
                bp_name = m.group(1)
                url_prefix = (m.group(3) or "").strip() or None
                # rutas por decoradores @<bp>.route("...") / @app.route("...")
                endpoints = []
                for d in ROUTE_DECOR_RE.finditer(code):
                    dec = d.group(1)
                    path = d.group(2)
                    endpoints.append({"decorator": dec, "path": path})
                data["blueprints"].append({
                    "file": rpath,
                    "name": bp_name,
                    "url_prefix": url_prefix,
                    "endpoints_found": endpoints,
                    "legacy_by_name": is_legacy_name(rpath) or is_legacy_name(bp_name)
                })

            # -------- models: clases que heredan de db.Model (heurística)
            try:
                for node in ast.walk(tree or ast.parse("pass")):
                    if isinstance(node, ast.ClassDef):
                        bases = [getattr(b, "attr", getattr(b, "id", "")) for b in node.bases]
                        if any(x in bases for x in ["Model"]):  # db.Model -> Model
                            data["models"].append({
                                "file": rpath, "class": node.name,
                                "bases": bases
                            })
                            model_files.add(rpath)
            except Exception:
                pass

            # -------- services: todo .py bajo /services o que “huela” a servicio
            if path_matches_any(rpath, ["services/"]):
                data["services"].append({
                    "file": rpath,
                    "name": os.path.splitext(os.path.basename(rpath))[0]
                })

    # enriquecer con evidencia git + clasificación active/legacy
    registered_bps = set()
    # detectar registro en app.py (heurística)
    app_py = os.path.join(REPO_ROOT, "app.py")
    app_code = read_text(app_py)
    for bp in data["blueprints"]:
        fname = bp["file"]
        bp["git_last_commit"] = git_last_commit(fname)
        # active si: importado en app.py o “register_blueprint(<<nombre>>”
        active_evidence = []
        bn = bp["name"]
        if bn and re.search(rf"register_blueprint\([^)]*{re.escape(bn)}", app_code):
            active_evidence.append("app.py: register_blueprint(...)")
            registered_bps.add(bn)
        if os.path.basename(fname) in app_code or f"from {os.path.splitext(os.path.basename(fname))[0]} " in app_code:
            active_evidence.append("app.py: import")
        bp["active_evidence"] = active_evidence
        bp["status"] = "active" if active_evidence and not bp["legacy_by_name"] else ("legacy" if bp["legacy_by_name"] else "unknown")

    # services evidencia
    for s in data["services"]:
        s["git_last_commit"] = git_last_commit(s["file"])
        s["status"] = "active" if "services/" in s["file"] else "unknown"

    # models evidencia
    for m in data["models"]:
        m["git_last_commit"] = git_last_commit(m["file"])

    return data

# ---------------------- write evidence & reports -----------------------------
def write_evidence_files(data: Dict):
    # blueprints
    bp_lines = []
    for bp in sorted(data["blueprints"], key=lambda x: (x["status"], x["name"] or "", x["file"])):
        bp_lines.append(f"{bp['status'].upper():7} | {bp['name']:<22} | {bp['url_prefix'] or '-':<15} | {bp['file']}")
        if bp.get("git_last_commit"):
            bp_lines.append(f"    last_commit: {bp['git_last_commit']}")
        if bp.get("active_evidence"):
            for ev in bp["active_evidence"]:
                bp_lines.append(f"    evidence: {ev}")
        if bp.get("endpoints_found"):
            for ep in bp["endpoints_found"][:10]:
                bp_lines.append(f"    route: @{ep['decorator']}('{ep['path']}')")
        if len(bp.get("endpoints_found") or []) > 10:
            bp_lines.append("    ...")
    bp_txt = os.path.join(EVIDENCE_DIR, "blueprints.txt")
    with open(bp_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(bp_lines))

    # services
    sv_lines = []
    for s in sorted(data["services"], key=lambda x: x["file"]):
        sv_lines.append(f"{s.get('status','unknown').upper():7} | {s['name']:<25} | {s['file']}")
        if s.get("git_last_commit"):
            sv_lines.append(f"    last_commit: {s['git_last_commit']}")
    sv_txt = os.path.join(EVIDENCE_DIR, "services.txt")
    with open(sv_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(sv_lines))

    # models
    md_lines = []
    for m in sorted(data["models"], key=lambda x: (x["file"], x["class"])):
        md_lines.append(f"{m['class']:<30} | {m['file']}")
        if m.get("git_last_commit"):
            md_lines.append(f"    last_commit: {m['git_last_commit']}")
    md_txt = os.path.join(EVIDENCE_DIR, "models.txt")
    with open(md_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    # imports graph (crudo)
    imp_txt = os.path.join(EVIDENCE_DIR, "imports_graph.txt")
    with open(imp_txt, "w", encoding="utf-8") as f:
        for k, v in sorted(data["imports_graph"].items()):
            f.write(f"{k}: {', '.join(v)}\n")

def guess_backlog(data: Dict) -> List[Dict]:
    """Heurística para candidatos a deprecación."""
    backlog = []
    # Reglas:
    # - blueprint con status 'legacy' o filename *_old/*legacy/*backup
    # - servicio sin evidencia de uso (sin importado por otros o nombre sospechoso)
    # - módulos *_new coexistiendo con versiones antiguas
    def last_commit_age(path: str) -> Optional[datetime]:
        meta = None
        try:
            out = subprocess.check_output(
                ["git", "log", "-1", "--pretty=%ci", "--", path],
                cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True
            ).strip()
            if out:
                # formato 'YYYY-MM-DD HH:MM:SS +0000'
                meta = datetime.strptime(out.split(" ")[0], "%Y-%m-%d")
        except Exception:
            pass
        return meta

    now = datetime.utcnow()

    # blueprints
    for bp in data["blueprints"]:
        if bp["status"] in ("legacy", "unknown") and (is_legacy_name(bp["file"]) or is_legacy_name(bp["name"] or "")):
            age = last_commit_age(bp["file"])
            backlog.append({
                "module": bp["name"],
                "file": bp["file"],
                "type": "blueprint",
                "reason": "Nombre sugiere legacy/old/backup y/o no hay evidencia de registro activo en app.py",
                "impact": "medio",
                "priority": "media",
                "effort": "M",
                "risk": "bajo-medio",
                "suggested_steps": [
                    "Verificar si existe reemplazo (_new) o rutas equivalentes",
                    "Correr un grep de referencias en templates/ y tests/",
                    "Si no hay uso, marcar para eliminar; si hay uso parcial, migrar rutas"
                ],
                "last_commit": bp.get("git_last_commit")
            })

    # servicios con nombre o carpeta sospechosa
    for sv in data["services"]:
        if is_legacy_name(sv["file"]):
            backlog.append({
                "module": sv["name"],
                "file": sv["file"],
                "type": "service",
                "reason": "Nombre de archivo sugiere estado legacy/backup",
                "impact": "bajo-medio",
                "priority": "baja",
                "effort": "S",
                "risk": "bajo",
                "suggested_steps": [
                    "Verificar imports entrantes (imports_graph)",
                    "Si no hay referencias, eliminar",
                    "Si hay pocas, consolidar en servicio actual"
                ],
                "last_commit": sv.get("git_last_commit")
            })

    # módulos *_new vs antiguos
    by_stem = defaultdict(list)
    for f in data["files"]:
        stem = os.path.splitext(os.path.basename(f))[0]
        by_stem[stem].append(f)

    for stem, files in by_stem.items():
        if stem.endswith("_new"):
            old_stem = stem.replace("_new", "")
            if old_stem in by_stem:
                backlog.append({
                    "module": f"{old_stem} vs {stem}",
                    "file": ", ".join(sorted(files + by_stem[old_stem])),
                    "type": "conflict",
                    "reason": "Coexisten *_new y versión previa; unificar o deprecar una de las dos",
                    "impact": "medio-alto",
                    "priority": "alta",
                    "effort": "M",
                    "risk": "medio",
                    "suggested_steps": [
                        "Comparar rutas y templates usados",
                        "Mover endpoints faltantes a la versión definitiva",
                        "Retirar imports/rutas de la versión a deprecar y borrar"
                    ],
                    "last_commit": git_last_commit(files[0])
                })

    return backlog

def write_markdown_report(data: Dict, backlog: List[Dict]):
    md = []
    md.append(f"# Obyra – Architecture Field Report\n")
    md.append(f"_Generated: {datetime.utcnow().isoformat()}Z_\n")
    md.append("## Blueprints\n")
    for bp in sorted(data["blueprints"], key=lambda x: (x["status"], x["name"] or "")):
        md.append(f"- **{bp['name']}** ({bp['status']}) — `{bp['file']}`" +
                  (f", prefix: `{bp['url_prefix']}`" if bp['url_prefix'] else ""))
        if bp.get("active_evidence"):
            md.append(f"  - evidence: " + "; ".join(bp["active_evidence"]))
        if bp.get("git_last_commit"):
            md.append(f"  - last commit: `{bp['git_last_commit']}`")
    md.append("\n## Services\n")
    for sv in sorted(data["services"], key=lambda x: x["file"]):
        md.append(f"- `{sv['file']}` ({sv.get('status','unknown')})" + (f" — last: `{sv.get('git_last_commit')}`" if sv.get("git_last_commit") else ""))
    md.append("\n## Models\n")
    for m in sorted(data["models"], key=lambda x: (x["file"], x["class"])):
        md.append(f"- **{m['class']}** — `{m['file']}`" + (f" — last: `{m.get('git_last_commit')}`" if m.get("git_last_commit") else ""))
    md.append("\n## Diagrams\n")
    md.append("- `reports/routes_diagram.svg`")
    md.append("- `reports/dependencies_graph.svg`")
    md.append("\n## Backlog (Deprecation/Refactor Candidates)\n")
    for item in backlog:
        md.append(f"- **{item['module']}** [{item['type']}] — `{item['file']}`")
        md.append(f"  - reason: {item['reason']}")
        md.append(f"  - impact: {item['impact']} | priority: {item['priority']} | effort: {item['effort']} | risk: {item['risk']}")
        md.append("  - steps: " + "; ".join(item["suggested_steps"]))
        if item.get("last_commit"):
            md.append(f"  - last commit: `{item['last_commit']}`")
    out = os.path.join(REPORTS_DIR, "architecture_report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

def main():
    data = scan_repo()
    write_evidence_files(data)
    backlog = guess_backlog(data)
    # backlog JSON
    with open(os.path.join(REPORTS_DIR, "backlog_modules.json"), "w", encoding="utf-8") as f:
        json.dump(backlog, f, ensure_ascii=False, indent=2)
    write_markdown_report(data, backlog)
    print("[OK] architecture_report.md, backlog_modules.json y evidencias generadas.")

if __name__ == "__main__":
    sys.exit(main())
