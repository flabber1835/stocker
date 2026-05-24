/* global state */
const $ = id => document.getElementById(id);

let rankData      = [];
let deltaData     = [];
let liveData      = [];
let liveSyncData  = {};
let ordersData    = [];

let rankSort  = { col: 'rank', dir: 1 };
let liveSort  = { col: 'market_value', dir: -1 };

let _approvalState   = {};   // intent_id → { status, msg }
let _expandedTicker  = null;
let _pipelineData    = {};
let _prevPipelineData= {};
let _aaStatus        = { auto_approve_minutes: 60, pending: [], fetchedAt: Date.now() };
let _lastRefreshAt   = Date.now();
let _rankChainRunning= false;
let _runRequestedAt  = 0;      // ms timestamp of last Run click; button stays locked for RUN_LOCK_MS
let _initialLoadDone = false;  // prevents refresh() from double-loading on boot

const RUN_LOCK_MS = 30000;     // keep button disabled for 30 s after clicking Run
let _selectedIntents = new Set();

const REFRESH_SECS = 30;

/* ── Formatting ──────────────────────────────────────────────────────── */
function fmtMoney(v, dec = 2) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return n < 0 ? '-$' + abs : '$' + abs;
}
function fmtPL(v, dec = 2) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  const abs = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return n < 0 ? '-$' + abs : '+$' + abs;
}
function fmtPct(v, dec = 2) {
  if (v == null || v === '') return '—';
  const n = parseFloat(v);
  if (isNaN(n)) return '—';
  return (n >= 0 ? '+' : '') + (n * 100).toFixed(dec) + '%';
}
function fmtCountdown(secs) {
  if (secs <= 0) return '0:00';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m + ':' + String(s).padStart(2, '0');
}
function fmtScore(v) { return v == null ? '—' : (+v).toFixed(3); }
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
function _parseAlpacaError(msg) {
  if (!msg) return 'Order failed';
  try {
    const obj = JSON.parse(msg);
    if (obj.message) return 'Alpaca: ' + obj.message;
    if (obj.detail)  return obj.detail;
  } catch (e) { /* not JSON */ }
  return msg.length > 140 ? msg.substring(0, 140) + '…' : msg;
}
function zColor(v) {
  // Factor values are cross-sectional percentile ranks in (0, 1].
  // Top 30% → green, bottom 40% → red, middle → neutral.
  if (v == null) return 'neu';
  return +v > 0.70 ? 'pos' : +v <= 0.40 ? 'neg' : 'neu';
}
function pctColor(v) {
  if (v == null) return 'neu';
  return +v >= 0.75 ? 'pos' : +v <= 0.25 ? 'neg' : 'neu';
}

/* ── Screen navigation ───────────────────────────────────────────────── */
function showScreen(name, btnEl) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('screen-' + name).classList.add('active');
  if (btnEl) btnEl.classList.add('active');
  if (name === 'portfolio') { loadLivePortfolio(); fetchOrders(); }
  if (name === 'trader')    renderTrader();
}

/* ── Clock ───────────────────────────────────────────────────────────── */
function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  $('sb-clock').textContent = hh + ':' + mm + ':' + ss;
}

/* ── Status bar ──────────────────────────────────────────────────────── */
function updateStatusBar(d) {
  const rank      = d.rank      || {};
  const vetter    = d.vetter    || {};
  const portfolio = d.portfolio || {};
  const universe  = d.universe  || {};

  let text = 'IDLE', textCls = 'sb-gray';
  let sub = '', subCls = '';

  if (vetter.status === 'running') {
    const p = vetter.progress;
    if (p && p.total > 0) {
      const pct = Math.min(100, Math.round((p.completed / p.total) * 100));
      text = 'LLM ANALYSIS ' + p.completed + '/' + p.total + ' · ' + pct + '%';
    } else {
      text = 'LLM ANALYSIS';
    }
    textCls = 'sb-purple';
  } else if (portfolio.status === 'running') {
    text = 'BUILDING PORTFOLIO'; textCls = 'sb-blue';
  } else if (rank.status === 'running') {
    const sl = rank.step_label || '';
    if (sl === 'Fetching Data')       { text = rank.pct != null ? 'FETCHING DATA  ' + rank.pct + '%' : 'FETCHING DATA'; textCls = 'sb-amber'; }
    else if (sl === 'Calculating Factors') { text = 'CALCULATING FACTORS'; textCls = 'sb-amber'; }
    else if (sl === 'Ranking')        { text = 'RANKING STOCKS'; textCls = 'sb-amber'; }
    else if (sl.indexOf('Delta') !== -1) { text = 'EVALUATING SIGNALS'; textCls = 'sb-amber'; }
    else                               { text = 'PROCESSING'; textCls = 'sb-amber'; }
  } else if (universe.status === 'running') {
    text = 'FETCHING UNIVERSE'; textCls = 'sb-blue';
  } else if (universe.status === 'failed') {
    text = 'UNIVERSE FETCH FAILED'; textCls = 'sb-red';
    sub = 'Set AV_API_KEY or MOCK_DATA=true and restart';
  } else if (rank.status === 'failed') {
    text = 'PIPELINE FAILED'; textCls = 'sb-red';
  } else if (rank.status === 'success' || rank.date) {
    text = 'READY'; textCls = 'sb-green';
    if (rank.date) sub = 'Ranked ' + rank.date;
  }

  // Override with auto-approve countdown when trades are pending and pipeline idle
  if (rank.status !== 'running') {
    const pending = _aaStatus.pending;
    if (pending.length > 0) {
      const fetchedAt = _aaStatus.fetchedAt || Date.now();
      const urgentRemaining = pending.reduce((min, p) => {
        const r = p.remaining_seconds - (Date.now() - fetchedAt) / 1000;
        return r < min ? r : min;
      }, Infinity);
      const cnt = pending.length;
      text = cnt + ' TRADE' + (cnt > 1 ? 'S' : '') + ' PENDING';
      textCls = 'sb-amber';
      sub = urgentRemaining > 0 ? 'AUTO-APPROVE IN ' + fmtCountdown(urgentRemaining) : 'AUTO-APPROVING…';
      subCls = urgentRemaining < 600 ? 'sb-red' : 'sb-amber';
    }
  }

  const sbText = $('sb-text');
  sbText.textContent = text;
  sbText.className = 'sb-text ' + textCls;

  const sbSub = $('sb-sub');
  if (sub) {
    sbSub.textContent = sub;
    sbSub.className = 'sb-sub ' + subCls;
    sbSub.style.display = '';
  } else {
    sbSub.style.display = 'none';
  }
}

