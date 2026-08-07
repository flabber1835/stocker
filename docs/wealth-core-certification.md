# Wealth Core v1 — certification manifest

**Status: NO-GO.** `execution_model` stays `target_portfolio` in production. This
file is the evidence record: what is proven, what is not, and what the remaining
evidence runs must show. It is deliberately separate from
docs/wealth-core-test-rewrite.md (which narrates how the suite got here) because
a certification record has to be readable as a claim about the SYSTEM, not about
the work.

Nothing below may be summarised as "all repository tests pass". Three suites fail
on this branch AND on its parent; they are named in full at the bottom.

## Resuming this work

**STATE AS OF 2026-08-06 (session end). Steps 1-4 of the evidence sequence are
DONE.** Last certification-relevant commit `f7104c1` on `main`.

```text
DONE   1  base rebuilt, both stacks deployed (scripts/deploy-wealth-core.sh)
DONE   2  every shared/ consumer rebuilt; deploy steps 6-10 all PASSED —
          all THREE deployed images produce golden hash a09b12a87d1ecc97,
          identical on all 7 layers (backtester / pipeline / windtunnel)
DONE   3  bt_actions backfilled: 664,039 rows, 1998-01-01..2026-12-31, 4m29s.
          Every run from here reports split_source: actions, not derived.
DONE   4  exact raw-close scan COMPLETED (not degraded): coverage 99.7649%
          (36,684,527 / 36,770,974). Gaps are per-TICKER vendor gaps in 43
          non-common-stock instruments, NOT a truncated backfill.
VOID   7  chain_rehearsal 2021-2023 ATTEMPTED and its result DISCARDED — the
          run had no pre-start warm-up. Fixed and tested; re-run required.
          See "Step 7 ran and produced an invalid experiment" below.
NEXT   7  chain_rehearsal, RE-RUN on the warm-up fix
BLOCKED 5,6,9  no producer for the backtester-side hashes — see below
```

### Step 7 ran and produced an invalid experiment (warm-up defect, fixed)

A 2021-2023 `chain_rehearsal` was started and its January-July 2021 behaviour is
**not a valid assessment of Wealth Core**. `_load_corpus` loaded bars only
between the REQUESTED dates and nothing outside the test suite ever called
`Feed.warmup`, so the signal had no history to read: eligibility needs
`REQUIRED_CLOSES` (127) observations, and the book therefore could not rank a
single name until roughly session 127 — late June. It sat in cash for half the
first year, built its opening book from a truncated window, and was compared
against a benchmark measured fully invested from day one. Every number was
arithmetically correct and the experiment was still wrong.

**Why nothing caught it.** Every fixture arrives with enough history or drives
the normalised engine directly. The property that failed belongs to the LOADER —
"an arbitrary DATED database rehearsal receives a pre-start window" — and the
loader is the one part the golden fixture cannot reach. The chain-vs-bulk
equivalence check could not catch it either: both paths were unwarmed, so their
hashes agreed. **Equivalence is a consistency check, not a correctness one**, and
that distinction is the reusable lesson here.

**The fix.** `_load_corpus` widens its query by `WARMUP_CALENDAR_DAYS` (400),
`_split_warmup` splits the sessions at the requested start and trims the earlier
part to `WARMUP_SESSIONS` (derived as `REQUIRED_CLOSES - 1`, never hardcoded), and
the warm-up is threaded into `rehearse_chain`, `baseline_replay` and `experiment`.
Warm-up sessions feed the series and nothing else: no decision, no fill, no equity
point, nothing hashed. Both the chain feed AND the bulk-replay feed are warmed —
warming one only would look exactly like a real divergence. A corpus with too
little history is REFUSED with a message naming the consequence, rather than
silently producing the delayed-start run again.

**Falsifiers, all confirmed to fail before the fix** (`tests/bt_engine/
test_wealth_core_warmup.py`, 19 tests). Removing either `feed.warmup` call breaks
the equivalence tests; removing BOTH — the case that first slipped through —
breaks `TestTheRehearsalBuildsABookOnSessionOne`, which asserts the observable
directly: 25 `OPEN_SLOT_POSITION` intents on the first measured session and a full
book within five. Dropping `warmup_sessions=` from any of the three `_execute`
dispatch sites breaks `TestTheWarmupSurvivesTheHandoff`.

**Acceptance criterion for the re-run.** On the first simulated session,
`eligible_universe_count` and the ranked candidate count must be substantial and
the run should construct up to 25 positions immediately — not after six months.

### Step 4 is passed; `operational` was lying, and is fixed

