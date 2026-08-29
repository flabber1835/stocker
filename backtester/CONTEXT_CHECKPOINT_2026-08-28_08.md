# Context checkpoint — 2026-08-28 08

## Newly completed gates

### Shared-Wealth-Core equivalence — PASS

Workflow run: `33217309808`
Job: `99003711529`
Head SHA: `19ac4b2caf9e29656e3c54ad2856ec9f606b9906`
Pinned production/main source: `c502d077cae9c494f8b74a41ee8be7f40b25837d`

Bounded equivalence window: 1998-01-02 through 1998-12-31, 252 sessions.

Results:
- baseline elapsed: `1725.68` seconds
- shared-Wealth-Core implementation elapsed: `3605.45` seconds
- shared runner recorded `real_wealth_core_plans=252`, `reused_wealth_core_plans=252`
- baseline and optimized `daily.csv.gz` were byte-identical
- metrics files were byte-identical
- daily SHA256: `a7be9ad2044cb0fc952ea87b99c53548753f4cdacb0f431033279c4692b3eda0`
- both ended at A=D=1.0975759104 on 1998-12-31

Conclusion: computation reuse is economically exact for the certified window, but the current deep-copy implementation is materially slower (~2.09x elapsed time). Do not use this implementation as a performance optimization yet. The likely culprit is repeated deep-copy/equality work around state/feed images. Any follow-up optimization must preserve the byte-identical gate.

### Full-corpus split adjudication — PASS

Workflow run: `33218143982`
Exact corpus boundary: 46,238,394 bars, last session 2026-07-31.
Certified primary-source adjudications: 4.
Unresolved split population reduced exactly 128 -> 124.

### Full 128 split-window classification — PASS

Workflow run: `33217768333`
Classification counts:
- exact_inverse_match: 3
- shifted_direct_match: 44
- shifted_inverse_match: 4
- exact_no_transition_no_nearby_match: 66
- unresolved_price_domain_conflict: 11

Four of the 11 genuine price-domain conflicts are already certified/adjudicated: ACER, GOLLQ, MTL 2008, MTL 2016. Seven genuine price-domain conflicts remain for primary-source adjudication.

## Scanner status

### Original unresolved-open scanner — cancelled by GitHub runner time ceiling

Workflow run: `33196508963`
Job: `98934905157`
Status: cancelled after about six hours.

Useful partial chronology survived in logs:
- reached 2009-01-09 / session ~2773
- logged one unresolved-open allocation transition through that point: GPU security_id `121383` on 2001-11-14
- LIT/CIT boundary repair was confirmed: 2001-06-04 open resolved exactly at `242839480.805039`
- last checkpoint before cancellation: 2009-01-09 A=D multiple `5.0981715556`, running CAGR `15.9293090309%`

This is diagnostic-only NAV because the scanner intentionally continues after unresolved boundaries. Do not use scanner NAV as a backtest result.

### Comprehensive held-terminal-gap scanner

Workflow run: `33211049538`
Status at this checkpoint: still in progress on `Scan full chronological A path`.
This is the preferred terminal-gap scan because it records held unresolved terminal states even if no Sentinel allocation transition occurs.

## A/D replay status

Workflow run: `33210946520`
Status at this checkpoint: still in progress on the full chronological A/D replay v2.
This run predates the split-adjudication v3 launcher and should not be promoted as final PIT-certified output even if it completes; it remains useful as control/diagnostic evidence.

## Split-adjudication implementation

Research-only files remain on `research/backtester`:
- `backtester/causal_split_overrides.py`
- `backtester/data/causal-split-overrides-v1.json`
- `backtester/data/causal-split-overrides-v1.SHA256`
- `backtester/run_sector_ad_causal_terminal_splits_v3.py`

Current split override dataset SHA256:
`8951eb47afef2987b2101a80a9411c0e24356d50813a510c3fee4e773a982a9c`

The v3 launcher is intentionally dormant until remaining split and terminal certification work is closed.

## Current certification interpretation

A final financially defensible causal/PIT replay still requires:
1. resolve/adjudicate the remaining seven genuine price-domain split conflicts;
2. decide the correct treatment for shifted/inverted split classes and 66 no-transition cases with identity-safe, causal evidence;
3. finish the comprehensive held-terminal-gap scan or replace it with a checkpointed/bounded equivalent if GitHub's six-hour ceiling intervenes;
4. repair every economically reachable terminal gap discovered;
5. replace the current slow shared-Wealth-Core reuse implementation with a faster design only if byte-identical equivalence continues to pass;
6. run the final A/D replay under the completed causal terminal + split evidence bundle;
7. require all final fail-closed data/economic gates to pass before publishing CAGR/Sharpe/drawdown as certified PIT results.

## Next actions

1. Inspect `33211049538` as soon as it completes or hits the runner ceiling. Preserve its deepest completed chronology and all terminal-gap evidence.
2. Continue primary-source adjudication of the seven remaining genuine split conflicts.
3. Build a safe faster shared-Wealth-Core implementation. Avoid whole-feed/state deep copies; use canonical commitments / immutable post-plan state where proven safe. Re-run the 252-session byte-identical equivalence gate after every performance change.
4. Add bounded checkpoint/resume for scanners/replays so six-hour runner ceilings cannot erase full-history progress.
5. Do not modify production/main during this research sequence.
