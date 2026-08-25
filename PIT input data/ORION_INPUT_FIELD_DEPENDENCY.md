# Orion exact input-field dependency audit

## Scope

For this experiment, Orion is the runnable CAGR-producing executable at:

`research/sentinel-fastgate/experiments/2026-08-25-pit-vs-full-c/recovered/terminal_issuer_corrected/output/sentinel_1p1_standalone.py`

Source Git blob: `b9dba0c1999c1baf9f454189450235e4629906e6`

This is the executable that retained 5,032 sessions, 22.0946184986% CAGR, -21.9630978769% maximum drawdown, and a 54.1958520997x ending multiple. This audit does not treat the separate 22.6302156206% retained lineage as the same executable.

The trace covered `load_meta`, `load_actions`, `load_spy_bil`, the yearly SEP loader inside `run`, and every downstream reference to each loaded field.

## Result

- 25 source columns are read.
- 22 are economically active.
- 3 are dead reads: TICKERS `exchange`, TICKERS `lastpricedate`, and ACTIONS `contraticker`.
- Phase 1 directly supplies 10 of the 22 active fields.
- TICKERS `ticker` is functionally derivable from Phase-1 SEP rows, but current-snapshot TICKERS ordering cannot be reused.
- 11 active direct fields remain absent: six price/return fields and five TICKERS snapshot fields.
- Phase 1 also supplies SFP `closeunadj`, which the legacy executable does not read directly but which is the correct raw-close basis for the PIT SFP reconstruction. Phase-1 SFP `volume` is unused by this executable.

Conclusion: Phase 1 is valid, but it is not yet a complete Orion replay input set.

## Exact dependency table

| Dataset | Field | Active | Phase 1 | Current use | PIT disposition |
|---|---|---:|---|---|---|
| SEP | `ticker` | yes | present | Security row key and state mapping | Retain; create causal listing episodes and explicit tie ordering. |
| SEP | `date` | yes | present | Session chronology and action joins | Retain unchanged. |
| SEP | `open` | yes | missing | Raw-open reconstruction and entry signal | Derive `raw_open = open * closeunadj / close`; derive causal split-normalized signal open. |
| SEP | `close` | yes | missing | Momentum, risk, stops, review, breadth, split checks | Derive causal signal close from raw close plus effective split events. Do not copy the adjusted level. |
| SEP | `volume` | yes | present | Dollar volume, ADV20, execution availability, split CIL | Retain unchanged. |
| SEP | `closeadj` | yes | missing | Same-day split/dividend basis inference only | Derive only `dividend_basis` from adjacent adjusted-return ratio; discard adjusted levels. |
| SEP | `closeunadj` | yes | present | Raw close for marks, liquidity, P&L, split and dividend accounting | Retain as raw close. |
| TICKERS | `table` | yes | missing | Filters metadata to SEP rows | Eliminate; the PIT SEP namespace replaces it. |
| TICKERS | `permaticker` | yes | missing | Fallback issuer identity | Replace with date-gated SEC CIK issuer key. |
| TICKERS | `ticker` | yes | derivable | Master ticker list, integer map, implicit tie order | Build append-on-first-seen registry from SEP; lexical tie break for same-session arrivals. |
| TICKERS | `category` | yes | missing | Common-stock eligibility | Reconstruct dated common-stock evidence; unknown is ineligible. Coverage is not yet proven. |
| TICKERS | `sector` | yes | missing | Sector contagion in damaged breadth | Latest SEC SIC filed before decision session -> frozen FF12; missing SIC is singleton unknown. |
| TICKERS | `exchange` | no | missing | Loaded but never referenced | Remove; do not reconstruct. |
| TICKERS | `relatedtickers` | yes | missing | Same-issuer admission/holding exclusion | Replace with date-gated SEC CIK issuer key plus causal action lineage. |
| TICKERS | `lastpricedate` | no | missing | Loaded but never referenced | Remove; do not reconstruct. |
| ACTIONS | `date` | yes | present | Session index for events | Retain; add explicit session-phase availability rule. |
| ACTIONS | `action` | yes | present | Split, dividend, spinoff, terminal semantics | Retain frozen taxonomy and date/phase gating. |
| ACTIONS | `ticker` | yes | present | Event-to-security join | Retain; join through listing episode. |
| ACTIONS | `value` | yes | present | Split ratio and cash amount | Retain; reconcile split ratios to event-local price factor. |
| ACTIONS | `contraticker` | no | missing | Loaded, then always discarded | Remove; do not reconstruct. |
| SFP | `ticker` | yes | present | Selects SPY and BIL | Retain. |
| SFP | `date` | yes | present | Session index | Retain. |
| SFP | `open` | yes | missing | BIL adjusted open and return-leg split | Derive raw open and invariant overnight/intraday factors. |
| SFP | `close` | yes | missing | Denominator in BIL adjusted-open calculation | Use Phase-1 raw close; do not retain adjusted close. |
| SFP | `closeadj` | yes | missing | SPY stress returns and BIL total-return legs | Derive only invariant daily total-return factors; discard adjusted levels. |

