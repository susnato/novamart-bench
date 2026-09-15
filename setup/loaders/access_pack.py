"""Write the access pack: the environment-specific values the frozen brief's
placeholders refer to, plus rendered convenience copies of the brief."""
import os, sys

def main(warehouse_project, redash_url, redash_key, workspace):
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    out = os.path.join(root, "setup", "access-pack")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "values.env"), "w") as f:
        f.write(f"WAREHOUSE_PROJECT={warehouse_project}\nREDASH_URL={redash_url}\n"
                f"REDASH_API_KEY={redash_key}\nWORKSPACE={workspace}\nGITHUB_ORG=novamart-sim\n")
    with open(os.path.join(out, "redash-agent-creds"), "w") as f:
        f.write(f"REDASH_URL={redash_url}\nREDASH_API_KEY={redash_key}\n")
    subs = {"<warehouse-project>": warehouse_project, "<redash-url>": redash_url,
            "<workspace>": workspace, "<github-org>": "novamart-sim",
            "<access-pack>": out}
    for name in ("novamart_sim_goal_context.md", "novamart_sim_extra_context.md"):
        s = open(os.path.join(root, "default_prompts", name)).read()
        for k, v in subs.items(): s = s.replace(k, v)
        open(os.path.join(out, "rendered_" + name), "w").write(s)
    print(f"access pack written to {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:5]))
