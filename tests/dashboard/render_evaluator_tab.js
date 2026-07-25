// Headless render of the dashboard's Review tab.
//
// dashboard.js is plain browser JS with no test runner, so a ReferenceError in
// a render path is only discovered when a human opens the tab — and the Review
// tab's catch reports it as "Evaluator unreachable", which points the blame at
// the evaluator SERVICE rather than at the UI. That is exactly how a leftover
// `applyUi` reference (deleted with the one-click apply) survived: no rendered
// recommendation card was ever exercised outside a browser.
//
// This loads the real file into a vm with a minimal DOM and calls
// _renderEvalReport with report fixtures covering every card shape.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', '..', 'services', 'dashboard', 'static', 'dashboard.js');

function makeEl() {
  const el = {
    innerHTML: '', textContent: '', value: '', className: '', style: {},
    dataset: {}, children: [],
    classList: {add() {}, remove() {}, toggle() {}, contains() { return false; }},
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, removeEventListener() {}, setAttribute() {},
    getAttribute() { return null; }, remove() {}, focus() {}, closest() { return null; },
    querySelector() { return makeEl(); }, querySelectorAll() { return []; },
    scrollIntoView() {},
  };
  return el;
}

const els = new Map();
const document = {
  getElementById(id) {
    if (!els.has(id)) els.set(id, makeEl());
    return els.get(id);
  },
  querySelector() { return makeEl(); },
  querySelectorAll() { return []; },
  createElement() { return makeEl(); },
  addEventListener() {},
  body: makeEl(),
  documentElement: makeEl(),
  hidden: false,
};

const sandbox = {
  document,
  console,
  JSON, Math, Date, Number, String, Object, Array, Boolean, RegExp, Error,
  isNaN, parseFloat, parseInt, encodeURIComponent, decodeURIComponent,
  // Timers are no-ops: the file arms polling intervals at load time and we only
  // want the pure render path, not a live dashboard.
  setInterval: () => 0, clearInterval: () => {},
  setTimeout: () => 0, clearTimeout: () => {},
  fetch: () => Promise.resolve({json: () => Promise.resolve({}), ok: true}),
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  location: {href: '', search: '', hash: ''},
  navigator: {userAgent: 'node'},
  alert() {}, confirm: () => true,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

const code = fs.readFileSync(SRC, 'utf8');
vm.createContext(sandbox);
try {
  new vm.Script(code, {filename: 'dashboard.js'}).runInContext(sandbox);
} catch (e) {
  console.error('LOAD_FAILED: ' + e.message);
  process.exit(2);
}

// Fixtures: every recommendation shape the evaluator can emit. The VALID
// single-field edit is the one that crashed — it is the only branch that used
// to reach the deleted apply widget.
const REPORTS = {
  'valid single-field edit': {
    status: 'success', iso_year: 2026, iso_week: 30, as_of_date: '2026-07-25',
    manual: false, model: 'x', input_tokens: 1, output_tokens: 2, latency_ms: 3,
    recommendations: {
      overall_assessment: 'mixed',
      items: [{
        config_field: 'portfolio_builder.max_positions', config_field_valid: true,
        is_edit: true, suggested_value: '17', current_value: '30',
        direction: 'decrease', confidence: 'medium',
        observation: 'concentration', expected_effect: 'more edge per name',
        evidence: ['selection_audit: cap_blocked beat selected'],
      }],
      structural: [{finding: 'no news input', category: 'missing_data_source',
                    evidence: ['e'], suggested_approach: 'ingest', confidence: 'low'}],
    },
    report_markdown: '## Verdict\ntext', data_gaps: ['g'],
  },
  'general advice (config_field none)': {
    status: 'success', iso_year: 2026, iso_week: 30, as_of_date: '2026-07-25',
    recommendations: {overall_assessment: 'healthy', items: [{
      config_field: 'none', config_field_valid: true, is_edit: false,
      suggested_value: '', direction: 'investigate', confidence: 'high',
      observation: 'hold everything', expected_effect: 'avoid churn', evidence: [],
    }]},
    report_markdown: '', data_gaps: [],
  },
  'unknown config field': {
    status: 'success', iso_year: 2026, iso_week: 30, as_of_date: '2026-07-25',
    recommendations: {overall_assessment: 'concerning', items: [{
      config_field: 'made.up.knob', config_field_valid: false, is_edit: true,
      suggested_value: '1', direction: 'increase', confidence: 'low',
      observation: 'hallucinated', expected_effect: '?', evidence: [],
    }]},
    report_markdown: '', data_gaps: [],
  },
  'no recommendations': {
    status: 'success', iso_year: 2026, iso_week: 30, as_of_date: '2026-07-25',
    recommendations: {overall_assessment: 'healthy', items: []},
    report_markdown: '', data_gaps: [],
  },
  'running': {status: 'running', iso_year: 2026, iso_week: 30, as_of_date: '2026-07-25'},
  'failed': {status: 'failed', error_message: 'boom', iso_year: 2026,
             iso_week: 30, as_of_date: '2026-07-25'},
  'null report': null,
};

// The applied-changes strip reads module state loaded by a separate fetch, so
// seed it with the real row shapes the api writes (auto_promotion carries its
// diff/hypothesis/evidence inside new_value; 'pending'/'failed' must not show).
const APPLIED = [
  {applied_at: '2026-07-21T04:00:00Z', status: 'applied', applied_by: 'auto_promotion',
   config_field: '__full_config__', config_hash_before: 'aaaa1111',
   config_hash_after: 'bbbb2222',
   new_value: {config_hash: 'bbbb2222', promotion_hash: 'cafe',
               hypothesis: 'fewer names concentrate the edge',
               diff_vs_active: {'portfolio_builder.max_positions': {from: 30, to: 17}},
               evidence: {gate: 'tune edge +0.0400'}}},
  {applied_at: '2026-07-20T04:00:00Z', status: 'failed', applied_by: 'auto_promotion',
   config_field: '__full_config__', new_value: {}},
  {applied_at: '2026-07-19T04:00:00Z', status: 'pending', applied_by: 'auto_promotion',
   config_field: '__full_config__', new_value: null},
  // a legacy row from before whole-config promotion: no diff_vs_active at all
  {applied_at: '2026-06-01T04:00:00Z', status: 'applied', applied_by: 'dashboard',
   config_field: 'vetter.candidate_count', old_value: 50, new_value: 60,
   config_hash_before: 'cccc', config_hash_after: 'dddd'},
];

// The audit rows live in a top-level `let`, which in a vm is lexically scoped
// and NOT reachable as a sandbox property — so seed them the way the page does,
// through the real _loadAppliedChanges() fetch. That exercises the load path too.
function serveChanges(rows) {
  sandbox.fetch = (url) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(
      String(url).includes('/api/config/changes') ? {changes: rows} : {}),
  });
  return sandbox._loadAppliedChanges();
}

