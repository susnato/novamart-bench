"""Write the access pack: the environment-specific values the frozen brief's
placeholders refer to, rendered copies of the brief, an env file that points the
standard BigQuery clients at the warehouse, and a short README.

  python setup/loaders/access_pack.py <warehouse-project> <redash-url> <redash-key> <workspace>
      [--mode local|cloud-bigquery] [--emulator-endpoint URL] [--estate-pg-port N]
"""
import argparse, os

PIN = "5ae1182"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("warehouse_project"); ap.add_argument("redash_url")
    ap.add_argument("redash_key"); ap.add_argument("workspace")
    ap.add_argument("--mode", choices=["local", "cloud-bigquery"], default="local")
    ap.add_argument("--emulator-endpoint", default="http://localhost:9050")
    ap.add_argument("--estate-pg-port", default="15433")
    ap.add_argument("--out", default="~/novamart-estate/access-pack", help="where to write the pack")
    a = ap.parse_args()

    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out = os.path.abspath(os.path.expanduser(a.out))
    os.makedirs(out, exist_ok=True)
    workspace = os.path.abspath(a.workspace)          # the brief appends /novamart itself
    compose = os.path.join(root, "setup", "docker-compose.yml")
    local = a.mode == "local"
    host = a.emulator_endpoint   # the Python client needs the scheme in BIGQUERY_EMULATOR_HOST
    manifest = os.path.join(out, ".generated")   # every file this script writes; nothing else is ever deleted
    previously_generated = set(open(manifest).read().split()) if os.path.exists(manifest) else set()
    generated = []
    def write(rel, text, mode="w"):
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f: f.write(text)
        generated.append(rel)
        return path

    values = [f"MODE={a.mode}", f"WAREHOUSE_PROJECT={a.warehouse_project}",
              f"REDASH_URL={a.redash_url}", f"REDASH_API_KEY={a.redash_key}",
              f"WORKSPACE={workspace}", "GITHUB_ORG=novamart-sim", f"ESTATE_PG_PORT={a.estate_pg_port}"]
    if local:
        values += [f"BIGQUERY_API_ENDPOINT={a.emulator_endpoint}", f"BIGQUERY_EMULATOR_HOST={host}"]
    write("values.env", "\n".join(values) + "\n")
    write("redash-agent-creds", f"REDASH_URL={a.redash_url}\nREDASH_API_KEY={a.redash_key}\n")

    if local:
        # bq needs a token (any token; the emulator never checks it) and the API's discovery
        # document, which the emulator does not serve. Both live in the rc file, so they apply
        # to bq only and never touch the user's gcloud login.
        disc = os.path.join(out, "bigquery-v2-discovery.json")
        try:
            import urllib.request
            urllib.request.urlretrieve("https://bigquery.googleapis.com/$discovery/rest?version=v2", disc)
            generated.append("bigquery-v2-discovery.json")
        except Exception as e:
            print(f"note: could not fetch the BigQuery discovery document ({e}); bq will not work until "
                  f"it is saved as {disc}; the Python client is unaffected")
            disc = None
        rc = [f"api = {a.emulator_endpoint}", f"project_id = {a.warehouse_project}"]
        if disc: rc.append(f"discovery_file = {disc}")
        write("bigqueryrc", "\n".join(rc) + "\n\n[query]\nuse_legacy_sql = false\n")
        # bq only honors the dummy token as a command-line flag, so a wrapper first on PATH
        # supplies it; this reaches agent subprocesses and leaves gcloud itself untouched.
        import shutil, stat
        real_bq = shutil.which("bq")
        bindir = os.path.join(out, "bin"); os.makedirs(bindir, exist_ok=True)
        if real_bq:
            wrapper = write(os.path.join("bin", "bq"), f'#!/bin/sh\n# NovaMart local mode: the emulator accepts any token\nexec "{real_bq}" --oauth_access_token=dummy "$@"\n')
            os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            print("note: bq is not installed on this machine; install the Google Cloud SDK to use it against the emulator")

    env = ["# NovaMart access pack. Source this before running an agent or any BigQuery client:",
           f"#   source {os.path.join(out, 'env.sh')}",
           f'export WAREHOUSE_PROJECT="{a.warehouse_project}"',
           f'export GOOGLE_CLOUD_PROJECT="{a.warehouse_project}"',
           f'export REDASH_URL="{a.redash_url}"', f'export REDASH_API_KEY="{a.redash_key}"',
           f'export WORKSPACE="{workspace}"', f'export ESTATE_PG_PORT="{a.estate_pg_port}"']
    if local:
        env += [f'export BIGQUERY_EMULATOR_HOST="{host}"   # Python, Go, Node and Java clients switch to the emulator',
                f'export BQ_EMULATOR_ENDPOINT="{a.emulator_endpoint}"   # setup/parity/run_parity.py',
                f'export BIGQUERYRC="{os.path.join(out, "bigqueryrc")}"   # bq CLI: endpoint, project, discovery document',
                f'export PATH="{os.path.join(out, "bin")}:$PATH"   # bq wrapper that passes the dummy token',
                f'if [ "$(curl -s -o /dev/null -w \'%{{http_code}}\' {a.emulator_endpoint}/ 2>/dev/null)" = "000" ]; then',
                f'  echo "warning: the BigQuery emulator is not answering on {a.emulator_endpoint}; start it with: docker compose -f {compose} up -d bq-emulator" >&2',
                'fi']
    else:
        # A previous local run left files that are wrong in cloud mode. Remove ONLY the ones the
        # manifest says this script wrote; anything a user put in the pack is never touched.
        for stale in ("bigqueryrc", "bigquery-v2-discovery.json", "sa-key.json.NOT_NEEDED",
                      "agent-github-pat.NOT_NEEDED", os.path.join("bin", "bq")):   # the GitHub marker is from older packs
            path = os.path.join(out, stale)
            if stale in previously_generated and os.path.exists(path): os.remove(path)
        if os.path.isdir(os.path.join(out, "bin")) and not os.listdir(os.path.join(out, "bin")):
            os.rmdir(os.path.join(out, "bin"))
        env += ['unset BIGQUERY_EMULATOR_HOST BIGQUERYRC',
                'if ! gcloud auth print-access-token >/dev/null 2>&1; then',
                '  echo "warning: gcloud is not logged in; run gcloud auth login, or export GOOGLE_APPLICATION_CREDENTIALS pointing at your own key" >&2',
                'fi']
    write("env.sh", "\n".join(env) + "\n")

    subs = {"<warehouse-project>": a.warehouse_project, "<redash-url>": a.redash_url,
            "<workspace>": workspace, "<github-org>": "novamart-sim", "<access-pack>": out}
    # the launcher names the original runs' paths; the rendered copy points at the rendered contexts
    for name in ("novamart_sim_goal_context.md", "novamart_sim_extra_context.md"):
        subs[f"~/book_runs/prompts/{name}"] = os.path.join(out, "rendered_" + name)
    # The only thing that differs between the modes is the warehouse. Local mode has no
    # service-account key (the emulator accepts any token), so the one sentence in the brief that
    # points the agent at sa-key.json is swapped for one that describes this machine. Exact-string
    # swap on the released text: the cloud-bigquery rendering and default_prompts/ are untouched.
    local_swaps = {
        "read-only service-account credentials at `<access-pack>/sa-key.json`.":
            f"served by a local emulator at {a.emulator_endpoint} that needs no credentials. Run `source <access-pack>/env.sh` first; `bq` and the client libraries then work with no Google login.",
    } if local else {}
    for name in ("novamart_sim_launcher.md", "novamart_sim_goal_context.md", "novamart_sim_extra_context.md"):
        s = open(os.path.join(root, "default_prompts", name)).read()
        if name == "novamart_sim_extra_context.md":
            for k, v in local_swaps.items():
                if k not in s:
                    print(f"note: the released brief no longer contains the sentence this local swap expects; "
                          f"update local_swaps in {__file__}: {k[:60]}...")
                s = s.replace(k, v)
        for k, v in subs.items(): s = s.replace(k, v)
        write("rendered_" + name, s)

    if local:
        warehouse = f"""The warehouse is a BigQuery emulator on {a.emulator_endpoint}, project `{a.warehouse_project}`. It needs no credentials and accepts any token, so the `sa-key.json` the brief mentions does not exist here and is not needed.

`env.sh` points `bq` at the emulator (`BIGQUERYRC`: endpoint, project, a local copy of the API's discovery document) and puts a one-line `bq` wrapper first on `PATH` that passes a dummy token, so `bq` works with no Google login at all:

    bq ls

`env.sh` also sets `BIGQUERY_EMULATOR_HOST`, which the Python, Go, Node and Java client libraries read for the endpoint. They still insist on some credential object before sending a request: on a machine that has run `gcloud auth application-default login` (any account) they work unchanged; otherwise pass anonymous credentials explicitly, for example in Python:

    from google.cloud import bigquery
    from google.auth.credentials import AnonymousCredentials
    client = bigquery.Client(project="{a.warehouse_project}", credentials=AnonymousCredentials())"""
    else:
        warehouse = f"""The warehouse is your own BigQuery project, `{a.warehouse_project}`. Use the credentials you already have: `gcloud auth application-default login`, or your own service-account key saved as `sa-key.json` in this folder with `GOOGLE_APPLICATION_CREDENTIALS` pointing at it (that is the file the brief mentions). With `env.sh` sourced:

    bq ls"""
    nokey = f"""The released brief says the warehouse credentials are at `{os.path.join(out, "sa-key.json")}`; the rendered copy in this folder says instead that none are needed. In local mode there is no key: the emulator accepts any token. Run `source {os.path.join(out, "env.sh")}` and use `bq` as usual (`bq ls` lists the datasets)."""
    if local:
        write("sa-key.json.NOT_NEEDED", nokey + "\n")
    # the brief names this file in both modes ("if you need remote git operations"); the repo is
    # public, so an empty token means anonymous access and works. Never overwrite one the user filled.
    pat = os.path.join(out, "agent-github-pat")
    if not os.path.exists(pat) or os.path.getsize(pat) == 0:
        write("agent-github-pat", "")
    nokey_section = f"## There is no sa-key.json here\n\n{nokey}\n\n" if local else ""
    readme = f"""# Access pack ({a.mode})

The values the brief's placeholders refer to, for this machine. Source `env.sh` in the shell you launch the agent from, then check everything answers:

    source {os.path.join(out, "env.sh")}
    python {os.path.join(root, "setup", "verify_access.py")}

{nokey_section}## Warehouse (BigQuery)

{warehouse}

## Dashboards (Redash)

{a.redash_url}, read-only. The API key is in `redash-agent-creds` (the file the brief points at):

    curl -s -H "Authorization: Key $REDASH_API_KEY" {a.redash_url}/api/dashboards | python3 -c 'import json,sys; print(json.load(sys.stdin)["count"], "dashboards")'

## Codebase

The application repo is checked out at `{os.path.join(workspace, "novamart")}` at commit `{PIN}`. It is public, so `git log` and `git fetch` work without a token; `agent-github-pat` (the file the brief mentions) is empty by default, which every git and `gh` client treats as no token. Put a read-only PAT of your own in it only if your agent needs the GitHub API.

## The rendered brief

`rendered_novamart_sim_launcher.md`, `rendered_novamart_sim_goal_context.md` and `rendered_novamart_sim_extra_context.md` are the released brief with the placeholders filled in for this machine. Start your agent with the rendered launcher; it points at the two rendered context files. `values.env` holds the same values for scripts.

Run the agent with `{os.path.join(workspace, "novamart")}` as its working directory. The benchmark repo (with the gold claims and the released books) is not part of the estate and must not be given to the agent.
"""
    write("README.md", readme)
    open(manifest, "w").write("\n".join(sorted(set(generated))) + "\n")
    print(f"access pack written to {out} (mode: {a.mode})")

if __name__ == "__main__":
    main()
