/* global state */
const $ = id => document.getElementById(id);

let rankData      = [];
let deltaData     = [];
let liveData      = [];
let liveSyncData  = {};
let ordersData    = [];

let rankSort  = { col: 'rank', dir: 1 };
let liveSort  = { col: 'market_value', dir: -1 };

let _searchMode    = false;   // true when showing API search results instead of top-N
let _searchData    = [];      // rows returned by /rankings/search
let _searchDebounce = null;   // setTimeout handle for debouncing keystrokes

let _clearedTrades   = new Set();  // intent ids dismissed from the trader UI (cosmetic only)
let _clearedRunId    = null;       // delta run_id the dismissals belong to
let _approvalState   = {};   // intent_id → { status, msg }
let _expandedTicker  = null;
let _pipelineData    = {};
let _prevPipelineData= {};
let _aaStatus        = { auto_approve_minutes: 60, pending: [], fetchedAt: Date.now() };
let _lastRefreshAt   = Date.now();
let _rankChainRunning= false;
let _runRequestedAt  = 0;      // ms timestamp of last Run click; button stays locked for RUN_LOCK_MS
let _initialLoadDone = false;  // prevents refresh() from double-loading on boot
let _rankingsLoadState = 'pending';  // 'pending' | 'ok' | 'empty' — drives status badge / table message

const RUN_LOCK_MS = 30000;     // keep button disabled for 30 s after clicking Run
let _selectedIntents = new Set();
let _completedExpanded = false; // trader tab: whether the Completed section is open

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
function _fmtDeferred(isoTs) {
  // Render an OPG-deferred order's wakeup time as "Queued — fires HH:MM ET"
  // so the operator can see the trade is parked, not lost.
  if (!isoTs) return 'Queued for OPG window';
  try {
    const d = new Date(isoTs);
    const hhmm = d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
    return 'Queued — fires ' + hhmm + ' ET';
  } catch (e) { return 'Queued for OPG window'; }
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
    const p = rank.pct != null ? '  ' + rank.pct + '%' : '';
    if (sl === 'Fetching Data')            { text = 'FETCHING DATA' + p;         textCls = 'sb-amber'; }
    else if (sl === 'Calculating Factors') { text = 'CALCULATING FACTORS' + p;  textCls = 'sb-amber'; }
    else if (sl === 'Ranking')             { text = 'RANKING STOCKS' + p;        textCls = 'sb-amber'; }
    else if (sl === 'Evaluating Signals')  { text = 'EVALUATING SIGNALS' + p;   textCls = 'sb-amber'; }
    else if (sl === 'Building Portfolio')  { text = 'BUILDING PORTFOLIO';        textCls = 'sb-blue'; }
    else if (sl === 'Vetting')             { text = 'LLM ANALYSIS';              textCls = 'sb-purple'; }
    else                                   { text = 'PIPELINE RUNNING' + p;      textCls = 'sb-amber'; }
  } else if (universe.status === 'running') {
    text = 'FETCHING UNIVERSE'; textCls = 'sb-blue';
  } else if (universe.status === 'failed') {
    text = 'UNIVERSE FETCH FAILED'; textCls = 'sb-red';
    sub = 'Set AV_API_KEY or MOCK_DATA=true and restart';
  } else if (rank.status === 'failed') {
    text = 'PIPELINE FAILED'; textCls = 'sb-red';
  } else if (rank.status === 'success' || rank.date) {
    // Don't say READY when the rankings table is empty — the user complaint:
    // "READY" + "No ranking data" is a contradiction. If rankings haven't
    // loaded successfully, show that state explicitly.
    if (_rankingsLoadState === 'empty') {
      text = 'NO DATA'; textCls = 'sb-amber';
      sub = 'Click ▶ RUN to populate';
    } else {
      text = 'READY'; textCls = 'sb-green';
      if (rank.date) sub = 'Ranked ' + rank.date;
    }
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
  // Don't let recentlyRequested keep the bar "running" if the pipeline already
  // reached a terminal state — a fast run that completes within 30 s would
  // otherwise show "QUEUED…" instead of "READY".
  const showAsRunning = running || (vetRunning && !success && !failed) || (recentlyRequested && !success && !failed);
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

}

