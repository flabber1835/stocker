import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

API_URL = os.getenv("API_URL", "http://api:8000")

app = FastAPI(title="stocker-dashboard")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "dashboard"}


async def _proxy(path: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{API_URL}{path}", params=params or {})
        return JSONResponse(content=r.json(), status_code=r.status_code)


@app.get("/api/regime")
async def proxy_regime():
    return await _proxy("/regime")


@app.get("/api/rankings")
async def proxy_rankings(limit: int = 500):
    return await _proxy("/rankings", {"limit": limit})


@app.get("/api/universe")
async def proxy_universe():
    return await _proxy("/universe")


@app.get("/api/factor-runs")
async def proxy_factor_runs(limit: int = 20):
    return await _proxy("/factor-runs", {"limit": limit})


@app.get("/api/ranking-runs")
async def proxy_ranking_runs(limit: int = 20):
    return await _proxy("/ranking-runs", {"limit": limit})


@app.get("/api/ingest-runs")
async def proxy_ingest_runs(limit: int = 20):
    return await _proxy("/ingest-runs", {"limit": limit})


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=_HTML)


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STOCKER // GRID</title>
<style>
:root {
  --bg: #020c18;
  --panel: #040f1f;
  --panel2: #071525;
  --cyan: #00e5ff;
  --cyan-dim: #007a8c;
  --cyan-faint: rgba(0,229,255,0.06);
  --orange: #ff6a00;
  --orange-dim: rgba(255,106,0,0.7);
  --white: #e6f3ff;
  --green: #00ff9d;
  --red: #ff4d6a;
  --yellow: #ffd060;
  --muted: #5aabca;
  --border: rgba(0,229,255,0.18);
  --border-strong: rgba(0,229,255,0.45);
  --glow-sm: 0 0 8px rgba(0,229,255,0.5);
  --glow-md: 0 0 14px rgba(0,229,255,0.6), 0 0 28px rgba(0,229,255,0.25);
  --glow-lg: 0 0 20px rgba(0,229,255,0.8), 0 0 40px rgba(0,229,255,0.35);
  --glow-orange: 0 0 12px rgba(255,106,0,0.7), 0 0 24px rgba(255,106,0,0.3);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow-x:hidden}
