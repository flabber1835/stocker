# Candidate versus certificate: semantic differences

Date: 2026-09-06. Scope: original candidate run 34007704385 and certificate run 34014048220. The candidate's 20.09% and certificate's 9.20% are observed outputs, not correctness criteria.

## Identities

| Field | Candidate | Certificate |
|---|---|---|
| Source | ba74e79490beb8950611b1d17f5d124833b3d91e | 27bb992087182c42c3c051e62bf837895f5d2ab7 |
| Workflow | champion-corrected-classification-20y.yml | backtester-research-champion-pit-v2-cert.yml |
| Entrypoint | research_champion_corrected_classification.py | run_research_champion_strict_pit_20y_v2.py |
| Profile | strategy9-e3-research-champion-v1 | Same |
| Runtime | 887f479b15ad861313da666ad698034d3847121c | Same |
| Canonical corpus | 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993 | Same |
| Warmup / measurement / end | 2006-01-03 / 2006-07-31 / 2026-07-31 | Same |
| Initial shadow cash | $100,000,000 | Same |
| Published status | CORRECTED_RECONSTRUCTED_PATH_NOT_YET_CERTIFIED | PIT_CERTIFIED |

The shared corpus digest binds the stored dataset. It does not make the two effective classifiers, terminal policies, execution rules, or generated programs identical.

## Economically material difference matrix

| Rule/input | Candidate behavior | Certified behavior | Why different / lineage | Intended-spec adjudication | Economic significance |
|---|---|---|---|---|---|
| Executable-order participation | No participation guard in the ordinary buy/sell path | Full requested order must fit 10% of mean prior 20 positive raw-compatible share volumes; excess remains pending | Research overlay 8c88ba180f9a7158ed02505e6562084eeffe848a; whole-order deferral 466bf93211851dc5c1ec45e10c5ee538cfee19a8; corrected closure explicitly removed it | Certificate contains a demonstrated harness regression: pinned production omits it and prior user instructions prohibit reintroduction | Changes fills, cash deployment, held exits, reserved slots and all subsequent selection/state paths; scale-dependent |
| Unknown security-type policy | Fills canonical unknowns using a provisional base ledger, reviewed-18 layer and PDS/EQM historical corrections | Unknowns remain ineligible | Candidate-only classification imports and `_BEST_TYPES.classify` loop | Effective universe intent is unresolved; candidate availability enforcement demonstrably defective for PDS | Changes eligible population, top-decile size, rankings, leadership witness, admissions and later risk control |
| Dividend cash lag | 1 trading session | 15 trading sessions | Candidate production-parity closure restores 1; hardening e820e3af9e2893cae301198201e2f5bf4b8f6944 selected 15; FZ later explicitly requires 15 | Documented conflict. Production config explains 1; freeze document expressly adopts 15 for formal certification. Neither is selected here by return | Changes spendable cash and affordable orders; accrued total NAV should remain conserved at settlement |
| Terminal-ID retirement | Tracks cumulative canonical terminal IDs; permanently excludes them from eligibility and cancels pending entries | Same-session terminal cancellation and next-leadership-witness filtering; no candidate-style permanent retired set | Candidate terminal lifecycle layer versus certificate terminal leadership overlay | Requires causal episode/terminal authority and explicit intended rule; exact lifetime of retirement must be specified | Can alter eligibility or re-admission after the event and alter the independent leadership portfolio |
| Leadership return on terminal date | Uses exact consideration when present; otherwise observed signal return; missing-return wrapper can use zero contribution | Observed signal close-to-close return; unavailable return raises | Candidate `_closure.production_leadership_return` / research_terminal_lifecycle versus C fail-closed transform | FZ names fail-closed leadership; production-parity candidate adopts another economic convention. Resolve explicitly | The leadership witness drives E3 recovery independently of whether the security is held in Wealth Core |
| Next-session leadership witness | Uses the post-retirement eligible ranking | Filters same-session terminal IDs from `prior_recent_sel` | Separate terminal overlays | Coupled to the retirement/terminal availability contract | Changes witness membership and denominator even when the held portfolio is unchanged |
| Missing held NAV mark | Last-raw mark remains valued; unresolved condition suppresses new admissions | After measurement start, raises unless the held ID is an approved pending terminal claim with a positive prior mark | Candidate production-parity closure versus strict financial-grade gate plus bounded C1 exception | Explicit contract conflict; FZ names resolved-NAV behavior | Can stop a replay or allow an economically different carried-value path |

Path journaling, output directories and summary labels also differ. They are observational/reporting differences. The complete normalized source comparison separates them from the seven economic rows above.

