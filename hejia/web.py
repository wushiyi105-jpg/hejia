"""Web 入口:零依赖 http.server,单页 + JSON API。"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import agent, llm, rules
from . import db as dbmod

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>核价 · 装修报价核查</title>
<style>
  :root{--bg:#f5f7fa;--card:#fff;--ink:#1f2937;--muted:#6b7280;--blue:#0f766e;--soft:#ccfbf1;
        --amber:#f59e0b;--line:#e5e7eb;--radius:16px}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink)}
  .wrap{max-width:920px;margin:0 auto;padding:32px 20px 80px}
  h1{font-size:26px;margin:0 0 4px} header p{color:var(--muted);margin:0 0 22px}
  .badge{display:inline-block;font-size:12px;padding:3px 10px;border-radius:999px;background:var(--soft);color:var(--blue);margin-left:8px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
  label{display:block;font-size:13px;color:var(--muted);margin:0 0 6px}
  textarea,input,select{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:12px;font-size:14px;font-family:inherit;background:#fff}
  textarea{font-family:ui-monospace,Consolas,monospace;line-height:1.7}
  textarea:focus,input:focus,select:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--soft)}
  .row{display:flex;gap:12px;flex-wrap:wrap}.row>div{flex:1;min-width:150px}
  button{background:var(--blue);color:#fff;border:none;padding:12px 22px;border-radius:12px;font-size:15px;cursor:pointer}
  button:hover{filter:brightness(1.08)}
  .hint{color:var(--muted);font-size:12px;margin-top:8px}
  .spin{display:inline-block;width:16px;height:16px;border:2px solid #fff;border-top-color:transparent;border-radius:50%;animation:sp .7s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}
  .result{display:none}.result.show{display:block}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:600}
  .bad{color:#b91c1c}.ok{color:#15803d}
  .tag{display:inline-block;font-size:11px;padding:1px 8px;border-radius:6px;background:var(--soft);color:var(--blue);margin-right:6px}
  .item{border-left:3px solid var(--amber);padding:6px 0 6px 12px;margin:8px 0;font-size:14px}
  .item p{margin:2px 0}
  .q{background:#f9fafb;border-radius:10px;padding:10px 12px;margin:8px 0;font-size:14px}
  h3{font-size:15px;color:var(--muted);margin:18px 0 8px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>核价 · 装修报价核查<span class="badge" id="badge">…</span></h1>
    <p>把报价单粘进来,逐行复算、查出重复与漏项,再告诉你该问施工方什么。</p>
  </header>
  <div class="card">
    <label>报价单(每行:项目 单位 数量 单价 小计)</label>
    <textarea id="text" rows="9" placeholder="拆除墙体 ㎡ 12 45 540&#10;卫生间防水 ㎡ 8 55 440&#10;墙砖铺贴 ㎡ 25 65 1625"></textarea>
    <div class="row" style="margin-top:12px">
      <div><label>城市(单价系数)</label><select id="city">
        <option value="">不限</option><option>北京</option><option>上海</option><option>深圳</option>
        <option>广州</option><option>杭州</option><option>南京</option><option>成都</option>
        <option>武汉</option><option>西安</option><option>重庆</option></select></div>
      <div><label>建筑面积(㎡,可选)</label><input type="number" id="area" placeholder="例:89"></div>
    </div>
    <div style="margin-top:16px"><button id="btn">开始核查</button></div>
    <div class="hint">复算、对标、漏项与重复都在本地算;模型只写问题清单,不允许改写金额。</div>
  </div>
  <div class="result" id="res"></div>
</div>
<script>
const $=s=>document.querySelector(s);
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function load(btn,on){btn.disabled=on;if(on){btn.dataset.label=btn.dataset.label||btn.textContent.trim();btn.innerHTML='<span class="spin"></span>';}else{btn.innerHTML=btn.dataset.label||btn.textContent;}}
$('#btn').onclick=async()=>{
  const el=$('#res');el.classList.remove('show');load($('#btn'),true);
  try{
    const p=await fetch('/api/audit',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:$('#text').value,city:$('#city').value,area:$('#area').value})});
    const r=await p.json(); if(r.error) throw new Error(r.error);
    let h='<div class="card"><div class="hint">'+(r.mode==='model'?'模型已连接':'离线模式')+(r.saved_id?' · 已入库 #'+r.saved_id:'')+'</div>';
    h+='<p style="line-height:1.7">'+esc(r.summary)+'</p>';
    h+='<table><tr><th>#</th><th>项目</th><th>数量×单价</th><th>小计</th><th>工序</th></tr>';
    r.lines.filter(x=>x.ok).forEach(x=>{
      h+='<tr><td>'+x.line_no+'</td><td>'+esc(x.name)+'</td><td>'+x.qty+x.unit+' × '+x.price+'</td>'+
         '<td class="'+(x.flag?'bad':'ok')+'">'+x.subtotal+(x.flag?' ⚠️':'')+'</td><td><span class="tag">'+esc(x.process)+'</span></td></tr>';
    });
    h+='</table>';
    if(r.summary.by_process.length){h+='<h3>按工序</h3>';
      r.summary.by_process.forEach(p=>h+='<div>'+esc(p.process)+':'+p.amount+' 元('+p.share+'%)</div>');}
    if(r.issues.length){h+='<h3>疑点 '+r.issues.length+'</h3>';
      r.issues.forEach(i=>h+='<div class="item"><p><b>['+esc(i.kind)+']</b> '+esc(i.detail)+'</p><p class="hint">'+esc(i.raw)+'</p></div>');}
    if(r.questions.length){h+='<h3>要问施工方</h3>';
      r.questions.forEach(q=>h+='<div class="q">「'+esc(q.quote)+'」→ '+esc(q.question)+'</div>');}
    if(r.risks.length){h+='<h3>结算风险</h3><ul>';r.risks.forEach(x=>h+='<li>'+esc(x)+'</li>');h+='</ul>';}
    h+='</div>'; el.innerHTML=h;
  }catch(e){el.innerHTML='<div class="card" style="color:#b91c1c">请求失败:'+esc(e.message)+'</div>';}
  el.classList.add('show');load($('#btn'),false);
};
fetch('/api/status').then(r=>r.json()).then(s=>{const b=$('#badge');
  if(s.mock){b.textContent='离线模式';b.style.background='#fee2e2';b.style.color='#b91c1c';}
  else{b.textContent=s.model||'模型已连接';b.style.background='#dcfce7';b.style.color='#15803d';}
}).catch(()=>{});
</script>
</body></html>
"""