let failed = 0;

async function main() {
  for (const [name, rep] of Object.entries(REPORTS)) {
    for (const [variant, changes] of [['', []], [' + applied changes', APPLIED]]) {
      await serveChanges(changes);
      try {
        sandbox._renderEvalReport(rep);
        console.log('OK   ' + name + variant);
      } catch (e) {
        failed++;
        console.log('FAIL ' + name + variant + ' :: ' + e.constructor.name + ': ' + e.message);
      }
    }
  }

  // The strip must actually SHOW the promotion (it was fetched and dropped on
  // the floor for a while) and must never present a failed/pending apply as a
  // change that landed.
  await serveChanges(APPLIED);
  let html = '';
  try {
    sandbox._renderEvalReport(REPORTS['valid single-field edit']);
    html = sandbox.document.getElementById('eval-recs').innerHTML;
  } catch (e) {
    // A throw here is a RENDER failure (exit 1), not a harness failure (exit 2).
    failed++;
    console.log('FAIL strip :: render threw :: ' + e.constructor.name + ': ' + e.message);
  }
  for (const [must, why] of [
    ['Auto-promoted', 'auto-promotion not shown'],
    ['portfolio_builder.max_positions: 30 → 17', 'promoted diff not shown'],
    ['fewer names concentrate the edge', 'hypothesis not shown'],
    ['bbbb2222', 'resulting config hash not shown'],
  ]) {
    if (!html.includes(must)) { failed++; console.log('FAIL strip :: ' + why); }
  }
  if ((html.match(/Auto-promoted/g) || []).length !== 1) {
    failed++; console.log('FAIL strip :: a pending/failed apply was rendered as applied');
  }
  if (!failed) console.log('OK   applied-changes strip content');
  process.exit(failed ? 1 : 0);
}

main().catch(e => { console.log('FAIL harness :: ' + e); process.exit(2); });