## Shared mechanics that do not explain the cross-run gap

Both paths start the shadow book at $100M, use 25 slots and 4% entry sizing, consume the same canonical dataset, use the same frozen E3 parameters, use next-open raw-price execution, charge 10bps per Wealth Core side, apply the same ordinary trailing-stop/review rules, and promote Candidate A to the authoritative strategy curve.

The shared book terminal overlay has exact-term settlement plus C1 carried-mark machinery. Candidate-specific terminal leadership and retirement still create distinct economic behavior. Calling both paths 'terminal-grace enabled' does not establish semantic equivalence.

Neither path substitutes an S&P 500 or Russell membership universe. Their materially different eligible universes arise inside the broad-corpus classification/retirement rules.

## Shared implementation defect: open dividend entitlement

Both generated sources compute `open_eq` before appending the current ex-date dividend receivable. They correctly capture entitlement quantity before open fills, but post the claim after those fills. Pinned production accrues the claim before the resolved-open-equity witness.

The allocation overlay splits return into overnight and intraday components when exposure changes. A missing open receivable shifts dividend economics across that boundary. The exact-source synthetic fixture uses previous NAV 100, an ex-dividend position worth 90 at the open, a dividend claim of 10, and closing NAV 100. With 10bps allocation-transition cost:

| Exposure change | Current generated factor | Entitlement-complete factor |
|---|---:|---:|
| 100% to 0% | 0.8991 | 0.9990 |
| 0% to 100% | 1.1100 | 0.9990 |
| 100% to 100% | 1.0000 | 1.0000 |
| 55% to 100% | 1.0495275 | 0.9995500 |

These are synthetic reproductions using the extracted `apply_overlay` functions, not claims about historical return impact. Both functions have the same normalized AST. `backtester/champion_economic_source_probes.py` reproduces the defect and checks source ordering.

The same probe executes the candidate's exact `_historical_correction` method and demonstrates the PDS 2006/2010 availability mismatch. Correct historical classification and contemporaneously available classification are separate requirements.

## Chronological observations from original retained daily artifacts

The two original files each retain 5,032 measured sessions. Their first retained session is 2006-07-31, after trading has already begun during warmup.

| Observation at 2006-07-31 | Candidate | Certificate |
|---|---:|---:|
| Eligible securities | 1,065 | 807 |
| Leadership pool size | 107 | 81 |
| Held positions | 25 | 18 |
| Shadow closing NAV | 92,410,966.71752562 | 93,207,107.2657491 |
| Shadow open NAV | 91,522,149.87468864 | 92,678,635.2706211 |
| Rebased strategy NAV | 1.0 | 1.0 |

First retained normalized strategy NAV difference: **2006-08-01**, candidate 0.9834836198103472 and certificate 0.98489555570064. The true first economic divergence precedes this reported-curve difference and is recovered by the bounded warmup audit.

First observed strategy-allocation difference: **2015-08-26**, candidate 0% and certificate 100%. The many earlier stock/book differences therefore precede that allocation divergence. This chronology does not assign the eventual CAGR gap to one cause.

Full-run summaries report 506 versus 197 buys, 424 versus 169 sells, and 930 versus 431 held dividend events. The common count of 6,100 applied tape splits is not evidence that both portfolios held the same split-affected positions.

## Prior capacity experiment: limited comparability

Run [33993610034](https://github.com/flabber1835/stocker/actions/runs/33993610034) on `372e2e40a8f65e6992de36dfabe8a98e5c3417ad` already tested an older best-effort terminal model. Its capacity-off $100M, capacity-on $10M and capacity-on $1M scenarios are retained and are not rerun here.

Comparing capacity-off $100M with capacity-on $10M changes two dimensions. The $10M-versus-$1M pair changes capital only, but on a different terminal fixture. These results cannot directly decompose the target 20.09%-versus-9.20% gap.

## Attribution discipline

The preregistered audit recovers both original warmup prefixes and changes one dimension at a time for three controls: participation guard, dividend lag, and unknown-type classifier. It holds $100M fixed. Baseline prefix reproduction, observer-stripped AST equality and independently reconstructed accounting are mandatory.

One-factor differences are path-dependent and interaction-sensitive. They must not be added as an arithmetic decomposition of the full CAGR gap. The prefix proves bounded mechanisms; full-horizon economic attribution and every terminal settlement remain separate outstanding proof obligations.

See `ECONOMIC_ATTRIBUTION_AUDIT.md` for actual diagnostic outcomes and `CERTIFICATION_ECONOMIC_SPEC.md` for the authoritative hold and unresolved decisions.
