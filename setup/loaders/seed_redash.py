"""Seed the local Redash from the released export: data source, queries, dashboards.

Idempotent: re-running on an already seeded Redash creates nothing and just prints the key.
Prints the read-only API key for the access pack.
"""
import json, os, subprocess, sys, time
import urllib.request

BASE = os.environ.get("REDASH_URL", "http://localhost:5050")

def compose(*args, capture=False):
    cmd = ["docker", "compose", "-f", os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and capture is False:
        print(r.stdout[-800:], r.stderr[-800:]); raise SystemExit(f"compose {' '.join(args[:3])} failed")
    return r.stdout

def api(key, method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
        headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def admin_key():
    out = compose("exec", "-T", "redash-pg", "psql", "-U", "redash", "-tA", "-c",
                  "select api_key from users where email='admin@novamart.sim'", capture=True)
    return out.strip().splitlines()[-1].strip() if out.strip() else None

def main():
    base = os.path.join(os.path.dirname(__file__), "..", "data", "redash_export")
    compose("run", "--rm", "redash", "create_db")
    if not admin_key():
        compose("run", "--rm", "redash", "manage", "users", "create_root",
                "admin@novamart.sim", "Admin", "--password", "novamart-local")
    key = admin_key()
    if not key: print("could not obtain admin api key"); return 1

    # data source -> the estate postgres
    sources = api(key, "GET", "/api/data_sources")
    if not any(s["name"] == "novamart" for s in sources):
        api(key, "POST", "/api/data_sources", {"name": "novamart", "type": "pg",
            "options": {"host": "estate-pg", "port": 5432, "user": "novamart",
                        "password": "novamart", "dbname": "novamart"}})
    ds_id = [s["id"] for s in api(key, "GET", "/api/data_sources") if s["name"] == "novamart"][0]

    dashboards = json.load(open(os.path.join(base, "dashboards_full.json")))
    existing = {d["name"] for d in api(key, "GET", "/api/dashboards?page_size=250").get("results", [])}
    if {d["name"] for d in dashboards} <= existing:
        print(f"redash already seeded ({len(dashboards)} dashboards present), nothing to do")
        print(f"REDASH_ADMIN_API_KEY={key}")
        return 0

    queries = json.load(open(os.path.join(base, "queries_full.json")))
    qmap = {}
    for q in queries:
        made = api(key, "POST", "/api/queries", {"name": q["name"], "query": q["query"],
                   "data_source_id": ds_id, "description": q.get("description") or "",
                   "options": {}, "is_draft": False})
        api(key, "POST", f"/api/queries/{made['id']}", {"is_draft": False})
        qmap[q["id"]] = made
        for v in q.get("visualizations", []):
            if v.get("type") == "TABLE" and v.get("name") == "Table":
                continue
            made_v = api(key, "POST", "/api/visualizations", {"query_id": made["id"],
                        "type": v["type"], "name": v["name"], "description": v.get("description") or "",
                        "options": v.get("options") or {}})
            qmap.setdefault("viz", {})[v["id"]] = made_v["id"]

    for d in dashboards:
        if d["name"] in existing:
            continue
        made = api(key, "POST", "/api/dashboards", {"name": d["name"]})
        for w in d.get("widgets") or []:
            viz = w.get("visualization")
            body = {"dashboard_id": made["id"], "options": w.get("options") or {},
                    "width": w.get("width", 1), "text": w.get("text") or ""}
            if viz:
                old_q = viz["query"]["id"]
                new_q = qmap.get(old_q)
                if not new_q: continue
                new_viz = None
                if viz.get("type") == "TABLE":
                    vs = api(key, "GET", f"/api/queries/{new_q['id']}").get("visualizations", [])
                    new_viz = next((v["id"] for v in vs if v["type"] == "TABLE"), None)
                else:
                    new_viz = qmap.get("viz", {}).get(viz["id"])
                if new_viz is None: continue
                body["visualization_id"] = new_viz
            api(key, "POST", "/api/widgets", body)
        api(key, "POST", f"/api/dashboards/{made['id']}", {"is_draft": False})

    print(f"seeded {len(qmap)-(1 if 'viz' in qmap else 0)} queries, {len(dashboards)} dashboards")
    print(f"REDASH_ADMIN_API_KEY={key}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