/* ── Screener pipeline bar ───────────────────────────────────────────── */
function updatePipelineBar(rank, vetter) {
  vetter = vetter || {};
  const running = rank.status === 'running';
  const success = rank.status === 'success' || rank.status === 'partial_success';
  const failed  = rank.status === 'failed';
  const vetRunning = vetter.status === 'running';

  const dot   = $('pb-dot');
  const label = $('pb-label');
  const progWrap = $('pb-prog-wrap');
  const fill  = $('pb-prog-fill');
  const pct   = $('pb-pct');
  const btn   = $('run-btn');

  // Show "running"-style indicator if pipeline OR vetter is in flight, so the user
  // sees forward progress through the whole chain rather than the bar disappearing
  // the moment pipeline finishes and the vetter takes over for the next ~20 minutes.
  // Also keep it locked for RUN_LOCK_MS after the user clicked Run — the backend
  // needs a moment to start the new run; without this guard the first status poll
  // (which still sees the previous run's "success") would re-enable the button.
  const recentlyRequested = (Date.now() - _runRequestedAt) < RUN_LOCK_MS;
  const showAsRunning = running || (vetRunning && !success && !failed) || recentlyRequested;
  dot.className   = 'pb-dot'   + (showAsRunning ? ' running' : success ? ' success' : failed ? ' failed' : '');
  label.className = 'pb-label' + (showAsRunning ? ' running' : success ? ' success' : failed ? ' failed' : '');

  let labelText, barPct;
  if (running) {
    labelText = rank.step_label || 'RUNNING';
    barPct = rank.pct;
  } else if (recentlyRequested) {
    labelText = 'QUEUED…';
    barPct = null;
  } else if (vetRunning) {
    const vp = vetter.progress;
    if (vp && vp.total > 0) {
      const vpct = Math.min(100, Math.round((vp.completed / vp.total) * 100));
      labelText = 'LLM ANALYSIS ' + vp.completed + '/' + vp.total;
      barPct = vpct;
    } else {
      labelText = 'LLM ANALYSIS';
      barPct = null;
    }
  } else if (success) {
    labelText = 'READY' + (rank.date ? ' — ' + rank.date : '');
  } else if (failed) {
    labelText = 'FAILED';
  } else {
    labelText = 'IDLE';
  }
  label.textContent = labelText;

  if (showAsRunning) {
    progWrap.style.display = 'flex';
    fill.classList.remove('indeterminate');
    if (barPct != null) {
      fill.style.width = barPct + '%';
      pct.textContent  = barPct + '%';
    } else {
      fill.style.width = '30%';
      fill.classList.add('indeterminate');
      pct.textContent  = '';
    }
  } else {
    progWrap.style.display = 'none';
  }
  if (btn) btn.disabled = showAsRunning;

  // Update summary strip last-run
  if (rank.date) $('ss-last-run').textContent = rank.date;
}

/* ── Screener summary strip ──────────────────────────────────────────── */
function updateSummaryStrip() {
  $('ss-ranked').textContent   = rankData.length || '—';
  $('ss-holdings').textContent = rankData.filter(r => r.held).length || '—';
}

/* ── Regime ───────────────────────────────────────────────────────────── */
async function loadRegime() {
  try {
    const d = await fetch('/api/regime').then(r => r.json());
    const regime = d.regime || 'unknown';
    const sbReg = $('sb-regime');
    sbReg.textContent = regime.toUpperCase().replace(/_/g, ' ');
    sbReg.className = 'regime-pill regime-' + regime;
    if (d.spy_price) $('ss-spy').textContent = fmtMoney(d.spy_price);
  } catch (e) {
    const sbReg = $('sb-regime');
    sbReg.textContent = '—';
    sbReg.className = 'regime-pill regime-unknown';
  }
}