/* ── Regime ───────────────────────────────────────────────────────────── */
async function loadRegime() {
  try {
    const d = await fetch('/api/regime').then(r => r.json());
    const regime = d.regime || 'unknown';
    const sbReg = $('sb-regime');
    sbReg.textContent = regime.toUpperCase().replace(/_/g, ' ');
    sbReg.className = 'regime-pill regime-' + regime;
    // spy_price available but stat boxes removed from screener
  } catch (e) {
    const sbReg = $('sb-regime');
    sbReg.textContent = '—';
    sbReg.className = 'regime-pill regime-unknown';
  }
}

/* ── Rankings search ─────────────────────────────────────────────────── */
function _mapRankRow(r) {
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
}

function onSearchInput() {
  clearTimeout(_searchDebounce);
  const q = ($('r-search').value || '').trim().toUpperCase();
  if (!q) {
    _searchMode = false;
    _searchData = [];
    renderRankings();
    return;
  }
  // Show "searching…" immediately so the user gets feedback
  $('r-count').textContent = 'searching…';
  _searchDebounce = setTimeout(() => _doApiSearch(q), 300);
}

async function _doApiSearch(q) {
  try {
    const d = await fetch('/api/rankings/search?q=' + encodeURIComponent(q)).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    _searchMode = true;
    _searchData = (d.rankings || []).map(_mapRankRow);
    renderRankings();
  } catch (_) {
    // On error fall back to client-side filter from loaded data
    _searchMode = false;
    _searchData = [];
    renderRankings();
  }
}