The coverage endpoint reported `operational: false` on a 99.76%-covered corpus.
That was a defect in the DIAGNOSTIC, not the corpus: the per-session probe read an
unordered `LIMIT` slice while the nulls are TICKER-correlated, so every probe
under-reported (0.895-0.945 sampled against 99.71-99.82% measured on the same
five sessions), and `exact=1` never revised the verdict it superseded. Fixed in
`c6b8355`; see docs/architecture.md "the coverage probe measured the wrong
thing". **`SESSION_USABLE_THRESHOLD` stays 0.95** — the input was wrong, not the
limit, and lowering it would have hidden the bug behind a green light.

### Steps 5, 6 and 9 are BLOCKED — and it is a missing producer, not a run

Step 5 requires `expected_hashes` "supplied by the BACKTESTER", and bt-engine
rightly refuses to compute them itself. **Nothing in the repo produces them.**

```text
run_wealth_core_replay()   services/backtester/app/wealth_core_replay.py:833
                           has ZERO callers — no route, no CLI, no script, no test
backtester container       has only DATABASE_URL -> live postgres. BT_DATABASE_URL
                           is on the EVALUATOR, not the backtester, so it cannot
                           reach the Sharadar corpus at all
parity_cli                 runs only the synthetic golden scenario, never a corpus
```

Closing it needs a route on the backtester running `run_wealth_core_replay` and
returning the seven hashes, plus read-only access to bt-postgres over the
published host port (the posture the evaluator already uses). Agreed shape:
background job + run row, mirroring bt-engine rather than inventing a second one.

**Also correct the claim while doing it.** Step 5 does NOT prove independent
implementation: bt-engine's `_load_corpus` imports `app.live.wealth_core_replay`,
the BACKTESTER's own loader, COPYed in at image build ("ONE CORPUS LOADER, NOT
TWO"). What it proves is IMAGE/ENVIRONMENT parity over real data — worth having,
but the manifest currently implies something stronger.

Step 7 (`chain_rehearsal`) is NOT blocked: `rehearse_chain` computes the bulk
hashes in-process and compares against them itself.

### Practical notes

**Every remaining step needs the NAS** — the authoritative corpus lives in
`bt-postgres` there and no dev container can reach it. Deploy repo is
`/volume1/docker/github/stocker` (NOT `/volume1/docker/docker/...`, which does
not exist). `make` is NOT installed on the NAS. Ports: bt-data **8030**,
bt-engine **8031**.

A `shared/` change still requires an UNCONDITIONAL base rebuild before any
consumer — the editable install caches the module list and the backtest stack has
no `shared/` bind-mount. Never pass `--volumes` to any compose command.

Before touching anything, check nothing is in flight (`curl -s
localhost:8030/runs/latest`). One trap already hit: `scripts/deploy-wealth-core.sh`
curls the coverage endpoint ~1 minute after recreating bt-data, and bt-data
re-applies `init_bt.sql` on startup — so the connection is RESET and the step
fails spuriously. Re-run rather than diagnose.

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
| deployed-image parity | **proven 2026-08-06** | all three images emit golden `a09b12a87d1ecc97`, identical on 7 layers, INSIDE the containers |
| exact SEP raw-close verification | **proven 2026-08-06** | `exact=1` COMPLETED: 99.7649% (36,684,527/36,770,974); gaps are per-ticker vendor gaps in 43 non-common-stock instruments |
| authoritative ACTIONS ingested | **done 2026-08-06** | `bt_actions` 664,039 rows, 1998-01-01..2026-12-31 |
| authoritative ACTIONS / data parity | **pending** | needs a run whose `provenance.split_source == "actions"` — step 7 |
| a dated replay is a backtest FROM its start date | **fixed 2026-08-07** | pre-start warm-up in `_load_corpus`/`_split_warmup`, threaded to all three modes and to BOTH the chain and bulk feeds; tests/bt_engine/test_wealth_core_warmup.py (19). The first 2021-2023 rehearsal is VOID — it ran unwarmed |
| exact Sharadar control (baseline_replay) | **BLOCKED** | no producer for the backtester-side hashes; see "Resuming this work". When unblocked it proves IMAGE/ENVIRONMENT parity, NOT independent implementation — one loader, COPYed; see step 5 |
| independent implementation parity | **not proven, and not provable by step 5** | would need a second loader written against the same spec; no such thing exists |
| live activation | disabled by default | — |
| performance measurement | **built 2026-08-06** | `shared/.../wealth_core/performance.py`; a rehearsal now persists CAGR / drawdown / turnover on the run row, surviving the >400-session elision. Derived output — asserted not to move any of the seven hashes |

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

**Status: 1-4 DONE (2026-08-06). 7 is next and runnable. 5, 6 and 9 are blocked
on the missing backtester-side hash producer — see "Resuming this work" above.**