/* ── Rankings ────────────────────────────────────────────────────────── */
async function loadRankings() {
  $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">Loading rankings&#8230;</td></tr>';
  try {
    const d = await fetch('/api/rankings/with-overlays?limit=150').then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    rankData = (d.rankings || []).map(r => {
      const fs = r.factor_scores || {};
      return {
        rank: r.rank, ticker: r.ticker, name: r.name || null,
        composite_score: r.composite_score, percentile: r.percentile,
        momentum: fs.momentum, quality: fs.quality, value: fs.value,
        growth: fs.growth, low_volatility: fs.low_volatility, liquidity: fs.liquidity,
        rank_date: r.rank_date, regime: r.regime,
        rank_slope: r.rank_slope != null ? +r.rank_slope : null,
        prior_rank: r.prior_rank != null ? +r.prior_rank : null,
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
    _expandedTicker = null;
    renderRankings();
    updateSummaryStrip();
  } catch (e) {
    $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">No ranking data</td></tr>';
  }
}

function sortRankings(col) {
  if (rankSort.col === col) rankSort.dir *= -1;
  else { rankSort.col = col; rankSort.dir = col === 'rank' ? 1 : -1; }
  _expandedTicker = null;
  clearSort('rh-');
  const th = $('rh-' + col);
  if (th) th.classList.add(rankSort.dir === 1 ? 'asc' : 'desc');
  renderRankings();
}

function clearSort(pfx) {
  document.querySelectorAll('[id^="' + pfx + '"]').forEach(el => el.classList.remove('asc', 'desc'));
}

function renderRankings() {
  const q = ($('r-search').value || '').toUpperCase().trim();
  const onlyHeld = $('r-only-held') && $('r-only-held').checked;
  const hideExcl = $('r-hide-excl') && $('r-hide-excl').checked;
  let rows = rankData.filter(r => {
    if (q && !r.ticker.includes(q)) return false;
    if (onlyHeld && !r.held) return false;
    if (hideExcl && r.vetter_excluded) return false;
    return true;
  });
  const { col, dir } = rankSort;
  rows.sort((a, b) => {
    const av = a[col], bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });
  const maxComp = Math.max(...rows.map(r => +(r.composite_score) || 0));
  $('r-count').textContent = rows.length + ' / ' + rankData.length;
  if (!rows.length) {
    _expandedTicker = null;
    $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">No results</td></tr>';
    return;
  }
  const html = rows.map(r => {
    const w = maxComp ? Math.max(0, Math.min(100, (+r.composite_score || 0) / maxComp * 100)) : 0;
    const pctCls = pctColor(r.percentile);
    const pctVal = r.percentile != null ? (+r.percentile * 100).toFixed(0) + '%' : '—';
    const compCls = r.composite_score != null ? (+r.composite_score > 0.5 ? 'pos' : 'neg') : 'neu';

    let arrow = '';
    if (r.prior_rank != null) {
      const delta = r.prior_rank - r.rank;
      if (delta >= 2)       arrow = '<span class="rank-up" title="up ' + delta + '">&#9650;' + delta + '</span>';
      else if (delta <= -2) arrow = '<span class="rank-dn" title="down ' + (-delta) + '">&#9660;' + (-delta) + '</span>';
    } else if (r.rank_slope != null && Math.abs(r.rank_slope) >= 1) {
      arrow = r.rank_slope < 0
        ? '<span class="rank-up">&#9650;</span>'
        : '<span class="rank-dn">&#9660;</span>';
    }

    const flags = [];
    if (r.held)           flags.push('<span class="overlay-badge held">HELD</span>');
    if (r.not_in_universe) flags.push('<span class="overlay-badge not-ranked" title="Held but not in ranking universe">NOT RANKED</span>');
    if (r.vetter_excluded) flags.push('<span class="overlay-badge excl" title="' + esc(r.vetter_reason || '') + '">&#9888; ' + (r.vetter_risk_type || '').toUpperCase().replace(/_/g,' ') + '</span>');
    if (r.positive_catalyst) flags.push('<span class="overlay-badge pos-cat" title="' + esc(r.positive_reason || '') + '">&#9733;</span>');
    const flagsHtml = flags.length ? flags.join('') : '<span style="color:var(--text3)">—</span>';

    const FACTORS = ['momentum', 'quality', 'value', 'growth', 'low_volatility', 'liquidity'];
    const factorCells = FACTORS.map(f => '<td class="' + zColor(r[f]) + '">' + (r[f] != null ? (+r[f]).toFixed(2) : '—') + '</td>').join('');

    const heldCls     = r.held ? ' row-held' : '';
    const exclCls     = r.vetter_excluded ? ' row-excluded' : '';
    const expandedCls = _expandedTicker === r.ticker ? ' expanded' : '';

    return '<tr class="rank-row' + heldCls + exclCls + expandedCls + '" id="rank-row-' + esc(r.ticker) + '" onclick="toggleDetail(\'' + esc(r.ticker) + '\',this)">'
      + '<td><span class="t-rank">' + r.rank + '</span>' + arrow + '</td>'
      + '<td><span class="t-ticker">' + r.ticker + '</span></td>'
      + '<td><div class="score-wrap"><span class="score-num ' + compCls + '">' + fmtScore(r.composite_score) + '</span>'
      + '<div class="score-track"><div class="score-fill" style="width:' + w + '%"></div></div></div></td>'
      + '<td>' + flagsHtml + '</td>'
      + factorCells
      + '</tr>';
  }).join('');

  $('r-body').innerHTML = html;

  if (_expandedTicker !== null) {
    const mainRow = document.getElementById('rank-row-' + _expandedTicker);
    if (mainRow) {
      const rec = rankData.find(r => r.ticker === _expandedTicker);
      if (rec) _insertDetailRow(mainRow, rec);
    } else {
      _expandedTicker = null;
    }
  }
}

function toggleDetail(ticker, rowEl) {
  if (_expandedTicker === ticker) {
    _expandedTicker = null;
    const next = rowEl.nextSibling;
    if (next && next.classList && next.classList.contains('detail-row')) next.remove();
    rowEl.classList.remove('expanded');
    return;
  }
  if (_expandedTicker !== null) {
    const prev = document.getElementById('detail-row-' + _expandedTicker);
    if (prev) prev.remove();
    const prevMain = document.getElementById('rank-row-' + _expandedTicker);
    if (prevMain) prevMain.classList.remove('expanded');
  }
  _expandedTicker = ticker;
  rowEl.classList.add('expanded');
  const rec = rankData.find(r => r.ticker === ticker);
  if (rec) _insertDetailRow(rowEl, rec);
}

function _insertDetailRow(rowEl, rec) {
  const tr = document.createElement('tr');
  tr.className = 'detail-row';
  tr.id = 'detail-row-' + rec.ticker;
  const td = document.createElement('td');
  td.colSpan = 10;
  td.innerHTML = _buildDetailHtml(rec);
  tr.appendChild(td);
  rowEl.parentNode.insertBefore(tr, rowEl.nextSibling);
}

function _buildDetailHtml(r) {
  const nameHtml = r.name ? '<span class="detail-name">' + esc(r.name) + '</span>' : '<span class="detail-name"></span>';
  const yfLink = '<a class="detail-yf-link" href="https://finance.yahoo.com/quote/' + esc(r.ticker) + '" target="_blank" rel="noopener">&#8599; Yahoo Finance</a>';
  const head = '<div class="detail-head"><span class="detail-ticker">' + esc(r.ticker) + '</span>' + nameHtml + yfLink + '</div>';

  const pctVal = r.percentile != null ? (+(r.percentile) * 100).toFixed(1) + '%' : '—';
  const grid = '<div class="detail-grid">'
    + '<div class="detail-cell"><div class="dc-lbl">Rank</div><div class="dc-val">' + r.rank + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Score</div><div class="dc-val">' + fmtScore(r.composite_score) + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Percentile</div><div class="dc-val">' + pctVal + '</div></div>'
    + '</div>';

  const FACTORS = [
    { key: 'momentum', lbl: 'Momentum' }, { key: 'quality', lbl: 'Quality' },
    { key: 'value', lbl: 'Value' }, { key: 'growth', lbl: 'Growth' },
    { key: 'low_volatility', lbl: 'Low Vol' }, { key: 'liquidity', lbl: 'Liquidity' },
  ];
  const chips = FACTORS.map(f => {
    const v = r[f.key];
    const cls = v == null ? 'fc-neu' : +v > 0.5 ? 'fc-pos' : +v < -0.5 ? 'fc-neg' : 'fc-neu';
    return '<span class="factor-chip"><span class="fc-lbl">' + f.lbl + '</span><span class="fc-val ' + cls + '">' + (v != null ? (+v).toFixed(3) : '—') + '</span></span>';
  }).join('');
  const factorSection = '<div class="detail-section-label">Factor Z-Scores</div><div class="factor-chips">' + chips + '</div>';

  let llmHtml = '';
  if (r.vetter_excluded || r.vetter_confidence || r.vetter_reason) {
    const crashed = (r.vetter_reason || '').toUpperCase().indexOf('CRASHED') !== -1;
    const verdict = crashed ? 'CRASHED' : r.vetter_excluded ? 'EXCLUDE' : 'KEEP';
    const vbCls = crashed ? 'vb-crashed' : r.vetter_excluded ? 'vb-exclude' : 'vb-keep';
    const conf = (r.vetter_confidence || 'low').toLowerCase();
    const riskType = (r.vetter_risk_type && r.vetter_risk_type !== 'none')
      ? '<span class="llm-risk-type">' + esc(r.vetter_risk_type.replace(/_/g, ' ').toUpperCase()) + '</span>'
      : '';
    const catalystHtml = (r.positive_catalyst && r.positive_reason)
      ? '<div class="llm-catalyst"><div class="llm-catalyst-label">&#8679; Positive Catalyst</div><div class="llm-catalyst-reason">' + esc(r.positive_reason) + '</div></div>'
      : '';
    llmHtml = '<div class="detail-llm">'
      + '<div class="llm-header"><span class="llm-label">LLM ANALYSIS</span>'
      + '<span class="llm-verdict-badge ' + vbCls + '">' + verdict + '</span>'
      + '<span class="llm-conf-badge cb-' + conf + '">' + conf.toUpperCase() + '</span>'
      + riskType + '</div>'
      + (r.vetter_reason ? '<div class="llm-reason">' + esc(r.vetter_reason) + '</div>' : '')
      + catalystHtml + '</div>';
  } else if (r.positive_catalyst && r.positive_reason) {
    llmHtml = '<div class="detail-llm"><div class="llm-header"><span class="llm-label">LLM ANALYSIS</span></div>'
      + '<div class="llm-catalyst"><div class="llm-catalyst-label">&#8679; Positive Catalyst</div>'
      + '<div class="llm-catalyst-reason">' + esc(r.positive_reason) + '</div></div></div>';
  }

  const heldHtml = r.held ? '<div class="detail-held-note">HELD — ' + (r.qty != null ? r.qty + ' shares' : 'position') + '</div>' : '';
  const notRankedHtml = r.not_in_universe
    ? '<div class="detail-held-note" style="color:var(--text2)">&#9888; NOT IN RANKING UNIVERSE — missing price data, below liquidity threshold, or insufficient history.</div>'
    : '';
  const borderCls = r.held ? 'dl-held' : r.vetter_excluded ? 'dl-excl' : 'dl-default';

  return '<div class="detail-inner ' + borderCls + '">' + head + grid + factorSection + llmHtml + heldHtml + notRankedHtml + '</div>';
}

/* ── Trader screen ───────────────────────────────────────────────────── */
async function loadDelta() {
  try {
    const d = await fetch('/api/delta/latest').then(r => r.json());
    const run = d.run || {};
    deltaData = d.intents || [];
    $('ds-entries').textContent = run.entries_count ?? '—';
    $('ds-exits').textContent   = run.exits_count   ?? '—';
    $('ds-holds').textContent   = run.holds_count   ?? '—';
    $('ds-watches').textContent = run.watches_count  ?? '—';
    $('ds-date').textContent    = run.run_date       || '—';
    _approvalState = {};
    _selectedIntents.clear();
    renderTrader();
    updateTraderBadge();
  } catch (e) {
    deltaData = [];
    renderTrader();
  }
}

/* ── Action metadata maps ────────────────────────────────────────────── */
const ACTION_ORDER  = { exit: 0, sell_trim: 1, entry: 2, buy_add: 3, hold: 4, watch: 5, at_risk: 6 };
const ACTION_LABELS = {
  exit: 'SELL TO EXIT', sell_trim: 'SELL TO TRIM',
  entry: 'BUY TO ENTER', buy_add: 'BUY TO ADD',
  hold: 'HOLD', watch: 'WATCH', at_risk: 'AT RISK',
};
const ACTION_PILL = {
  exit: 'pill-sell-exit', sell_trim: 'pill-sell-trim',
  entry: 'pill-buy-enter', buy_add: 'pill-buy-add',
  hold: 'pill-hold', watch: 'pill-watch', at_risk: 'pill-at-risk',
};

function _isApprovable(r) {
  if (!['entry', 'exit', 'buy_add', 'sell_trim'].includes(r.action)) return false;
  if (_approvalState[r.id]) return false;
  const os = r.order_status;
  if (os === 'submitted' || os === 'pending' || os === 'failed' || os === 'risk_rejected') return false;
  if (r.rejected_at) return false;
  if ((r.action === 'entry' || r.action === 'buy_add') && r.vetter_excluded) return false;
  return true;
}

function renderTrader() {
  const sorted = [...deltaData].sort((a, b) => {
    const ao = ACTION_ORDER[a.action] ?? 99;
    const bo = ACTION_ORDER[b.action] ?? 99;
    return ao - bo || (a.rank ?? 999) - (b.rank ?? 999);
  });

  const toolbar = $('trader-toolbar');
  // Show toolbar whenever there are any signals — the Purge & Reset button must be
  // reachable even when all signals are hold/watch (open orders may still need canceling).
  if (toolbar) toolbar.style.display = sorted.length > 0 ? '' : 'none';

  const tbody = $('trader-body');
  if (!tbody) return;

  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" class="tbl-empty">No signals — <strong>all clear</strong></td></tr>';
    _syncSelectAllState();
    updateTraderBadge();
    return;
  }

  let lastSection = null;
  const rows = [];
  for (const r of sorted) {
    const section = (r.action === 'exit' || r.action === 'sell_trim') ? 'sell'
                  : (r.action === 'entry' || r.action === 'buy_add')  ? 'buy'
                  : 'hold';
    if (section !== lastSection) {
      const label = section === 'sell' ? 'Sell Orders'
                  : section === 'buy'  ? 'Buy Orders'
                  : 'Hold &amp; Watch';
      rows.push('<tr class="tr-section-divider"><td colspan="9">' + label + '</td></tr>');
      lastSection = section;
    }
    rows.push(_buildTradeRow(r));
  }
  tbody.innerHTML = rows.join('');
  _syncSelectAllState();
  updateTraderBadge();
}

function _buildTradeRow(r) {
  const isActionable = ['entry', 'exit', 'buy_add', 'sell_trim'].includes(r.action);
  const approvable   = _isApprovable(r);
  const isSell = r.action === 'exit' || r.action === 'sell_trim';
  const isBuy  = r.action === 'entry' || r.action === 'buy_add';
  const rowCls = isSell ? 'tr-sell' : isBuy ? 'tr-buy' : 'tr-hold';

  const isSelected = _selectedIntents.has(String(r.id));
  const chkCell = approvable
    ? '<td class="col-chk"><input type="checkbox" class="trade-chk"'
      + (isSelected ? ' checked' : '')
      + ' onchange="toggleSelectIntent(\'' + r.id + '\',this.checked)"></td>'
    : '<td class="col-chk"></td>';

  const pillCls  = ACTION_PILL[r.action]   || 'pill-hold';
  const pillText = ACTION_LABELS[r.action] || r.action.toUpperCase();
  const actionCell = '<td><span class="tc-pill ' + pillCls + '" style="white-space:nowrap">' + pillText + '</span></td>';

  const tickerCell = '<td>'
    + '<span class="t-ticker">' + esc(r.ticker) + '</span>'
    + (r.name ? '<div class="t-name">' + esc(r.name) + '</div>' : '')
    + '</td>';

  const rankCell  = '<td class="t-num">' + (r.rank != null ? '#' + r.rank : '—') + '</td>';
  const scoreCell = '<td class="t-num">' + fmtScore(r.composite_score) + '</td>';
  const qty = (r.order_qty != null && r.order_qty > 0) ? r.order_qty : '—';
  const qtyCell   = '<td class="t-num">' + qty + '</td>';

  const vetterBadge = (r.vetter_excluded && isBuy)
    ? '<span class="overlay-badge excl" title="' + esc(r.vetter_reason || '') + '">&#9888; '
      + (r.vetter_risk_type || '').toUpperCase().replace(/_/g, ' ') + '</span>'
    : '';
  let timerHtml = '';
  if (approvable) {
    const aaItem = _aaStatus.pending.find(p => p.intent_id === String(r.id));
    if (aaItem) {
      const fetchedAt = _aaStatus.fetchedAt || Date.now();
      const totalSecs = _aaStatus.auto_approve_minutes * 60;
      const remaining = Math.max(0, aaItem.remaining_seconds - (Date.now() - fetchedAt) / 1000);
      const timerCls  = remaining > 1800 ? 'time-plenty' : remaining > 600 ? 'time-warn' : 'time-urgent';
      timerHtml = '<div class="tc-timer-mini ' + timerCls + '" id="tct-' + r.id + '">'
                + fmtCountdown(remaining) + '</div>';
    }
  }
  const flagsCell = '<td>' + vetterBadge + timerHtml + '</td>';

  const st = _approvalState[r.id] || {};
  let statusHtml;
  if (st.status === 'pending') {
    statusHtml = '<span class="tc-submitting">Submitting&#8230;</span>';
  } else if (st.status === 'rejecting') {
    statusHtml = '<span class="tc-submitting">Rejecting&#8230;</span>';
  } else if (st.status === 'rejected' || r.rejected_at) {
    statusHtml = '<span class="tc-rejected">&#10007; Rejected</span>';
  } else if (st.status === 'ok') {
    statusHtml = '<span class="tc-submitted">&#10003; ' + esc(st.msg || 'Submitted') + '</span>';
  } else if (r.order_status === 'submitted' || r.order_status === 'pending') {
    statusHtml = '<span class="tc-submitted">&#10003; ' + r.order_status + '</span>';
  } else if (st.status === 'err') {
    statusHtml = '<span class="tc-error">&#x26A0; ' + esc(st.msg || 'Error') + '</span>';
  } else if (r.order_status === 'failed' || r.order_status === 'risk_rejected') {
    const dbMsg = r.order_status === 'risk_rejected'
      ? 'Risk rejected'
      : _parseAlpacaError(r.order_error_message);
    statusHtml = '<span class="tc-error">&#x26A0; ' + esc(dbMsg) + '</span>';
  } else if (r.vetter_excluded && isBuy) {
    statusHtml = '<span class="tc-error">&#x26A0; Vetter blocked</span>';
  } else if (!isActionable) {
    statusHtml = '<span class="act-hold">' + (ACTION_LABELS[r.action] || r.action.toUpperCase()) + '</span>';
  } else {
    statusHtml = '<span style="color:var(--text3)">—</span>';
  }
  const statusCell = '<td>' + statusHtml + '</td>';

  let actionsCell;
  if (approvable) {
    actionsCell = '<td class="tc-actions-cell">'
      + '<button class="btn-sm-approve" onclick="approveTrade(\'' + r.id + '\',\'immediate\')" title="Approve (MOO)">&#9654;</button>'
      + ' <button class="btn-sm-reject" onclick="rejectTrade(\'' + r.id + '\')" title="Reject">&#10005;</button>'
      + '</td>';
  } else {
    actionsCell = '<td></td>';
  }

  return '<tr class="' + rowCls + '" id="tc-' + r.id + '">'
    + chkCell + actionCell + tickerCell + rankCell + scoreCell + qtyCell + flagsCell + statusCell + actionsCell
    + '</tr>';
}

function updateTraderBadge() {
  const cnt = deltaData.filter(r => {
    if (!['entry', 'exit', 'buy_add', 'sell_trim'].includes(r.action)) return false;
    const st = _approvalState[r.id];
    if (st && (st.status === 'ok' || st.status === 'err' || st.status === 'rejected')) return false;
    const os = r.order_status;
    if (os === 'submitted' || os === 'pending' || os === 'failed' || os === 'risk_rejected') return false;
    if (r.rejected_at) return false;
    if ((r.action === 'entry' || r.action === 'buy_add') && r.vetter_excluded) return false;
    return true;
  }).length;
  const badge = $('nav-trade-badge');
  if (!badge) return;
  if (cnt > 0) {
    badge.textContent = cnt;
    badge.style.display = 'flex';
  } else {
    badge.style.display = 'none';
  }
}

/* ── Multi-select helpers ────────────────────────────────────────────── */
function toggleSelectAll() {
  const checked = $('select-all-trades').checked;
  deltaData.filter(_isApprovable).forEach(r => {
    if (checked) _selectedIntents.add(String(r.id));
    else         _selectedIntents.delete(String(r.id));
  });
  renderTrader();
}

function toggleSelectIntent(id, checked) {
  if (checked) _selectedIntents.add(String(id));
  else         _selectedIntents.delete(String(id));
  _syncSelectAllState();
}

function _syncSelectAllState() {
  const approvable = deltaData.filter(_isApprovable);
  const n = approvable.filter(r => _selectedIntents.has(String(r.id))).length;
  const allChk = $('select-all-trades');
  if (allChk) {
    allChk.checked       = n > 0 && n === approvable.length;
    allChk.indeterminate = n > 0 && n < approvable.length;
  }
  const btn = $('btn-approve-sel');
  const cnt = $('sel-count');
  if (btn) btn.disabled = n === 0;
  if (cnt) cnt.textContent = n > 0 ? n + ' selected' : '';
}

async function approveSelected() {
  const toApprove = [..._selectedIntents].filter(id =>
    deltaData.some(r => String(r.id) === id && _isApprovable(r))
  );
  if (!toApprove.length) return;
  _selectedIntents.clear();
  await Promise.all(toApprove.map(id => approveTrade(id, 'immediate')));
}

async function approveTrade(intentId, mode) {
  if (_approvalState[intentId]) return;
  _approvalState[intentId] = { status: 'pending' };
  renderTrader();
  try {
    const r = await fetch('/api/trade/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent_id: intentId, mode }),
    });
    const d = await r.json();
    if (!r.ok || d.error) {
      _approvalState[intentId] = { status: 'err', msg: d.error || d.detail || 'Failed' };
    } else if (d.status === 'duplicate') {
      _approvalState[intentId] = { status: 'ok', msg: 'Already submitted' };
    } else if (!d.risk_approved) {
      _approvalState[intentId] = { status: 'err', msg: 'Risk rejected: ' + (d.risk_reason || '') };
    } else if (d.status === 'failed') {
      _approvalState[intentId] = { status: 'err', msg: _parseAlpacaError(d.reason || d.error_message || 'Order failed') };
    } else {
      const modeLabel = mode === 'scheduled' ? 'MOO scheduled' : 'Market order sent';
      _approvalState[intentId] = { status: 'ok', msg: modeLabel + (d.alpaca_order_id ? ' (' + d.alpaca_order_id.substring(0, 8) + '…)' : '') };
    }
  } catch (e) {
    _approvalState[intentId] = { status: 'err', msg: String(e) };
  }
  renderTrader();
}

async function rejectTrade(intentId) {
  if (_approvalState[intentId]) return;
  _approvalState[intentId] = { status: 'rejecting' };
  renderTrader();
  try {
    const r = await fetch('/api/trade/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent_id: intentId }),
    });
    const d = await r.json();
    if (!r.ok) {
      _approvalState[intentId] = { status: 'err', msg: d.detail || 'Reject failed' };
    } else {
      _approvalState[intentId] = { status: 'rejected' };
    }
  } catch (e) {
    _approvalState[intentId] = { status: 'err', msg: String(e) };
  }
  renderTrader();
  updateTraderBadge();
}