## Reconstruction contracts

### SEP price domain

The PIT builder must produce, without retaining hindsight-adjusted levels:

1. `raw_open = open * closeunadj / close`; the same-row split factor cancels.
2. Event-local `effective_split_ratio` from changes in `close / closeunadj`, reconciled against dated ACTIONS `split` and `adrratiosplit` rows.
3. Causal `signal_open` and `signal_close` from raw prices multiplied by the cumulative effective split ratio through the session. With a complete split chain, this is equivalent to the legacy signal coordinate up to a ticker-constant scale.
4. Sparse `dividend_basis = pre_split|post_split` only for sessions containing both a split and dividend, derived from `closeadj_t / closeadj_(t-1)`.

Before metadata changes are enabled, the reconstructed price adapter must reproduce the legacy momentum ratios, risk scores, stop/review decisions, split quantities, dividend entitlements, raw fills, and complete Wealth Core session path.

### SFP SPY/BIL return domain

Retain only date-local factors in which future adjustment scales cancel:

```text
close_to_close_t      = closeadj_t / closeadj_(t-1)
adjusted_open_t       = open_t * closeadj_t / close_t
prior_close_to_open_t = adjusted_open_t / closeadj_(t-1)
open_to_close_t       = closeadj_t / adjusted_open_t
```

SPY `r20` and volatility acceleration are recomputed from daily close-to-close factors. BIL uses close-to-close when allocation is unchanged and the overnight/intraday factors when allocation changes. `raw_open` is separately derived from `open * closeunadj / close`; Phase-1 `closeunadj` supplies raw close.

### Issuer identity

Replace `permaticker` and `relatedtickers` with `issuer_key(session,ticker)` built only from SEC symbol/CIK evidence public strictly before the decision session. Shared CIKs group share classes. Later observations are never backfilled. Unresolved identities are singleton listing episodes. The branch already contains `symbol_cik_evidence.csv.gz`, `sec_cik_change_events.csv.gz`, and the Alphabet dual-class control.

### Sector

Sector is economically active: if at least half of held names in a sector are red, non-green peers become amber, changing damaged breadth and potentially fast-gate entry.

Use:

```text
ticker/session -> causal CIK
latest SIC with filed < decision_session
SIC -> frozen FF12
missing SIC -> singleton unknown peer
```

The retained SIC tape begins in 2009Q2. The 2006-2009 segment must therefore use singleton unknown unless earlier causal evidence is added. Current Sharadar sector is never a fallback.

### Category

The exact legacy eligibility rule is: category contains `Common Stock` and contains neither `Warrant` nor `Preferred`.

Reconstruct dated `is_common_stock` from as-filed SEC cover-page trading-symbol/security-title evidence, supplemented where reliable by Form 3/4/5 non-derivative security titles. Evidence is usable only after publication; unknown is ineligible.

The existing branch issuer tape comes from the Form 3/4/5 `SUBMISSION` table. It establishes symbol and CIK, not complete historical security type. Existing archives may provide partial title evidence, but candidate/session coverage has not been proven. If that gate fails, additional SEC cover-page data is required and must be approved before use. This is the principal unresolved data-coverage blocker.

### ACTIONS timing

The four active ACTIONS fields are present, and the current code only selects rows keyed to the simulated session. Certification must still bind every event type to a session phase. A terminal action consumed before the open must be public/effective by that cutoff or be deferred.

## Non-column economic dependency

The executable embeds:

```python
VERIFIED_CASH_SETTLEMENTS = {'VRNA': 107.0, 'DAWN': 21.50}
```

These are economic data, not strategy parameters. Move them into a dated terminal-settlement evidence file containing cash per share, effective session, first-public date, source provenance, and hash. Until then, the PIT directory is not self-contained.

The CLI start/end dates are experiment configuration and must be pinned in the replay manifest. The legacy `EXPECTED_HASHES` table is corpus identity only and must be replaced by the PIT-folder manifest.

## Required Phase 2 outputs

1. `SEP_PRICE_RECONSTRUCTION_PIT_ONLY`
2. `SFP_SPY_BIL_RETURNS_PIT_ONLY`
3. `SEC_ISSUER_IDENTITY_PIT_ONLY`
4. `SEC_FF12_PEERS_PIT_ONLY`
5. `SEC_SECURITY_TYPE_PIT_ONLY`
6. `TERMINAL_SETTLEMENTS_PIT_ONLY`
7. Updated source/derivation/output manifest

## Gates before the PIT A/B

1. Legacy adapter reproduces 22.0946184986% and the full retained daily path.
2. Price-only PIT adapter reproduces trades, fills, actions, shadow equity, allocation, and NAV before metadata substitutions.
3. Causal registry ordering has no unexplained tie-path drift.
4. Issuer and FF12 substitutions pass retained controls and use no future evidence.
5. Category coverage is complete for every candidate/session, or unknowns fail closed.
6. A filesystem guard proves the PIT replay opens no market-data path outside `PIT input data/`.

Only after all six gates pass is the full day-by-day PIT A/B a certified Orion comparison.
