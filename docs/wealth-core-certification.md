# Wealth Core v1 — certification manifest

**Status: NO-GO.** `execution_model` stays `target_portfolio` in production. This
file is the evidence record: what is proven, what is not, and what the remaining
evidence runs must show. It is deliberately separate from
docs/wealth-core-test-rewrite.md (which narrates how the suite got here) because
a certification record has to be readable as a claim about the SYSTEM, not about
the work.

Nothing below may be summarised as "all repository tests pass". Three suites fail
on this branch AND on its parent; they are named in full at the bottom.

## What is proven, and by what

| Layer | Status | Evidence |
|---|---|---|
| deterministic state machine | strong | tests/wealth_core (434), golden fixture pinned `a09b12a87d1e…` |
| one implementation across live/backtest/tunnel | strong | `sys.modules` re-export shims, module IDENTITY asserted; tests/parity (45) |
| volatility-profile discrimination | strong | discriminator fixture; sabotaging `score_universe` is caught ONLY there |
| risk profile: initial construction | fixed + rehearsed | tests/risk_service TestInitialConstruction; chain rehearsal |
| risk profile: gate arithmetic | fixed + rehearsed | see "the 24-vs-25 result" below |
| legacy production behaviour | unchanged | `execution_model` defaults to `target_portfolio`; tests/scheduler (406), tests/pipeline (356), tests/delta_engine (376) |
| end-to-end chain rehearsal | implemented | bt-engine `POST /wealth-core/jobs/run` mode `chain_rehearsal` |
| exact Sharadar control | **pending** | needs the NAS |
| authoritative ACTIONS / data parity | **pending** | needs `POST /jobs/backfill-actions` |
| exact SEP raw-close verification | **pending** | needs the NAS |
| live activation | disabled by default | — |

## The 24-vs-25 opening result, resolved

The first rehearsal after the initial-construction fix reported **1 rejected
intent, 24 positions**. That reads as a legitimate refusal and was not. Asking
the rehearsal to NAME the rejection rather than count it exposed two defects in
the tunnel's risk gate — neither in the strategy, both in how the gate was fed:

1. **Reservation double-count.** `plan_session` reserves the slot at the moment
   of decision, so by the time the gate ran the intent's OWN reservation was
   already in `reserved_security_ids()`. `evaluate_entry`'s contract is that
   `pending_reservations` are the OTHER orders in flight, so `projected` was one
   too high for every entry. At the 25th admission that is the difference
   between a full book and a permanently short one: 24 held + its own
   reservation = 25 ≥ `maximum_positions`, refused **forever**. A book that can
   never fill its last slot holds 4% in dead cash and is not the strategy that
   was backtested.
2. **Always-zero notional.** The gate read `intent["price"]`, a key
   `OrderIntent.to_dict()` does not emit, so every entry was judged at a
   notional of 0.0 — and `aggregate_exposure_after` / `issuer_exposure_after`
   were left at their 0.0 defaults. `MIN_CASH_BUFFER`, `INSUFFICIENT_CASH` and
   both concentration caps were **structurally inert** while the suite reported
   "every intent carries a verdict". Neither changes a verdict in the golden
   scenario, so no result would ever have revealed it.

Both are fixed. The notional now comes from `last_known[security_id]` — the same
float the engine divided 4% of equity by, read back rather than re-derived — and
exposures from the shared `aggregate_exposures`. After the fix, over the golden
scenario:

```text
rejected intents        0
entries without a price 0
peak book size          25   (== n_slots)
S126  held  0 -> 24          opening: 24 ELIGIBLE candidates, not 24 slots
S127  25th admitted          ordinary one-per-session rule; state.initialized
S128  held 24 -> 25          book full
S145  SEC_STOPOUT            EXIT_TRAILING_STOP
S146  held 25 -> 24
```

So the answer is the second of the two acceptable outcomes: **the book opens with
24 and fills the vacancy by normal admission on the next session.** The first
outcome — backfilling inside the opening — does not apply, because the binding
constraint at S126 is the READY SET (24 eligible candidates), not the slot count;
there was no further eligible candidate to backfill with. Over the full 260-session
scenario the book oscillates 22–25 as exits and re-admissions occur.

`ChainRehearsal` now persists `rejections[]` (session, security, rule, reasons,
and the `held_positions` / `pending_reservations` the rule READ),
`entries_without_a_price`, `peak_book_size` and `book_size_by_session`. Reading
those counts back is how the double-count was found; a bare total could not have
distinguished a legitimate refusal from a gate miscounting its own inputs.

Falsifiers, so neither defect can return silently:

```text
test_the_book_actually_REACHES_max_positions          peak == n_slots
test_WITHOUT_THE_EXCLUSION_the_last_slot_can_never_be_FILLED
                                                      re-add the own-reservation
                                                      => MAX_POSITIONS rejection
test_every_entry_is_PRICED                            notional > 0 on every entry
test_the_gate_receives_a_REAL_notional_and_REAL_exposure
                                                      captured AT THE CALL, since
                                                      the inertness was invisible
                                                      in the result
test_a_ZERO_notional_cannot_trip_the_CASH_rules       why it mattered
test_a_DEFAULTED_exposure_cannot_trip_the_concentration_caps
test_the_opening_shortfall_is_filled_by_NORMAL_admission
```

## Initial construction — the exemption, stated exactly

Spec §6 opens the book by filling every available slot together; only afterwards
is there at most one admission per session. `evaluate_entry(is_initial_construction=True)`
stands down EXACTLY TWO limits:

```text
STOOD DOWN   maximum_new_entries_per_session      describes a steady state that
             maximum_pending_entry_reservations   does not exist yet
STILL BINDS  maximum_positions                    the opening FILLS slots, it does
                                                  not exceed them
             minimum_cash_buffer / cash            
             maximum_single_security_aggregate_exposure
             maximum_same_issuer_exposure
```

The caller must assert it explicitly; the default is the restrictive regime; and
it cannot silently recur, because `initialized` is set by the first FILL and
never cleared. Exits are unaffected in both regimes.

## Required evidence sequence (all remaining steps need the NAS)

1. `docker build --network host -t stocker-base:latest -f Dockerfile.base .`
   FIRST — `shared/` gained new module files and the backtest stack has no
   bind-mount override.
2. Rebuild every consumer of `shared/` (live and backtest stacks;
   `scripts/deploy-all.sh` if in any doubt).
3. `POST /jobs/backfill-actions` on bt-data. Until `bt_actions` is populated
   every run reports `split_source: derived` and is not certified-reproducible.
4. Complete the exact raw-close verification (`/coverage/raw-close`, exact
   endpoint) — the sampled endpoint reported 96.8875%.
5. `POST /wealth-core/jobs/run` mode `baseline_replay` over the authoritative
   period; require **all seven** hashes to match. Expected hashes come FROM the
   backtester — the endpoint refuses to recompute them, and refuses a partial set.
6. Repeat it and require byte-identical persisted artifacts.
7. `POST /wealth-core/jobs/run` mode `chain_rehearsal` over the same period.
   Require: no `ChainRehearsalDiverged`, `trace_problems: []`,
   `entries_without_a_price: 0`, and every entry in `rejections[]` explained.
8. Restart cuts through admissions, exits, dividends, terminal actions,
   cooldowns and defensive state, over the authoritative data.
9. Cross-engine parity over the authoritative data (not only the golden stream).
10. Keep `execution_model=target_portfolio` until every one of the above passes.

Steps 5–9 have only ever been run against the golden fixture. That is a synthetic
stream with known coverage gaps (no rename/reuse, no volatility dispersion), so a
green result there is necessary and not sufficient.

## Known-failing suites (pre-existing — NOT caused by Wealth Core)

Verified identical on the parent commit `f29c8d4` by stashing the branch and
re-running. None touches Wealth Core, the risk profile, the scheduler chain or
the backtest engines. Recorded here so no certification statement can round up
to "all tests pass".

| Suite | Failures | Cause |
|---|---|---|
| `tests/contracts` | 4 — `test_av_ingestor_runs_latest_contract`, `test_pipeline_runs_latest_contract`, `test_pipeline_delta_latest_contract`, `test_portfolio_builder_runs_latest_contract` | service-contract probes |
| `tests/cross_service` | 7 — `test_all_chain_services_agree_on_today[4 params]`, `test_all_chain_services_share_schedule_tz_name[None, UTC]`, `test_chain_services_today_is_eastern_not_utc_in_evening_window` | the `pipeline` TZ probe subprocess fails to start |
| `tests/trade_executor` | 1 collection ERROR — `test_state_transitions.py` | `ModuleNotFoundError: psycopg2` (not installed in this container) |

Separately, three suites cannot share one interpreter with another suite because
every service ships an `app` package: `tests/bt_engine` + `tests/risk_service`,
and `tests/parity` + `tests/shared`
(`test_bt_engine_imports_the_canonical_module`). Both collisions predate this
work and both pass when the suites run in their own process, which is what the
project's runner does.

## Green on this branch

```text
tests/wealth_core   434      tests/bt_engine    355      tests/scheduler   406
tests/parity         45      tests/risk_service 138      tests/pipeline    356
tests/backtester    156      tests/shared       781      tests/delta_engine 376
tests/bt_data       156      tests/smoke         10
```