def _handler(db, cfg, force_mock):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body, ctype, status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=200):
            self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", status)

        def _read(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
            return json.loads(text) if text else {}

        def do_GET(self):
            if urlparse(self.path).path in ("/", "/index.html"):
                self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif urlparse(self.path).path == "/api/status":
                mock = force_mock or not cfg.get("api_key")
                self._json({"mock": mock, "model": None if mock else cfg.get("model")})
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if urlparse(self.path).path != "/api/audit":
                self._json({"error": "not found"}, 404)
                return
            try:
                body = self._read()
                area = body.get("area")
                area = float(area) if area not in (None, "", "null") else None
                r = agent.audit(body.get("text", ""), city=body.get("city"), area=area,
                                config=cfg, db=db, force_mock=force_mock, save=True)
                self._json(r)
            except llm.LLMError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 500)

        def log_message(self, *args):
            pass

    return Handler


def serve(host="127.0.0.1", port=8000, db_path=None, force_mock=False):
    db = dbmod.Database(db_path)
    rules.load_seed("prices.json")
    cfg = llm.default_config()
    httpd = ThreadingHTTPServer((host, port), _handler(db, cfg, force_mock))
    mode = "离线模式(未配置 key)" if (force_mock or not cfg.get("api_key")) else f"模型:{cfg.get('model')}"
    print(f"🧮 核价已启动:http://{host}:{port}  [{mode}]")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