Ports on the NAS: **bt-data 8030**, **bt-engine 8031** (published host ports; the
two stacks share no docker network by design).

1. **[DONE]** **Rebuild the base.** `shared/` gained new module files
   (`wealth_core/execution_model.py`, `wealth_core/live.py`) and the editable
   install caches the module list, so this is mandatory, not defensive:

   ```bash
   cd /volume1/docker/github/stocker && git pull origin main
   docker build --network host -t stocker-base:latest -f Dockerfile.base .
   ```

2. **[DONE]** **Rebuild every consumer of `shared/`**, both stacks. The backtest stack has
   no `shared/` bind-mount, so bt-engine and bt-data import the BAKED copy.
   `scripts/deploy-all.sh` if in any doubt — slower, and certain.
   `scripts/deploy-all.sh --verify` checks without changing anything.

3. **[DONE — 664,039 rows, 1998-01-01..2026-12-31]** **Backfill ACTIONS.** Until `bt_actions` is populated every run reports
   `split_source: derived` and is NOT certified-reproducible.

   ```bash
   # date_from / date_to are REQUIRED query params; cover the whole period the
   # certification runs will replay, or the uncovered span silently falls back
   # to derived splits.
   curl -sX POST "localhost:8030/jobs/backfill-actions?date_from=1998-01-01&date_to=2026-12-31"
   ```

   A certified run must additionally set `WEALTH_CORE_REQUIRE_ACTIONS`, which
   turns the derived-split fallback from a caveat into a refusal.

4. **[DONE — completed, 99.7649%]** **Exact raw-close verification.** The sampled endpoint reported 96.8875%; the
   exact one was previously broken by a ~15s statement timeout, now governed by
   `EXACT_STATEMENT_TIMEOUT_MS` with graceful degradation. Confirm it COMPLETES
   rather than degrades:

   ```bash
   curl -s "localhost:8030/coverage/raw-close?exact=1"
   ```

   Coverage is reported per SESSION and per TICKER, deliberately: a date range
   with no coverage means the backfill did not reach that far and should be
   re-run, while a ticker with no coverage means the vendor has none and
   re-running changes nothing. 97% looks identical in aggregate either way.

5. **[BLOCKED — no producer for the expected hashes]** **`baseline_replay` over the authoritative period.** Require all SEVEN hashes
   to match. The expected hashes come FROM the backtester — the endpoint refuses
   to recompute them (that would prove only that the tunnel agrees with itself)
   and refuses a partial set.

   ```bash
   curl -sX POST localhost:8031/wealth-core/jobs/run \
     -H 'content-type: application/json' -d '{
       "mode": "baseline_replay", "start_date": "...", "end_date": "...",
       "expected_hashes": { ...seven... }}'
   curl -s localhost:8031/wealth-core/runs/latest
   ```

   Check `provenance.split_source == "actions"` on the result before reading any
   other number.

   **WHAT THIS STEP PROVES, STATED EXACTLY — it is narrower than it looks.**
   bt-engine's `_load_corpus` imports `app.live.wealth_core_replay`, which is the
   BACKTESTER's own loader COPYed in at image build ("ONE CORPUS LOADER, NOT
   TWO"). Shared loader code compiled into separately built images proves
   **environment and image parity over real data** — that the same source, built
   twice and deployed twice, agrees. It does **NOT** prove independent
   implementation parity: there is one implementation, so a defect in it is
   reproduced identically on both sides and cancels out of the comparison. Two
   engines agreeing is only evidence when they are two engines. This distinction
   stays in the record permanently; it is not a caveat to be dropped once the
   step goes green.

6. **[BLOCKED on 5]** **Repeat it** and require byte-identical persisted artifacts.

7. **[NEXT — runnable now, NOT blocked on 5]** **`chain_rehearsal` over the same period.** Require: the run reaches
   `status: success` (a divergence RAISES, so a success row means the live path
   reproduced the bulk replay), `trace_problems: []`,
   `entries_without_a_price: 0`, `peak_book_size == 25`, and every entry in
   `rejections[]` explained by name — not merely counted. The 24-vs-25 episode
   above is why that last clause is not optional.

   ALSO require, since the first attempt failed exactly here:
   `provenance.warmup_sessions == 126` and a `warmup_first_session` roughly six
   months before `start_date`; and on the FIRST measured session, a substantial
   eligible universe with the book constructing up to 25 positions at once. A run
   that idles in cash into June is the unwarmed defect, not a strategy result —
   discard it rather than interpret it.

8. **Restart cuts** through admissions, exits, dividends, terminal actions,
   cooldowns and defensive state, over the authoritative data.

9. **[BLOCKED on 5]** **Cross-engine parity over the authoritative data**, not only the golden
   stream.

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
