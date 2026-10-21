#!/usr/bin/env python3
"""Local labelling app for a kit built by build_kit.py. Serves the books and the sampled claims side by side
and saves every verdict to the kit's sheet.csv at once.

  python scoring/judges/validation/kit/rate_app.py --kit kit_out [--port 8795]

The app is blind: it reads books/ (opaque codes), the sheet and claims/, and never reads sealed/.
Each label is written to the sheet immediately (atomic rewrite), so closing the tab loses nothing.
Standard library only; the optional `markdown` package gives a nicer book rendering when installed.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import LABELS, REPO_ROOT, compact_evidence, load_claims  # noqa: E402

EVIDENCE = ["", "specific", "weak", "none"]
LOCK = threading.Lock()


def md_to_html(text: str) -> str:
    """Small markdown renderer: headings, code fences, inline code, bold, lists, paragraphs."""
    try:
        import markdown  # type: ignore
        return markdown.markdown(text, extensions=["fenced_code", "tables"])
    except Exception:
        pass
    out, in_code, para = [], False, []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def inline(s):
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        return s

    for line in text.splitlines():
        if line.strip().startswith("```"):
            flush()
            out.append("<pre>" if not in_code else "</pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            flush(); out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>"); continue
        if re.match(r"^\s*[-*]\s+", line):
            flush(); out.append("<li>" + inline(re.sub(r"^\s*[-*]\s+", "", line)) + "</li>"); continue
        if re.match(r"^\s*\|", line):
            flush(); out.append("<div class='row'>" + inline(line) + "</div>"); continue
        if not line.strip():
            flush(); continue
        para.append(line)
    flush()
    return "\n".join(out)


class Store:
    def __init__(self, kit, sheet, repo):
        self.kit, self.sheet_path = kit, os.path.join(kit, sheet)
        self.claims = load_claims(repo)
        self.rows = list(csv.DictReader(open(self.sheet_path, newline="")))
        self.fields = list(self.rows[0].keys())
        self.books = {}
        for f in sorted(os.listdir(os.path.join(kit, "books"))):
            code = f.replace("book_", "").replace(".md", "")
            self.books[code] = md_to_html(open(os.path.join(kit, "books", f)).read())

    def state(self):
        claims = {}
        for cid in sorted({r["claim_id"] for r in self.rows}):
            c = self.claims[cid]
            m = c.get("match") or {}
            claims[cid] = {"claim_text": " ".join(str(c.get("claim_text", "")).split()),
                           "must_include": m.get("must_include") or [],
                           "must_not_include": m.get("must_not_include") or [],
                           "evidence": compact_evidence(c.get("evidence"))}
        return {"sheet": os.path.basename(self.sheet_path), "rows": self.rows, "claims": claims,
                "labels": LABELS, "evidence_options": EVIDENCE, "book_codes": sorted(self.books)}

    def label(self, cell, verdict, book_evidence, notes):
        if verdict not in LABELS + [""]:
            raise ValueError("bad verdict")
        if book_evidence not in EVIDENCE:
            raise ValueError("bad book_evidence")
        with LOCK:
            hit = None
            for r in self.rows:
                if r["cell"] == cell:
                    r["verdict"] = verdict
                    if "book_evidence" in r:
                        r["book_evidence"] = book_evidence
                    r["notes"] = notes
                    hit = r
            if hit is None:
                raise KeyError(cell)
            fd, tmp = tempfile.mkstemp(dir=self.kit, prefix=".sheet.", suffix=".csv")
            with os.fdopen(fd, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=self.fields)
                w.writeheader(); w.writerows(self.rows)
            os.replace(tmp, self.sheet_path)
            return hit


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Judge validation: labelling</title>
<style>
:root{--bg:#F7F8FA;--surface:#fff;--ink:#1B2430;--muted:#5B6773;--line:#D8DEE5;--accent:#2C5F8A;--soft:#E8EFF6;--ok:#2E7D4F;--warn:#8A5A2C;--bad:#A23B3B}
@media (prefers-color-scheme:dark){:root{--bg:#131720;--surface:#1A2029;--ink:#E6EAF0;--muted:#9AA6B4;--line:#2E3742;--accent:#7FB0DB;--soft:#1F2C3A}}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
header{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--surface);position:sticky;top:0;z-index:2}
header b{font-size:15px} header .prog{color:var(--muted);font-variant-numeric:tabular-nums}
header select,header input,header button{font:inherit;padding:4px 8px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink)}
main{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:0;height:calc(100vh - 54px)}
@media (max-width:900px){main{grid-template-columns:1fr;height:auto}}
#bookpane{overflow:auto;padding:16px 22px;border-right:1px solid var(--line);font-size:14.5px}
#bookpane h1,#bookpane h2,#bookpane h3{margin:18px 0 6px} #bookpane pre{background:var(--soft);padding:8px 10px;overflow-x:auto;font-size:12.5px}
#bookpane code{background:var(--soft);padding:0 3px} #bookpane li{margin-left:18px} #bookpane .row{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:pre}
mark{background:#FFE58A;color:#1B2430;padding:0 1px} mark.cur{background:#FF9632;outline:2px solid #FF9632}
#cellpane{overflow:auto;padding:16px 22px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px;margin-bottom:12px}
.eyebrow{font-family:ui-monospace,Menlo,monospace;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.claim{font-size:16px;margin:6px 0 10px}
.list li{margin-bottom:4px} .ev li{font-size:13px;color:var(--muted);margin-bottom:6px}
.verdicts{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin:8px 0}
.verdicts button{font:inherit;font-weight:600;padding:12px 10px;border:2px solid var(--line);border-radius:6px;background:var(--surface);color:var(--ink);cursor:pointer;text-align:left}
.verdicts button small{display:block;font-weight:400;color:var(--muted);font-size:12.5px}
.verdicts button.on{border-color:var(--accent);background:var(--soft)}
.verdicts button:focus-visible{outline:2px solid var(--accent)}
.row2{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:8px}
.row2 select,.row2 input,.row2 button{font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink)}
.row2 input{flex:1;min-width:200px}
.nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.nav button{font:inherit;padding:8px 12px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink);cursor:pointer}
.nav button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.hint{color:var(--muted);font-size:12.5px;margin-top:8px}
.saved{color:var(--ok);font-size:13px;min-width:70px}
</style></head><body>
<header>
  <b id="title">Labelling</b>
  <span class="prog" id="prog"></span>
  <label>Book <select id="bookSel"></select></label>
  <label>Cell <select id="cellSel"></select></label>
  <input id="find" placeholder="find in book" size="26">
  <span class="prog" id="findCount"></span>
  <button id="findPrev" title="previous match (Shift+Enter)">&uarr;</button>
  <button id="findNext" title="next match (Enter)">&darr;</button>
  <button id="clearFind" title="clear (Esc)">clear</button>
</header>
<main>
  <div id="bookpane"></div>
  <div id="cellpane">
    <div class="card">
      <div class="eyebrow" id="cellHead"></div>
      <div class="claim" id="claimText"></div>
      <div id="must"></div>
      <div id="mustnot"></div>
      <details><summary class="eyebrow" style="cursor:pointer">gold evidence, context only, not evidence in the book</summary><ul class="ev" id="ev"></ul></details>
    </div>
    <div class="card">
      <div class="eyebrow">verdict</div>
      <div class="verdicts" id="verdicts"></div>
      <div class="row2">
        <label>book evidence <select id="bev"><option value="">(skip)</option><option>specific</option><option>weak</option><option>none</option></select></label>
        <input id="notes" placeholder="notes (optional)">
        <span class="saved" id="saved"></span>
      </div>
      <div class="nav">
        <button id="prev">prev</button>
        <button id="next">next</button>
        <button id="nextU" class="primary">next unlabelled</button>
      </div>
      <div class="hint">Rules: only what the book itself says counts. Any must-not-include point in the book = contradicted. All must-include points present = correct. Some present, important ones missing = partial. Most or all missing = missing. The published labels were made with the rubric in scoring/judges/validation/prompts/v1_system_prompt.txt.</div>
    </div>
  </div>
</main>
<script>
let S=null, idx=0;
const $=id=>document.getElementById(id);
async function load(){ S=await (await fetch('/api/state')).json(); $('title').textContent='Labelling: '+S.sheet;
  const books=S.book_codes; $('bookSel').innerHTML=books.map(b=>`<option>${b}</option>`).join('');
  idx=S.rows.findIndex(r=>!r.verdict); if(idx<0) idx=0; render(); }
function rowsOfBook(b){ return S.rows.map((r,i)=>[r,i]).filter(([r])=>r.book===b); }
function render(){ const r=S.rows[idx]; const c=S.claims[r.claim_id];
  $('bookSel').value=r.book;
  $('cellSel').innerHTML=rowsOfBook(r.book).map(([x,i])=>`<option value="${i}" ${i===idx?'selected':''}>${x.cell} ${x.verdict?'• '+x.verdict:''}</option>`).join('');
  const done=S.rows.filter(x=>x.verdict).length; const bdone=rowsOfBook(r.book).filter(([x])=>x.verdict).length, btot=rowsOfBook(r.book).length;
  $('prog').textContent=`${done} / ${S.rows.length} labelled · book ${r.book}: ${bdone} / ${btot}`;
  $('cellHead').textContent=`${r.cell} · claim ${r.claim_id} · book ${r.book}`;
  $('claimText').textContent=c.claim_text;
  $('must').innerHTML=c.must_include.length?`<div class="eyebrow">must include, all of these for correct</div><ul class="list">${c.must_include.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'';
  $('mustnot').innerHTML=c.must_not_include.length?`<div class="eyebrow">must not include, any of these means contradicted</div><ul class="list">${c.must_not_include.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'';
  $('ev').innerHTML=c.evidence.map(x=>`<li>${esc(x)}</li>`).join('');
  const sub={correct:'all must-include points, no forbidden point',partial:'some required points, important ones missing',missing:'most or all required points absent',contradicted:'a must-not-include point is in the book'};
  $('verdicts').innerHTML=S.labels.map((l,i)=>`<button data-l="${l}" class="${r.verdict===l?'on':''}"><span>${l}</span><small>${sub[l]}</small></button>`).join('');
  document.querySelectorAll('#verdicts button').forEach(b=>b.onclick=()=>setVerdict(b.dataset.l));
  $('bev').value=r.book_evidence||''; $('notes').value=r.notes||''; $('saved').textContent='';
  if($('bookpane').dataset.book!==r.book){ $('bookpane').innerHTML=S_books[r.book]; $('bookpane').dataset.book=r.book; $('bookpane').scrollTop=0; marks=[]; mi=-1; if($('find').value) doFind($('find').value); }
}
function esc(s){ return s.replace(/[&<>]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch])); }
async function save(v){ const r=S.rows[idx]; const body={cell:r.cell,verdict:v===undefined?r.verdict:v,book_evidence:$('bev').value,notes:$('notes').value};
  const res=await fetch('/api/label',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!res.ok){ $('saved').textContent='save failed'; $('saved').style.color='var(--bad)'; return; }
  Object.assign(r, body); $('saved').style.color='var(--ok)'; $('saved').textContent='saved'; render(); }
function setVerdict(l){ save(l); }
function go(i){ if(i<0||i>=S.rows.length) return; idx=i; render(); }
function nextUnlabelled(){ for(let k=1;k<=S.rows.length;k++){ const i=(idx+k)%S.rows.length; if(!S.rows[i].verdict){ go(i); return; } } $('saved').textContent='all labelled'; }
$('prev').onclick=()=>go(idx-1); $('next').onclick=()=>go(idx+1); $('nextU').onclick=nextUnlabelled;
$('bookSel').onchange=e=>{ const first=rowsOfBook(e.target.value)[0]; if(first) go(first[1]); };
$('cellSel').onchange=e=>go(parseInt(e.target.value));
$('bev').onchange=()=>save(); $('notes').onchange=()=>save();
// find in book: highlights every match, shows "current / total", Enter next, Shift+Enter previous, Esc clears
let marks=[], mi=-1, findTimer=null;
function clearMarks(){ const p=$('bookpane'); p.querySelectorAll('mark').forEach(m=>m.replaceWith(document.createTextNode(m.textContent))); p.normalize(); marks=[]; mi=-1; $('findCount').textContent=''; }
function showCurrent(){ marks.forEach(m=>m.classList.remove('cur')); if(mi>=0&&marks[mi]){ marks[mi].classList.add('cur'); marks[mi].scrollIntoView({block:'center'}); } $('findCount').textContent=marks.length?`${mi+1} / ${marks.length}`:($('find').value?'0 / 0':''); }
function doFind(q){ clearMarks(); if(!q) return; const p=$('bookpane'); const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT); const nodes=[]; while(walker.nextNode()) nodes.push(walker.currentNode);
  const re=new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi');
  nodes.forEach(n=>{ const t=n.textContent; if(!re.test(t)) return; re.lastIndex=0; const frag=document.createDocumentFragment(); let last=0,m; while((m=re.exec(t))){ frag.appendChild(document.createTextNode(t.slice(last,m.index))); const mk=document.createElement('mark'); mk.textContent=m[0]; frag.appendChild(mk); marks.push(mk); last=m.index+m[0].length; } frag.appendChild(document.createTextNode(t.slice(last))); n.replaceWith(frag); });
  mi=marks.length?0:-1; showCurrent(); }
function stepFind(d){ if(!marks.length){ doFind($('find').value); return; } mi=(mi+d+marks.length)%marks.length; showCurrent(); }
$('find').addEventListener('input',()=>{ clearTimeout(findTimer); findTimer=setTimeout(()=>doFind($('find').value),150); });
$('find').addEventListener('keydown',e=>{ if(e.key==='Enter'){ e.preventDefault(); stepFind(e.shiftKey?-1:1); } else if(e.key==='Escape'){ $('find').value=''; clearMarks(); } });
$('findNext').onclick=()=>stepFind(1); $('findPrev').onclick=()=>stepFind(-1);
// Cmd/Ctrl+F opens the page's own find box instead of the browser's; Cmd/Ctrl+G steps to the next match
document.addEventListener('keydown',e=>{ const mod=e.metaKey||e.ctrlKey; if(!mod) return;
  if(e.key==='f'||e.key==='F'){ e.preventDefault(); $('find').focus(); $('find').select(); }
  else if(e.key==='g'||e.key==='G'){ e.preventDefault(); stepFind(e.shiftKey?-1:1); } });
$('clearFind').onclick=()=>{ $('find').value=''; clearMarks(); };
let S_books={};
(async()=>{ S_books=await (await fetch('/api/books')).json(); await load(); })();
</script></body></html>"""


def make_handler(store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self._send(200, PAGE.encode(), "text/html")
            elif self.path == "/api/state":
                self._send(200, store.state())
            elif self.path == "/api/books":
                self._send(200, store.books)
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/label":
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n) or b"{}")
            try:
                row = store.label(body["cell"], body.get("verdict", ""), body.get("book_evidence", ""), body.get("notes", ""))
                self._send(200, row)
            except (KeyError, ValueError) as e:
                self._send(400, {"error": str(e)})

        def log_message(self, *a):
            pass
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", required=True, help="kit directory built by build_kit.py")
    ap.add_argument("--repo", default=REPO_ROOT)
    ap.add_argument("--sheet", default="sheet.csv")
    ap.add_argument("--port", type=int, default=8795)
    a = ap.parse_args()
    store = Store(a.kit, a.sheet, a.repo)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(store))
    print(f"labelling {a.sheet}: {sum(1 for r in store.rows if r['verdict'])} / {len(store.rows)} labelled")
    print(f"open http://127.0.0.1:{a.port}/   (Ctrl-C to stop; every label is saved immediately)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
