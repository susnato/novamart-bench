"""Render the site: bake the leaderboard table into the HTML from leaderboard.json.

  python website/render.py [--out DIR]     # default DIR = _site
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
START, END = "<!-- LEADERBOARD_ROWS_START -->", "<!-- LEADERBOARD_ROWS_END -->"

ROW = """          <tr>
            <td class="rankcell"><div class="ranknum num">{rank}</div><div class="rankdate">{date_h}</div>{pill}</td>
            <td>
              <div><span class="sysname">{system}</span> <span class="sysver">v{version}</span></div>
              <div class="sysmodel">{model} ({effort} effort)</div>
              <div class="sysruns mono num">runs {runs}</div>
            </td>
            <td class="r"><div class="meanbig num">{mean_recall}%</div><div class="cicell mono num">[{ci0}, {ci1}]</div></td>
            <td class="r num">{pass3}%</td>
          </tr>"""

def fmt_date(iso):
    m = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    p = (iso or "").split("-")
    return f"{m[int(p[1])-1]} {int(p[2])}, {p[0]}" if len(p) == 3 else (iso or "")

def main():
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROOT, "_site")
    lb = json.load(open(os.path.join(HERE, "leaderboard.json")))
    rows = []
    for e in lb["entries"]:
        pill = '<div class="rankdate maintainer">maintainer submitted</div>' if (e.get("submitted_by") or "").lower() in ("maintainers", "maintainer", "susnato") else ""
        rows.append(ROW.format(rank=e["rank"], date_h=fmt_date(e["date"]), pill=pill, system=e["system"],
                    version=e["version"], model=e["model"],
                    effort=e["effort"], runs=" / ".join(f"{r:.1f}" for r in e["runs_sorted"]),
                    mean_recall=f'{e["mean_recall"]:.1f}', ci0=f'{e["ci95"][0]:.1f}',
                    ci1=f'{e["ci95"][1]:.1f}', pass3=f'{e["pass3"]:.1f}'))
    html = open(os.path.join(HERE, "index.html")).read()
    a, b = html.index(START) + len(START), html.index(END)
    html = html[:a] + "\n" + "\n".join(rows) + "\n          " + html[b:]
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "index.html"), "w").write(html)
    shutil.copy(os.path.join(HERE, "leaderboard.json"), os.path.join(out, "leaderboard.json"))
    shutil.copy(os.path.join(HERE, "paper.pdf"), os.path.join(out, "paper.pdf"))
    print(f"rendered {len(rows)} rows -> {out}/index.html")

if __name__ == "__main__":
    main()
