"""Render the site: bake the leaderboard table into the HTML from leaderboard.json.

  python website/render.py [--out DIR]     # default DIR = _site
"""
import html as _html
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
START, END = "<!-- LEADERBOARD_ROWS_START -->", "<!-- LEADERBOARD_ROWS_END -->"

# One entry is a harness and a model together, named the Spider 2.0 way
# ("Harness + Model"), the effort setting after it, the harness version on
# its own line; the environment mode rides on that line's tooltip.
ROW = """          <tr>
            <td class="rankcell"><div class="ranknum num">{rank}</div><div class="rankdate">{date_h}</div></td>
            <td>
              <div><span class="sysname">{system} + {model}</span>{effort_h}</div>
              <div class="sysver"{title_h}>v{version}</div>
            </td>
            <td class="r"><div class="meanbig num">{mean_recall}%</div><div class="cicell mono num">[{ci0}, {ci1}]</div><div class="sysruns mono num">runs {runs}</div></td>
            <td class="r num">{pass3}%</td>
          </tr>"""

MODE_LABEL = {"cloud-bigquery": "cloud BigQuery", "local-emulator": "local emulator"}

def esc(v):
    return _html.escape(str(v or ""), quote=True)

def fmt_date(iso):
    m = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    p = (iso or "").split("-")
    return f"{m[int(p[1])-1]} {int(p[2])}, {p[0]}" if len(p) == 3 else (iso or "")

def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "_site")
    lb = json.load(open(os.path.join(HERE, "leaderboard.json")))
    rows = []
    for e in lb["entries"]:
        effort = str(e.get("effort") or "").strip()
        mode = MODE_LABEL.get(e.get("mode", ""), e.get("mode", ""))
        tip = f'{e["system"]} v{e["version"]}' + (f", {mode}" if mode else "")
        rows.append(ROW.format(rank=e["rank"], date_h=fmt_date(e["date"]), system=esc(e["system"]),
                    version=esc(e["version"]), model=esc(e["model"]),
                    effort_h=f' <span class="syseffort">({esc(effort)})</span>' if effort else "",
                    title_h=f' title="{esc(tip)}"',
                    runs=" / ".join(f"{r:.1f}" for r in e["runs_sorted"]),
                    mean_recall=f'{e["mean_recall"]:.1f}', ci0=f'{e["ci95"][0]:.1f}',
                    ci1=f'{e["ci95"][1]:.1f}', pass3=f'{e["pass3"]:.1f}'))
    html = open(os.path.join(HERE, "index.html")).read()
    a, b = html.index(START) + len(START), html.index(END)
    html = html[:a] + "\n" + "\n".join(rows) + "\n          " + html[b:]
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "index.html"), "w").write(html)
    shutil.copy(os.path.join(HERE, "leaderboard.json"), os.path.join(out, "leaderboard.json"))
    shutil.copy(os.path.join(HERE, "paper.pdf"), os.path.join(out, "paper.pdf"))
    shutil.copy(os.path.join(HERE, "pipeline.png"), os.path.join(out, "pipeline.png"))
    shutil.copy(os.path.join(HERE, "social-card.png"), os.path.join(out, "social-card.png"))   # 1200x630 social preview card
    print(f"rendered {len(rows)} rows -> {out}/index.html")

if __name__ == "__main__":
    main()