/* ── Rankings ────────────────────────────────────────────────────────── */
async function loadRankings() {
  $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">Loading rankings&#8230;</td></tr>';
  try {
    const d = await fetch('/api/rankings/with-overlays?limit=100').then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    if (!d.rankings || d.rankings.length === 0) {
      _rankingsLoadState = 'empty';
      rankData = [];
      $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">'
        + 'No ranking data &mdash; click <strong>&#9654; RUN</strong> to populate'
        + '</td></tr>';
      // Refresh status bar so READY badge is downgraded if data missing
      if (_pipelineData && _pipelineData.rank) updateStatusBar(_pipelineData);
      return;
    }
    _rankingsLoadState = 'ok';
    rankData = (d.rankings || []).map(_mapRankRow);
    // Clear any stale search state so the fresh top-N is shown
    _searchMode = false;
    _searchData = [];
    _expandedTicker = null;
    renderRankings();
  } catch (e) {
    _rankingsLoadState = 'empty';
    rankData = [];
    $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">'
      + 'No ranking data &mdash; click <strong>&#9654; RUN</strong> to populate'
      + '</td></tr>';
    if (_pipelineData && _pipelineData.rank) updateStatusBar(_pipelineData);
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

  // In search mode the API already filtered by ticker prefix — only apply the
  // held/excl toggles locally. Otherwise filter client-side from the top-N set.
  const base = _searchMode ? _searchData : rankData.filter(r => {
    if (q && !r.ticker.startsWith(q)) return false;
    return true;
  });
  let rows = base.filter(r => {
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
  $('r-count').textContent = _searchMode
    ? rows.length + ' result' + (rows.length !== 1 ? 's' : '') + ' for ‘' + q + '’'
    : rows.length + ' / ' + rankData.length;
  if (!rows.length) {
    _expandedTicker = null;
    $('r-body').innerHTML = '<tr><td colspan="10" class="tbl-empty">No results</td></tr>';
    return;
  }

  const html = rows.map(r => {
    const pctCls = pctColor(r.percentile);
    const pctVal = r.percentile != null ? (+r.percentile * 100).toFixed(0) + '%' : '—';

    // Trend arrow shows the rank's direction over the last 5 runs (REGR_SLOPE).
    // Negative slope = rank number falling = stock improving. The slope smooths
    // single-day jitter, matching the system's 5-day-confirmation philosophy.
    // Before 5 runs of history exist the slope is computed over however many
    // runs are available (e.g. on day 2 it equals the 1-day diff). The prior_rank
    // 1-day diff is only a fallback for tickers too new to have any slope at all.
    let arrow = '';
    if (r.rank_slope != null && Math.abs(r.rank_slope) >= 1) {
      const mag = Math.round(Math.abs(r.rank_slope));
      arrow = r.rank_slope < 0
        ? '<span class="rank-up" title="trending up ~' + mag + '/run (5-run slope)">&#9650;' + mag + '</span>'
        : '<span class="rank-dn" title="trending down ~' + mag + '/run (5-run slope)">&#9660;' + mag + '</span>';
    } else if (r.prior_rank != null) {
      const delta = r.prior_rank - r.rank;
      if (delta >= 2)       arrow = '<span class="rank-up" title="up ' + delta + ' since last run">&#9650;' + delta + '</span>';
      else if (delta <= -2) arrow = '<span class="rank-dn" title="down ' + (-delta) + ' since last run">&#9660;' + (-delta) + '</span>';
    }

    const flags = [];
    if (r.held)           flags.push('<span class="overlay-badge held">HOLDINGS</span>');
    if (r.not_in_universe) flags.push('<span class="overlay-badge not-ranked" title="Held but not in ranking universe">NOT RANKED</span>');
    if (r.vetter_excluded) flags.push('<span class="overlay-badge excl" title="' + esc(r.vetter_reason || '') + '">&#9888; ' + (r.vetter_risk_type || '').toUpperCase().replace(/_/g,' ') + '</span>');
    const flagsHtml = flags.length ? flags.join('') : '<span style="color:var(--text3)">—</span>';

    const FACTORS = ['momentum', 'quality', 'value', 'growth', 'low_volatility', 'liquidity'];
    const factorCells = FACTORS.map(f => '<td class="' + zColor(r[f]) + '">' + (r[f] != null ? (+r[f]).toFixed(2) : '—') + '</td>').join('');

    const heldCls     = r.held ? ' row-held' : '';
    const exclCls     = r.vetter_excluded ? ' row-excluded' : '';
    const expandedCls = _expandedTicker === r.ticker ? ' expanded' : '';

    return '<tr class="rank-row' + heldCls + exclCls + expandedCls + '" id="rank-row-' + esc(r.ticker) + '" onclick="toggleDetail(\'' + esc(r.ticker) + '\',this)">'
      + '<td><span class="t-rank">' + r.rank + '</span>' + arrow + '</td>'
      + '<td><span class="t-ticker">' + r.ticker + '</span></td>'
      + '<td class="t-company" title="' + (r.name ? esc(r.name) : '') + '">' + (r.name ? esc(r.name) : '—') + '</td>'
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
  td.colSpan = 11;
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
    const crashed = !!r.vetter_crashed;
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

  const heldHtml = r.held ? '<div class="detail-held-note">HOLDINGS — ' + (r.qty != null ? r.qty + ' shares' : 'position') + '</div>' : '';
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
    _loadClearedTrades(run.run_id || run.run_date || null);
    const dateEl = $('ds-date');
    if (dateEl) dateEl.textContent = run.run_date || '—';
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
// The trader screen is an order blotter — only these four actionable order types
// appear there (Buy to Open / Buy to Add / Sell to Close / Sell to Trim).
// hold / watch / at_risk are informational and live on the screener instead.
const TRADE_ACTIONS = ['entry', 'buy_add', 'exit', 'sell_trim'];
const ACTION_LABELS = {
  exit: 'Sell to Close', sell_trim: 'Sell to Trim',
  entry: 'Buy to Open', buy_add: 'Buy to Add',
  hold: 'Hold', watch: 'Hold - Watch', at_risk: 'AT RISK',
};
const ACTION_PILL = {
  exit: 'pill-sell-exit', sell_trim: 'pill-sell-trim',
  entry: 'pill-buy-enter', buy_add: 'pill-buy-add',
  hold: 'pill-hold', watch: 'pill-watch', at_risk: 'pill-at-risk',
};

/* Classify an intent into one of three display sections:
 *   'attention'  — needs operator action: awaiting approval, failed, or vetter-blocked buy
 *   'progress'   — submitted to broker and in-flight; no action needed yet
 *   'completed'  — filled, rejected, hold/watch; no action possible
 */
function _sectionFor(r) {
  const os = r.order_status;
  const st = _approvalState[r.id] || {};

  // Local approval-state takes priority over DB state (UI is ahead of next refresh)
  if (st.status === 'pending' || st.status === 'rejecting') return 'progress';
  if (st.status === 'queued') return 'progress';
  if (st.status === 'ok') return 'progress';
  if (st.status === 'rejected') return 'completed';
  if (st.status === 'err') return 'attention';

  // DB order status
  if (os === 'submitted' || os === 'pending' || os === 'deferred') return 'progress';
  if (os === 'filled' || os === 'partial_fill') return 'completed';
  if (os === 'failed' || os === 'risk_rejected') return 'attention';
  if (r.rejected_at) return 'completed';

  // No order yet — check if approvable
  if (_isApprovable(r)) return 'attention';

  // Vetter-excluded buy with no order: show in attention so operator can investigate
  const isBuy = r.action === 'entry' || r.action === 'buy_add';
  if (isBuy && r.vetter_excluded) return 'attention';

  // Hold, watch, at_risk, and any other non-actionable state
  return 'completed';
}

function _isApprovable(r) {
  if (!['entry', 'exit', 'buy_add', 'sell_trim'].includes(r.action)) return false;
  if (_approvalState[r.id]) return false;
  const os = r.order_status;
  if (os === 'submitted' || os === 'pending' || os === 'deferred' || os === 'failed' || os === 'risk_rejected' || os === 'filled' || os === 'partial_fill') return false;
  if (r.rejected_at) return false;
  if ((r.action === 'entry' || r.action === 'buy_add') && r.vetter_excluded) return false;
  return true;
}

function toggleCompleted() {
  _completedExpanded = !_completedExpanded;
  renderTrader();
}

function renderTrader() {
  // Hide trades the user has cleared from the view (cosmetic only — the intents
  // and any orders are untouched; clearing survives the polling refresh and
  // resets automatically when a new delta run appears).
  const visible = deltaData.filter(r => !_clearedTrades.has(String(r.id)));
  // Order blotter: show only actionable orders (buy open / buy add / sell close /
  // sell trim). hold / watch / at_risk are informational and excluded here.
  const orders = visible.filter(r => TRADE_ACTIONS.includes(r.action));
  const sorted = [...orders]
    .sort((a, b) => {
      const ao = ACTION_ORDER[a.action] ?? 99;
      const bo = ACTION_ORDER[b.action] ?? 99;
      return ao - bo || (a.rank ?? 999) - (b.rank ?? 999);
    });

  // Split intents into three sections
  const attentionItems = [];
  const progressItems  = [];
  const completedItems = [];
  for (const r of sorted) {
    const s = _sectionFor(r);
    if      (s === 'attention') attentionItems.push(r);
    else if (s === 'progress')  progressItems.push(r);
    else                        completedItems.push(r);
  }

  // Update live-count chips (reflect the order blotter)
  const hasData = orders.length > 0;
  const pendEl = $('ds-pending');  if (pendEl)  pendEl.textContent  = hasData ? attentionItems.length : '—';
  const flEl   = $('ds-inflight'); if (flEl)    flEl.textContent    = hasData ? progressItems.length  : '—';
  const doneEl = $('ds-done');     if (doneEl)  doneEl.textContent  = hasData ? completedItems.length : '—';

  // Toolbar: visible whenever any signals exist
  const toolbar = $('trader-toolbar');
  if (toolbar) toolbar.style.display = hasData ? '' : 'none';

  const tbody = $('trader-body');
  if (!tbody) return;

  if (sorted.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="tbl-empty">No orders — <strong>all clear</strong></td></tr>';
    _syncSelectAllState();
    updateTraderBadge();
    return;
  }

  // Auto-expand completed section when there is nothing actionable
  const autoExpand = attentionItems.length === 0 && progressItems.length === 0;
  const showCompleted = _completedExpanded || autoExpand;

  const rows = [];

  // ── Section 1: Needs Attention ───────────────────────────────────────────
  if (attentionItems.length > 0) {
    const approvableCount = attentionItems.filter(_isApprovable).length;
    let hdrLabel, hdrDetail;
    if (approvableCount > 0) {
      hdrLabel = '&#9888; Needs Attention';
      hdrDetail = ' — ' + approvableCount + ' awaiting approval';
    } else {
      // Only failures / vetter-blocks visible — no action to take
      hdrLabel = '&#9888; Order Failures';
      hdrDetail = '';
    }
    rows.push('<tr class="tr-section-attention"><td colspan="8">'
      + hdrLabel + hdrDetail
      + '</td></tr>');
    for (const r of attentionItems) rows.push(_buildTradeRow(r));
  }

  // ── Section 2: In Progress ───────────────────────────────────────────────
  if (progressItems.length > 0) {
    const n = progressItems.length;
    rows.push('<tr class="tr-section-progress"><td colspan="8">'
      + 'In Progress — ' + n + ' order' + (n === 1 ? '' : 's') + ' submitted to broker'
      + '</td></tr>');
    for (const r of progressItems) rows.push(_buildTradeRow(r));
  }

  // ── Section 3: Completed (collapsible) ──────────────────────────────────
  if (completedItems.length > 0) {
    const arrow = showCompleted ? '▼' : '▶';
    rows.push('<tr class="tr-section-completed" onclick="toggleCompleted()"><td colspan="8">'
      + '<span class="completed-toggle" aria-hidden="true">' + arrow + '</span>'
      + ' Completed &amp; Holds — ' + completedItems.length
      + '</td></tr>');
    if (showCompleted) {
      for (const r of completedItems) rows.push(_buildTradeRow(r));
    }
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
  const targetPct = r.current_weight != null
    ? (r.current_weight * 100).toFixed(1) + '%'
    : '—';
  const targetCell = '<td class="t-num">' + targetPct + '</td>';

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
  } else if (st.status === 'queued') {
    statusHtml = '<span class="tc-queued">&#9203; ' + esc(st.msg || 'Queued') + '</span>';
  } else if (r.order_status === 'submitted') {
    statusHtml = '<span class="tc-submitted">&#10003; Submitted</span>';
  } else if (r.order_status === 'pending') {
    statusHtml = '<span class="tc-submitted">&#10003; Submitting&#8230;</span>';
  } else if (r.order_status === 'deferred') {
    statusHtml = '<span class="tc-queued">&#9203; ' + esc(_fmtDeferred(r.order_deferred_until)) + '</span>';
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
    + chkCell + actionCell + tickerCell + rankCell + targetCell + flagsCell + statusCell + actionsCell
    + '</tr>';
}

function updateTraderBadge() {
  // Badge = only items requiring a human DECISION (approve or reject).
  // Failed orders and vetter-blocked buys appear in the Needs Attention section
  // for visibility, but don't inflate the badge — there's nothing to click on them.
  const cnt = deltaData.filter(_isApprovable).length;
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
    } else if (d.status === 'deferred') {
      _approvalState[intentId] = { status: 'queued', msg: _fmtDeferred(d.deferred_until) };
    } else if (d.status === 'failed') {
      _approvalState[intentId] = { status: 'err', msg: _parseAlpacaError(d.reason || d.error_message || 'Order failed') };
    } else {
      _approvalState[intentId] = { status: 'ok', msg: 'Submitted' + (d.alpaca_order_id ? ' (' + d.alpaca_order_id.substring(0, 8) + '…)' : '') };
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

// ── Clear approved trades (cosmetic UI-only) ─────────────────────────────────
// Hides already-actioned rows (anything not awaiting a human decision) from the
// trader view. No orders are canceled and no intents are rejected — the dismissal
// is stored client-side, keyed by the current delta run_id, so it survives the
// polling refresh and auto-resets when a new delta run produces a fresh proposal.

function _clearedKey(runId) { return 'clearedTrades:' + (runId || 'none'); }

function _loadClearedTrades(runId) {
  if (runId === _clearedRunId) return;   // same run — keep current dismissals
  _clearedRunId = runId;
  try {
    // Drop dismissal sets for any older run so localStorage doesn't grow.
    Object.keys(localStorage).forEach(k => {
      if (k.startsWith('clearedTrades:') && k !== _clearedKey(runId)) localStorage.removeItem(k);
    });
    const raw = localStorage.getItem(_clearedKey(runId));
    _clearedTrades = new Set(raw ? JSON.parse(raw) : []);
  } catch (e) {
    _clearedTrades = new Set();
  }
}

function _persistClearedTrades() {
  try {
    localStorage.setItem(_clearedKey(_clearedRunId), JSON.stringify([..._clearedTrades]));
  } catch (e) { /* localStorage unavailable — dismissals are session-only */ }
}

function clearApprovedTrades() {
  // Dismiss every row that is NOT awaiting a human approval decision, i.e. the
  // approved/submitted/filled/rejected/failed and hold/watch rows.
  deltaData.forEach(r => { if (!_isApprovable(r)) _clearedTrades.add(String(r.id)); });
  _persistClearedTrades();
  renderTrader();
  updateTraderBadge();
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
