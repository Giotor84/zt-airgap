"""Standalone HTML dashboard: one file, CSS and JS inline, no CDN (it must open on an offline PC).

Light and dark themes follow the OS. Data are embedded as JSON with ``</script`` escaped. The chat box posts to
the local bridge (``http://127.0.0.1:8765/chat``) when it is running.
"""
from __future__ import annotations

import html
import json
from typing import Any

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--mut:#667085;--bd:#e4e7ec;--acc:#2f5bd3;--warn:#b54708}
@media (prefers-color-scheme:dark){:root{--bg:#11141a;--card:#1a1f27;--fg:#e6e9ef;--mut:#98a2b3;--bd:#2b3240;--acc:#7aa2ff;--warn:#f79009}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:16px 20px;border-bottom:1px solid var(--bd)}h1{margin:0;font-size:18px}.sub{color:var(--mut)}
main{padding:16px 20px;display:grid;gap:16px;max-width:1200px;margin:auto}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 14px}
.k{font-size:22px;font-weight:600}.l{color:var(--mut);font-size:12px}
table{width:100%;border-collapse:collapse}th,td{padding:6px 8px;border-bottom:1px solid var(--bd);text-align:left;vertical-align:top}
th{cursor:pointer;color:var(--mut);font-weight:600}input{width:100%;padding:8px;border:1px solid var(--bd);border-radius:8px;background:var(--card);color:var(--fg)}
.err{color:var(--warn)}#chatlog{white-space:pre-wrap;color:var(--mut);min-height:1.5em}
@media print{input,#chat{display:none}}
"""

_JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const tb = document.querySelector('#t tbody'), q = document.getElementById('q');
let key = 'entity_id', asc = true;
function render(){
  const f = q.value.toLowerCase();
  const rows = D.rows.filter(r => JSON.stringify(r).toLowerCase().includes(f))
    .sort((a,b)=> (a[key]>b[key]?1:a[key]<b[key]?-1:0)*(asc?1:-1));
  tb.innerHTML = rows.map(r => '<tr>' + D.columns.map(c => {
    const v = r[c] ?? ''; const cls = (c==='status' && v!=='ok') ? ' class="err"' : '';
    return '<td'+cls+'>' + String(v).replace(/[&<>]/g, s=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[s])) + '</td>';
  }).join('') + '</tr>').join('');
}
document.querySelectorAll('#t th').forEach(th => th.onclick = () => { key = th.dataset.k; asc = !asc; render(); });
q.oninput = render; render();
document.getElementById('send').onclick = async () => {
  const m = document.getElementById('msg').value, log = document.getElementById('chatlog');
  log.textContent = '...';
  try { const r = await fetch('http://127.0.0.1:8765/chat', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({message: m})}); log.textContent = (await r.json()).answer; }
  catch(e){ log.textContent = 'Bridge not running on 127.0.0.1:8765'; }
};
"""


def render(title: str, kpis: dict[str, Any], rows: list[dict], columns: list[str], subtitle: str = "") -> str:
    data = json.dumps({"rows": rows, "columns": columns}, ensure_ascii=False, default=str).replace("</", "<\\/")
    kpi_html = "".join(
        f'<div class="card"><div class="k">{html.escape(str(v))}</div><div class="l">{html.escape(k)}</div></div>'
        for k, v in kpis.items()
    )
    head = "".join(f'<th data-k="{html.escape(c)}">{html.escape(c)}</th>' for c in columns)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>{_CSS}</style></head><body>
<header><h1>{html.escape(title)}</h1><div class="sub">{html.escape(subtitle)}</div></header>
<main><section class="kpis">{kpi_html}</section>
<section class="card"><input id="q" placeholder="Filter..."><table id="t"><thead><tr>{head}</tr></thead><tbody></tbody></table></section>
<section class="card" id="chat"><input id="msg" placeholder="Ask (needs the local bridge)"> <button id="send">Send</button><div id="chatlog"></div></section>
</main><script id="data" type="application/json">{data}</script><script>{_JS}</script></body></html>"""