body{
  background:var(--bg);
  color:var(--white);
  font-family:'Courier New',Courier,monospace;
  font-size:13px;
  line-height:1.5;
}
body::before{
  content:'';
  position:fixed;inset:0;
  background-image:
    linear-gradient(rgba(0,229,255,0.025) 1px,transparent 1px),
    linear-gradient(90deg,rgba(0,229,255,0.025) 1px,transparent 1px);
  background-size:48px 48px;
  pointer-events:none;z-index:0;
}
body::after{
  content:'';
  position:fixed;inset:0;
  background:repeating-linear-gradient(
    0deg,transparent,transparent 3px,
    rgba(0,0,0,0.08) 3px,rgba(0,0,0,0.08) 4px
  );
  pointer-events:none;z-index:9999;
}
.c{position:fixed;width:28px;height:28px;z-index:100}
.c.tl{top:12px;left:12px;border-top:2px solid var(--cyan);border-left:2px solid var(--cyan)}
.c.tr{top:12px;right:12px;border-top:2px solid var(--cyan);border-right:2px solid var(--cyan)}
.c.bl{bottom:12px;left:12px;border-bottom:2px solid var(--cyan);border-left:2px solid var(--cyan)}
.c.br{bottom:12px;right:12px;border-bottom:2px solid var(--cyan);border-right:2px solid var(--cyan)}
.wrap{position:relative;z-index:1;max-width:1500px;margin:0 auto;padding:20px 28px}
header{
  text-align:center;
  padding:32px 0 22px;
  margin-bottom:22px;
  border-bottom:1px solid var(--border);
  position:relative;
}
header::before,header::after{
  content:'';
  position:absolute;bottom:0;
  height:1px;width:30%;
  background:linear-gradient(90deg,transparent,var(--cyan));
}
header::before{left:0}
header::after{right:0;background:linear-gradient(270deg,transparent,var(--cyan))}
.logo{
  font-size:2.8rem;font-weight:700;
  letter-spacing:.55em;
  color:var(--cyan);
  text-shadow:var(--glow-lg);
  text-transform:uppercase;
}
.logo em{color:var(--orange);font-style:normal;text-shadow:var(--glow-orange)}
.sub{
  font-size:.65rem;letter-spacing:.35em;
  color:var(--muted);margin-top:6px;
  text-transform:uppercase;
}
#regime-bar{
  display:flex;flex-wrap:wrap;align-items:center;gap:6px 24px;
  background:var(--panel);
  border:1px solid var(--border);
  border-left:3px solid var(--cyan);
  padding:11px 20px;
  margin-bottom:20px;
  font-size:.78rem;
}
.rb-label{color:var(--muted);letter-spacing:.15em;text-transform:uppercase;font-weight:600}
.rb-val{color:var(--cyan);font-weight:700;text-shadow:var(--glow-sm);letter-spacing:.08em}
.rb-sep{color:var(--border-strong)}
.rb-metric{color:var(--muted)}
.rb-metric span{color:var(--white);font-weight:600}
.rb-badge{
  padding:2px 12px;
  border:1px solid currentColor;
  font-size:.7rem;letter-spacing:.12em;
  text-transform:uppercase;
  font-weight:700;
}
.regime-bull_calm   {color:#00ff9d;text-shadow:0 0 10px #00ff9d80}
.regime-bull_volatile{color:#ffd060;text-shadow:0 0 10px #ffd06080}
.regime-bear_calm   {color:#00aaff;text-shadow:0 0 10px #00aaff80}
.regime-bear_volatile{color:#ff4d6a;text-shadow:0 0 10px #ff4d6a80}
.tabs{
  display:flex;gap:3px;
  margin-bottom:20px;
  border-bottom:1px solid var(--border);
}
.tab{
  padding:10px 32px;cursor:pointer;
  font-family:inherit;font-size:.75rem;
  letter-spacing:.22em;text-transform:uppercase;
  background:transparent;border:none;color:var(--muted);
  border-bottom:2px solid transparent;
  transition:color .2s,border-color .2s,background .2s;
  position:relative;bottom:-1px;
}
.tab:hover{color:var(--cyan)}
.tab.active{
  color:var(--cyan);text-shadow:var(--glow-sm);
  border-bottom:2px solid var(--cyan);
  background:rgba(0,229,255,0.05);
}
.pane{display:none}.pane.active{display:block}
.stats{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap}
.stat{
  background:var(--panel);
  border:1px solid var(--border);
  padding:14px 22px;
  flex:1;min-width:140px;
}
.stat .lbl{
  font-size:.65rem;color:var(--muted);
  letter-spacing:.2em;text-transform:uppercase;margin-bottom:5px;
  font-weight:600;
}
.stat .val{
  font-size:1.7rem;font-weight:700;
  color:var(--cyan);text-shadow:var(--glow-sm);
}
.stat .val.orange{color:var(--orange);text-shadow:var(--glow-orange)}
.stat .val.green{color:var(--green)}
.stat .val.red{color:var(--red)}
.toolbar{display:flex;gap:10px;margin-bottom:14px;align-items:center;flex-wrap:wrap}
input[type=search]{
  background:var(--panel);
  border:1px solid var(--border);
  color:var(--cyan);
  font-family:inherit;font-size:.8rem;
  padding:8px 14px;outline:none;
  width:260px;letter-spacing:.04em;
  transition:border-color .2s,box-shadow .2s;
}
input[type=search]:focus{border-color:var(--cyan);box-shadow:var(--glow-sm)}
input[type=search]::placeholder{color:var(--muted)}
select{
  background:var(--panel);
  border:1px solid var(--border);
  color:var(--cyan);
  font-family:inherit;font-size:.78rem;
  padding:8px 12px;outline:none;cursor:pointer;
}
select option{background:var(--panel2)}
.btn{
  background:transparent;
  border:1px solid var(--border);
  color:var(--muted);
  font-family:inherit;font-size:.72rem;
  letter-spacing:.15em;padding:8px 16px;
  cursor:pointer;transition:all .2s;
  text-transform:uppercase;
}
.btn:hover{border-color:var(--cyan);color:var(--cyan);box-shadow:var(--glow-sm)}
.badge-count{
  margin-left:auto;font-size:.7rem;
  color:var(--muted);letter-spacing:.1em;
}
.tbl-wrap{
  overflow-x:auto;
  border:1px solid var(--border);
  max-height:68vh;
  overflow-y:auto;
}
table{width:100%;border-collapse:collapse}
thead{position:sticky;top:0;z-index:10}
thead tr{background:#071828;border-bottom:2px solid var(--cyan-dim)}
th{
  padding:11px 14px;text-align:left;
  color:var(--cyan);font-weight:600;
  letter-spacing:.16em;text-transform:uppercase;
  font-size:.67rem;cursor:pointer;
  user-select:none;white-space:nowrap;
  transition:background .15s;
}
th:hover{background:rgba(0,229,255,0.1)}
th.asc::after{content:' \25b2';color:var(--orange)}
th.desc::after{content:' \25bc';color:var(--orange)}
tbody tr{border-bottom:1px solid rgba(0,229,255,0.13);transition:background .12s}
tbody tr:hover{background:rgba(0,229,255,0.08)}
td{padding:9px 14px;white-space:nowrap}
.t-ticker{
  color:var(--cyan);font-weight:700;
  text-shadow:0 0 8px rgba(0,229,255,0.4);
  letter-spacing:.06em;
}
.t-rank{
  color:var(--orange);font-weight:700;
  text-shadow:0 0 8px rgba(255,106,0,0.4);
  min-width:36px;display:inline-block;text-align:right;
}
.t-name{color:#9fd4e8;font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis}
.t-sector{
  display:inline-block;padding:2px 8px;
  font-size:.66rem;border:1px solid rgba(0,229,255,0.25);
  color:var(--muted);letter-spacing:.05em;
}
.t-wt{color:#7dc4db;font-size:.78rem}
.pos{color:var(--green)}
.neg{color:var(--red)}
.neu{color:var(--muted)}
.score-wrap{display:flex;align-items:center;gap:8px;min-width:120px}
.score-num{min-width:42px;text-align:right;font-size:.82rem}
.score-track{
  flex:1;height:5px;
  background:rgba(0,229,255,0.12);
  position:relative;overflow:hidden;
}
.score-fill{
  height:100%;
  background:linear-gradient(90deg,var(--cyan-dim),var(--cyan));
  box-shadow:0 0 6px var(--cyan);
  transition:width .4s ease;
}
.fbars{display:flex;gap:2px;align-items:flex-end;height:22px}
.fbar{
  width:9px;background:rgba(0,229,255,0.25);
  cursor:help;position:relative;transition:background .15s;
}
.fbar:hover{background:var(--cyan)}
.fbar::after{
  content:attr(data-tip);
  position:absolute;bottom:calc(100% + 4px);left:50%;
  transform:translateX(-50%);
  background:var(--panel2);
  border:1px solid var(--border);
  padding:4px 8px;font-size:.65rem;
  color:var(--cyan);white-space:nowrap;
  pointer-events:none;opacity:0;transition:opacity .15s;z-index:50;
}
.fbar:hover::after{opacity:1}
.pct-pill{
  display:inline-flex;align-items:center;justify-content:center;
  width:44px;height:20px;
  font-size:.7rem;font-weight:700;
  border:1px solid currentColor;
}
.loading,.error{
  text-align:center;padding:64px 20px;
  font-size:.82rem;letter-spacing:.2em;
}
.loading{color:var(--muted);animation:pulse 1.4s infinite}
.loading::before{content:'// ';color:var(--cyan)}
.error{color:var(--red)}
.error::before{content:'!! ';color:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes spin{to{transform:rotate(360deg)}}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--cyan-dim)}

/* ── Runs tab ── */
.run-badge{
  display:inline-block;padding:2px 10px;
  font-size:.65rem;font-weight:700;
  letter-spacing:.12em;text-transform:uppercase;
  border:1px solid currentColor;
}
.badge-ingest {color:#b060ff;border-color:#b060ff40}
.badge-factors{color:var(--cyan);border-color:rgba(0,229,255,0.4)}
.badge-rank   {color:var(--orange);border-color:rgba(255,106,0,0.4)}
.status-success{color:var(--green)}
.status-failed {color:var(--red)}
.status-running{color:var(--yellow);animation:pulse 1.4s infinite}
.status-skipped{color:var(--muted)}
.run-detail{color:var(--white);font-size:.78rem}
.run-time{color:var(--muted);font-size:.75rem}
.run-dur {color:var(--muted);font-size:.75rem}
.autorefresh-indicator{
  font-size:.65rem;color:var(--muted);letter-spacing:.1em;
  display:flex;align-items:center;gap:6px;
}
.spinner{
  width:8px;height:8px;
  border:1px solid var(--cyan-dim);
  border-top-color:var(--cyan);
  border-radius:50%;
  animation:spin 1s linear infinite;
  display:inline-block;
}

footer{
  text-align:center;
  padding:20px 0;
  margin-top:20px;
  border-top:1px solid var(--border);
  color:var(--muted);
  font-size:.65rem;letter-spacing:.2em;
  text-transform:uppercase;
}
footer span{color:var(--cyan)}
</style>
</head>
<body>
<div class="c tl"></div><div class="c tr"></div>
<div class="c bl"></div><div class="c br"></div>

<div class="wrap">

<header>
  <div class="logo">S<em>T</em>OCKER</div>
  <div class="sub">grid // quantitative equity research system</div>
</header>

<div id="regime-bar">
  <span class="rb-label">MARKET REGIME</span>
  <span class="rb-sep">//</span>
  <span id="rb-regime" class="rb-val rb-badge">LOADING</span>
  <span class="rb-sep">//</span>
  <span class="rb-metric">SPY <span id="rb-spy">&#8212;</span></span>
  <span class="rb-metric">vs SMA200 <span id="rb-sma">&#8212;</span></span>
  <span class="rb-metric">RVOL20 <span id="rb-vol">&#8212;</span></span>
  <span style="margin-left:auto;font-size:.68rem;color:var(--muted)" id="rb-ts">&#8212;</span>
</div>

<div class="tabs">
  <button class="tab active" onclick="switchTab('rankings',this)">Rankings</button>
  <button class="tab" onclick="switchTab('universe',this)">Universe</button>
  <button class="tab" onclick="switchTab('runs',this)">Pipeline Runs</button>
</div>

<!-- Rankings pane -->
<div id="pane-rankings" class="pane active">
  <div class="stats">
    <div class="stat"><div class="lbl">Total Ranked</div><div class="val" id="r-total">&#8212;</div></div>
    <div class="stat"><div class="lbl">Top Score</div><div class="val" id="r-top">&#8212;</div></div>
    <div class="stat"><div class="lbl">Regime</div><div class="val orange" id="r-regime">&#8212;</div></div>
    <div class="stat"><div class="lbl">Rank Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="r-date">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="r-search" placeholder="// FILTER TICKER" oninput="renderRankings()">
    <button class="btn" onclick="loadRankings()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="r-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortRankings('rank')" id="rh-rank">RANK</th>
          <th onclick="sortRankings('ticker')" id="rh-ticker">TICKER</th>
          <th onclick="sortRankings('composite_score')" id="rh-composite_score">COMPOSITE</th>
          <th onclick="sortRankings('percentile')" id="rh-percentile">PCTILE</th>
          <th>FACTORS</th>
          <th onclick="sortRankings('momentum')" id="rh-momentum">MOM</th>
          <th onclick="sortRankings('quality')" id="rh-quality">QLTY</th>
          <th onclick="sortRankings('value')" id="rh-value">VAL</th>
          <th onclick="sortRankings('growth')" id="rh-growth">GRTH</th>
          <th onclick="sortRankings('low_volatility')" id="rh-low_volatility">LOVOL</th>
          <th onclick="sortRankings('liquidity')" id="rh-liquidity">LIQ</th>
        </tr>
      </thead>
      <tbody id="r-body">
        <tr><td colspan="11" class="loading">LOADING RANKINGS</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Universe pane -->
<div id="pane-universe" class="pane">
  <div class="stats">
    <div class="stat"><div class="lbl">Total Tickers</div><div class="val" id="u-total">&#8212;</div></div>
    <div class="stat"><div class="lbl">Sectors</div><div class="val" id="u-sectors">&#8212;</div></div>
    <div class="stat"><div class="lbl">ETF Source</div><div class="val" style="font-size:1.1rem;padding-top:6px" id="u-etf">&#8212;</div></div>
    <div class="stat"><div class="lbl">Snapshot Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="u-date">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="u-search" placeholder="// FILTER TICKER OR NAME" oninput="renderUniverse()">
    <select id="u-sector" onchange="renderUniverse()"><option value="">ALL SECTORS</option></select>
    <button class="btn" onclick="loadUniverse()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="u-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortUniverse('ticker')" id="uh-ticker">TICKER</th>
          <th onclick="sortUniverse('name')" id="uh-name">NAME</th>
          <th onclick="sortUniverse('sector')" id="uh-sector">SECTOR</th>
          <th onclick="sortUniverse('weight_pct')" id="uh-weight_pct">WEIGHT %</th>
        </tr>
      </thead>
      <tbody id="u-body">
        <tr><td colspan="4" class="loading">LOADING UNIVERSE</td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- Pipeline Runs pane -->
<div id="pane-runs" class="pane">
  <div class="stats">
    <div class="stat">
      <div class="lbl">Last Ingest</div>
      <div class="val green" style="font-size:.85rem;padding-top:4px" id="run-last-ingest">&#8212;</div>
    </div>
    <div class="stat">
      <div class="lbl">Last Factors</div>
      <div class="val green" style="font-size:.85rem;padding-top:4px" id="run-last-factors">&#8212;</div>
    </div>
    <div class="stat">
      <div class="lbl">Last Rank</div>
      <div class="val green" style="font-size:.85rem;padding-top:4px" id="run-last-rank">&#8212;</div>
    </div>
    <div class="stat">
      <div class="lbl">System</div>
      <div class="val" id="run-system">STANDBY</div>
    </div>
  </div>
  <div class="toolbar">
    <button class="btn" onclick="loadRuns()">&#x21BA; REFRESH</button>
    <div class="autorefresh-indicator"><span class="spinner"></span>&nbsp;AUTO-REFRESH 30s</div>
    <span class="badge-count" id="run-count"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>TIME</th>
          <th>SERVICE</th>
          <th>JOB</th>
          <th>STATUS</th>
          <th>DETAIL</th>
          <th>DURATION</th>
        </tr>
      </thead>
      <tbody id="run-body">
        <tr><td colspan="6" class="loading">LOADING PIPELINE RUNS</td></tr>
      </tbody>
    </table>
  </div>
</div>

<footer>STOCKER // GRID &nbsp;<span>v0.1</span> &nbsp;//&nbsp; PAPER TRADING ONLY &nbsp;//&nbsp; NOT FINANCIAL ADVICE</footer>
</div>

<script>
let rankData=[], uniData=[], runsData=[];
let rankSort={col:'rank',dir:1};
let uniSort={col:'weight_pct',dir:-1};
let activeTab='rankings';
let runsTimer=null;

const $=id=>document.getElementById(id);
const fmtScore=v=>v==null?'—':(+v).toFixed(3);

function zColor(v){
  if(v==null)return 'neu';
  return +v>0.5?'pos':+v<-0.5?'neg':'neu';
}
function pctColor(v){
  if(v==null)return 'neu';
  return +v>=0.75?'pos':+v<=0.25?'neg':'neu';
}
function barH(z){
  if(z==null)return 2;
  return Math.max(2,Math.round(((+z+3)/6)*20));
}
function barW(comp,max){
  if(comp==null||max==null||max===0)return 0;
  return Math.max(0,Math.min(100,((+comp)/max)*100));
}
function clearSort(pfx){
  document.querySelectorAll('[id^="'+pfx+'"]').forEach(el=>el.classList.remove('asc','desc'));
}
function fmtDuration(s,e){
  if(!s)return '—';
  const ms=(e?new Date(e):new Date())-new Date(s);
  if(ms<0)return '—';
  if(ms<60000)return (ms/1000).toFixed(1)+'s';
  return Math.floor(ms/60000)+'m '+(Math.floor(ms/1000)%60)+'s';
}
function fmtTime(ts){
  if(!ts)return '—';
  const d=new Date(ts);
  return d.toLocaleDateString()+' '+d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
}
function fmtAgo(ts){
  if(!ts)return '—';
  const ms=new Date()-new Date(ts);
  if(ms<60000)return 'just now';
  if(ms<3600000)return Math.floor(ms/60000)+'m ago';
  if(ms<86400000)return Math.floor(ms/3600000)+'h ago';
  return new Date(ts).toLocaleDateString();
}

function switchTab(name,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
  activeTab=name;
  if(name==='runs'){
    loadRuns();
    if(!runsTimer) runsTimer=setInterval(()=>{if(activeTab==='runs')loadRuns();},30000);
  }
}

// ── Regime ───────────────────────────────────────────────────────────────────────

async function loadRegime(){
  try{
    const d=await fetch('/api/regime').then(r=>r.json());
    const regime=d.regime||'unknown';
    const el=$('rb-regime');
    el.textContent=regime.toUpperCase().replace('_',' ');
    el.className='rb-val rb-badge regime-'+regime;
    $('rb-spy').textContent=d.spy_price?'$'+parseFloat(d.spy_price).toFixed(2):'—';
    const sv=d.spy_vs_sma;
    const smaStr=sv!=null?(parseFloat(sv)*100).toFixed(1)+'%':'—';
    const smaCls=sv!=null?(parseFloat(sv)>=0?'pos':'neg'):'';
    $('rb-sma').innerHTML='<span class="'+smaCls+'">'+smaStr+'</span>';
    $('rb-vol').textContent=d.realized_vol?(parseFloat(d.realized_vol)*100).toFixed(1)+'%':'—';
    if(d.calculated_at)$('rb-ts').textContent=new Date(d.calculated_at).toLocaleString();
    $('r-regime').textContent=regime.toUpperCase().replace('_',' ');
  }catch(e){
    $('rb-regime').textContent='UNAVAILABLE';
  }
}

// ── Rankings ──────────────────────────────────────────────────────────────────────

async function loadRankings(){
  $('r-body').innerHTML='<tr><td colspan="11" class="loading">LOADING RANKINGS</td></tr>';
  try{
    const d=await fetch('/api/rankings?limit=500').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    rankData=(d.rankings||[]).map(r=>{
      const fs=r.factor_scores||{};
      return{rank:r.rank,ticker:r.ticker,composite_score:r.composite_score,
        percentile:r.percentile,momentum:fs.momentum,quality:fs.quality,
        value:fs.value,growth:fs.growth,low_volatility:fs.low_volatility,
        liquidity:fs.liquidity,rank_date:r.rank_date,regime:r.regime};
    });
    $('r-total').textContent=rankData.length;
    if(rankData.length){
      const best=rankData.reduce((a,b)=>(+(a.composite_score)||0)>(+(b.composite_score)||0)?a:b);
      $('r-top').textContent=fmtScore(best.composite_score);
      $('r-date').textContent=rankData[0].rank_date||'—';
    }
    renderRankings();
  }catch(e){
    $('r-body').innerHTML='<tr><td colspan="11" class="error">NO RANKING DATA — RUN: make pipeline</td></tr>';
  }
}

function sortRankings(col){
  if(rankSort.col===col)rankSort.dir*=-1;
  else{rankSort.col=col;rankSort.dir=col==='rank'?1:-1;}
  clearSort('rh-');
  const th=$('rh-'+col);
  if(th)th.classList.add(rankSort.dir===1?'asc':'desc');
  renderRankings();
}

function renderRankings(){
  const q=($('r-search').value||'').toUpperCase().trim();
  let rows=rankData.filter(r=>!q||r.ticker.includes(q));
  const col=rankSort.col,dir=rankSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('r-count').textContent=rows.length+' / '+rankData.length+' SHOWN';
  if(!rows.length){$('r-body').innerHTML='<tr><td colspan="11" class="loading">NO RESULTS</td></tr>';return;}
  const FACTORS=['momentum','quality','value','growth','low_volatility','liquidity'];
  const FLABELS=['MOM','QLTY','VAL','GRTH','LOVOL','LIQ'];
  $('r-body').innerHTML=rows.map(r=>{
    const bars=FACTORS.map((f,i)=>{
      const v=r[f];const h=barH(v);
      const tip=FLABELS[i]+': '+(v!=null?(+v).toFixed(3):'n/a');
      const bg=v==null?'rgba(0,229,255,0.12)':+v>0.5?'var(--green)':+v<-0.5?'var(--red)':'var(--cyan-dim)';
      return '<div class="fbar" style="height:'+h+'px;background:'+bg+'" data-tip="'+tip+'"></div>';
    }).join('');
    const w=barW(r.composite_score,maxComp);
    const pctCls=pctColor(r.percentile);
    const pctVal=r.percentile!=null?(+r.percentile*100).toFixed(0)+'%':'—';
    const compCls=r.composite_score!=null?(+r.composite_score>0?'pos':'neg'):'neu';
    return '<tr>'
      +'<td><span class="t-rank">'+r.rank+'</span></td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td><span class="pct-pill '+pctCls+'">'+pctVal+'</span></td>'
      +'<td><div class="fbars">'+bars+'</div></td>'
      +FACTORS.map(f=>'<td class="'+zColor(r[f])+'">'+(r[f]!=null?(+r[f]).toFixed(2):'—')+'</td>').join('')
      +'</tr>';
  }).join('');
}

// ── Universe ────────────────────────────────────────────────────────────────────────

async function loadUniverse(){
  $('u-body').innerHTML='<tr><td colspan="4" class="loading">LOADING UNIVERSE</td></tr>';
  try{
    const d=await fetch('/api/universe').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    uniData=d.tickers||[];
    const snap=d.snapshot||{};
    $('u-total').textContent=uniData.length;
    $('u-etf').textContent=snap.etf_ticker||'—';
    $('u-date').textContent=snap.snapshot_date||'—';
    const sectors=[...new Set(uniData.map(t=>t.sector).filter(Boolean))].sort();
    $('u-sectors').textContent=sectors.length;
    const sel=$('u-sector');
    sel.innerHTML='<option value="">ALL SECTORS</option>'+sectors.map(s=>'<option value="'+s+'">'+s+'</option>').join('');
    renderUniverse();
  }catch(e){
    $('u-body').innerHTML='<tr><td colspan="4" class="error">NO UNIVERSE DATA — RUN: make universe</td></tr>';
  }
}

function sortUniverse(col){
  if(uniSort.col===col)uniSort.dir*=-1;
  else{uniSort.col=col;uniSort.dir=col==='weight_pct'?-1:1;}
  clearSort('uh-');
  const th=$('uh-'+col);
  if(th)th.classList.add(uniSort.dir===1?'asc':'desc');
  renderUniverse();
}

function renderUniverse(){
  const q=($('u-search').value||'').toUpperCase().trim();
  const sec=$('u-sector').value;
  let rows=uniData.filter(t=>
    (!q||t.ticker.includes(q)||(t.name||'').toUpperCase().includes(q))&&
    (!sec||t.sector===sec)
  );
  const col=uniSort.col,dir=uniSort.dir;
  rows.sort((a,b)=>{
    let av=a[col],bv=b[col];
    if(col==='weight_pct'){av=+(av||0);bv=+(bv||0);}
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('u-count').textContent=rows.length+' / '+uniData.length+' SHOWN';
  if(!rows.length){$('u-body').innerHTML='<tr><td colspan="4" class="loading">NO RESULTS</td></tr>';return;}
  $('u-body').innerHTML=rows.map(t=>'<tr>'
    +'<td><span class="t-ticker">'+t.ticker+'</span></td>'
    +'<td><span class="t-name">'+(t.name||'—')+'</span></td>'
    +'<td><span class="t-sector">'+(t.sector||'—')+'</span></td>'
    +'<td class="t-wt">'+(t.weight_pct!=null?(+t.weight_pct).toFixed(4)+'%':'—')+'</td>'
    +'</tr>').join('');
}

// ── Pipeline Runs ───────────────────────────────────────────────────────────────────────

async function loadRuns(){
  try{
    const [iRes,fRes,rRes]=await Promise.allSettled([
      fetch('/api/ingest-runs?limit=15').then(r=>r.ok?r.json():[]),
      fetch('/api/factor-runs?limit=15').then(r=>r.ok?r.json():[]),
      fetch('/api/ranking-runs?limit=15').then(r=>r.ok?r.json():[]),
    ]);
    const ingest =(iRes.status==='fulfilled'?iRes.value:[]).map(r=>({...r,_svc:'ingest'}));
    const factors=(fRes.status==='fulfilled'?fRes.value:[]).map(r=>({...r,_svc:'factors'}));
    const ranks  =(rRes.status==='fulfilled'?rRes.value:[]).map(r=>({...r,_svc:'rank'}));

    runsData=[...ingest,...factors,...ranks]
      .sort((a,b)=>new Date(b.started_at||0)-new Date(a.started_at||0))
      .slice(0,45);

    const li=ingest[0], lf=factors[0], lr=ranks[0];

    const setStatBox=(id,run,detail)=>{
      const el=$(id);
      if(!run){el.textContent='—';el.className='val';return;}
      el.textContent=fmtAgo(run.started_at)+(detail?' // '+detail:'');
      el.className='val '+(run.status==='failed'?'red':run.status==='running'?'orange':'green');
    };
    setStatBox('run-last-ingest', li, li?.ticker_count?li.ticker_count+' tickers':null);
    setStatBox('run-last-factors', lf, lf?.regime?lf.regime.toUpperCase().replace('_',' '):null);
    setStatBox('run-last-rank', lr, lr?.ranked_count?lr.ranked_count+' ranked':null);

    const anyRunning=runsData.some(r=>r.status==='running');
    const anyFailed =runsData.slice(0,6).some(r=>r.status==='failed');
    $('run-system').textContent=anyRunning?'RUNNING':anyFailed?'CHECK LOGS':'IDLE';
    $('run-system').className='val '+(anyRunning?'orange':anyFailed?'red':'green');

    $('run-count').textContent=runsData.length+' RUNS SHOWN';
    renderRuns();
  }catch(e){
    $('run-body').innerHTML='<tr><td colspan="6" class="error">COULD NOT LOAD RUN DATA</td></tr>';
  }
}

function renderRuns(){
  if(!runsData.length){
    $('run-body').innerHTML='<tr><td colspan="6" class="loading">NO PIPELINE RUNS YET — RUN: make pipeline</td></tr>';
    return;
  }
  $('run-body').innerHTML=runsData.map(r=>{
    const svc=r._svc;
    const badgeLbl=svc==='ingest'?'INGEST':svc==='factors'?'FACTORS':'RANK';

    let detail='';
    if(svc==='ingest'){
      if(r.ticker_count!=null)detail+=r.ticker_count+' tickers';
      if(r.price_rows!=null)  detail+=(detail?' // ':'')+r.price_rows.toLocaleString()+' px rows';
      if(r.fund_rows!=null)   detail+=(detail?' // ':'')+r.fund_rows+' fund rows';
      if(r.error_count)       detail+=(detail?' // ':'')+'<span class="neg">'+r.error_count+' errors</span>';
    }else if(svc==='factors'){
      if(r.regime)            detail+=r.regime.toUpperCase().replace('_',' ');
      if(r.ticker_count!=null)detail+=(detail?' // ':'')+r.ticker_count+' scored';
      if(r.score_date)        detail+=(detail?' // ':'')+r.score_date;
    }else{
      if(r.ranked_count!=null)detail+=r.ranked_count+' ranked';
      if(r.dropped_count)     detail+=(detail?' // ':'')+r.dropped_count+' dropped';
      if(r.regime)            detail+=(detail?' // ':'')+r.regime.toUpperCase().replace('_',' ');
    }

    const jobLbl=(r.job_type||r.strategy_id||'—').replace(/-/g,' ');

    return '<tr>'
      +'<td class="run-time">'+fmtTime(r.started_at)+'</td>'
      +'<td><span class="run-badge badge-'+svc+'">'+badgeLbl+'</span></td>'
      +'<td style="color:var(--muted);font-size:.75rem">'+jobLbl+'</td>'
      +'<td><span class="status-'+r.status+'">'+r.status.toUpperCase()+'</span></td>'
      +'<td class="run-detail">'+detail+'</td>'
      +'<td class="run-dur">'+fmtDuration(r.started_at,r.completed_at)+'</td>'
      +'</tr>';
  }).join('');
}

// ── Init ──────────────────────────────────────────────────────────────────────────

(async()=>{
  await loadRegime();
  await loadRankings();
  await loadUniverse();
  $('rh-rank').classList.add('asc');
  $('uh-weight_pct').classList.add('desc');
  setInterval(loadRegime,120000);
})();
</script>
</body>
</html>
"""
