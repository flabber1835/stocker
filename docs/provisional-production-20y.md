# Provisional current-production twenty-year backtest

## Bounded decision smoke comparison, 2026-09-19

The owner requested a quick smoke comparison instead of further historical
data repair. Reuse the retained PR #352 result and independently recorded
observations from run 34544522249, artifact 10179195109. Verify its checksums
and the production source binding. Drive the current production native and
recovery controllers from the recorded observation inputs, starting from fresh
controller state and preserving all subsequent state. Compare dated native
targets, recovery targets/reasons, effective exposure and severe signals to
the retained decisions. Expected decisions must never become transition inputs.
Replay controller JSON restoration every 300 sessions and compare that path too.
Report dated exposure changes and explicit comparison failures; do not repair
inputs or change production to obtain agreement. This small controller replay
can cover the full tape without rerunning universe selection.

This verifies controller decisions conditional on the old observed Core path.
It does not recompute stock selection, sizing, stops, corporate-action accounting,
breadth or leadership inputs. The old run used the reviewed-18 classification
overlay and an already invested July 2006 book, while the provisional current
engine run uses a fresh July account and leaves unknown classifications excluded.
Comparing those two stock-decision tapes directly would confound changed inputs,
initial state and implementation. No stock-decision parity or current production
CAGR is inferred from this smoke test. Keep the larger replay deferred.

Also replay the canonical V5 admission and opening-quantity functions against
the retained dated candidate, equity, cash, intent and opening-price records.
Compare admission/skip outcomes and whole-share quantities, recording exact
budget differences separately from changed decisions. These are conditional
checks of each recorded case, not a reconstruction of candidate ranking or the
subsequent book. Verify opening quantities with independent high-precision
cost bounds and an intentionally oversized-quantity falsifier.

Owner request, 2026-09-19: prioritize a twenty-year CAGR and ending-capital
multiple; defer completion of Stage 1. This is Stage 2 work. No NAS or real
broker access is authorized or required. Base verification used authenticated
Git fetch from `flabber1835/stocker`; experiment production revision is
`daa43caf995779bfa7e67195785520744021cb45`. Changes are delivered by PR only.

## Decisions before implementation

Use the current canonical Wealth Core and Sentinel economic transition without
patching strategy functions, changing thresholds, or relabelling old runtime
identities. Report a provisional economic-engine backtest separately from
full-service publication, execution, restart and deployment qualification.
An engine-only result cannot close those Stage 1 or NAS gates.

The requested measurement interval is 2006-07-31 through 2026-07-31. Initialize
a fresh account at the first measured close, after feature-only warmup over
the exact 252 preceding production-calendar sessions, 2005-07-29 through
2006-07-28. This is a conventional fresh-account twenty-year experiment; it
does not reproduce the frozen research book that began trading in January.
Preserve all positions, cooldowns and controller memory thereafter; do not
reset the book in each 300-session chunk. Capital defaults to USD 100,000 unless the owner
selects another amount. Record capital because whole-share sizing matters.

The production champion requires 252 causal feature-warmup sessions. The
retained packages start 2006-01-03; they cannot alone support the earlier
production startup schedule. First investigate reconstruction of the missing
2005 prefix from retained raw Sharadar and dated metadata authorities. Unknown
classification remains unknown/ineligible; no future metadata may be backfilled.
Absent evidence is not evidence of completeness. Any derived dataset receives
its own manifest and content identity, with the original packages untouched.

The attempted full-2005 reconstruction is retained with FAIL status: FCEC on
2005-04-28 and FSNMQ on 2005-02-09 have unresolved split evidence. Both precede
the fresh-account experiment's feature window. Reconstruct the exact required
prefix independently; do not relabel the failed artifact as passing. Extending
the experiment to reproduce January-start research state still requires those
earlier actions to be resolved.

The first input scenario uses the verified schema-1 base with a separately
verified 2005 prefix. It makes no schema-2 or frozen-champion equivalence claim.
Record every input identity. Dated SEC issuer groups are represented as opaque
grouping keys in the engine's metadata contract; an unknown issuer is a unique
security group, as declared by the dataset. No current TICKERS facts or reviewed
research classification guesses are substituted. Supply all retained spin-off
actions to the production entitlement guard, including incomplete child terms.

Each canonical benchmark partition rebases its first observation to one. Joining
those levels directly creates a false market return. The first attempt was
stopped after this adapter defect was found. Bind the original SFP factor source
to both manifests, recover its 2006-01-03 close-to-close factor, and uniformly
rescale the entire 2005 benchmark prefix onto the base package's level. Preserve
all within-partition ratios and the measured 2006-2026 levels. Missing, duplicated
or changed bridge evidence refuses the run. The rejected probe is not evidence
of valid economics.

The champion reference uses dataset
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`,
schema 2, while the locally downloaded base is schema 1, dataset
`7ceaaf4f88a3cd038df8fed328a52cf138251fad36ab32cf4a7af8c26c2266b2`.
Their identities cannot be interchanged. Verify source and member differences
before choosing a declared input scenario. Existing champion result and golden
artifacts remain historical evidence, not an acceptance oracle for corrected
production economics.

Retrieve the newer immutable schema-2 package through a narrowly scoped GitHub
Actions job when local package credentials cannot read it. The job has read-only
repository/package permissions, copies data from the pinned image without running
it, and retains a three-day artifact for authenticated local download. It does
not publish a package or alter source data. Verify its bytes against the already
retained manifest before any new scenario; never silently switch the input of
an ongoing run. This avoids leaving known retained terminal corrections out of
the eventual best-available-input result.

Compute multiple from final / initial measured NAV and annualize using the
actual elapsed calendar interval, explicitly recording the boundary convention.
Report the combined Core + defensive sleeve separately from Wealth Core alone,
with costs, benchmark, drawdown, terminal valuation and data limitations.
Never publish a headline multiple from blocked or unresolved production equity.
If missing authority prevents a valid run, retain the precise refusal and do
not substitute the historical 56.265x reference as a current result.
