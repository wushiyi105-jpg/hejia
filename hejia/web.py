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
<title>核价 · 这轮多花在哪</title>
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

.prod{display:block;font-size:11px;line-height:1.4;letter-spacing:.18em;font-weight:650;margin-bottom:8px;opacity:.72}
.lede{max-width:62ch;line-height:1.75}
.route{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin:0 0 20px;border:1px solid var(--line);background:var(--line)}
.route span{padding:11px 13px;background:var(--card);font-size:12px;line-height:1.5}
.route b{display:block;font-size:10px;letter-spacing:.1em;margin-bottom:3px;opacity:.66}
button{min-height:46px}
input,select{min-height:44px}
@media(max-width:680px){
  .wrap{padding:20px 16px 56px}
  .route{grid-template-columns:1fr}
  header h1{font-size:30px!important}
  .row>div{min-width:100%!important}
  button{width:100%}
}

body{background:#fbf6eb;color:#29302e;font-family:"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:980px}
header{padding:8px 0 22px;border-bottom:1px solid #cfc2aa;margin-bottom:20px}
header h1{font-family:"Songti SC","SimSun",Georgia,serif;font-size:38px;line-height:1.24;letter-spacing:-.01em}
header p{color:#6b6255;font-size:14px}
.card{background:#fffdf8;border:1px solid #d9cebb;border-top:3px solid #29302e;border-radius:1px;box-shadow:none}
button{background:#29302e;border-radius:1px;letter-spacing:.05em}
button:hover{background:#3d4b47}
textarea,input,select{background:#fffdfa;border-color:#d5c9b4;border-radius:1px}
textarea:focus,input:focus,select:focus{border-color:#b23b2a;box-shadow:0 0 0 2px #ead8d1}
.item{border-left:3px solid #b23b2a;background:#fffaf5}
.item.low{border-left-color:#d9cebb}
.cost .cell,.cell{border-color:#d9cebb;border-radius:1px}
h3{color:#8d3526;letter-spacing:.08em}


/* palette-normalized */
:root{--bg:#fbf6eb;--card:#fffdf8;--ink:#29302e;--text:#29302e;--dim:#6b6255;--line:#d9cebb;--accent:#b23b2a}

/* polish-batch1 */
button.ghost,button.secondary{background:transparent!important;color:#b23b2a!important;border:1px solid #d9cebb!important}

/* mobile-32 */

@media(max-width:760px){
  main{grid-template-columns:1fr!important}
  aside{border-right:0!important;border-bottom:1px solid #d9cebb;width:auto!important}
  section{padding:16px!important}
  .row{flex-wrap:wrap!important}
  .row>div{min-width:100%!important}
  h1{font-size:30px!important}
  .route{grid-template-columns:1fr!important}
  button{min-height:48px}
  pre{overflow-x:auto}
}

/* mobile-height */
@media(max-width:760px){main{min-height:auto!important}aside{min-height:0!important}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="prod">核价</span>这份报价，哪些钱不该花 <span class="badge" id="badge">…</span></h1>
    <p class="lede">给第一次装修的业主：把两家报价按工序、面积和计量单位对齐，复算金额，挑出重复项、合同外项目和待问项。</p>
  </header>
  <div class="route" aria-label="任务步骤"><span><b>01</b>贴两家报价</span><span><b>02</b>对齐工序复算</span><span><b>03</b>生成询价问题单</span></div>

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
    h+='<p style="line-height:1.7">'+esc(r.verdict||'')+'</p>';
    h+='<div class="hint" style="margin-bottom:10px">合计 '+(r.summary.total||0)+' 元'+
       (r.summary.per_sqm?' · '+r.summary.per_sqm+' 元/㎡':'')+'</div>';
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
