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


@app.get("/api/portfolio")
async def proxy_portfolio():
    return await _proxy("/portfolio")


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
  --white: #d8eeff;
  --green: #00ff9d;
  --red: #ff2d55;
  --muted: #2a5c72;
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
.rb-label{color:var(--muted);letter-spacing:.15em;text-transform:uppercase}
.rb-val{color:var(--cyan);font-weight:700;text-shadow:var(--glow-sm);letter-spacing:.08em}
.rb-sep{color:var(--border-strong)}
.rb-metric{color:var(--muted)}
.rb-metric span{color:var(--white)}
.rb-badge{
  padding:2px 12px;
  border:1px solid currentColor;
  font-size:.7rem;letter-spacing:.12em;
  text-transform:uppercase;
  font-weight:700;
}
.regime-bull_calm   {color:#00ff9d;text-shadow:0 0 10px #00ff9d80}
.regime-bull_volatile{color:#ffcc00;text-shadow:0 0 10px #ffcc0080}
.regime-bear_calm   {color:#00aaff;text-shadow:0 0 10px #00aaff80}
.regime-bear_volatile{color:#ff2d55;text-shadow:0 0 10px #ff2d5580}
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
}
.stat .val{
  font-size:1.7rem;font-weight:700;
  color:var(--cyan);text-shadow:var(--glow-sm);
}
.stat .val.orange{color:var(--orange);text-shadow:var(--glow-orange)}
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
thead tr{background:#061020;border-bottom:1px solid var(--cyan-dim)}
th{
  padding:11px 14px;text-align:left;
  color:var(--cyan);font-weight:400;
  letter-spacing:.16em;text-transform:uppercase;
  font-size:.67rem;cursor:pointer;
  user-select:none;white-space:nowrap;
  transition:background .15s;
}
th:hover{background:rgba(0,229,255,0.1)}
th.asc::after{content:' \25b2';color:var(--orange)}
th.desc::after{content:' \25bc';color:var(--orange)}
tbody tr{border-bottom:1px solid rgba(0,229,255,0.07);transition:background .12s}
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
.t-name{color:#7aaabb;font-size:.78rem;max-width:180px;overflow:hidden;text-overflow:ellipsis}
.t-sector{
  display:inline-block;padding:2px 8px;
  font-size:.66rem;border:1px solid rgba(0,229,255,0.2);
  color:var(--muted);letter-spacing:.05em;
}
.t-wt{color:#5a8fa0;font-size:.78rem}
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
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--cyan-dim)}
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
  <button class="tab" onclick="switchTab('portfolio',this)">Portfolio</button>
  <button class="tab" onclick="switchTab('universe',this)">Universe</button>
</div>

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

<div id="pane-portfolio" class="pane">
  <div class="stats">
    <div class="stat"><div class="lbl">Positions</div><div class="val" id="p-count">&#8212;</div></div>
    <div class="stat"><div class="lbl">Est. Annual Vol</div><div class="val orange" id="p-vol">&#8212;</div></div>
    <div class="stat"><div class="lbl">Avg Pairwise Corr</div><div class="val" id="p-corr">&#8212;</div></div>
    <div class="stat"><div class="lbl">Portfolio Date</div><div class="val" style="font-size:1rem;padding-top:4px" id="p-date">&#8212;</div></div>
    <div class="stat"><div class="lbl">Regime</div><div class="val orange" id="p-regime">&#8212;</div></div>
  </div>
  <div class="toolbar">
    <input type="search" id="p-search" placeholder="// FILTER TICKER" oninput="renderPortfolio()">
    <button class="btn" onclick="loadPortfolio()">&#x21BA; REFRESH</button>
    <span class="badge-count" id="p-count-badge"></span>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th onclick="sortPortfolio('position')" id="ph-position">POS</th>
          <th onclick="sortPortfolio('ticker')" id="ph-ticker">TICKER</th>
          <th onclick="sortPortfolio('weight')" id="ph-weight">WEIGHT</th>
          <th onclick="sortPortfolio('composite_score')" id="ph-composite_score">COMPOSITE</th>
          <th onclick="sortPortfolio('original_rank')" id="ph-original_rank">ORIG RANK</th>
          <th onclick="sortPortfolio('adj_score')" id="ph-adj_score">ADJ SCORE</th>
          <th onclick="sortPortfolio('portfolio_vol_at_add')" id="ph-portfolio_vol_at_add">VOL AT ADD</th>
        </tr>
      </thead>
      <tbody id="p-body">
        <tr><td colspan="7" class="loading">LOADING PORTFOLIO</td></tr>
      </tbody>
    </table>
  </div>
</div>

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
    <button class="btn" id="u-hide-tiny" onclick="toggleTiny()">HIDE TINY &#10003;</button>
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

<footer>STOCKER // GRID &nbsp;<span>v0.1</span> &nbsp;//&nbsp; PAPER TRADING ONLY &nbsp;//&nbsp; NOT FINANCIAL ADVICE</footer>
</div>

<script>
let rankData=[], uniData=[], portData=[];
let rankSort={col:'rank',dir:1};
let uniSort={col:'weight_pct',dir:-1};
let portSort={col:'position',dir:1};
let uniHideTiny=true;

function toggleTiny(){
  uniHideTiny=!uniHideTiny;
  $('u-hide-tiny').textContent='HIDE TINY '+(uniHideTiny?'✓':'○');
  renderUniverse();
}

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

function switchTab(name,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
}

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

async function loadPortfolio(){
  $('p-body').innerHTML='<tr><td colspan="7" class="loading">LOADING PORTFOLIO</td></tr>';
  try{
    const d=await fetch('/api/portfolio').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    const run=d.run||{};
    portData=d.holdings||[];
    $('p-count').textContent=run.selected_count??portData.length;
    $('p-vol').textContent=run.portfolio_estimated_vol!=null?(+run.portfolio_estimated_vol*100).toFixed(1)+'%':'—';
    $('p-corr').textContent=run.avg_pairwise_correlation!=null?(+run.avg_pairwise_correlation).toFixed(3):'—';
    $('p-date').textContent=run.portfolio_date||'—';
    $('p-regime').textContent=(run.regime||'—').toUpperCase().replace('_',' ');
    renderPortfolio();
  }catch(e){
    $('p-body').innerHTML='<tr><td colspan="7" class="error">NO PORTFOLIO DATA — RUN: make portfolio</td></tr>';
  }
}

function sortPortfolio(col){
  if(portSort.col===col)portSort.dir*=-1;
  else{portSort.col=col;portSort.dir=col==='position'||col==='original_rank'?1:-1;}
  clearSort('ph-');
  const th=$('ph-'+col);
  if(th)th.classList.add(portSort.dir===1?'asc':'desc');
  renderPortfolio();
}

function renderPortfolio(){
  const q=($('p-search').value||'').toUpperCase().trim();
  let rows=portData.filter(r=>!q||r.ticker.includes(q));
  const col=portSort.col,dir=portSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('p-count-badge').textContent=rows.length+' / '+portData.length+' SHOWN';
  if(!rows.length){$('p-body').innerHTML='<tr><td colspan="7" class="loading">NO RESULTS</td></tr>';return;}
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('p-body').innerHTML=rows.map(r=>{
    const w=barW(r.composite_score,maxComp);
    const compCls=r.composite_score!=null?(+r.composite_score>0?'pos':'neg'):'neu';
    const wt=r.weight!=null?((+r.weight)*100).toFixed(1)+'%':'—';
    const vol=r.portfolio_vol_at_add!=null?((+r.portfolio_vol_at_add)*100).toFixed(1)+'%':'—';
    const adj=r.adj_score!=null?(+r.adj_score).toFixed(3):'—';
    return '<tr>'
      +'<td><span class="t-rank">'+r.position+'</span></td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td class="neu">'+(r.original_rank??'—')+'</td>'
      +'<td class="pos">'+adj+'</td>'
      +'<td class="t-wt">'+vol+'</td>'
      +'</tr>';
  }).join('');
}

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
    (!sec||t.sector===sec)&&
    (!uniHideTiny||(t.weight_pct!=null&&+t.weight_pct>=0.01))
  );
  const hiddenCount=uniHideTiny?uniData.filter(t=>t.weight_pct==null||+t.weight_pct<0.01).length:0;
  const col=uniSort.col,dir=uniSort.dir;
  rows.sort((a,b)=>{
    let av=a[col],bv=b[col];
    if(col==='weight_pct'){av=+(av||0);bv=+(bv||0);}
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('u-count').textContent=rows.length+' shown'+(hiddenCount?' ('+hiddenCount+' tiny hidden)':'');
  if(!rows.length){$('u-body').innerHTML='<tr><td colspan="4" class="loading">NO RESULTS</td></tr>';return;}
  $('u-body').innerHTML=rows.map(t=>'<tr>'
    +'<td><span class="t-ticker">'+t.ticker+'</span></td>'
    +'<td><span class="t-name">'+(t.name||'—')+'</span></td>'
    +'<td><span class="t-sector">'+(t.sector||'—')+'</span></td>'
    +'<td class="t-wt">'+(t.weight_pct!=null?(+t.weight_pct).toFixed(4)+'%':'—')+'</td>'
    +'</tr>').join('');
}

(async()=>{
  await loadRegime();
  await loadRankings();
  loadPortfolio();
  loadUniverse();
  $('rh-rank').classList.add('asc');
  $('uh-weight_pct').classList.add('desc');
  $('ph-position').classList.add('asc');
})();
</script>
</body>
</html>
"""
