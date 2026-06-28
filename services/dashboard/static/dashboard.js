/* global state */
const $ = id => document.getElementById(id);

let rankData      = [];
let deltaData     = [];
let liveData      = [];
let liveSyncData  = {};
let ordersData    = [];

let rankSort  = { col: 'rank', dir: 1 };
let liveSort  = { col: 'market_value', dir: -1 };
let targetSort = { col: 'rank', dir: 1 };   // Target tab table sort
let targetRows = [];                         // merged held∪target rows for the Target tab
let _fullRankByTicker = {};                  // ticker → full-universe rank record (Target tab
                                             // detail cards: a target/held name ranked beyond
                                             // the screener's top-100 must still resolve its
                                             // real rank/score/factors, not look "not in universe")
let targetPortfolioRun = null;               // /portfolio run summary (portfolio_beta, est vol)
let _expandedTargetTicker = null;            // Target tab detail-expansion state

// Navigate-typeahead state. The search box no longer FILTERS the list — it shows a
// helper dropdown of matches; selecting one scrolls/highlights that row in the full
// list (fetching+injecting the row if it's ranked outside the displayed window).
let _suggestMatches = [];      // [{ticker,name,rank}] from /rankings/suggest
let _suggestActive  = -1;      // highlighted dropdown index (keyboard nav); -1 = none
let _searchDebounce = null;    // setTimeout handle for debouncing keystrokes
let _flashTimer     = null;    // setTimeout handle for clearing the row-flash highlight

// ── Screener virtualization + lazy-overlay state ────────────────────────────
// The screener now renders the ENTIRE ranked universe (thousands of rows) via a
// windowed (virtualized) table: only the visible rows (+ a buffer) are in the DOM,
// with top/bottom spacer <tr>s sized to preserve the full scroll height.
const RANK_ROW_H   = 38;   // px — MUST match #screen-screener tr.rank-row height in CSS
const RANK_BUFFER  = 12;   // extra rows rendered above/below the viewport
let   _sortedRank  = [];   // the currently-sorted full array renderRankings windows over
let   _overlayCache = {};  // ticker → merged heavy overlay fields (session cache)
let   _overlayInflight = {}; // ticker → Promise (dedupe concurrent lazy fetches)
let   _loadedRunId = null;    // run_id the overlay cache was populated against — when a
                              // NEW ranking run lands the cached overlays (prior_rank /
                              // rank_slope arrow inputs AND factor_scores like
                              // earnings_surprise) are stale and must be dropped, else the
                              // Screener shows stale values while the Target tab (always
                              // fresh) shows the current one. Keyed on run_id, NOT rank_date:
                              // a same-date RE-RUN (e.g. a fresh build after an earnings
                              // ingest, same rank_date) changes the run_id but not the date,
                              // so a date-keyed check would never invalidate (the bug that
                              // left earnings_surprise showing "—" on a same-day re-run).
let   _flashTicker  = null; // ticker whose row should currently carry the flash class
                            // (re-applied on each window repaint — a virtualized row
                            //  is destroyed/recreated on scroll, so the class can't
                            //  live only on the DOM node)

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
  // A deferred order is parked for the next market open (the fill-gated drain
  // submits it then). Show the wakeup time when known — "Queued — fires HH:MM ET"
  // — else a generic "Queued for next open" (deferred_until is NULL when the
  // Alpaca clock was unreadable at approval; the drain still fires it at the open).
  if (!isoTs) return 'Queued for next open';
  try {
    const d = new Date(isoTs);
    const hhmm = d.toLocaleTimeString('en-US', {
      timeZone: 'America/New_York',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
    return 'Queued — fires ' + hhmm + ' ET';
  } catch (e) { return 'Queued for next open'; }
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
function capTier(mcap) {
  // Market-cap tier for the SIZE column. null when unknown (ETFs/funds, no fundamentals).
  if (mcap == null || !(mcap > 0)) return null;
  if (mcap >= 200e9) return { label: 'MEGA',  cls: 'cap-mega' };
  if (mcap >= 10e9)  return { label: 'LARGE', cls: 'cap-large' };
  if (mcap >= 2e9)   return { label: 'MID',   cls: 'cap-mid' };
  if (mcap >= 3e8)   return { label: 'SMALL', cls: 'cap-small' };
  return { label: 'MICRO', cls: 'cap-micro' };
}
function fmtCap(mcap) {
  if (mcap == null || !(mcap > 0)) return 'unknown';
  if (mcap >= 1e12) return '$' + (mcap / 1e12).toFixed(2) + 'T';
  if (mcap >= 1e9)  return '$' + (mcap / 1e9).toFixed(1) + 'B';
  if (mcap >= 1e6)  return '$' + (mcap / 1e6).toFixed(0) + 'M';
  return '$' + Math.round(mcap);
}

/* ── Screen navigation ───────────────────────────────────────────────── */
function showScreen(name, btnEl) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('screen-' + name).classList.add('active');
  if (btnEl) btnEl.classList.add('active');
  if (name === 'portfolio') { loadLivePortfolio(); fetchOrders(); }
  if (name === 'trader')    renderTrader();
  if (name === 'target')    loadTargetPortfolio();
}

/* ── Clock ───────────────────────────────────────────────────────────── */
function updateClock() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');
  const el = $('sb-clock');           // removed from the status bar (RUN button took its place)
  if (el) el.textContent = hh + ':' + mm + ':' + ss;
}

/* ── Status bar ──────────────────────────────────────────────────────── */
// Keep-last-good for the vetter's live progress. The {completed,total} travels
// two hops (dashboard → api /system/status → llm-vetter), each with a 6s timeout;
// while the vetter is busy with per-ticker LLM calls that field intermittently
// drops out of a poll, which made the label flip between "VETTER x/y · n%" and a
// bare "VETTER". Cache the last-good value (scoped to the run) and reuse it while
// the same run is still running, so the bar stays steady through the dropouts.
let _lastVetterProgress = null;   // { runId, progress:{completed,total} }

function _resolveVetterProgress(vetter) {
  const p = vetter.progress;
  const live = (p && p.total > 0) ? p : null;
  if (vetter.status !== 'running') {
    _lastVetterProgress = null;   // run ended → forget last-good (don't leak to next run)
    return live;
  }
  if (live) {
    _lastVetterProgress = { runId: vetter.run_id || null, progress: live };
    return live;
  }
  // Running but no live progress this poll → reuse last-good for the SAME run.
  if (_lastVetterProgress && _lastVetterProgress.runId === (vetter.run_id || null)) {
    return _lastVetterProgress.progress;
  }
  return null;
}

// Same keep-last-good for the pipeline sub-step % (factors/ranking/delta). rank.pct
// comes from the pipeline's /runs/progress, which can time out on a busy poll and
// blink the % off the label ("CALCULATING FACTORS 25%" → "CALCULATING FACTORS").
// Cache scoped to the step label so a stale factors % can't leak into ranking/delta.
let _lastRankPct = null;   // { step, pct }

function _resolveRankPct(rank) {
  if (rank.status !== 'running') { _lastRankPct = null; return rank.pct != null ? rank.pct : null; }
  const step = rank.step_label || '';
  if (rank.pct != null) { _lastRankPct = { step, pct: rank.pct }; return rank.pct; }
  if (_lastRankPct && _lastRankPct.step === step) return _lastRankPct.pct;  // dropout → last-good
  return null;
}

