const $=id=>document.getElementById(id);
const fmtScore=v=>v==null?'—':(+v).toFixed(3);

// ── Data stores ──────────────────────────────────────────────────────────────
let rankData=[], deltaData=[];
let rankSort={col:'rank',dir:1};
let deltaSort={col:'rank',dir:1};

// Per-intent approval state: intent_id → {status, msg}
let _approvalState = {};

// Currently expanded rank row ticker (null = none expanded)
let _expandedTicker = null;

// ── Tabs ─────────────────────────────────────────────────────────────────────
function switchTab(name, btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  $('pane-'+name).classList.add('active');
  if (name === 'live') loadLivePortfolio();
  if (name === 'portfolio') loadDelta();
}

// ── Helpers ──────────────────────────────────────────────────────────────────
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
function esc(s){
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Job control ───────────────────────────────────────────────────────────────
const TAB_IDS = {
  rank: {wrap:'rank-prog-wrap',fill:'rank-fill',pct:'rank-pct',badge:'rank-badge',start:'rank-start'},
  // universe and portfolio job panels are not in the HTML — renderJob() null-guards handle missing elements
};

function _setProgress(tab, pct, error){
  const ids = TAB_IDS[tab];
  if(!ids) return;
  const wrapEl = $(ids.wrap);
  if(wrapEl) wrapEl.style.display = 'flex';
  const fillEl = $(ids.fill);
  if(fillEl){
    fillEl.style.width = Math.min(100, Math.max(0, pct)) + '%';
    fillEl.classList.toggle('error', !!error);
  }
  const pctEl = $(ids.pct);
  if(pctEl) pctEl.textContent = Math.round(pct) + '%';
}

function _setBadge(tab, text, cls){
  const ids = TAB_IDS[tab];
  if(!ids) return;
  const el = $(ids.badge);
  if(!el) return;
  el.textContent = text;
  el.className = 'job-status-badge badge-' + cls;
}

function _setJobPanel(tab, cls){
  const panel = $('jp-'+tab);
  if(panel) panel.className = 'job-panel ' + (cls||'');
  const ids = TAB_IDS[tab];
  const btn = ids ? $(ids.start) : null;
  if(btn) btn.disabled = (cls === 'running');
}

async function startJob(tab) {
  const cfg = {
    universe:  {url: '/api/jobs/universe',   start: 'uni-start'},
    rank:      {url: '/api/jobs/rank-chain', start: 'rank-start'},
    portfolio: {url: '/api/jobs/portfolio',  start: 'portfolio-start'},
  }[tab];
  if (!cfg) return;
  const btn = $(cfg.start);
  if (btn) btn.disabled = true;
  try {
    await fetch(cfg.url, {method: 'POST'});
  } catch(e) {
    if (btn) btn.disabled = false;
  }
}

// ── Status bar ────────────────────────────────────────────────────────────────
// Maps pipeline-status data to the thin sticky status bar.
function updateStatusBar(d) {
  const rank     = d.rank     || {};
  const vetter   = d.vetter   || {};
  const portfolio= d.portfolio|| {};
  const universe = d.universe || {};

  // Determine activity label + color
  let label = 'IDLE';
  let colorCls = 'act-gray';
  let showProg = false;
  let progPct  = null;  // null = indeterminate
  let progColCls = 'col-gray';

  if (vetter.status === 'running') {
    label = 'LLM ANALYSIS'; colorCls = 'act-purple'; progColCls = 'col-purple'; showProg = true;
  } else if (portfolio.status === 'running') {
    label = 'BUILDING PORTFOLIO'; colorCls = 'act-blue'; progColCls = 'col-blue'; showProg = true;
  } else if (rank.status === 'running') {
    const sl = rank.step_label || '';
    if (sl === 'Fetching Data') {
      label = rank.pct != null ? 'FETCHING DATA  ' + rank.pct + '%' : 'FETCHING DATA';
      colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true;
      progPct = rank.pct;
    } else if (sl === 'Calculating Factors') {
      label = 'CALCULATING FACTORS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else if (sl === 'Ranking') {
      label = 'RANKING STOCKS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else if (sl && sl.indexOf('Delta') !== -1) {
      label = 'EVALUATING SIGNALS'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true; progPct = rank.pct;
    } else {
      label = 'PROCESSING'; colorCls = 'act-amber'; progColCls = 'col-amber'; showProg = true;
    }
  } else if (universe.status === 'running') {
    label = 'FETCHING UNIVERSE'; colorCls = 'act-blue'; progColCls = 'col-blue'; showProg = true;
  } else if (rank.status === 'failed') {
    label = 'PIPELINE FAILED'; colorCls = 'act-red'; showProg = false;
  } else if (rank.status === 'success' || rank.date) {
    label = 'READY'; colorCls = 'act-green'; showProg = false;
  } else {
    label = 'IDLE'; colorCls = 'act-gray'; showProg = false;
  }

  const actEl = $('sb-activity');
  actEl.textContent = label;
  actEl.className = 'sb-activity ' + colorCls;

  const progWrap = $('sb-prog-wrap');
  const progFill = $('sb-prog-fill');
  progFill.classList.remove('indeterminate', 'col-green','col-amber','col-blue','col-purple','col-red','col-gray');
  progFill.classList.add(progColCls);
  if (showProg) {
    progWrap.style.display = 'block';
    if (progPct != null) {
      progFill.style.width = progPct + '%';
    } else {
      progFill.classList.add('indeterminate');
    }
  } else {
    progWrap.style.display = 'none';
  }

  // Regime badge
  // (updated separately by loadRegime; here we don't override it)

  // Rank date (right side)
  const rdEl = $('sb-rankdate');
  if (rank.date) {
    rdEl.textContent = rank.date;
  } else {
    rdEl.textContent = '';
  }
}

// ── Regime ────────────────────────────────────────────────────────────────────
async function loadRegime(){
  try{
    const d=await fetch('/api/regime').then(r=>r.json());
    const regime=d.regime||'unknown';

    // Status bar regime badge
    const sbReg = $('sb-regime');
    sbReg.textContent = regime.toUpperCase().replace(/_/g,' ');
    sbReg.className = 'sb-regime-badge regime-' + regime;

    // Status bar SPY price
    const spyEl = $('sb-spy');
    if(d.spy_price) spyEl.textContent = '$'+parseFloat(d.spy_price).toFixed(2);
    else spyEl.textContent = '';
  }catch(e){
    const sbReg=$('sb-regime');
    sbReg.textContent='UNAVAILABLE';
    sbReg.className='sb-regime-badge regime-unknown';
  }
}

// ── Rankings ──────────────────────────────────────────────────────────────────
async function loadRankings(){
  $('r-body').innerHTML='<tr><td colspan="12" class="loading">Loading rankings</td></tr>';
  try{
    const d=await fetch('/api/rankings/with-overlays?limit=100').then(r=>{
      if(!r.ok)throw new Error(r.status);
      return r.json();
    });
    rankData=(d.rankings||[]).map(r=>{
      const fs=r.factor_scores||{};
      return{
        rank:r.rank, ticker:r.ticker,
        name: r.name || null,
        composite_score:r.composite_score, percentile:r.percentile,
        momentum:fs.momentum, quality:fs.quality, value:fs.value,
        growth:fs.growth, low_volatility:fs.low_volatility, liquidity:fs.liquidity,
        rank_date:r.rank_date, regime:r.regime,
        rank_slope: r.rank_slope!=null ? +r.rank_slope : null,
        prior_rank: r.prior_rank!=null ? +r.prior_rank : null,
        held: !!r.held, qty: r.qty, market_value: r.market_value,
        unrealized_plpc: r.unrealized_plpc,
        vetter_excluded: !!r.vetter_excluded,
        vetter_confidence: r.vetter_confidence,
        vetter_risk_type: r.vetter_risk_type,
        vetter_reason: r.vetter_reason,
        positive_catalyst: !!r.positive_catalyst,
        positive_reason: r.positive_reason,
        not_in_universe: !!r.not_in_universe,
      };
    });
    // Show vetter-pending notice when the LLM vetter hasn't run yet
    const vetterNotice = $('r-vetter-notice');
    if (vetterNotice) {
      if (d.vetter_run_id) {
        vetterNotice.style.display = 'none';
      } else {
        vetterNotice.style.display = '';
        vetterNotice.textContent = 'LLM vetter has not run yet — vetter columns will be empty until step 5 of the daily chain completes.';
      }
    }
    _expandedTicker = null;
    renderRankings();
  }catch(e){
    $('r-body').innerHTML='<tr><td colspan="12" class="error">No ranking data</td></tr>';
  }
}

function sortRankings(col){
  if(rankSort.col===col)rankSort.dir*=-1;
  else{rankSort.col=col;rankSort.dir=col==='rank'?1:-1;}
  _expandedTicker = null;
  clearSort('rh-');
  const th=$('rh-'+col);
  if(th)th.classList.add(rankSort.dir===1?'asc':'desc');
  renderRankings();
}

// Build the detail row HTML for a given rank data record.
function _buildDetailHtml(r) {
  // Top line
  const nameHtml = r.name ? '<span class="detail-name">'+esc(r.name)+'</span>' : '<span class="detail-name"></span>';
  const yfLink = '<a class="detail-yf-link" href="https://finance.yahoo.com/quote/'+esc(r.ticker)+'" target="_blank" rel="noopener">&#8599; Yahoo Finance</a>';
  const head = '<div class="detail-head">'
    +'<span class="detail-ticker">'+esc(r.ticker)+'</span>'
    +nameHtml
    +yfLink
    +'</div>';

  // Rank / Score / Percentile grid
  const pctVal = r.percentile!=null ? (+(r.percentile)*100).toFixed(1)+'%' : '—';
  const scoreVal = r.composite_score!=null ? fmtScore(r.composite_score) : '—';
  const grid = '<div class="detail-grid">'
    +'<div class="detail-cell"><div class="dc-lbl">Rank</div><div class="dc-val">'+r.rank+'</div></div>'
    +'<div class="detail-cell"><div class="dc-lbl">Score</div><div class="dc-val">'+scoreVal+'</div></div>'
    +'<div class="detail-cell"><div class="dc-lbl">Percentile</div><div class="dc-val">'+pctVal+'</div></div>'
    +'</div>';

  // Factor z-score chips
  const FACTORS = [
    {key:'momentum',      lbl:'Momentum'},
    {key:'quality',       lbl:'Quality'},
    {key:'value',         lbl:'Value'},
    {key:'growth',        lbl:'Growth'},
    {key:'low_volatility',lbl:'Low Vol'},
    {key:'liquidity',     lbl:'Liquidity'},
  ];
  const chips = FACTORS.map(f=>{
    const v = r[f.key];
    const cls = v==null ? 'fc-neu' : +v>0.5 ? 'fc-pos' : +v<-0.5 ? 'fc-neg' : 'fc-neu';
    const valStr = v!=null ? (+v).toFixed(3) : '—';
    return '<span class="factor-chip"><span class="fc-lbl">'+f.lbl+'</span><span class="fc-val '+cls+'">'+valStr+'</span></span>';
  }).join('');
  const factorSection = '<div class="detail-section-label">Factor Z-Scores</div>'
    +'<div class="factor-chips">'+chips+'</div>';

  // Vetter / LLM section
  let llmHtml = '';
  const hasVetter = r.vetter_excluded || r.vetter_confidence || r.vetter_reason;
  if (hasVetter) {
    // Verdict
    const crashed = (r.vetter_reason||'').toUpperCase().indexOf('CRASHED') !== -1;
    const verdict = crashed ? 'CRASHED' : r.vetter_excluded ? 'EXCLUDE' : 'KEEP';
    const vbCls = crashed ? 'vb-crashed' : r.vetter_excluded ? 'vb-exclude' : 'vb-keep';
    const conf = (r.vetter_confidence||'low').toLowerCase();
    const cbCls = 'cb-' + conf;
    const riskType = (r.vetter_risk_type && r.vetter_risk_type !== 'none')
      ? '<span class="llm-risk-type">'+esc(r.vetter_risk_type.replace(/_/g,' ').toUpperCase())+'</span>'
      : '';
    const llmHeader = '<div class="llm-header">'
      +'<span class="llm-label">LLM ANALYSIS</span>'
      +'<span class="llm-verdict-badge '+vbCls+'">'+verdict+'</span>'
      +'<span class="llm-conf-badge '+cbCls+'">'+conf.toUpperCase()+'</span>'
      +riskType
      +'</div>';
    const reasonHtml = r.vetter_reason
      ? '<div class="llm-reason">'+esc(r.vetter_reason)+'</div>'
      : '';
    const exclHtml = r.vetter_excluded && r.vetter_reason
      ? '<div class="llm-excl-reason">Excluded: '+esc(r.vetter_reason)+'</div>'
      : '';
    const catalystHtml = (r.positive_catalyst && r.positive_reason)
      ? '<div class="llm-catalyst">'
        +'<div class="llm-catalyst-label">&#8679; Positive Catalyst</div>'
        +'<div class="llm-catalyst-reason">'+esc(r.positive_reason)+'</div>'
        +'</div>'
      : '';
    llmHtml = '<div class="detail-llm">'+llmHeader+reasonHtml+exclHtml+catalystHtml+'</div>';
  } else if (r.positive_catalyst && r.positive_reason) {
    // Has catalyst but no exclusion info
    llmHtml = '<div class="detail-llm">'
      +'<div class="llm-header"><span class="llm-label">LLM ANALYSIS</span></div>'
      +'<div class="llm-catalyst">'
      +'<div class="llm-catalyst-label">&#8679; Positive Catalyst</div>'
      +'<div class="llm-catalyst-reason">'+esc(r.positive_reason)+'</div>'
      +'</div></div>';
  }

  // Held note
  const heldHtml = r.held
    ? '<div class="detail-held-note">HELD &#8212; '+(r.qty!=null ? r.qty+' shares' : 'position')+'</div>'
    : '';

  // Not-in-universe warning
  const notRankedHtml = r.not_in_universe
    ? '<div class="detail-held-note" style="border-color:var(--secondary);color:var(--secondary)">'
      +'&#9888; NOT IN RANKING UNIVERSE &#8212; This position is held at the broker but was '
      +'filtered out of the ranking pipeline. Possible reasons: missing price data in the '
      +'database, below min_price or min_avg_dollar_volume threshold, or insufficient price '
      +'history for momentum calculation (needs 253+ days). Run av-ingestor fetch-data to '
      +'backfill data, then re-run the pipeline.'
      +'</div>'
    : '';

  // Border class for detail-inner
  const borderCls = r.held ? 'dl-held' : r.vetter_excluded ? 'dl-excl' : 'dl-default';

  return '<div class="detail-inner '+borderCls+'">'
    +head+grid+factorSection+llmHtml+heldHtml+notRankedHtml
    +'</div>';
}

// Toggle a detail row open/closed beneath the clicked rank row.
function toggleDetail(ticker, rowEl) {
  // If clicking the currently expanded row, collapse it.
  if (_expandedTicker === ticker) {
    _expandedTicker = null;
    const existing = rowEl.nextSibling;
    if (existing && existing.classList && existing.classList.contains('detail-row')) {
      existing.remove();
    }
    rowEl.classList.remove('expanded');
    return;
  }

  // Collapse any previously open detail row.
  if (_expandedTicker !== null) {
    const prevRow = document.getElementById('detail-row-'+_expandedTicker);
    if (prevRow) prevRow.remove();
    const prevMain = document.getElementById('rank-row-'+_expandedTicker);
    if (prevMain) prevMain.classList.remove('expanded');
  }

  _expandedTicker = ticker;
  rowEl.classList.add('expanded');

  // Find the data record
  const rec = rankData.find(r => r.ticker === ticker);
  if (!rec) return;

  // Insert detail row immediately after the clicked row
  const detailTr = document.createElement('tr');
  detailTr.className = 'detail-row';
  detailTr.id = 'detail-row-' + ticker;
  const td = document.createElement('td');
  td.colSpan = 12;
  td.innerHTML = _buildDetailHtml(rec);
  detailTr.appendChild(td);
  rowEl.parentNode.insertBefore(detailTr, rowEl.nextSibling);
}

function renderRankings(){
  const q=($('r-search').value||'').toUpperCase().trim();
  const onlyHeld = $('r-only-held') && $('r-only-held').checked;
  const hideExcl = $('r-hide-excl') && $('r-hide-excl').checked;
  let rows=rankData.filter(r=>{
    if(q && !r.ticker.includes(q)) return false;
    if(onlyHeld && !r.held) return false;
    if(hideExcl && r.vetter_excluded) return false;
    return true;
  });
  const col=rankSort.col,dir=rankSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  const maxComp=Math.max(...rows.map(r=>+(r.composite_score)||0));
  $('r-count').textContent=rows.length+' / '+rankData.length+' SHOWN';
  if(!rows.length){
    _expandedTicker=null;
    $('r-body').innerHTML='<tr><td colspan="12" class="loading">No results</td></tr>';
    return;
  }
  const FACTORS=['momentum','quality','value','growth','low_volatility','liquidity'];
  const FLABELS=['MOM','QLTY','VAL','GRTH','LOVOL','LIQ'];

  // Build HTML rows; detail rows are re-inserted after if previously expanded
  const html = rows.map(r=>{
    const bars=FACTORS.map((f,i)=>{
      const v=r[f];const h=barH(v);
      const tip=FLABELS[i]+': '+(v!=null?(+v).toFixed(3):'n/a');
      const bg=v==null?'var(--panel3)':+v>0.5?'var(--green)':+v<-0.5?'var(--red)':'var(--blue)';
      return '<div class="fbar" style="height:'+h+'px;background:'+bg+'" data-tip="'+tip+'"></div>';
    }).join('');
    const w=barW(r.composite_score,maxComp);
    const pctCls=pctColor(r.percentile);
    const pctVal=r.percentile!=null?(+r.percentile*100).toFixed(0)+'%':'—';
    const compCls=r.composite_score!=null?(+r.composite_score>0?'pos':'neg'):'neu';

    // Rank movement
    let arrow='';
    if(r.prior_rank!=null){
      const delta=r.prior_rank - r.rank;
      if(delta >= 2)      arrow='<span class="rank-up" title="up '+delta+' from prior run">&#9650;'+delta+'</span>';
      else if(delta <= -2)arrow='<span class="rank-dn" title="down '+(-delta)+' from prior run">&#9660;'+(-delta)+'</span>';
      else if(delta !== 0)arrow='<span style="color:var(--secondary);font-size:.7rem" title="prior rank '+r.prior_rank+'">~</span>';
    } else if(r.rank_slope!=null && Math.abs(r.rank_slope)>=1){
      arrow = r.rank_slope<0
        ? '<span class="rank-up" title="trending up (slope='+r.rank_slope.toFixed(1)+')">&#9650;</span>'
        : '<span class="rank-dn" title="trending down (slope='+r.rank_slope.toFixed(1)+')">&#9660;</span>';
    }

    // Overlay badges
    const flags=[];
    if(r.held) flags.push('<span class="overlay-badge held" title="Held: qty='+(r.qty||'?')+(r.market_value!=null?', $'+(+r.market_value).toFixed(0):'')+'">HELD</span>');
    if(r.not_in_universe) flags.push('<span class="overlay-badge not-ranked" title="This position is held at the broker but did not pass the ranking pipeline (missing price data, below liquidity threshold, or insufficient history). The pipeline will force-exit it.">NOT RANKED</span>');
    if(r.vetter_excluded){
      const why=(r.vetter_reason||'').replace(/"/g,'&quot;');
      flags.push('<span class="overlay-badge excl" title="'+why+'">&#9888; '+(r.vetter_confidence||'').toUpperCase()+'</span>');
    }
    if(r.positive_catalyst){
      const why=(r.positive_reason||'').replace(/"/g,'&quot;');
      flags.push('<span class="overlay-badge pos-cat" title="'+why+'">&#9733; CATALYST</span>');
    }
    const flagsHtml = flags.length ? flags.join(' ') : '<span style="color:var(--secondary);font-size:.7rem">—</span>';

    const heldCls  = r.held ? ' row-held' : '';
    const exclCls  = r.vetter_excluded ? ' row-excluded' : '';
    const expandedCls = (_expandedTicker === r.ticker) ? ' expanded' : '';

    return '<tr class="rank-row'+heldCls+exclCls+expandedCls+'" id="rank-row-'+esc(r.ticker)+'" onclick="toggleDetail(\''+esc(r.ticker)+'\',this)">'
      +'<td><span class="t-rank">'+r.rank+'</span> '+arrow+'</td>'
      +'<td><span class="t-ticker">'+r.ticker+'</span></td>'
      +'<td>'+flagsHtml+'</td>'
      +'<td><div class="score-wrap"><span class="score-num '+compCls+'">'+fmtScore(r.composite_score)+'</span>'
      +'<div class="score-track"><div class="score-fill" style="width:'+w+'%"></div></div></div></td>'
      +'<td><span class="pct-pill '+pctCls+'">'+pctVal+'</span></td>'
      +'<td><div class="fbars">'+bars+'</div></td>'
      +FACTORS.map(f=>'<td class="'+zColor(r[f])+'">'+(r[f]!=null?(+r[f]).toFixed(2):'—')+'</td>').join('')
      +'</tr>';
  }).join('');

  $('r-body').innerHTML = html;

  // Re-insert the detail row for the currently expanded ticker if it's still visible
  if (_expandedTicker !== null) {
    const mainRow = document.getElementById('rank-row-'+_expandedTicker);
    if (mainRow) {
      const rec = rankData.find(r => r.ticker === _expandedTicker);
      if (rec) {
        const detailTr = document.createElement('tr');
        detailTr.className = 'detail-row';
        detailTr.id = 'detail-row-' + _expandedTicker;
        const td = document.createElement('td');
        td.colSpan = 12;
        td.innerHTML = _buildDetailHtml(rec);
        detailTr.appendChild(td);
        mainRow.parentNode.insertBefore(detailTr, mainRow.nextSibling);
      }
    } else {
      // Row filtered out — collapse
      _expandedTicker = null;
    }
  }
}

// ── Live Portfolio ────────────────────────────────────────────────────────────
let liveData = [];
let liveSort = {col:'market_value', dir:-1};

function sortLive(col){
  if(liveSort.col===col)liveSort.dir*=-1;
  else{liveSort.col=col;liveSort.dir=-1;}
  clearSort('lh-');
  const th=$('lh-'+col);
  if(th)th.classList.add(liveSort.dir===1?'asc':'desc');
  renderLive();
}

function renderLive(){
  const col=liveSort.col,dir=liveSort.dir;
  const rows=[...liveData].sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('live-count-badge').textContent=rows.length+' POSITIONS';
  if(!rows.length){$('live-body').innerHTML='<tr><td colspan="10" style="padding:20px 14px;color:var(--secondary)">No positions</td></tr>';return;}
  const fmt$=v=>v==null?'—':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const fmtPct=v=>v==null?'—':(v*100).toFixed(2)+'%';
  const fmtChg=v=>v==null?'—':((v>=0?'+':'')+(v*100).toFixed(2)+'%');
  const fmtShares=v=>v==null?'—':(Math.abs(v)>=100?(+v).toFixed(0):(+v).toFixed(4));
  const plSign=(v,f)=>v==null?'—':((v>=0?'+':'')+f(v));
  $('live-body').innerHTML=rows.map(p=>{
    const dayPlCls=p.day_pl==null?'pl-neu':p.day_pl>0?'pl-pos':'pl-neg';
    const dayPctCls=p.change_today==null?'pl-neu':p.change_today>0?'pl-pos':'pl-neg';
    const plCls=p.unrealized_pl==null?'pl-neu':p.unrealized_pl>0?'pl-pos':'pl-neg';
    const plPctCls=p.unrealized_plpc==null?'pl-neu':p.unrealized_plpc>0?'pl-pos':'pl-neg';
    const wt=p.weight!=null?((p.weight)*100).toFixed(1)+'%':'—';
    return '<tr>'
      +'<td><span class="t-ticker">'+esc(p.ticker)+'</span></td>'
      +'<td class="t-wt">'+fmt$(p.market_value)+'</td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td class="t-wt">'+fmtShares(p.qty)+'</td>'
      +'<td class="t-wt">'+fmt$(p.avg_entry_price)+'</td>'
      +'<td class="t-wt">'+fmt$(p.current_price)+'</td>'
      +'<td class="'+dayPlCls+'">'+plSign(p.day_pl,fmt$)+'</td>'
      +'<td class="'+dayPctCls+'">'+fmtChg(p.change_today)+'</td>'
      +'<td class="'+plCls+'">'+plSign(p.unrealized_pl,fmt$)+'</td>'
      +'<td class="'+plPctCls+'">'+fmtChg(p.unrealized_plpc)+'</td>'
      +'</tr>';
  }).join('');
}

async function loadLivePortfolio(){
  try{
    const d=await fetch('/api/live-portfolio').then(r=>r.json());

    const dotEl=$('live-dot');
    const lblEl=$('live-conn-label');
    const statsEl=$('live-account-stats');
    const notConnEl=$('live-not-connected');
    const toolbarEl=$('live-toolbar');
    const tblEl=$('live-tbl-wrap');

    if(!d.connected){
      dotEl.className='live-dot disconnected';
      lblEl.textContent='NOT CONNECTED';
      lblEl.className='live-conn-label disconnected';
      $('live-sync-time').textContent='';
      statsEl.style.display='none';
      notConnEl.style.display='block';
      toolbarEl.style.display='none';
      tblEl.style.display='none';
      return;
    }

    const sync=d.sync||{};
    dotEl.className='live-dot connected';
    lblEl.textContent='CONNECTED — PAPER TRADING';
    lblEl.className='live-conn-label connected';
    if(sync.synced_at){
      $('live-sync-time').textContent='Last sync: '+new Date(sync.synced_at).toLocaleString();
    }

    const fmt$=v=>v==null?'—':'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
    $('live-acct-val').textContent=fmt$(sync.account_value);
    $('live-cash').textContent=fmt$(sync.cash);
    $('live-bp').textContent=fmt$(sync.buying_power);
    $('live-pos-count').textContent=sync.position_count??d.positions.length;

    statsEl.style.display='flex';
    notConnEl.style.display='none';
    toolbarEl.style.display='flex';
    tblEl.style.display='block';

    liveData=d.positions||[];
    renderLive();
    $('lh-market_value').classList.add('desc');
    const totalDayPL=liveData.reduce((s,p)=>s+(p.day_pl||0),0);
    const dayPlEl=$('live-day-pl');
    if(dayPlEl){
      const fmt$=v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
      dayPlEl.textContent=(totalDayPL>=0?'+':'')+fmt$(totalDayPL);
      dayPlEl.className='val '+(totalDayPL>0?'pos':totalDayPL<0?'neg':'');
    }
  }catch(e){
    const lblEl=$('live-conn-label');
    if(lblEl){ lblEl.textContent='ERROR'; lblEl.className='live-conn-label disconnected'; }
    console.warn('live-portfolio error', e);
  }
}

// ── Server-driven render loop ──────────────────────────────────────────────
let _prevJobState = {universe:{}, rank:{}, portfolio:{}};

async function refresh() {
  try {
    const d = await fetch('/api/pipeline-status').then(r => r.json());
    renderJob('universe', d.universe || {}, _prevJobState.universe || {});
    renderJob('rank',     d.rank     || {}, _prevJobState.rank     || {});
    renderJob('portfolio',d.portfolio|| {}, _prevJobState.portfolio|| {});
    updateStatusBar(d);
    // Warnings
    if (d.warnings) {
      $('rank-warning').style.display = d.warnings.rank ? 'block' : 'none';
      _setTabWarn('tab-rank', d.warnings.rank);
      _setTabWarn('tab-portfolio', d.warnings.portfolio);
    }
    _prevJobState = {
      universe:  d.universe  || {},
      rank:      d.rank      || {},
      portfolio: d.portfolio || {},
    };
  } catch(e) { /* service may be temporarily down */ }
}

function renderJob(tab, state, prev) {
  const status   = state.status || 'none';
  const running  = status === 'running';
  const done     = status === 'success' || status === 'partial_success';
  const failed   = status === 'failed';
  const label    = running ? (state.step_label || 'RUNNING')
                 : done    ? 'DONE'
                 : failed  ? 'FAILED'
                 : 'NOT RUN';
  const badgeCls = running ? 'running' : done ? 'success' : failed ? 'failed' : 'notrun';

  _setBadge(tab, label, badgeCls);
  _setJobPanel(tab, running ? 'running' : done ? 'success' : failed ? 'failed' : '');

  const fillId = {universe:'uni-fill', rank:'rank-fill', portfolio:'portfolio-fill'}[tab];
  const wrapId = {universe:'uni-prog-wrap', rank:'rank-prog-wrap', portfolio:'portfolio-prog-wrap'}[tab];
  const pctId  = {universe:'uni-pct', rank:'rank-pct', portfolio:'portfolio-pct'}[tab];
  const fillEl = $(fillId), wrapEl = $(wrapId), pctEl = $(pctId);
  if (fillEl) {
    fillEl.classList.remove('indeterminate', 'pulsing', 'error');
    if (running) {
      wrapEl && (wrapEl.style.display = 'flex');
      const pct = (state.pct != null) ? state.pct : null;
      if (pct != null) {
        fillEl.style.width = pct + '%';
        fillEl.classList.add('pulsing');
        if (pctEl) pctEl.textContent = pct + '%';
      } else {
        fillEl.classList.add('indeterminate');
        if (pctEl) pctEl.textContent = '';
      }
    } else if (done) {
      fillEl.style.width = '100%';
      if (pctEl) pctEl.textContent = '100%';
      wrapEl && (wrapEl.style.display = 'flex');
    } else if (failed) {
      fillEl.style.width = '100%';
      fillEl.classList.add('error');
      if (pctEl) pctEl.textContent = '';
      wrapEl && (wrapEl.style.display = 'flex');
    } else {
      fillEl.style.width = '0%';
      if (pctEl) pctEl.textContent = '0%';
      wrapEl && (wrapEl.style.display = 'none');
    }
  }

  // Date
  const dateEl = {universe:'uni-last-date', rank:'rank-last-date', portfolio:'port-last-date'}[tab];
  if (dateEl && state.date) $(dateEl) && ($(dateEl).textContent = state.date);

  // Reload tab data on transition running→done or prevUnknown→done
  const wasRunning  = (prev.status === 'running');
  const prevUnknown = (prev.status == null || prev.status === 'none' || prev.status === undefined);
  if ((wasRunning && done) || (prevUnknown && done)) {
    if (tab === 'universe')  loadRankings();
    if (tab === 'rank')      { loadRankings(); loadRegime(); }
    if (tab === 'portfolio') loadDelta();
  }
}

function _setTabWarn(tabId, show){
  const btn = $(tabId);
  if(!btn) return;
  const existing = btn.querySelector('.tab-warn');
  if(show && !existing){
    const dot = document.createElement('span');
    dot.className = 'tab-warn';
    btn.appendChild(dot);
  } else if(!show && existing){
    existing.remove();
  }
}

// ── Trade Proposal (delta engine) ────────────────────────────────────────────
function sortDelta(col){
  if(deltaSort.col===col)deltaSort.dir*=-1;
  else{deltaSort.col=col;deltaSort.dir=col==='rank'?1:-1;}
  clearSort('dh-');
  const th=$('dh-'+col);
  if(th)th.classList.add(deltaSort.dir===1?'asc':'desc');
  renderDelta();
}

function renderDelta(){
  const q=($('delta-search').value||'').toUpperCase().trim();
  let rows=deltaData.filter(r=>!q||r.ticker.includes(q));
  const col=deltaSort.col,dir=deltaSort.dir;
  rows.sort((a,b)=>{
    const av=a[col],bv=b[col];
    if(av==null&&bv==null)return 0;
    if(av==null)return 1;if(bv==null)return -1;
    return(av<bv?-1:av>bv?1:0)*dir;
  });
  $('delta-count-badge').textContent=rows.length+' INTENTS';
  if(!rows.length){$('delta-body').innerHTML='<tr><td colspan="9" class="loading">No proposals</td></tr>';return;}
  const actionTag={
    entry:'<span style="background:#1a4a1a;color:#4caf50;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">BUY</span>',
    exit:'<span style="background:#4a1a1a;color:#f44336;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">SELL</span>',
    hold:'<span style="background:#1a2a4a;color:#42a5f5;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">HOLD</span>',
    watch:'<span style="background:#3a2a0a;color:#ff9800;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">WATCH</span>',
    at_risk:'<span style="background:#3a1a00;color:#ff6d00;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">AT RISK</span>',
    buy_add:'<span style="background:#0a3a1a;color:#00e676;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">BUY+</span>',
    sell_trim:'<span style="background:#3a2a00;color:#ffd54f;padding:2px 6px;border-radius:3px;font-size:.7rem;font-weight:700">TRIM</span>',
  };
  $('delta-body').innerHTML=rows.map(r=>{
    const tag=actionTag[r.action]||r.action;
    const wt=r.current_weight!=null?((r.current_weight)*100).toFixed(1)+'%':'—';
    const drift=r.weight_drift!=null?((r.weight_drift>=0?'+':'')+((r.weight_drift)*100).toFixed(1)+'%'):'—';
    const reason=r.reason?esc(r.reason.substring(0,60))+(r.reason.length>60?'&#8230;':''):'—';

    // Vetter cell — show for entry and at_risk intents where vetter data exists
    let vetterCell='<td></td>';
    const showVetter=(r.action==='entry'||r.action==='at_risk')&&r.vetter_confidence!=null;
    if(showVetter){
      const excl=r.vetter_excluded;
      const verdict=excl?'EXCL':'KEEP';
      const vColor=excl?'#f44336':'#4caf50';
      const vBg=excl?'rgba(244,67,54,.12)':'rgba(76,175,80,.12)';
      const conf=(r.vetter_confidence||'').toLowerCase();
      const tip=r.vetter_reason?esc(r.vetter_reason.substring(0,120)):'';
      vetterCell='<td style="font-size:.72rem">'
        +'<span style="background:'+vBg+';color:'+vColor+';padding:1px 5px;border-radius:3px;font-weight:700" title="'+tip+'">'+verdict+'</span>'
        +(conf?' <span style="color:var(--secondary)">'+conf+'</span>':'')
        +'</td>';
    }else if(r.action==='entry'||r.action==='at_risk'){
      vetterCell='<td style="font-size:.72rem;color:var(--secondary)">—</td>';
    }

    let approveCells='<td></td>';
    if(r.action==='entry'||r.action==='exit'||r.action==='buy_add'||r.action==='sell_trim'){
      const st=_approvalState[r.id]||{};
      if(st.status==='pending'){
        approveCells='<td><span style="color:var(--secondary);font-size:.75rem">Submitting&#8230;</span></td>';
      }else if(st.status==='ok'){
        approveCells='<td><span style="color:#4caf50;font-size:.75rem">'+esc(st.msg||'Submitted')+'</span></td>';
      }else if(st.status==='err'){
        approveCells='<td><span style="color:#f44336;font-size:.75rem" title="'+esc(st.msg||'')+'">Error</span></td>';
      }else{
        approveCells='<td>'
          +'<button class="btn" style="padding:3px 8px;font-size:.72rem;margin-right:4px" onclick="approveTrade(\''+r.id+'\',\'immediate\')">&#9654; NOW</button>'
          +'<button class="btn" style="padding:3px 8px;font-size:.72rem" onclick="approveTrade(\''+r.id+'\',\'scheduled\')">&#9711; MOO</button>'
          +'</td>';
      }
    }
    return '<tr>'
      +'<td><span class="t-ticker">'+esc(r.ticker)+'</span></td>'
      +'<td>'+tag+'</td>'
      +'<td class="t-wt">'+(r.rank??'—')+'</td>'
      +'<td class="t-wt">'+fmtScore(r.composite_score)+'</td>'
      +'<td class="t-wt">'+wt+'</td>'
      +'<td class="t-wt">'+drift+'</td>'
      +'<td style="font-size:.75rem;color:var(--secondary);max-width:200px">'+reason+'</td>'
      +vetterCell
      +approveCells
      +'</tr>';
  }).join('');
}

async function loadDelta(){
  $('delta-body').innerHTML='<tr><td colspan="9" class="loading">Loading proposals</td></tr>';
  try{
    const d=await fetch('/api/delta/latest').then(r=>r.json());
    const run=d.run||{};
    deltaData=d.intents||[];
    $('delta-entries').textContent=run.entries_count??'—';
    $('delta-exits').textContent=run.exits_count??'—';
    $('delta-holds').textContent=run.holds_count??'—';
    $('delta-watches').textContent=run.watches_count??'—';
    $('delta-at-risks').textContent=run.at_risk_count??'—';
    $('delta-buy-adds').textContent=run.buy_add_count??'—';
    $('delta-sell-trims').textContent=run.sell_trim_count??'—';
    $('delta-run-date').textContent=run.run_date||'—';
    $('delta-ranks').textContent=(run.entry_rank&&run.exit_rank)?(run.entry_rank+' / '+run.exit_rank):'—';
    // Show a notice when displaying the intermediate embedded-pipeline delta
    // (triggered before portfolio-builder runs) rather than the authoritative
    // scheduler-triggered delta (triggered after portfolio-builder).
    const notice = $('delta-source-notice');
    if (notice) {
      const isEmbedded = run.status && (d.run?.triggered_by === 'pipeline');
      notice.style.display = isEmbedded ? '' : 'none';
      if (isEmbedded) {
        notice.textContent = 'Showing intermediate delta (before portfolio-builder ran). '
          + 'Entry proposals will appear after the full daily chain completes (scheduler step 4).';
      }
    }
    _approvalState={};
    renderDelta();
  }catch(e){
    $('delta-body').innerHTML='<tr><td colspan="9" class="error">No delta data — run delta engine first</td></tr>';
  }
}

async function startDeltaRun(){
  const btn=$('delta-run-btn');
  if(btn)btn.disabled=true;
  try{
    await fetch('/api/jobs/delta',{method:'POST'});
    await new Promise(r=>setTimeout(r,2000));
    await loadDelta();
  }finally{
    if(btn)btn.disabled=false;
  }
}

async function approveTrade(intentId, mode){
  if(_approvalState[intentId]) return;
  _approvalState[intentId]={status:'pending'};
  renderDelta();
  try{
    const r=await fetch('/api/trade/approve',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({intent_id:intentId,mode:mode})
    });
    const d=await r.json();
    if(!r.ok||d.error){
      _approvalState[intentId]={status:'err',msg:d.error||d.detail||'Failed'};
    }else if(d.status==='duplicate'){
      _approvalState[intentId]={status:'ok',msg:'Already submitted'};
    }else if(!d.risk_approved){
      _approvalState[intentId]={status:'err',msg:'Risk rejected: '+(d.risk_reason||'')};
    }else if(d.status==='failed'){
      _approvalState[intentId]={status:'err',msg:d.reason||d.error_message||'Order failed'};
    }else{
      const modeLabel=mode==='scheduled'?'MOO scheduled':'Market order sent';
      _approvalState[intentId]={status:'ok',msg:modeLabel+(d.alpaca_order_id?' ('+d.alpaca_order_id.substring(0,8)+'&#8230;)':'')};
    }
  }catch(e){
    _approvalState[intentId]={status:'err',msg:String(e)};
  }
  renderDelta();
}

async function syncAlpaca(){
  const btn=$('alpaca-sync-btn');
  if(btn){btn.disabled=true;btn.textContent='Syncing&#8230;';}
  try{
    await fetch('/api/alpaca-sync',{method:'POST'});
    await new Promise(r=>setTimeout(r,3000));
    await loadLivePortfolio();
  }finally{
    if(btn){btn.disabled=false;btn.textContent='⇄ SYNC ALPACA';}
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
(async()=>{
  await loadRegime();
  loadRankings();
  loadLivePortfolio();
  $('rh-rank').classList.add('asc');
  const dhRank=$('dh-rank'); if(dhRank)dhRank.classList.add('asc');

  // Server-driven render loop: poll every 2s
  setInterval(refresh, 2000);
  refresh();  // immediate first call
  // On mobile, browsers suspend setInterval when the tab is backgrounded.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });
})();