async function purgeAll() {
  if (!confirm(
    'Reject all pending signals and cancel all open orders?\n\n' +
    'This will purge the entire current pipeline run. Run the pipeline again after this to generate fresh signals.'
  )) return;
  const btn = $('btn-purge-all');
  const statusEl = $('purge-status');
  if (btn) btn.disabled = true;
  if (statusEl) { statusEl.textContent = 'Purging…'; statusEl.style.display = ''; }
  try {
    const r = await fetch('/api/trade/purge-all', { method: 'POST' });
    const d = await r.json();
    if (r.ok) {
      const alpacaNote = d.alpaca_status && d.alpaca_status !== 'ok'
        ? ` (Alpaca: ${d.alpaca_status})`
        : '';
      if (statusEl) statusEl.textContent =
        `Purged: ${d.intents_rejected || 0} signals rejected, ${d.orders_canceled_locally || 0} orders canceled locally${alpacaNote}`;
      _approvalState = {};
      await loadDelta();
      await fetchOrders();
    } else {
      if (statusEl) statusEl.textContent = 'Purge failed: ' + (d.error || d.detail || 'unknown error');
    }
  } catch (e) {
    if (statusEl) statusEl.textContent = 'Purge failed: ' + String(e);
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ── Live portfolio ───────────────────────────────────────────────────── */
function sortLive(col) {
  if (liveSort.col === col) liveSort.dir *= -1;
  else { liveSort.col = col; liveSort.dir = -1; }
  renderLive();
}

async function loadLivePortfolio() {
  try {
    const d = await fetch('/api/live-portfolio').then(r => r.json());
    const dot   = $('conn-dot');
    const label = $('conn-label');
    const sync  = d.sync || {};
    liveSyncData = sync;

    if (!d.connected) {
      dot.className = 'conn-dot';
      label.textContent = 'Not connected';
      $('conn-sync').textContent = '';
      $('port-summary').style.display = 'none';
      $('port-not-connected').style.display = 'block';
      $('port-tbl-wrap').style.display = 'none';
      liveData = [];
      return;
    }

    dot.className = 'conn-dot connected';
    label.textContent = 'Connected — Paper Trading';
    if (sync.synced_at) {
      $('conn-sync').textContent = 'Synced ' + new Date(sync.synced_at).toLocaleTimeString();
    }

    $('port-value').textContent = fmtMoney(sync.account_value);
    $('port-bp').textContent = 'Buying Power: ' + fmtMoney(sync.buying_power);

    liveData = d.positions || [];
    const totalDayPL = liveData.reduce((s, p) => s + (p.day_pl || 0), 0);
    const plEl = $('port-pl');
    plEl.textContent = fmtPL(totalDayPL) + ' today';
    plEl.className = 'port-pl ' + (totalDayPL > 0 ? 'pl-pos' : totalDayPL < 0 ? 'pl-neg' : 'pl-neu');

    $('port-summary').style.display = 'block';
    $('port-not-connected').style.display = 'none';
    $('port-tbl-wrap').style.display = 'block';
    renderLive();
  } catch (e) {
    $('conn-label').textContent = 'Error loading portfolio';
  }
}

function renderLive() {
  const { col, dir } = liveSort;
  const rows = [...liveData].sort((a, b) => {
    const av = a[col], bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });

  const fmtShares = v => v == null ? '—' : (Math.abs(v) >= 100 ? (+v).toFixed(0) : (+v).toFixed(4));
  const rowsHtml = rows.map(p => {
    const dayPlCls = p.day_pl == null ? 'pl-neu' : p.day_pl > 0 ? 'pl-pos' : 'pl-neg';
    const plCls    = p.unrealized_pl == null ? 'pl-neu' : p.unrealized_pl > 0 ? 'pl-pos' : 'pl-neg';
    const plPctCls = p.unrealized_plpc == null ? 'pl-neu' : p.unrealized_plpc > 0 ? 'pl-pos' : 'pl-neg';
    const wt = p.weight != null ? (p.weight * 100).toFixed(1) + '%' : '—';
    return '<tr>'
      + '<td><span class="t-ticker">' + esc(p.ticker) + '</span></td>'
      + '<td class="t-wt">' + fmtMoney(p.market_value) + '</td>'
      + '<td class="t-wt">' + wt + '</td>'
      + '<td class="t-wt">' + fmtShares(p.qty) + '</td>'
      + '<td class="t-wt">' + fmtMoney(p.current_price) + '</td>'
      + '<td class="' + dayPlCls + '">' + fmtPL(p.day_pl) + '</td>'
      + '<td class="' + plCls + '">' + fmtPL(p.unrealized_pl) + '</td>'
      + '<td class="' + plPctCls + '">' + fmtPct(p.unrealized_plpc) + '</td>'
      + '</tr>';
  }).join('');

  // Cash row at bottom
  const sync = liveSyncData;
  let cashRow = '';
  if (sync.cash != null) {
    const cashPct = sync.account_value && sync.account_value > 0
      ? (sync.cash / sync.account_value * 100).toFixed(1) + '%'
      : '—';
    cashRow = '<tr class="cash-row">'
      + '<td><span class="t-ticker">CASH</span></td>'
      + '<td class="t-wt">' + fmtMoney(sync.cash) + '</td>'
      + '<td class="t-wt">' + cashPct + '</td>'
      + '<td colspan="5" class="t-wt">—</td>'
      + '</tr>';
  }

  $('live-body').innerHTML = rowsHtml + cashRow
    || '<tr><td colspan="8" class="tbl-empty">No positions</td></tr>';
}

async function syncAlpaca() {
  const btn = $('sync-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Syncing…'; }
  try {
    await fetch('/api/alpaca-sync', { method: 'POST' });
    await new Promise(r => setTimeout(r, 3000));
    await loadLivePortfolio();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '⇄ SYNC'; }
  }
}

async function fetchOrders() {
  try {
    const d = await fetch('/api/orders/recent').then(r => r.json());
    ordersData = Array.isArray(d) ? d : [];
  } catch (e) {
    ordersData = [];
  }
  renderOrders();
}

function renderOrders() {
  const section = $('orders-section');
  const tbody   = $('orders-body');
  if (!section || !tbody) return;

  if (ordersData.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = 'block';

  const statusLabel = {
    pending:       'Pending',
    submitted:     'Submitted',
    risk_rejected: 'Risk Rejected',
    failed:        'Failed',
    filled:        'Filled',
  };

  function dotClass(status) {
    if (status === 'submitted' || status === 'filled') return 'od-green';
    if (status === 'pending')                          return 'od-amber';
    return 'od-red'; // risk_rejected, failed
  }

  function fmtTime(submitted_at, created_at) {
    const ts = submitted_at || created_at;
    if (!ts) return '—';
    const d = new Date(ts);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return hh + ':' + mm;
  }

  function fmtQty(qty, notional) {
    if (qty != null) return (+qty).toFixed(0);
    if (notional != null) return '$' + (+notional).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    return '—';
  }

  // Check if ALL recent orders are failed — likely a credentials problem
  const failedOrders = ordersData.filter(o => o.status === 'failed');
  const banner = $('orders-error-banner');
  if (banner) {
    if (failedOrders.length > 0) {
      const firstErr = failedOrders[0].error_message || '';
      const parsed   = _parseAlpacaError(firstErr);
      let msg;
      if (firstErr.toLowerCase().includes('credentials not configured')) {
        msg = '&#x26A0; Trade-executor does not have Alpaca credentials. '
            + 'Fix: run <code>docker compose up -d trade-executor</code> on your server '
            + 'after confirming ALPACA_API_KEY and ALPACA_SECRET_KEY are in your .env file.';
      } else {
        msg = '&#x26A0; ' + failedOrders.length + ' order(s) failed'
            + (failedOrders.length === ordersData.length ? ' (all)' : '') + ': '
            + esc(parsed);
      }
      banner.style.display = 'block';
      banner.innerHTML = msg;
      banner.className = 'orders-error-banner';
    } else {
      banner.style.display = 'none';
    }
  }

  const html = ordersData.map(o => {
    const dot   = '<span class="od-dot ' + dotClass(o.status) + '"></span>';
    const label = statusLabel[o.status] || o.status;
    const fill  = o.avg_fill_price != null ? '$' + (+o.avg_fill_price).toFixed(2) : '—';
    // Show error reason inline for failed orders
    const errHtml = (o.status === 'failed' || o.status === 'risk_rejected') && o.error_message
      ? '<br><span class="od-err">' + esc(_parseAlpacaError(o.error_message)) + '</span>'
      : '';
    return '<tr>'
      + '<td><span class="t-ticker">' + esc(o.ticker) + '</span></td>'
      + '<td>' + esc(o.side) + '</td>'
      + '<td>' + fmtQty(o.qty, o.notional) + '</td>'
      + '<td>' + dot + label + errHtml + '</td>'
      + '<td>' + fmtTime(o.submitted_at, o.created_at) + '</td>'
      + '<td>' + fill + '</td>'
      + '</tr>';
  }).join('');

  tbody.innerHTML = html || '<tr><td colspan="6" class="tbl-empty">No recent orders</td></tr>';
}

/* ── Auto-approve countdown ticker ───────────────────────────────────── */
function updateAutoApproveCountdowns() {
  const fetchedAt = _aaStatus.fetchedAt || Date.now();
  const totalSecs = _aaStatus.auto_approve_minutes * 60;

  for (const aa of _aaStatus.pending) {
    const elapsed   = (Date.now() - fetchedAt) / 1000;
    const remaining = Math.max(0, aa.remaining_seconds - elapsed);
    const timerCls  = remaining > 1800 ? 'time-plenty' : remaining > 600 ? 'time-warn' : 'time-urgent';
    const textEl = document.getElementById('tct-' + aa.intent_id);
    if (textEl) {
      textEl.textContent = fmtCountdown(remaining);
      textEl.className   = 'tc-timer-mini ' + timerCls;
    }
  }
}

/* ── Job trigger ─────────────────────────────────────────────────────── */
async function startJob(tab) {
  const urls = {
    universe: '/api/jobs/universe',
    rank:     '/api/jobs/rank-chain',
    portfolio:'/api/jobs/portfolio',
  };
  if (!urls[tab]) return;
  const btn   = $('run-btn');
  const label = $('pb-label');
  _runRequestedAt = Date.now();
  if (btn)   btn.disabled = true;
  if (label) { label.textContent = 'QUEUED…'; label.className = 'pb-label running'; }
  try {
    await fetch(urls[tab], { method: 'POST' });
    // Trigger an immediate status poll so the bar updates within seconds
    setTimeout(refresh, 1500);
  } catch (e) {
    _runRequestedAt = 0;  // release lock on hard failure
    if (btn)   btn.disabled = false;
    if (label) { label.textContent = 'FAILED TO START'; label.className = 'pb-label failed'; }
  }
}

/* ── Main refresh loop ───────────────────────────────────────────────── */
async function refresh() {
  _lastRefreshAt = Date.now();
  try {
    const [pipelineRes, aaRes] = await Promise.all([
      fetch('/api/pipeline-status').then(r => r.json()).catch(() => null),
      fetch('/api/auto-approve-status').then(r => r.json()).catch(() => null),
    ]);

    if (pipelineRes) {
      const prev = _pipelineData;
      _pipelineData = pipelineRes;
      updateStatusBar(pipelineRes);
      updatePipelineBar(pipelineRes.rank || {}, pipelineRes.vetter || {});

      // On rank done transition, reload rankings
      const wasRunning = prev.rank && prev.rank.status === 'running';
      const nowDone    = pipelineRes.rank && (pipelineRes.rank.status === 'success' || pipelineRes.rank.status === 'partial_success');
      const prevNone   = !prev.rank || prev.rank.status === 'none' || prev.rank.status == null;
      if (wasRunning && nowDone) {
        loadRankings();
        loadRegime();
        loadDelta();
      } else if (prevNone && nowDone && !_initialLoadDone) {
        // On first boot, boot sequence already called loadRankings()/loadDelta() — skip
      }
    }

    if (aaRes) {
      _aaStatus = { ...aaRes, fetchedAt: Date.now() };
      // Re-render trader cards to pick up new countdown data
      if (document.getElementById('screen-trader').classList.contains('active')) {
        renderTrader();
      }
    }
  } catch (e) { /* ignore */ }

  loadDelta();
  fetchOrders();
}

/* ── 1-second ticker ─────────────────────────────────────────────────── */
setInterval(() => {
  updateClock();
  updateAutoApproveCountdowns();
  // Keep status bar text in sync with cached pipeline data when something is active
  const _rank = (_pipelineData || {}).rank || {};
  if (_aaStatus.pending.length > 0 || _rank.status === 'running') {
    updateStatusBar(_pipelineData || {});
  }
}, 1000);

/* ── 5-second lightweight status poll ───────────────────────────────── */
// Only refreshes the status bar and pipeline bar (not rankings/delta/portfolio).
// Catches running→idle transitions quickly without reloading all data.
setInterval(async () => {
  if (document.hidden) return;
  try {
    const r = await fetch('/api/pipeline-status').then(res => res.json()).catch(() => null);
    if (r) {
      const prevRank = (_pipelineData.rank || {}).status;
      _pipelineData = r;
      updateStatusBar(r);
      updatePipelineBar(r.rank || {}, r.vetter || {});
      // On running→done transition, trigger a full refresh so rankings/delta reload
      const nowRank = (r.rank || {}).status;
      if (prevRank === 'running' && (nowRank === 'success' || nowRank === 'partial_success')) {
        refresh();
      }
    }
  } catch (_e) { /* ignore */ }
}, 5000);

/* ── 30-second full refresh ──────────────────────────────────────────── */
setInterval(refresh, REFRESH_SECS * 1000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refresh();
});

/* ── Boot ────────────────────────────────────────────────────────────── */
(async () => {
  updateClock();
  await loadRegime();
  loadRankings();
  loadDelta();
  _initialLoadDone = true;
  $('rh-rank').classList.add('asc');
  refresh();
})();
