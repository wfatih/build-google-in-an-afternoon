"""
server.py — Embedded web UI served by Python's built-in http.server.

No external web frameworks (no Flask, Django, FastAPI).

Endpoints
---------
GET  /            HTML single-page dashboard
GET  /api/stats   JSON — live crawler + index statistics
GET  /api/recent  JSON — recently indexed pages
POST /api/index   JSON body {url, depth, workers, rate, max_queue} → start crawl
POST /api/search  JSON body {query, limit} → search results
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from typing import Optional


# ---------------------------------------------------------------------------
# Embedded HTML/CSS/JS  (single-page app, no external dependencies)
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mini-Google</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f0f1a;color:#e0e0e0;min-height:100vh}
a{color:#7c6af7;text-decoration:none}a:hover{text-decoration:underline}
header{background:#1a1a2e;padding:1rem 2rem;border-bottom:1px solid #2d2d4e;display:flex;align-items:center;gap:1rem}
header h1{font-size:1.5rem;color:#7c6af7;letter-spacing:-0.02em}
header .sub{color:#666;font-size:.85rem}
.container{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;padding:1.5rem;max-width:1400px;margin:0 auto}
.card{background:#1a1a2e;border:1px solid #2d2d4e;border-radius:8px;padding:1.5rem}
.card h2{font-size:.8rem;color:#666;margin-bottom:1rem;text-transform:uppercase;letter-spacing:.1em}
.form-group{margin-bottom:.75rem}
label{display:block;font-size:.75rem;color:#888;margin-bottom:.25rem}
input{width:100%;background:#0f0f1a;border:1px solid #2d2d4e;border-radius:4px;padding:.5rem .75rem;color:#e0e0e0;font-size:.9rem}
input:focus{outline:none;border-color:#7c6af7}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem}
.btn{background:#7c6af7;border:none;border-radius:4px;color:#fff;padding:.6rem 1.2rem;cursor:pointer;font-size:.9rem;width:100%;margin-top:.5rem;transition:background .2s}
.btn:hover{background:#6a58e5}.btn:disabled{background:#333;color:#666;cursor:not-allowed}
.stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-top:1rem}
.stat{background:#0f0f1a;border:1px solid #2d2d4e;border-radius:6px;padding:.75rem;text-align:center}
.stat .val{font-size:1.4rem;font-weight:700;color:#7c6af7}
.stat .lbl{font-size:.65rem;color:#666;margin-top:.2rem;text-transform:uppercase;letter-spacing:.05em}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:10px;font-size:.7rem;font-weight:700}
.b-active{background:#0d2b0d;color:#4caf50;border:1px solid #4caf50}
.b-idle{background:#222;color:#666;border:1px solid #333}
.b-throttled{background:#2b0d0d;color:#f44;border:1px solid #f44}
.status-row{display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem;flex-wrap:wrap}
.qbar-wrap{background:#0f0f1a;border:1px solid #2d2d4e;border-radius:3px;height:5px;margin-top:.75rem}
.qbar{height:100%;border-radius:3px;background:#7c6af7;transition:width .5s}
.result{border:1px solid #2d2d4e;border-radius:6px;padding:.75rem;margin-top:.6rem;background:#0f0f1a}
.result .url{font-size:.9rem;word-break:break-all}
.result .meta{font-size:.7rem;color:#666;margin-top:.25rem}
.msg{font-size:.8rem;padding:.4rem .7rem;border-radius:4px;margin-top:.5rem}
.err{background:#2b0d0d;color:#f66;border:1px solid #f44}
.ok{background:#0d2b0d;color:#6d6;border:1px solid #4c4}
.wide{grid-column:1/-1}
table{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:.5rem}
th{color:#555;text-align:left;padding:.4rem;border-bottom:1px solid #2d2d4e;font-weight:400;font-size:.7rem;text-transform:uppercase;letter-spacing:.05em}
td{padding:.4rem;border-bottom:1px solid #111;color:#c0c0c0;word-break:break-all}
</style>
</head>
<body>
<header>
  <h1>&#128269; Mini-Google</h1>
  <span class="sub">Web Crawler &amp; Search Engine &mdash; localhost</span>
</header>
<div class="container">

  <!-- Crawler -->
  <div class="card">
    <h2>Crawler</h2>
    <div class="form-group">
      <label>Origin URL</label>
      <input type="url" id="iurl" placeholder="https://example.com">
    </div>
    <div class="form-group">
      <label>Depth (k)</label>
      <input type="number" id="idepth" value="2" min="0" max="10">
    </div>
    <div class="row3">
      <div class="form-group"><label>Workers</label><input type="number" id="iworkers" value="8" min="1" max="64"></div>
      <div class="form-group"><label>Rate (req/s)</label><input type="number" id="irate" value="10" min="1" max="200"></div>
      <div class="form-group"><label>Max Queue</label><input type="number" id="iqueue" value="500" min="10"></div>
    </div>
    <button class="btn" id="start-btn" onclick="startCrawl()">Start Crawl</button>
    <div id="crawl-msg"></div>

    <div style="margin-top:1.25rem">
      <div class="status-row">
        <span id="sbadge" class="badge b-idle">&#9632; IDLE</span>
        <span id="elapsed" style="font-size:.75rem;color:#666"></span>
        <span id="tbadge"></span>
      </div>
      <div class="stats-grid">
        <div class="stat"><div class="val" id="s-proc">0</div><div class="lbl">Processed</div></div>
        <div class="stat"><div class="val" id="s-idx">0</div><div class="lbl">Indexed</div></div>
        <div class="stat"><div class="val" id="s-words">0</div><div class="lbl">Words</div></div>
        <div class="stat"><div class="val" id="s-q">0</div><div class="lbl">Queue</div></div>
        <div class="stat"><div class="val" id="s-fail">0</div><div class="lbl">Failed</div></div>
        <div class="stat"><div class="val" id="s-drop">0</div><div class="lbl">Dropped&#x2009;(BP)</div></div>
      </div>
      <div class="qbar-wrap"><div class="qbar" id="qbar" style="width:0%"></div></div>
    </div>
  </div>

  <!-- Search -->
  <div class="card">
    <h2>Search</h2>
    <div class="form-group">
      <label>Query</label>
      <input type="text" id="sq" placeholder="Enter keywords..." onkeydown="if(event.key==='Enter')doSearch()">
    </div>
    <button class="btn" onclick="doSearch()">Search</button>
    <div id="smsg"></div>
    <div id="results"></div>
  </div>

  <!-- Recent -->
  <div class="card wide">
    <h2>Recently Indexed</h2>
    <table>
      <thead><tr><th>URL</th><th>Origin</th><th>Depth</th><th>Time</th></tr></thead>
      <tbody id="rtbody"></tbody>
    </table>
  </div>

  <!-- Session history -->
  <div class="card wide">
    <h2>Crawl History</h2>
    <table>
      <thead><tr><th>#</th><th>Origin</th><th>Depth</th><th>Started</th><th>Duration</th><th>Pages</th><th>Processed</th><th>Failed</th><th>Status</th></tr></thead>
      <tbody id="stbody"></tbody>
    </table>
  </div>

</div>
<script>
let maxQ=500;

async function startCrawl(){
  const url=document.getElementById('iurl').value.trim();
  const depth=parseInt(document.getElementById('idepth').value)||2;
  const workers=parseInt(document.getElementById('iworkers').value)||8;
  const rate=parseFloat(document.getElementById('irate').value)||10;
  maxQ=parseInt(document.getElementById('iqueue').value)||500;
  if(!url){showMsg('crawl-msg','URL is required','err');return;}
  document.getElementById('start-btn').disabled=true;
  try{
    const r=await fetch('/api/index',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url,depth,workers,rate,max_queue:maxQ})});
    const d=await r.json();
    if(d.error){showMsg('crawl-msg',d.error,'err');document.getElementById('start-btn').disabled=false;}
    else showMsg('crawl-msg','Crawl started: '+url+' (depth='+depth+')','ok');
  }catch(e){showMsg('crawl-msg','Request failed','err');document.getElementById('start-btn').disabled=false;}
}

async function doSearch(){
  const q=document.getElementById('sq').value.trim();
  if(!q)return;
  document.getElementById('smsg').innerHTML='';
  document.getElementById('results').innerHTML='<div style="color:#666;font-size:.85rem;margin-top:.5rem">Searching...</div>';
  try{
    const r=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:q,limit:20})});
    const d=await r.json();
    if(!d.results||d.results.length===0){
      document.getElementById('results').innerHTML='<div style="color:#666;font-size:.85rem;margin-top:.75rem">No results found.</div>';
      return;
    }
    document.getElementById('results').innerHTML=
      '<div style="font-size:.75rem;color:#666;margin-top:.75rem">'+d.total+' result(s) for "'+d.query+'"</div>'+
      d.results.map(r=>`<div class="result"><div class="url"><a href="${r.url}" target="_blank">${r.url}</a></div>`+
        `<div class="meta">origin: ${r.origin} &nbsp;&middot;&nbsp; depth: ${r.depth}</div></div>`).join('');
  }catch(e){document.getElementById('results').innerHTML='';showMsg('smsg','Search failed','err');}
}

async function refreshStats(){
  try{
    const s=await (await fetch('/api/stats')).json();
    document.getElementById('s-proc').textContent=s.urls_processed||0;
    document.getElementById('s-idx').textContent=s.pages_indexed||0;
    document.getElementById('s-words').textContent=(s.words_indexed||0).toLocaleString();
    document.getElementById('s-q').textContent=s.queue_depth||0;
    document.getElementById('s-fail').textContent=s.urls_failed||0;
    document.getElementById('s-drop').textContent=s.urls_dropped_backpressure||0;
    const btn=document.getElementById('start-btn');
    const sb=document.getElementById('sbadge');
    if(s.active){sb.textContent='● ACTIVE';sb.className='badge b-active';btn.disabled=true;btn.textContent='Crawling...';}
    else{sb.textContent='■ IDLE';sb.className='badge b-idle';btn.disabled=false;btn.textContent='Start Crawl';}
    document.getElementById('elapsed').textContent=s.elapsed_s?s.elapsed_s+'s elapsed':'';
    document.getElementById('tbadge').innerHTML=s.throttled?'<span class="badge b-throttled">⚠ THROTTLED</span>':'';
    const pct=maxQ>0?Math.min(100,((s.queue_depth||0)/maxQ)*100):0;
    document.getElementById('qbar').style.width=pct+'%';
  }catch(e){}
}

async function refreshRecent(){
  try{
    const pages=await (await fetch('/api/recent')).json();
    const tb=document.getElementById('rtbody');
    if(!pages||pages.length===0){tb.innerHTML='<tr><td colspan="4" style="color:#555;text-align:center;padding:.75rem">No pages indexed yet</td></tr>';return;}
    tb.innerHTML=pages.map(p=>`<tr><td><a href="${p.url}" target="_blank">${p.url}</a></td>`+
      `<td style="color:#666">${p.origin}</td><td style="text-align:center">${p.depth}</td>`+
      `<td style="color:#666">${new Date(p.indexed_at*1000).toLocaleTimeString()}</td></tr>`).join('');
  }catch(e){}
}

function showMsg(id,txt,cls){
  document.getElementById(id).innerHTML='<div class="msg '+cls+'">'+txt+'</div>';
  setTimeout(()=>{document.getElementById(id).innerHTML='';},5000);
}

async function refreshSessions(){
  try{
    const sessions=await (await fetch('/api/sessions')).json();
    const tb=document.getElementById('stbody');
    if(!sessions||sessions.length===0){
      tb.innerHTML='<tr><td colspan="9" style="color:#555;text-align:center;padding:.75rem">No crawl sessions yet</td></tr>';return;
    }
    tb.innerHTML=sessions.map(s=>{
      const started=new Date(s.started_at*1000).toLocaleString();
      const dur=s.finished_at?((s.finished_at-s.started_at).toFixed(1)+'s'):'running';
      const badge=s.status==='running'?'<span class="badge b-active">running</span>':'<span class="badge b-idle">done</span>';
      return `<tr><td style="color:#555">${s.id}</td><td><a href="${s.origin}" target="_blank">${s.origin}</a></td>`+
        `<td style="text-align:center">${s.depth}</td><td style="color:#666">${started}</td>`+
        `<td style="color:#666">${dur}</td><td style="color:#7c6af7">${s.pages_indexed??'—'}</td>`+
        `<td>${s.urls_processed??'—'}</td><td style="color:#f66">${s.urls_failed??'—'}</td><td>${badge}</td></tr>`;
    }).join('');
  }catch(e){}
}

setInterval(refreshStats,1000);
setInterval(refreshRecent,3000);
setInterval(refreshSessions,5000);
refreshStats();refreshRecent();refreshSessions();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    # Shared state injected by WebServer.start()
    index_store = None
    crawler_instance = None
    crawler_lock = threading.Lock()
    max_queue = 500

    def log_message(self, fmt, *args):
        pass  # suppress default access log noise

    # ── Routing ──────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(_HTML)
        elif path == "/api/stats":
            self._send_json(self._stats())
        elif path == "/api/recent":
            self._send_json(self._recent())
        elif path == "/api/sessions":
            self._send_json(self._sessions())
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()
        if path == "/api/index":
            self._send_json(self._start_index(body))
        elif path == "/api/search":
            self._send_json(self._search(body))
        else:
            self._send_json({"error": "not found"}, 404)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def _send_html(self, content: str, status: int = 200):
        enc = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(enc)))
        self.end_headers()
        self.wfile.write(enc)

    def _send_json(self, data, status: int = 200):
        enc = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(enc)))
        self.end_headers()
        self.wfile.write(enc)

    # ── API implementations ───────────────────────────────────────────────────

    def _stats(self) -> dict:
        c = _Handler.crawler_instance
        idx = _Handler.index_store
        base = c.stats.snapshot() if c else {
            "active": False, "urls_processed": 0, "urls_failed": 0,
            "urls_dropped_backpressure": 0, "queue_depth": 0,
            "throttled": False, "elapsed_s": 0,
        }
        base["pages_indexed"] = idx.page_count() if idx else 0
        base["words_indexed"] = idx.word_count() if idx else 0
        return base

    def _recent(self) -> list:
        idx = _Handler.index_store
        return idx.recent_pages(limit=10) if idx else []

    def _sessions(self) -> list:
        from storage.database import DB_PATH, SessionDB
        return SessionDB(path=DB_PATH).list_sessions(limit=20)

    def _start_index(self, body: dict) -> dict:
        from crawler.engine import Crawler
        from storage.database import DB_PATH

        url = body.get("url", "").strip()
        if not url:
            return {"error": "url is required"}

        depth = int(body.get("depth", 2))
        workers = int(body.get("workers", 8))
        rate = float(body.get("rate", 10.0))
        max_queue = int(body.get("max_queue", 500))
        _Handler.max_queue = max_queue

        with _Handler.crawler_lock:
            if _Handler.crawler_instance and _Handler.crawler_instance.is_active():
                return {"error": "A crawl is already active"}

            c = Crawler(
                index=_Handler.index_store,
                max_workers=workers,
                max_queue=max_queue,
                rate=rate,
                db_path=DB_PATH,
            )
            c.start(url, depth)
            _Handler.crawler_instance = c

        return {"ok": True, "url": url, "depth": depth}

    def _search(self, body: dict) -> dict:
        query = body.get("query", "").strip()
        limit = int(body.get("limit", 20))

        if not query:
            return {"results": [], "error": "query is required"}

        idx = _Handler.index_store
        if not idx:
            return {"query": query, "total": 0, "results": []}

        all_results = idx.search(query)
        return {
            "query": query,
            "total": len(all_results),
            "results": [
                {"url": u, "origin": o, "depth": d}
                for u, o, d in all_results[:limit]
            ],
        }


# ---------------------------------------------------------------------------
# WebServer
# ---------------------------------------------------------------------------

class WebServer:
    """
    Thin wrapper around ThreadingHTTPServer.

    ThreadingHTTPServer handles each HTTP request in a separate thread,
    so the dashboard's polling never blocks active crawl workers.
    """

    def __init__(self, index_store, host: str = "localhost", port: int = 8080):
        _Handler.index_store = index_store
        _Handler.crawler_instance = None
        self._host = host
        self._port = port
        self._server: Optional[ThreadingHTTPServer] = None

    def start(self) -> None:
        self._server = ThreadingHTTPServer((self._host, self._port), _Handler)
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()
        print(f"  Web UI  ->  http://{self._host}:{self._port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