function updateStatusBar(d) {
  const rank      = d.rank      || {};
  const vetter    = d.vetter    || {};
  const portfolio = d.portfolio || {};
  const universe  = d.universe  || {};

  let text = 'IDLE', textCls = 'sb-gray';
  let sub = '', subCls = '';

  if (vetter.status === 'running') {
    const p = _resolveVetterProgress(vetter);
    if (p && p.total > 0) {
      const pct = Math.min(100, Math.round((p.completed / p.total) * 100));
      text = 'VETTER ' + p.completed + '/' + p.total + ' · ' + pct + '%';
    } else {
      text = 'VETTER';
    }
    textCls = 'sb-purple';
  } else if (portfolio.status === 'running') {
    text = 'BUILDING PORTFOLIO'; textCls = 'sb-blue';
  } else if (rank.status === 'running') {
    const sl = rank.step_label || '';
    const _rp = _resolveRankPct(rank);
    const p = _rp != null ? '  ' + _rp + '%' : '';
    if (sl === 'Fetching Data')            { text = 'FETCHING DATA' + p;         textCls = 'sb-amber'; }
    else if (sl === 'Calculating Factors') { text = 'CALCULATING FACTORS' + p;  textCls = 'sb-amber'; }
    else if (sl === 'Ranking')             { text = 'RANKING STOCKS' + p;        textCls = 'sb-amber'; }
    else if (sl === 'Delta Eval')          { text = 'DELTA EVAL' + p;           textCls = 'sb-amber'; }
    else if (sl === 'Building Portfolio')  { text = 'BUILDING PORTFOLIO';        textCls = 'sb-blue'; }
    else if (sl === 'Vetter')              { text = 'VETTER';                    textCls = 'sb-purple'; }
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

  // Override with auto-approve countdown only when NO chain step is running. The
  // countdown reflects the latest COMPLETED delta; while any step of a fresh chain
  // is in flight (vetter/portfolio/rank/universe) that delta is the prior cycle's
  // and about to be replaced, so the timer must not overwrite the live step label.
  // (The backend also empties the pending list while a chain runs — belt + braces.)
  const _chainBusy = rank.status === 'running' || vetter.status === 'running'
    || portfolio.status === 'running' || universe.status === 'running';
  if (!_chainBusy) {
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
  // The RUN button now lives in the status bar; lock it while the chain runs.
  if (btn) btn.disabled = showAsRunning;
  // The inline pipeline-bar was removed — its state is shown in the top status
  // bar (updateStatusBar). Bail out if those elements aren't in the DOM.
  if (!dot || !label) return;
  dot.className   = 'pb-dot'   + (showAsRunning ? ' running' : success ? ' success' : failed ? ' failed' : '');
  label.className = 'pb-label' + (showAsRunning ? ' running' : success ? ' success' : failed ? ' failed' : '');

  let labelText, barPct;
  if (running) {
    labelText = rank.step_label || 'RUNNING';
    barPct = _resolveRankPct(rank);
  } else if (recentlyRequested) {
    labelText = 'QUEUED…';
    barPct = null;
  } else if (vetRunning) {
    const vp = _resolveVetterProgress(vetter);
    if (vp && vp.total > 0) {
      const vpct = Math.min(100, Math.round((vp.completed / vp.total) * 100));
      labelText = 'VETTER ' + vp.completed + '/' + vp.total;
      barPct = vpct;
    } else {
      labelText = 'VETTER';
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
  // Null-guard the element: if #sb-regime is ever absent (markup change, partial
  // DOM), .textContent on null throws — and since loadRegime is the FIRST awaited
  // boot step, that aborts the whole init chain and loadDelta() never runs, leaving
  // the trader/holdings panels frozen on "Loading…". The catch must NOT re-deref a
  // possibly-null element either. (Proven by tests/dashboard/test_holdings_render_playwright.py.)
  const setReg = (text, cls) => {
    const sbReg = $('sb-regime');
    if (!sbReg) return;
    sbReg.textContent = text;
    sbReg.className = cls;
  };
  try {
    const d = await fetch('/api/regime').then(r => r.json());
    const regime = d.regime || 'unknown';
    setReg(regime.toUpperCase().replace(/_/g, ' '), 'regime-pill regime-' + regime);
    // spy_price available but stat boxes removed from screener
  } catch (e) {
    setReg('—', 'regime-pill regime-unknown');
  }
}

/* ── Rankings search ─────────────────────────────────────────────────── */
function _mapRankRow(r) {
  const fs = r.factor_scores || {};
  return {
    rank: r.rank, ticker: r.ticker, name: r.name || null,
    cluster_id: r.cluster_id || null,
    market_cap: r.market_cap != null ? +r.market_cap : null,
    composite_score: r.composite_score, percentile: r.percentile,
    momentum: fs.momentum, quality: fs.quality, value: fs.value,
    growth: fs.growth, low_volatility: fs.low_volatility, liquidity: fs.liquidity,
    earnings_surprise: fs.earnings_surprise, near_high: fs.near_high,
    drawdown_21d: fs.drawdown_21d != null ? +fs.drawdown_21d : null,
    excess_dd_21d: fs.excess_dd_21d != null ? +fs.excess_dd_21d : null,
    idio_vol: fs.idio_vol != null ? +fs.idio_vol : null,
    excess_dd_limit: fs.excess_dd_limit != null ? +fs.excess_dd_limit : null,
    beta: fs.beta != null ? +fs.beta : null,
    rank_date: r.rank_date, regime: r.regime,
    rank_slope: r.rank_slope != null ? +r.rank_slope : null,
    prior_rank: r.prior_rank != null ? +r.prior_rank : null,
    held: !!r.held, qty: r.qty, market_value: r.market_value,
    unrealized_plpc: r.unrealized_plpc,
    vetter_excluded: !!r.vetter_excluded,
    vetter_confidence: r.vetter_confidence,
    vetter_risk_type: r.vetter_risk_type,
    vetter_reason: r.vetter_reason,
    vetter_crashed: !!r.vetter_crashed,
    positive_catalyst: !!r.positive_catalyst,
    positive_reason: r.positive_reason,
    not_in_universe: !!r.not_in_universe,
  };
}

/* ── Navigate-typeahead ──────────────────────────────────────────────────
 * The search box is a JUMP control, not a list filter. As the user types we show
 * a dropdown of matching tickers (ticker contains OR company name contains, from
 * /rankings/suggest). Selecting one — click, Enter, or Arrow+Enter — scrolls the
 * main list to that row and flashes it; the list itself is never filtered.       */
function onSearchInput() {
  clearTimeout(_searchDebounce);
  _clearSearchNote();
  const raw = ($('r-search').value || '').trim();
  const clr = $('r-search-clear');
  if (clr) clr.style.display = raw ? '' : 'none';
  if (!raw) {
    _hideSuggest();
    return;
  }
  // Debounce the suggest fetch; show local matches instantly for snappy feedback.
  _renderSuggest(_localSuggest(raw));
  _searchDebounce = setTimeout(() => _fetchSuggest(raw), 200);
}

function clearSearch() {
  const el = $('r-search');
  if (el) el.value = '';
  _hideSuggest();
  _clearSearchNote();
  const clr = $('r-search-clear');
  if (clr) clr.style.display = 'none';
  if (el) el.focus();
}

// Local fallback / instant matches from already-loaded rows. Mirrors the API's
// contains-on-ticker-or-name so the dropdown isn't empty while the fetch is in flight.
function _localSuggest(q) {
  const u = q.toUpperCase();
  const out = [];
  for (const r of rankData) {
    const tk = (r.ticker || '').toUpperCase();
    const nm = (r.name || '').toUpperCase();
    if (tk.includes(u) || nm.includes(u)) {
      out.push({ ticker: r.ticker, name: r.name, rank: r.rank });
    }
    if (out.length >= 20) break;
  }
  // Exact ticker → ticker-prefix → other, then rank asc (mirror the API ordering).
  out.sort((a, b) => {
    const at = (a.ticker || '').toUpperCase(), bt = (b.ticker || '').toUpperCase();
    const ax = at === u ? 0 : at.startsWith(u) ? 1 : 2;
    const bx = bt === u ? 0 : bt.startsWith(u) ? 1 : 2;
    return ax - bx || (a.rank ?? 1e9) - (b.rank ?? 1e9);
  });
  return out;
}

async function _fetchSuggest(q) {
  try {
    const d = await fetch('/api/rankings/suggest?q=' + encodeURIComponent(q) + '&limit=20')
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    // Ignore a stale response if the box moved on.
    if (($('r-search').value || '').trim() !== q) return;
    _renderSuggest(d.matches || []);
  } catch (_) {
    // Keep whatever local matches are showing; don't blank the dropdown on a blip.
  }
}

function _renderSuggest(matches) {
  _suggestMatches = matches || [];
  _suggestActive = -1;
  const dd = $('r-search-dd');
  if (!dd) return;
  if (!_suggestMatches.length) {
    dd.innerHTML = '<div class="search-dd-empty">No matching tickers</div>';
    dd.style.display = '';
    return;
  }
  dd.innerHTML = _suggestMatches.map((m, i) =>
    '<div class="search-dd-item" data-idx="' + i + '" onmousedown="onSuggestPick(event,' + i + ')">'
    + '<span class="sd-ticker">' + esc(m.ticker) + '</span>'
    + '<span class="sd-name">' + (m.name ? esc(m.name) : '—') + '</span>'
    + '<span class="sd-rank">#' + (m.rank != null ? m.rank : '—') + '</span>'
    + '</div>'
  ).join('');
  dd.style.display = '';
}

function _hideSuggest() {
  _suggestMatches = [];
  _suggestActive = -1;
  const dd = $('r-search-dd');
  if (dd) { dd.style.display = 'none'; dd.innerHTML = ''; }
}

function _setActiveSuggest(idx) {
  const items = $('r-search-dd') ? $('r-search-dd').querySelectorAll('.search-dd-item') : [];
  _suggestActive = idx;
  items.forEach((el, i) => el.classList.toggle('active', i === idx));
  if (idx >= 0 && items[idx]) items[idx].scrollIntoView({ block: 'nearest' });
}

// Keyboard nav on the search box: ↑/↓ move the highlight, Enter selects (the
// highlighted item, else an exact-ticker match, else the first match), Esc closes.
function onSearchKeydown(ev) {
  const open = _suggestMatches.length > 0 && $('r-search-dd') && $('r-search-dd').style.display !== 'none';
  if (ev.key === 'ArrowDown') {
    if (!open) { onSearchInput(); return; }
    ev.preventDefault();
    _setActiveSuggest(Math.min(_suggestActive + 1, _suggestMatches.length - 1));
  } else if (ev.key === 'ArrowUp') {
    if (!open) return;
    ev.preventDefault();
    _setActiveSuggest(Math.max(_suggestActive - 1, 0));
  } else if (ev.key === 'Enter') {
    ev.preventDefault();
    const typed = (($('r-search').value || '').trim()).toUpperCase();
    let pick = null;
    if (_suggestActive >= 0 && _suggestMatches[_suggestActive]) {
      pick = _suggestMatches[_suggestActive];
    } else {
      pick = _suggestMatches.find(m => (m.ticker || '').toUpperCase() === typed)
          || _suggestMatches[0] || null;
    }
    // No suggestion (e.g. an unknown ticker typed in full) → navigate to the typed
    // value anyway so the "not in this ranking run" note shows instead of doing nothing.
    if (pick) _navigateToTicker(pick.ticker);
    else if (typed) _navigateToTicker(typed);
  } else if (ev.key === 'Escape') {
    _hideSuggest();
  }
}

function onSuggestPick(ev, idx) {
  if (ev) ev.preventDefault();   // mousedown — keep focus stable
  const m = _suggestMatches[idx];
  if (m) _navigateToTicker(m.ticker);
}

// Scroll the main list to `ticker` and flash its row. Card stays COLLAPSED. If the
// ticker isn't in the rendered list, fetch its row via the scoped overlays endpoint
// and inject it (mirrors how held-but-unranked rows are injected). If it isn't
// ranked at all, show an inline note instead of scrolling to nothing.
async function _navigateToTicker(ticker) {
  const tk = (ticker || '').toUpperCase();
  if (!tk) return;
  _hideSuggest();
  _clearSearchNote();

  if (_scrollToRow(tk)) return;

  // Not in the rendered list — pull the single row via the scoped endpoint and inject.
  try {
    const d = await fetch('/api/rankings/with-overlays?tickers=' + encodeURIComponent(tk), {cache:'no-store'})
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const rows = (d.rankings || []).map(_mapRankRow);
    const match = rows.find(r => (r.ticker || '').toUpperCase() === tk);
    if (match) {
      // Inject if not already present (forward-compatible: a no-op once a full
      // list lands and the row is always already there).
      if (!rankData.some(r => (r.ticker || '').toUpperCase() === tk)) {
        rankData.push(match);
      }
      renderRankings();
      if (_scrollToRow(tk)) return;
    }
  } catch (_) { /* fall through to the not-in-run note */ }

  _showSearchNote(tk + ' not in this ranking run');
}

// INDEX-BASED scroll-to-row. Under virtualization an off-screen row is NOT in the DOM,
// so we can't getElementById it directly. Find the ticker's index in the current
// SORTED array, scroll the virtual container so that index is centered (scrollTop =
// index×rowH − viewH/2), repaint the window, THEN flash the row once it renders.
function _scrollToRow(ticker) {
  const tk = (ticker || '').toUpperCase();
  const idx = _sortedRank.findIndex(r => (r.ticker || '').toUpperCase() === tk);
  if (idx < 0) return false;

  // Mark the flashed ticker BEFORE repainting so _renderRankWindow re-applies the
  // class on the freshly-created row node (a virtualized row is destroyed/recreated
  // on every repaint, so we can't just add the class to a DOM node and walk away).
  clearTimeout(_flashTimer);
  document.querySelectorAll('.rank-row.row-flash').forEach(el => el.classList.remove('row-flash'));
  _flashTicker = tk;

  const sc = $('r-scroll');
  if (sc) {
    const viewH = sc.clientHeight || 600;
    let top = idx * RANK_ROW_H - viewH / 2 + RANK_ROW_H / 2;
    if (top < 0) top = 0;
    sc.scrollTop = top;     // direct set; centers the target index in the viewport
    _renderRankWindow();    // repaint so the target row is in the DOM (and flashed)
  } else {
    _renderRankWindow();    // no scroll container (test stub) → all rows, flash applies
  }

  const row = document.getElementById('rank-row-' + tk);
  if (row) {
    void row.offsetWidth;   // reflow so the animation restarts on re-selection
    row.classList.add('row-flash');
  }
  _flashTimer = setTimeout(() => {
    _flashTicker = null;
    document.querySelectorAll('.rank-row.row-flash').forEach(el => el.classList.remove('row-flash'));
  }, 1700);
  return true;
}

function _showSearchNote(msg) {
  const el = $('r-search-note');
  if (!el) return;
  el.textContent = '⚠ ' + msg;
  el.style.display = '';
}

function _clearSearchNote() {
  const el = $('r-search-note');
  if (el) { el.textContent = ''; el.style.display = 'none'; }
}

/* ── Rankings ────────────────────────────────────────────────────────── */
async function loadRankings() {
  $('r-body').innerHTML = '<tr><td colspan="3" class="tbl-empty">Loading rankings&#8230;</td></tr>';
  try {
    // Full-universe LIGHT list (rank/ticker/name/cluster/held + cheap overlays). The
    // heavy per-row overlays (rank_slope, vetter, market_cap, factor_scores,
    // excess_dd_*) are lazy-loaded when a row's detail card is opened — see
    // toggleDetail → _ensureOverlay. The table is virtualized (renderRankings).
    const d = await fetch('/api/rankings/universe', {cache:'no-store'}).then(r => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
    if (!d.rankings || d.rankings.length === 0) {
      _rankingsLoadState = 'empty';
      rankData = [];
      $('r-body').innerHTML = '<tr><td colspan="3" class="tbl-empty">'
        + 'No ranking data &mdash; click <strong>&#9654; RUN</strong> to populate'
        + '</td></tr>';
      // Refresh status bar so READY badge is downgraded if data missing
      if (_pipelineData && _pipelineData.rank) updateStatusBar(_pipelineData);
      return;
    }
    _rankingsLoadState = 'ok';
    rankData = (d.rankings || []).map(_mapRankRow);
    // Invalidate the per-ticker overlay cache when the ranking RUN changes. The
    // cache is keyed only by ticker, so without this the Screener keeps showing
    // overlays (prior_rank / rank_slope arrows AND lazy-loaded factor_scores such as
    // earnings_surprise) computed against the PRIOR run while the Target tab — which
    // always re-fetches fresh — shows the current one, so the same ticker disagrees
    // across tabs. Keyed on run_id, NOT rank_date: a same-date re-run (a fresh build
    // after e.g. an earnings ingest, same rank_date) changes run_id but not the date,
    // so a date-keyed check would never invalidate and the stale overlay would persist
    // (the "earnings_surprise shows — after a same-day re-run" bug). Clearing forces a
    // re-enrich against the new run; both tabs then agree.
    const _newRunId = (d.run && d.run.run_id) || null;
    if (_newRunId && _newRunId !== _loadedRunId) {
      _overlayCache = {};
      _fullRankByTicker = {};   // Target store too (rebuilt fresh on next open)
      rankData.forEach(r => { r._overlayLoaded = false; });
      _loadedRunId = _newRunId;
    }
    _expandedTicker = null;
    renderRankings();
  } catch (e) {
    // Transient fetch failure (proxy 504 while the api recomputes, network blip,
    // pool busy). Do NOT blank the screener if we already have rows — a single slow
    // response must not wipe the screen ("no data" flakiness on refresh). Keep the
    // last-good data and re-render it; the next poll/run will refresh it.
    if (rankData && rankData.length) {
      renderRankings();   // re-render last-good rows
      return;
    }
    // No prior data: a genuine cold-boot / no-rankings-yet state (the api returns
    // 503 until the first ranking run exists). Show the empty state, not a spinner.
    _rankingsLoadState = 'empty';
    rankData = [];
    $('r-body').innerHTML = '<tr><td colspan="3" class="tbl-empty">'
      + 'No ranking data &mdash; click <strong>&#9654; RUN</strong> to populate'
      + '</td></tr>';
    if (_pipelineData && _pipelineData.rank) updateStatusBar(_pipelineData);
  }
}

function sortRankings(col) {
  // Default direction per column: rank/ticker/name/cluster read best ascending
  // (1, A→Z); score/size columns read best descending (biggest first).
  const ascendingByDefault = (col === 'rank' || col === 'ticker' || col === 'name' || col === 'cluster_id');
  if (rankSort.col === col) rankSort.dir *= -1;
  else { rankSort.col = col; rankSort.dir = ascendingByDefault ? 1 : -1; }
  _expandedTicker = null;
  clearSort('rh-');
  const th = $('rh-' + col);
  if (th) th.classList.add(rankSort.dir === 1 ? 'asc' : 'desc');
  renderRankings();
}

function clearSort(pfx) {
  document.querySelectorAll('[id^="' + pfx + '"]').forEach(el => el.classList.remove('asc', 'desc'));
}

function rankArrowHtml(r) {
  // Red/green rank-trend arrow — shared by the Screener and Target tabs. Uses the
  // 1-day delta (prior run → this run) on BOTH tabs so the SAME ticker can never
  // show different arrows. prior_rank is returned by BOTH /rankings/universe (the
  // screener's light list) and /rankings/with-overlays (the Target tab); rank_slope
  // is only on the latter, so preferring it made the screener (1-day) and Target
  // (5-run slope) disagree for the same name. The richer 5-run slope still shows in
  // the detail card (see _buildDetailHtml "Rank trend").
  let arrow = '';
  if (r.prior_rank != null && r.rank != null) {
    const delta = r.prior_rank - r.rank;   // +ve = rank number fell = improved
    if (delta >= 2)       arrow = '<span class="rank-up" title="up ' + delta + ' since last run">&#9650;' + delta + '</span>';
    else if (delta <= -2) arrow = '<span class="rank-dn" title="down ' + (-delta) + ' since last run">&#9660;' + (-delta) + '</span>';
  }
  if (!arrow) arrow = '<span class="rank-flat" title="no movement vs last run">&ndash;</span>';
  return arrow;
}

// Build (and cache) the sorted full array. The list is NEVER filtered — the search
// box is a navigate-typeahead (see _navigateToTicker), not a filter. Only the column
// SORT applies. Virtualization windows over _sortedRank; _renderRankWindow() paints
// just the visible slice. Re-sorting (or new data) rebuilds _sortedRank then repaints.
function renderRankings() {
  const { col, dir } = rankSort;
  _sortedRank = rankData.slice().sort((a, b) => {
    const av = a[col], bv = b[col];
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });
  $('r-count').textContent = _sortedRank.length + ' / ' + rankData.length;
  if (!_sortedRank.length) {
    _expandedTicker = null;
    $('r-body').innerHTML = '<tr><td colspan="3" class="tbl-empty">No results</td></tr>';
    return;
  }
  _renderRankWindow();
}

// Map a sorted-array index → that row's <tr> HTML (data row only; the expanded
// detail card is injected separately, OUTSIDE the spacer math — see below).
function _rankRowHtml(r) {
  const arrow = rankArrowHtml(r);   // 1-day prior_rank delta (same metric on both tabs)
  // SIZE / drawdown / vetter-warning badges live in the detail card now (compact
  // row keeps only rank · ticker · company · cluster). See _buildDetailHtml.
  const heldCls     = r.held ? ' row-held' : '';
  const exclCls     = r.vetter_excluded ? ' row-excluded' : '';
  const expandedCls = _expandedTicker === r.ticker ? ' expanded' : '';
  return '<tr class="rank-row' + heldCls + exclCls + expandedCls + '" id="rank-row-' + esc(r.ticker) + '" onclick="toggleDetail(\'' + esc(r.ticker) + '\',this)">'
    + '<td><span class="t-rank">' + r.rank + '</span>' + arrow + '</td>'
    + '<td><span class="t-ticker">' + r.ticker + '</span></td>'
    + '<td class="t-company" title="' + (r.name ? esc(r.name) : '') + '">' + (r.name ? esc(r.name) : '—') + '</td>'
    + '</tr>';
}

// Paint only the rows visible in the scroll viewport (+ RANK_BUFFER above/below).
// Total scroll height is preserved with two spacer rows whose td height = number of
// hidden rows × RANK_ROW_H. The window math assumes a UNIFORM row height; the one
// expanded detail card is injected inline after its row (it lives inside the rendered
// window, so rows ABOVE it keep correct positions; rows below shift by the card's
// height and self-correct on the next scroll repaint — simplest robust approach for a
// single-open card without breaking <table> layout via absolute positioning).
function _renderRankWindow() {
  const sc = $('r-scroll');
  const total = _sortedRank.length;
  if (!sc) {  // no scroll container (test stub / partial DOM) → render all rows
    $('r-body').innerHTML = _sortedRank.map(_rankRowHtml).join('');
    _reinsertExpandedDetail();
    return;
  }
  const viewH = sc.clientHeight || 600;
  const scrollTop = sc.scrollTop || 0;
  let first = Math.floor(scrollTop / RANK_ROW_H) - RANK_BUFFER;
  if (first < 0) first = 0;
  let visCount = Math.ceil(viewH / RANK_ROW_H) + RANK_BUFFER * 2;
  let last = Math.min(total, first + visCount);
  const topPad = first * RANK_ROW_H;
  const botPad = (total - last) * RANK_ROW_H;

  const parts = [];
  if (topPad > 0) parts.push('<tr class="rank-spacer"><td colspan="3" style="height:' + topPad + 'px"></td></tr>');
  for (let i = first; i < last; i++) parts.push(_rankRowHtml(_sortedRank[i]));
  if (botPad > 0) parts.push('<tr class="rank-spacer"><td colspan="3" style="height:' + botPad + 'px"></td></tr>');
  $('r-body').innerHTML = parts.join('');
  _reinsertExpandedDetail();
  // Re-apply the flash class to the flashed row if it's in this window — the row's
  // DOM node is recreated on every repaint, so the class can't persist on the node.
  if (_flashTicker) {
    const fr = document.getElementById('rank-row-' + _flashTicker);
    if (fr) fr.classList.add('row-flash');
  }
}

// Re-attach the open detail card after a window repaint, if its row is in view.
function _reinsertExpandedDetail() {
  if (_expandedTicker == null) return;
  const mainRow = document.getElementById('rank-row-' + _expandedTicker);
  if (mainRow) {
    const rec = _rankSource().find(r => r.ticker === _expandedTicker);
    if (rec) _insertDetailRow(mainRow, rec);
  }
  // If the row scrolled out of the window the card simply isn't shown; the
  // _expandedTicker state is kept so it reappears when scrolled back into view.
}

// Scroll handler — repaint the window. Cheap (innerHTML of ~tens of rows); guarded by
// rAF so a fast scroll coalesces repaints to one per frame.
let _rankScrollRaf = 0;
function onRankScroll() {
  if (_rankScrollRaf) return;
  _rankScrollRaf = requestAnimationFrame(() => {
    _rankScrollRaf = 0;
    _renderRankWindow();
  });
}

// The array feeding the screener rows. The list is no longer filtered (the search
// box navigates instead), so this is simply the full rankData — kept as a helper so
// detail-card lookups (toggleDetail/_insertDetailRow) have a single source.
function _rankSource() {
  return rankData;
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
  const rec = _rankSource().find(r => r.ticker === ticker);
  if (!rec) return;
  // Render the card immediately (it tolerates not-yet-loaded heavy fields, showing a
  // brief "loading…" placeholder), then lazy-load the heavy overlays and re-render.
  _insertDetailRow(rowEl, rec);
  _ensureOverlay(ticker);
}

// Lazy-load the heavy overlays (rank_slope, vetter_*, market_cap, factor_scores,
// excess_dd_*) for a ticker when its detail card opens. The full-universe list is
// LIGHT — these fields are absent until fetched via /api/rankings/with-overlays?
// tickers=<T>. Cached per ticker for the session (re-open is instant) and deduped so a
// double-click fires one request. On success the overlay fields are merged into the
// rankData row and the open card re-rendered.
function _overlayLoaded(rec) {
  // A light row has none of the heavy fields; treat the presence of an explicit
  // overlay-loaded flag (set on merge) as the cache hit.
  return rec && rec._overlayLoaded === true;
}

async function _ensureOverlay(ticker) {
  const tk = (ticker || '').toUpperCase();
  const rec = _rankSource().find(r => (r.ticker || '').toUpperCase() === tk);
  if (!rec || _overlayLoaded(rec)) return;

  // Session cache hit → merge synchronously, re-render, done (no fetch).
  if (_overlayCache[tk]) {
    Object.assign(rec, _overlayCache[tk], { _overlayLoaded: true });
    _rerenderOpenCard(rec);
    return;
  }
  if (_overlayInflight[tk]) return;   // already fetching

  _overlayInflight[tk] = (async () => {
    try {
      const d = await fetch('/api/rankings/with-overlays?tickers=' + encodeURIComponent(tk), {cache:'no-store'})
        .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
      const rows = (d.rankings || []).map(_mapRankRow);
      const match = rows.find(r => (r.ticker || '').toUpperCase() === tk);
      if (match) {
        // Keep the light row's held/qty/market_value (universe list is authoritative
        // for those) but take all heavy overlay fields from the scoped response.
        const overlay = {
          rank_slope: match.rank_slope, prior_rank: match.prior_rank,
          market_cap: match.market_cap, beta: match.beta,
          momentum: match.momentum, quality: match.quality, value: match.value,
          growth: match.growth, low_volatility: match.low_volatility, liquidity: match.liquidity,
          earnings_surprise: match.earnings_surprise, near_high: match.near_high,
          drawdown_21d: match.drawdown_21d, excess_dd_21d: match.excess_dd_21d,
          idio_vol: match.idio_vol, excess_dd_limit: match.excess_dd_limit,
          vetter_excluded: match.vetter_excluded, vetter_confidence: match.vetter_confidence,
          vetter_risk_type: match.vetter_risk_type, vetter_reason: match.vetter_reason,
          vetter_crashed: match.vetter_crashed,
          positive_catalyst: match.positive_catalyst, positive_reason: match.positive_reason,
        };
        _overlayCache[tk] = overlay;
        Object.assign(rec, overlay, { _overlayLoaded: true });
        _rerenderOpenCard(rec);
      }
    } catch (_) {
      // Leave the card in its light state; a flagged retry happens on next open.
    } finally {
      delete _overlayInflight[tk];
    }
  })();
}

// Re-render the currently-open detail card in place (overlays just arrived).
function _rerenderOpenCard(rec) {
  if (_expandedTicker !== rec.ticker) return;   // user closed/changed it meanwhile
  const dr = document.getElementById('detail-row-' + rec.ticker);
  if (!dr) return;
  const td = dr.firstChild;
  if (td) td.innerHTML = _buildDetailHtml(rec);
}

function _insertDetailRow(rowEl, rec, colSpan = 4) {
  const tr = document.createElement('tr');
  tr.className = 'detail-row';
  tr.id = 'detail-row-' + rec.ticker;
  const td = document.createElement('td');
  td.colSpan = colSpan;
  td.innerHTML = _buildDetailHtml(rec);
  tr.appendChild(td);
  rowEl.parentNode.insertBefore(tr, rowEl.nextSibling);
}

function _buildDetailHtml(r) {
  const nameHtml = r.name ? '<span class="detail-name">' + esc(r.name) + '</span>' : '<span class="detail-name"></span>';
  const yfLink = '<a class="detail-yf-link" href="https://finance.yahoo.com/quote/' + esc(r.ticker) + '" target="_blank" rel="noopener">&#8599; Yahoo Finance</a>';
  // While the heavy overlays for this row are still lazy-loading, show a small inline
  // hint in the header. The card itself renders fine with light data (rank/score/
  // percentile come from the universe list); the loaded fields fill in on re-render.
  const loadingHtml = _overlayLoaded(r) ? ''
    : ' <span class="detail-loading" title="loading factor / vetter detail…">loading&#8230;</span>';
  const head = '<div class="detail-head"><span class="detail-ticker">' + esc(r.ticker) + '</span>' + nameHtml + loadingHtml + yfLink + '</div>';

  const pctVal = r.percentile != null ? (+(r.percentile) * 100).toFixed(1) + '%' : '—';

  // Size + drawdown moved here from the row (compact row is rank·ticker·company·cluster).
  const tier = capTier(r.market_cap);
  const sizeVal = tier
    ? '<span class="cap-badge ' + tier.cls + '" title="' + fmtCap(r.market_cap) + '">' + tier.label + '</span>'
      + (r.market_cap != null ? ' <span class="dc-sub">' + fmtCap(r.market_cap) + '</span>' : '')
    : '—';
  let ddVal = '—';
  if (r.drawdown_21d != null) {
    const ddPct = (r.drawdown_21d * 100).toFixed(0) + '%';
    // -25%+ (knife-deep) red, -10%..-25% amber, milder plain. Display-only.
    const ddCls = r.drawdown_21d <= -0.25 ? 'dd-deep' : r.drawdown_21d <= -0.10 ? 'dd-warn' : '';
    ddVal = ddCls
      ? '<span class="overlay-badge ' + ddCls + '" title="21-day peak-to-now drawdown (display only)">&#9660; ' + ddPct + '</span>'
      : ddPct;
  }
  // Beta-adjusted excess drawdown (what the falling-knife veto evaluates): raw drop
  // minus beta×SPY move over the same span, with idiosyncratic vol (σ) for context.
  let excessSub = '';
  if (r.excess_dd_21d != null) {
    const exPct = (r.excess_dd_21d * 100).toFixed(0) + '%';
    // Per-ticker excess trigger (vol-scaled). Show as a negative % to compare
    // directly with the excess, so "excess -6% / limit -12%" reads as 6pp of room.
    const lim = r.excess_dd_limit != null ? ' / limit -' + (r.excess_dd_limit * 100).toFixed(0) + '%' : '';
    const sig = r.idio_vol != null ? ' @ σ' + (r.idio_vol * 100).toFixed(0) + '%' : '';
    // Amber when within 5pp of the trigger (close to the falling-knife veto).
    const near = (r.excess_dd_limit != null && r.excess_dd_21d <= -(r.excess_dd_limit - 0.05));
    const cls = near ? ' dd-warn' : '';
    excessSub = '<div class="dc-sub' + cls + '" title="Beta-adjusted excess drawdown (raw minus beta×SPY move) vs this ticker\'s falling-knife trigger. The veto fires if excess ≤ -limit. limit = vol-scaled per σ (idiosyncratic vol). A separate flat 25% raw-drawdown floor also applies.">excess ' + exPct + lim + sig + '</div>';
  }

  // 5-run rank trend (REGR slope; negative = rank number falling = improving). The
  // compact table arrow uses the 1-day delta for cross-tab consistency; the smoothed
  // multi-run trend lives here, where rank_slope is loaded with the detail overlay.
  let trendVal = '—';
  if (r.rank_slope != null) {
    const mag = Math.round(Math.abs(r.rank_slope));
    if (mag >= 1) {
      trendVal = r.rank_slope < 0
        ? '<span class="rank-up" title="improving ~' + mag + ' places/run over the last 5 runs">&#9650; ' + mag + '/run</span>'
        : '<span class="rank-dn" title="slipping ~' + mag + ' places/run over the last 5 runs">&#9660; ' + mag + '/run</span>';
    } else {
      trendVal = '<span class="rank-flat" title="flat over the last 5 runs">&ndash; flat</span>';
    }
  }
  const grid = '<div class="detail-grid">'
    + '<div class="detail-cell"><div class="dc-lbl">Rank</div><div class="dc-val">' + r.rank + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Score</div><div class="dc-val">' + fmtScore(r.composite_score) + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Percentile</div><div class="dc-val">' + pctVal + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Size</div><div class="dc-val">' + sizeVal + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">21d Drawdown</div><div class="dc-val">' + ddVal + excessSub + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Beta (120d vs SPY)</div><div class="dc-val">' + (r.beta != null ? r.beta.toFixed(2) : '—') + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Rank trend (5-run)</div><div class="dc-val">' + trendVal + '</div></div>'
    + '<div class="detail-cell"><div class="dc-lbl">Cluster</div><div class="dc-val">' + (r.cluster_id ? esc(r.cluster_id) : '—') + '</div></div>'
    + '</div>';

  const FACTORS = [
    { key: 'momentum', lbl: 'Momentum' }, { key: 'quality', lbl: 'Quality' },
    { key: 'value', lbl: 'Value' }, { key: 'growth', lbl: 'Growth' },
    { key: 'low_volatility', lbl: 'Low Vol' }, { key: 'liquidity', lbl: 'Liquidity' },
    { key: 'earnings_surprise', lbl: 'Earn Surprise' }, { key: 'near_high', lbl: 'Near High' },
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
      + '<div class="llm-header"><span class="llm-label">VETTER</span>'
      + '<span class="llm-verdict-badge ' + vbCls + '">' + verdict + '</span>'
      + '<span class="llm-conf-badge cb-' + conf + '">' + conf.toUpperCase() + '</span>'
      + riskType + '</div>'
      + (r.vetter_reason ? '<div class="llm-reason">' + esc(r.vetter_reason) + '</div>' : '')
      + catalystHtml + '</div>';
  } else if (r.positive_catalyst && r.positive_reason) {
    llmHtml = '<div class="detail-llm"><div class="llm-header"><span class="llm-label">VETTER</span></div>'
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
let deltaRun = {};   // latest delta run meta (confirmation_days, etc.) for holdings-status

async function loadDelta() {
  try {
    const d = await fetch('/api/delta/latest', {cache:'no-store'}).then(r => r.json());
    const run = d.run || {};
    deltaRun = run;
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
  // 'closed' = close-position-404 terminal no-op (exit already flat at broker) — done.
  if (os === 'filled' || os === 'partial_fill' || os === 'closed') return 'completed';
  if (os === 'failed' || os === 'risk_rejected' || os === 'expired') return 'attention';
  if (r.rejected_at) return 'completed';

  // No order yet — check if approvable
  if (_isApprovable(r)) return 'attention';

  // Vetter-excluded buy with no order: show in attention so operator can investigate
  const isBuy = r.action === 'entry' || r.action === 'buy_add';
  if (isBuy && r.vetter_excluded) return 'attention';

  // Hold, watch, at_risk, and any other non-actionable state
  return 'completed';
}

// An already-held / duplicate dedup block is a PERMANENT failure: the position is
// already at the broker, so re-approving just hits the executor's dedup and blocks
// again. Distinguish it from a TRANSIENT failure (insufficient buying power, risk
// blip) which legitimately stays retryable. The signal is the executor's 'duplicate'
// status or the "already held"/"Duplicate entry" message it writes on the failed row.
function _isAlreadyHeldBlock(r) {
  if (r.order_status !== 'failed' && r.order_status !== 'duplicate') return false;
  if (r.order_status === 'duplicate') return true;
  const m = (r.order_error_message || '').toLowerCase();
  return m.includes('already held') || m.includes('duplicate entry');
}

function _isApprovable(r) {
  if (!['entry', 'exit', 'buy_add', 'sell_trim'].includes(r.action)) return false;
  if (_approvalState[r.id]) return false;
  // Permanent dedup block — never approvable (retry just re-blocks). MUST come before
  // the generic-failed fall-through below, which keeps transient failures retryable.
  if (_isAlreadyHeldBlock(r)) return false;
  const os = r.order_status;
  // Block only orders that are genuinely OPEN or already DONE — re-approving those
  // would double-submit. A TRANSIENT DEAD attempt (risk_rejected / failed / expired /
  // canceled) placed NO live broker order, so it must stay manually re-approvable: the
  // operator can retry after the cause is fixed (e.g. the risk-service exit bug). NOTE:
  // the server-side cron auto-approve deliberately still SKIPS risk_rejected/failed
  // (see dashboard app.main _auto_approve_once) so a persistent failure can't loop;
  // only this manual UI path allows the retry.
  if (os === 'submitted' || os === 'pending' || os === 'deferred' || os === 'filled' || os === 'partial_fill') return false;
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
  // Blotter = actionable orders (buy open / buy add / sell close / sell trim) PLUS
  // informational intents (hold / watch / at_risk). The actionable ones drive the
  // Needs Attention / In Progress sections and approvals; the informational ones are
  // never approvable but DO belong in the "Completed & Holds" section (and the DONE
  // count) — _sectionFor routes them to 'completed'. Excluding them entirely made the
  // "& Holds" header and DONE chip lie, and hid the toolbar on a hold-only cycle.
  const INFO_ACTIONS = ['hold', 'watch', 'at_risk'];
  const orders = visible.filter(r => TRADE_ACTIONS.includes(r.action) || INFO_ACTIONS.includes(r.action));
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
  // PENDING = items needing a human decision: approvable attention items + transient
  // failures (retryable). Already-held blocks sit in the failures section for
  // visibility but are NOT counted (nothing to do about them).
  const pendingCount = attentionItems.filter(r => !_isAlreadyHeldBlock(r)).length;
  const pendEl = $('ds-pending');  if (pendEl)  pendEl.textContent  = hasData ? pendingCount          : '—';
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
    // Holdings status is independent of the order blotter — it must render even
    // when there are no actionable orders (e.g. all hold/at_risk/watch). Without
    // this call the early-return skipped renderHoldingsStatus() and the panel was
    // stuck on "Loading…" whenever the delta had zero tradeable intents.
    renderHoldingsStatus();
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
  renderHoldingsStatus();
}

/* ── Holdings status (per-ticker, informational) ──────────────────────────
 * A plain-English status for every name the delta engine evaluated against the
 * broker book: held-in-target, orphan counting down to exit, drift add/trim, or
 * an order already submitted. Derived from the same delta intents as the blotter
 * above; this section is read-only (no approve/reject controls).               */
function _holdingStatus(r) {
  const cd = deltaRun.confirmation_days;
  const os = r.order_status;
  const st = _approvalState[r.id] || {};

  // An order is already in flight / done for this ticker — surface that first.
  if (st.status === 'ok' || st.status === 'queued' || st.status === 'pending')
    return { cls: 'hs-submitted', text: 'Order submitted (' + (ACTION_LABELS[r.action] || r.action) + ')' };
  if (os === 'submitted' || os === 'pending')
    return { cls: 'hs-submitted', text: 'Order submitted (' + (ACTION_LABELS[r.action] || r.action) + ')' };
  if (os === 'deferred')
    return { cls: 'hs-submitted', text: 'Order deferred — queued for next session' };
  if (os === 'filled' || os === 'partial_fill')
    return { cls: 'hs-done', text: (ACTION_LABELS[r.action] || r.action) + ' filled' };
  if (os === 'expired')
    return { cls: 'hs-attn', text: (ACTION_LABELS[r.action] || r.action) + ' expired — unfunded at close' };
  if (os === 'failed' || os === 'risk_rejected' || st.status === 'err')
    return { cls: 'hs-attn', text: (ACTION_LABELS[r.action] || r.action) + ' failed — needs attention' };
  if (r.rejected_at || st.status === 'rejected')
    return { cls: 'hs-done', text: 'Signal rejected' };

  // No order yet — describe the standing decision.
  switch (r.action) {
    case 'hold':
      return { cls: 'hs-hold', text: 'Hold — in target portfolio' };
    case 'at_risk': {
      // Orphan counting down to a forced exit. confirmation_days_met counts builds
      // already orphaned; days remaining = confirmation_days - met.
      const met = r.confirmation_days_met || 0;
      const left = (cd != null) ? Math.max(0, cd - met) : null;
      const when = left == null ? '' : left === 0 ? ' — exits next build'
        : ' — exits in ' + left + ' build' + (left === 1 ? '' : 's');
      return { cls: 'hs-atrisk', text: 'Orphan (not in target)' + when };
    }
    case 'exit':
      return { cls: 'hs-exit', text: 'Exit confirmed — sell pending approval' };
    case 'buy_add':
      return { cls: 'hs-drift', text: 'Underweight — buy-add pending approval' };
    case 'sell_trim':
      return { cls: 'hs-drift', text: 'Overweight — sell-trim pending approval' };
    case 'entry':
      return { cls: 'hs-entry', text: 'Entry pending approval' };
    case 'watch':
      return { cls: 'hs-hold', text: 'Watch — deferred (at capacity)' };
    default:
      return { cls: 'hs-hold', text: r.action };
  }
}

function renderHoldingsStatus() {
  const tbody = $('holdings-status-body');
  if (!tbody) return;
  // Every ticker the delta engine evaluated that maps to the broker book: held
  // names (hold/at_risk/exit/buy_add/sell_trim). entry/watch are not yet held.
  const HELD_ACTIONS = ['hold', 'buy_add', 'sell_trim', 'at_risk', 'exit'];
  const held = deltaData
    .filter(r => HELD_ACTIONS.includes(r.action))
    .sort((a, b) => (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0));
  if (!held.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="tbl-empty">No broker holdings evaluated yet</td></tr>';
    return;
  }
  tbody.innerHTML = held.map(r => {
    const s = _holdingStatus(r);
    const wt = r.actual_weight != null ? fmtPct(r.actual_weight) : '—';
    return '<tr>'
      + '<td><span class="t-ticker">' + esc(r.ticker) + '</span></td>'
      + '<td><span class="hs-badge ' + s.cls + '">' + esc(s.text) + '</span></td>'
      + '<td class="t-wt">' + wt + '</td>'
      + '</tr>';
  }).join('');
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
    + (r.reason ? '<div class="t-reason" title="' + esc(r.reason) + '">' + esc(r.reason) + '</div>' : '')
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
  } else if (r.order_status === 'expired') {
    statusHtml = '<span class="tc-error">&#x26A0; Expired — unfunded at close</span>';
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
      + '<button class="btn-sm-approve" onclick="approveTrade(\'' + r.id + '\',\'immediate\')" title="Approve — submit to the broker now if the market is open, else queue for the next open (sells-first drain).">&#9654; Approve</button>'
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
  // Respect _clearedTrades: dismissing the trader screen also dismisses the badge,
  // so the badge count and the blotter never disagree (no "badge=1, all clear").
  const cnt = deltaData.filter(r => _isApprovable(r) && !_clearedTrades.has(String(r.id))).length;
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

  // Single approval rule: submit to the broker NOW if the market is open, else
  // queue for the next open. Market-closed approvals (the usual after-close path)
  // go to the fill-gated drain (sells first, buys one at a time within buying
  // power); market-open approvals submit immediately. See docs/architecture.md.
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
  // Dismiss ALL current rows from the trader view — including ones still awaiting
  // a human decision. Per the chosen UX, clearing the screen also clears the badge
  // so the two never disagree. The intents/orders are untouched in the DB; this is
  // purely a per-run view dismissal that resets when a new delta run appears.
  deltaData.forEach(r => { _clearedTrades.add(String(r.id)); });
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
    const d = await fetch('/api/live-portfolio', {cache:'no-store'}).then(r => r.json());
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

/* ── Target tab — held ∪ target table ─────────────────────────────────── */
// Trade decision shown per ticker, derived from the delta action. Held / in-target
// are derivable from the action taxonomy (the delta engine emits exactly one action
// per held-or-target ticker). 'watch' IS a target name — a builder-selected entry
// that capacity deferred (no free slot yet, waiting for an orphan to time out) — so
// it's shown with Target ✓ / Holdings ✗ and a 'Watch' tag, NOT excluded.
const TARGET_TRADE = {
  entry:     { label: 'Buy',     cls: 'trade-buy',   held: false, target: true  },
  buy_add:   { label: 'Add',     cls: 'trade-buy',   held: true,  target: true  },
  hold:      { label: 'Hold',    cls: 'trade-hold',  held: true,  target: true  },
  sell_trim: { label: 'Trim',    cls: 'trade-sell',  held: true,  target: true  },
  exit:      { label: 'Sell',    cls: 'trade-sell',  held: true,  target: false },
  at_risk:   { label: 'At risk', cls: 'trade-risk',  held: true,  target: false },
  watch:     { label: 'Watch',   cls: 'trade-watch', held: false, target: true  },
};

function buildTargetRows() {
  const byTicker = {};
  rankData.forEach(r => { byTicker[r.ticker] = r; });
  targetRows = [];
  deltaData.forEach(it => {
    const meta = TARGET_TRADE[it.action];
    if (!meta) return;   // unknown/non-actionable action → skip (watch IS mapped now)
    // Prefer the OVERLAY-RICH record (_fullRankByTicker, fetched per target+held
    // ticker via with-overlays?tickers= with rank_slope/vetter/factors and marked
    // _overlayLoaded) over byTicker — which since the full-universe switch is the
    // LIGHT list (rank/ticker/name/cluster only). Using the light row here was the
    // "Target card stuck on loading… / data not calculated" bug: the card had no
    // heavy fields and _overlayLoaded was never set. Else fall back to the light
    // row, else a genuine "not ranked" stub.
    const rec = _fullRankByTicker[it.ticker] || byTicker[it.ticker] || {
      ticker: it.ticker, rank: it.rank, name: it.name || null,
      composite_score: it.composite_score, not_in_universe: true,
    };
    targetRows.push({
      ticker: it.ticker,
      rank: (rec.rank != null ? rec.rank : it.rank),
      prior_rank: rec.prior_rank != null ? rec.prior_rank : null,
      rank_slope: rec.rank_slope != null ? rec.rank_slope : null,
      held: meta.held,
      // Authoritative target membership from the API (ticker ∈ builder
      // portfolio_holdings) so the Target column shows the REAL builder target and
      // does NOT tick data-gap/degraded HOLDs (held, weight 0, never selected).
      // Fallback (API didn't supply the flag — version skew / partial fetch): the
      // action implies membership for builder-selected actions (entry/buy_add/
      // sell_trim/watch), but a HOLD is AMBIGUOUS — it can be a real target member
      // OR a data-gap orphan the engine is exiting — so a hold must NOT default to
      // true (that's the P4 false-tick). Default hold→false when the flag is absent.
      in_target: (it.in_target != null
                    ? it.in_target
                    : (it.action === 'hold' ? false : meta.target)),
      trade: it.action,
      tradeLabel: meta.label,
      tradeCls: meta.cls,
      tradeOrder: ACTION_ORDER[it.action] ?? 99,
      rec,
    });
  });
}

function sortTarget(col) {
  const ascendingByDefault = (col === 'rank' || col === 'ticker' || col === 'trade');
  if (targetSort.col === col) targetSort.dir *= -1;
  else { targetSort.col = col; targetSort.dir = ascendingByDefault ? 1 : -1; }
  _expandedTargetTicker = null;
  clearSort('tgh-');
  const th = $('tgh-' + col);
  if (th) th.classList.add(targetSort.dir === 1 ? 'asc' : 'desc');
  renderTargetTable();
}

async function loadTargetPortfolio() {
  const tbody = $('target-body');
  try {
    // The table is the union of held + target tickers (delta intents minus watch),
    // enriched with the screener's rank/arrows/detail. Refresh both sources.
    await loadDelta();
    if (!rankData.length) await loadRankings();
    // Resolve EVERY target/held name's record against the FULL ranking, not just the
    // screener's top-100 — otherwise a name ranked beyond 100 (e.g. a portfolio
    // holding at rank 133) isn't in rankData and falls to the "not in universe" stub
    // with blank factors, which is wrong (it IS ranked). We use the SAME enriched
    // endpoint the screener uses (with-overlays), NOT the bare /rankings: the bare
    // endpoint omits name, market_cap (SIZE), prior_rank, cluster_id, and the vetter
    // overlay, so a deep-ranked target name (e.g. a Watch beyond top-100) showed a
    // blank company name + "SIZE —" + no vetter verdict in its detail card. Sourcing
    // both the screener and the Target tab from with-overlays makes every field
    // populate identically (single source of truth).
    // Scope the enriched fetch to ONLY the target+held names (the delta intents),
    // not the whole universe. The old limit=5000 ran the expensive overlay CTEs
    // (rank_slope/prior_rank/joins) over ~2900 tickers just to display ~30 — the
    // screener's slow-load problem, ~30x worse. tickers= bounds it to the set, so
    // even a cold load is sub-second.
    const _targetTickers = [...new Set((deltaData || []).map(it => it && it.ticker).filter(Boolean))];
    if (_targetTickers.length) {
      try {
        const rk = await fetch('/api/rankings/with-overlays?tickers='
            + encodeURIComponent(_targetTickers.join(',')), {cache:'no-store'}).then(r => r.json());
        _fullRankByTicker = {};
        // Mark each as _overlayLoaded: these rows came from with-overlays?tickers=
        // (full heavy overlays), so the detail card must NOT show the "loading…" hint.
        (rk.rankings || []).forEach(r => {
          const m = _mapRankRow(r); m._overlayLoaded = true; _fullRankByTicker[r.ticker] = m;
        });
      } catch (_) { /* keep last good map; buildTargetRows still falls back to the stub */ }
    }
    // Target-book risk summary (weight-weighted portfolio beta + est vol).
    try {
      const pr = await fetch('/api/portfolio').then(r => r.json());
      targetPortfolioRun = (pr && pr.run) ? pr.run : null;
    } catch (_) { targetPortfolioRun = null; }
    buildTargetRows();
    renderTargetTable();
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="5" class="tbl-empty">Error loading target</td></tr>';
  }
}

function renderTargetTable() {
  const tbody = $('target-body');
  if (!tbody) return;
  const sub = $('target-sub');
  if (sub) {
    const nHeld = targetRows.filter(r => r.held).length;
    const nTgt  = targetRows.filter(r => r.in_target).length;
    let s = targetRows.length + ' names &middot; ' + nHeld + ' held &middot; ' + nTgt + ' target';
    const pr = targetPortfolioRun;
    if (pr && pr.portfolio_beta != null) {
      const cov = (pr.portfolio_beta_coverage != null && pr.selected_count)
        ? ' (' + pr.portfolio_beta_coverage + '/' + pr.selected_count + ')' : '';
      // Sleeve β = beta of the stocks (cash EXCLUDED). Effective β = sleeve β ×
      // invested fraction = the book's real market sensitivity (cash drag included).
      s += ' &middot; <strong title="beta of the holdings, as if fully invested (excludes the cash buffer)">sleeve &beta; '
        + (+pr.portfolio_beta).toFixed(2) + '</strong>' + cov;
      if (pr.effective_beta != null) {
        s += ' &middot; <strong title="effective market beta = sleeve β × invested fraction; what the book actually tracks SPY by, after the cash buffer">eff &beta; '
          + (+pr.effective_beta).toFixed(2) + '</strong>';
      }
    }
    if (pr && pr.cash_pct != null) {
      // Target cash = 1 − Σ target weights (cash_reserve + any vol-target de-lever).
      s += ' &middot; <span title="target cash buffer = cash reserve + vol-target de-lever (1 − invested fraction)">cash '
        + (pr.cash_pct * 100).toFixed(1) + '%</span>';
    }
    if (pr && pr.portfolio_estimated_vol != null) {
      s += ' &middot; est vol ' + (pr.portfolio_estimated_vol * 100).toFixed(1) + '%';
    }
    sub.innerHTML = s;
  }
  if (!targetRows.length) {
    _expandedTargetTicker = null;
    tbody.innerHTML = '<tr><td colspan="5" class="tbl-empty">No holdings or target yet</td></tr>';
    return;
  }
  const { col, dir } = targetSort;
  const keyOf = (r) => (col === 'held' ? (r.held ? 1 : 0)
                      : col === 'in_target' ? (r.in_target ? 1 : 0)
                      : col === 'trade' ? r.tradeOrder
                      : r[col]);
  const rows = targetRows.slice().sort((a, b) => {
    const av = keyOf(a), bv = keyOf(b);
    if (av == null && bv == null) return 0;
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });

  const mark = '<span class="tgt-x" title="yes">&#10003;</span>';
  const nomark = '<span class="tgt-no">&middot;</span>';
  tbody.innerHTML = rows.map(r => {
    const expandedCls = _expandedTargetTicker === r.ticker ? ' expanded' : '';
    const heldCls = r.held ? ' row-held' : '';
    return '<tr class="rank-row' + heldCls + expandedCls + '" id="tgt-row-' + esc(r.ticker)
        + '" onclick="toggleTargetDetail(\'' + esc(r.ticker) + '\',this)">'
      + '<td><span class="t-rank">' + (r.rank != null ? r.rank : '—') + '</span>' + rankArrowHtml(r) + '</td>'
      + '<td><span class="t-ticker">' + esc(r.ticker) + '</span></td>'
      + '<td class="tgt-cell">' + (r.held ? mark : nomark) + '</td>'
      + '<td class="tgt-cell">' + (r.in_target ? mark : nomark) + '</td>'
      + '<td><span class="trade-tag ' + r.tradeCls + '">' + r.tradeLabel + '</span></td>'
      + '</tr>';
  }).join('');

  if (_expandedTargetTicker !== null) {
    const mainRow = document.getElementById('tgt-row-' + _expandedTargetTicker);
    const row = targetRows.find(r => r.ticker === _expandedTargetTicker);
    if (mainRow && row) _insertDetailRow(mainRow, row.rec, 5);
    else _expandedTargetTicker = null;
  }
}

function toggleTargetDetail(ticker, rowEl) {
  if (_expandedTargetTicker === ticker) {
    _expandedTargetTicker = null;
    const next = rowEl.nextSibling;
    if (next && next.classList && next.classList.contains('detail-row')) next.remove();
    rowEl.classList.remove('expanded');
    return;
  }
  if (_expandedTargetTicker !== null) {
    const prev = document.getElementById('detail-row-' + _expandedTargetTicker);
    if (prev) prev.remove();
    const prevMain = document.getElementById('tgt-row-' + _expandedTargetTicker);
    if (prevMain) prevMain.classList.remove('expanded');
  }
  _expandedTargetTicker = ticker;
  rowEl.classList.add('expanded');
  const row = targetRows.find(r => r.ticker === ticker);
  if (row) _insertDetailRow(rowEl, row.rec, 5);
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
    const d = await fetch('/api/orders/recent', {cache:'no-store'}).then(r => r.json());
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

// Close the screener typeahead dropdown when clicking outside the search box.
document.addEventListener('click', (ev) => {
  const wrap = document.querySelector('#screen-screener .search-wrap');
  if (wrap && !wrap.contains(ev.target)) _hideSuggest();
});

/* ── Boot ────────────────────────────────────────────────────────────── */
// Each boot step is isolated: a throw in ONE step must never abort the others.
// Previously `await loadRegime()` ran first and unguarded — if it threw, the
// whole IIFE rejected and loadDelta() never ran, freezing the trader/holdings
// panels on "Loading…" forever (proven by the playwright render test). _safeStep
// keeps the chain alive so a single panel's failure stays contained to that panel.
async function _safeStep(label, fn) {
  try {
    await fn();
  } catch (e) {
    console.error('[boot] step failed: ' + label, e);
  }
}
(async () => {
  _safeStep('updateClock', () => updateClock());
  await _safeStep('loadRegime', () => loadRegime());
  _safeStep('loadRankings', () => loadRankings());
  _safeStep('loadDelta', () => loadDelta());
  _initialLoadDone = true;
  const rh = $('rh-rank'); if (rh) rh.classList.add('asc');
  _safeStep('refresh', () => refresh());
})();
