# Wealth Core v1 — certification manifest

**Status: NO-GO.** `execution_model` stays `target_portfolio` in production. This
file is the evidence record: what is proven, what is not, and what the remaining
evidence runs must show. It is deliberately separate from
docs/wealth-core-test-rewrite.md (which narrates how the suite got here) because
a certification record has to be readable as a claim about the SYSTEM, not about
the work.

Every suite in the repository passes at `ae2db54` when the test runner has the
dependencies the suites import. The earlier "three suites fail on this branch AND
on its parent" line was WRONG and is retracted — see "Suite failures that were
provisioning, not code" at the bottom. What may still not be summarised as "all
repository tests pass" is Wealth Core's CERTIFICATION, which is a claim about
evidence runs over real data, not about the suite.

## Resuming this work

**STATE AS OF 2026-08-08 (later session). C IS COMPLETE AND WIRED.**
`tests/wealth_core` is GREEN at 552 tests. The 2021-2023 rehearsal is now the
next action and nothing in the code blocks it. Read this section before anything
else.

```text
DONE      corpus defect A   bt_universe keyed on (snapshot_date, permaticker);
                            writer reports PERSISTED not attempted. Deployed;
                            universe rebuilt: 20,728 identities, 0 rejected,
                            29,108 multi-table duplicates collapsed
DONE      corpus defect B   spliced price history CLOSED. 2 tickers (BIOT, REF),
                            1,343 rows deleted, both prior holders verified
                            intact under BIOT1 / REF1. bt_data_version bumped
DONE      defect D1         'N/A' is a vendor SENTINEL, not a counterparty
DONE      defect D2         `value` is a deal size in $M, never a ratio or a
                            price; the stated-zero write-off route REMOVED
DONE      defect D          per-name action vocabulary with an explicit SIDE;
                            one termination stated across rows deduplicated
DONE      C, the rule       shared/.../wealth_core/settlement.py — the waterfall
                            as a PURE function
DONE      C, the semantics  C1 grace period + TERMINAL_PENDING_TERMS
DONE      C, the wiring     settlement.py + state.py + terminal.py + marks.py +
                            adapter.py. Golden fixture RE-PINNED, decomposed
                            below. 552 tests green
```

### What the wiring turned out to require, beyond the plan

The previous handover specified five steps. Four survived contact; the parts that
did not are recorded here because both were found by a test rather than by
reading, and both would have cost a rehearsal.

**1. `terminal_pending_reference` became `terminal_pending_terms`.** The plan
stored the event's reference string. That is not enough: a terminal event appears
in ACTIONS on ONE session and never again, so from the session after the
announcement there is nothing left to re-resolve against, and `sweep_pending_terms`
would have needed its own settlement rule for expiry — a second implementation of
the waterfall, which is how two engines drift. The state now carries the
serialised terms plus `stale_at_event`.

**2. AN ANNOUNCEMENT IS NOT A TERMINAL DAY.** The documented waterfall put
"executable terminal-day print" ABOVE the carry. True on a terminal day, false on
every other day, and nothing in the data distinguishes them — a contested bid
prints an ordinary executable close, so the print settled the position at market
on the announcement and foreclosed the terms. That is the SAME foreclosure defect
the grace period was introduced to fix, reached through a different branch, and
the golden fixture caught it for the THIRD time. The print now settles only once
there is nothing left to wait for. docs/architecture.md carries the correction.

**3. The grace clock runs on the TERMINAL CONDITION, not on the announcement**
(found by review, after the first wiring commit). `sweep_pending_terms` aged the
grace on every session, so a deal that stayed pending longer than ten sessions —
a contested bid, a long regulatory review — had its position proxy-settled at the
frozen event-time mark WHILE THE SECURITY WAS STILL TRADING at a different price.
A sale nobody made, at a price nobody traded, because a calendar ran out. A
session on which the security prints a current mark now does not age the grace;
the counter is paused, never reset, so an intermittently-printing security still
settles. Falsifiers:
`test_a_deal_pending_LONGER_than_the_grace_stays_owned_while_it_trades` and
`test_and_then_settles_once_it_STOPS_trading`, both shown to fail without the fix.

The golden fixture could not catch this AND was one session from being wrong
itself: SEC_STRANDED's counter reached 9 at S209 under the old rule and needed
10, so its $61.50 terms landed with a single session to spare. That margin was
load-bearing and nobody had chosen it.

**4. The recency bound is measured AT THE EVENT — rehearsal-blocking.**
`C1_GRACE_SESSIONS` and `MARK_RECENCY_SESSIONS` are both 10, and a security that
stops printing at its announcement goes stale at exactly the rate the grace
elapses:

```text
staleness   1  2  3 ...  10  11
pending     0  1  2 ...   9  10   <- grace expires
at expiry   staleness 11 > recency 10  -> BLOCKED, permanently
```

Every one of the 19,216 delisted Sharadar securities stops printing at delisting,
so the C1 settlement branch was UNREACHABLE for the entire population and the
rehearsal would have frozen exactly as it did before the waterfall existed. Two
individually-correct constants, interacting. Staleness at the announcement is now
frozen and reused. Falsifier:
`test_a_delisted_security_SETTLES_when_the_grace_expires`.

### The rehearsal OOM, and why the first two fixes were wrong

Three consecutive OOM kills on the 2021-2023 chain rehearsal. Recorded in full
because the first two diagnoses were both plausible, both acted on, and both
wrong — and the only reason the third is trustworthy is that it was MEASURED.

```text
attempt 1  raise the memory cap        WRONG DIAGNOSIS, and the cap was never
                                       even applied. .env said 8g; the container
                                       ran at 4g because mem_limit only takes
                                       effect on RECREATION and bt-engine was
                                       never recreated after the setting landed.
                                       Two runs died against a limit everyone
                                       believed had been raised
attempt 2  bound diagnostic retention  CORRECT CHANGE, WRONG TARGET. Bounding
                                       SessionRehearsal and RunTrace moved peak
                                       RSS on the 260-session golden fixture by
                                       ONE MEGABYTE:

                                         full     78MB
                                         bounded  77MB
                                         none     77MB

                                       Kept as bc2dfa6 because it is a proven-
                                       safe retention control with an
                                       equivalence harness, NOT because it fixed
                                       anything
attempt 3  candidate payload           MEASURED. Every session's Decision holds
                                       a `candidates` list with ONE ROW PER
                                       ELIGIBLE SECURITY: 124 rows/session on a
                                       125-security fixture, 32,014 dicts over
                                       260 sessions. At corpus scale that is
                                       ~2000 x 753 = ~1.5 MILLION dicts, held
                                       simultaneously by the chain pass and the
                                       bulk replay. That is the OOM
attempt 4  THE FIX HAD NO ROUTE        The streaming path was built, tested and
                                       merged, and PRODUCTION COULD NOT ASK FOR
                                       IT. `rehearse_chain` took `retention_mode`
                                       (which selects `hash_mode="streaming"` for
                                       anything but `full`); `WealthCoreJobRequest`
                                       had no such field and `_execute` never
                                       passed one. Every rehearsal ran `full`,
                                       i.e. materialised, i.e. the attempt-3 OOM.
                                       Three MORE runs died after the fix landed
                                       (08-07, 08-08 x2, 08-09), and a fourth on
                                       08-09 07:01 was instrumented and measured
                                       +0.128 GiB per 5-minute sample, DEAD LINEAR
                                       across eleven consecutive samples, to the
                                       cap at 2h52m. Fixed 2026-08-09: the field
                                       exists, is passed, is logged at job start,
                                       and a falsifier test fails when the two
                                       kwargs are removed
```

**Read attempts 2 and 4 together or attempt 4 is misleading.** Bounding the
retention lists is worth one megabyte; what `retention_mode != "full"` actually
buys is `hash_mode="streaming"` (`wealth_core_chain.py:515`), which folds the
~1.5 million candidate dicts into the parity hashes session-by-session and
discards them. Retention is the SWITCH, streaming is the SAVING. Naming the
switch as the cause — as the first read of the 08-09 RSS curve did — gets the
right fix for the wrong reason, which is how attempt 2 happened in the first
place.

**The lesson worth keeping.** `HostConfig.Memory` is the only statement about a
container's limit that counts — not `.env`, not the compose file, not the
manifest. `scripts/deploy-all.sh --verify` asserts it as of 2026-08-09
(`bt-engine memory limit`), because a limit that lives only in configuration is a
limit nobody is enforcing, and this one silently cost three multi-hour runs.

**The generalisation, which is the expensive part.** Attempts 1 and 4 are the
SAME defect at different layers: a setting that existed, was believed, and was
not in force. `.env` said 8g while the container ran 4g; the code accepted
`retention_mode` while the endpoint could not send one. Neither failed loudly —
both presented as the original symptom, so each was re-diagnosed from scratch.
Cost: six multi-hour runs. **A control is not in force until something OBSERVES
it in the running system**, which is why the cap is now asserted by `--verify`
and the retention mode is now printed at job start.

**The cap on this NAS is 5 GiB and must not be raised to 8g.** The compose
fallback is `4g`, `.env` supplies `5g`, `HostConfig.Memory` reads 5,368,709,120,
and `dmesg` confirms the kills land at ~4.96 GiB anon-rss. The 8g figure in
attempt 1 predates measuring the host: `free -h` shows **7.7 GiB total**. A
cgroup limit above physical RAM never binds — the HOST OOM killer fires instead
and chooses its own victim, which is the 2026-07-24 outage where every container
was gone by morning. The container cap exists to make bt-engine the predictable
casualty; setting it above RAM removes that property while looking like more
headroom.

**Why the candidates cannot simply be dropped.** They feed
`candidate_audit_hash`, `decision_hash` and `RunResult.to_dict()` — three parity
layers. Removing them moves hashes. The fix is to STREAM those hashes: fold each
session's rows into a running sha256 that emits byte-identical output, then
discard them. `CanonicalListStream` (d5f5702) is that primitive, proven against
the engine's own payloads and consumed by nothing yet.

**Acceptance gate before the three-year run is attempted again:**

```text
1  candidate_audit_hash, decision_hash and final_result_hash BYTE-IDENTICAL
   between the materialised and streaming paths on the golden fixture
2  the 17-output retention equivalence harness still exact
3  the streaming path demonstrably retains NO candidate rows after folding
4  a 125/500/1000/2000-universe scale test showing peak RSS tracks ONE
   session's universe, not universe x sessions
5  absolute peak RSS and slope RECORDED, not just pass/fail — so the full
   corpus can be estimated to fit BEFORE spending two hours finding out
```

`hash_mode` is explicit and immutable for a run (`materialized` | `streaming`)
so a long certification cannot mix both paths mid-run, and the sentinel used to
splice the sessions array into `final_result_hash` must be structurally
impossible to collide with real content and asserted to occur exactly once.

### The golden re-pin, decomposed

```text
a09b12a87d1ecc97...  ->  04a58dba05595dcd...  ->  5c1af5731f79c702...
```

TWO re-pins, in two commits. The FIRST carries the whole economic movement and is
decomposed below. The SECOND (the grace-clock fix) moved `result_hash` ALONE —
`final_state_hash`, `ledger_hash`, `final_cash`, `final_positions`,
`blocked_sessions` and every ledger event count are byte-identical across it. The
only difference is intermediate per-session bookkeeping:
`terminal_pending_sessions[SEC_STRANDED]` now reads 0 throughout instead of
climbing 1 to 9, because the security keeps printing. Zero economic change, which
is the evidence that SEC_STRANDED's outcome never depended on the buggy clock —
it was one session from depending on it.

MOVED, and why — one economic change, fully accounted:

```text
blocked_sessions   19 -> 9. S200-S209 (SEC_STRANDED's announcement to its
                   resolution) are now CARRIED at a trustworthy mark instead of
                   blocked, so they have a valuation. The other nine (S170,
                   S175-S179, S182-S184) are UNCHANGED — they come from vendor
                   bars flagged unresolved_corporate_action, a different
                   mechanism, and they still block
final_cash         34824.20 -> 34868.23, i.e. +44.03. Ledger cash deltas
                   -965175.80 -> -965131.77, the same +44.03. The book admitted
                   during the ten sessions it was previously frozen: two BUYs
                   moved EARLIER (S211->S201, S212->S207) and one later BUY
                   resized (S231 SEC_F090, 3 -> 659 shares)
ledger_hash        follows the above
final_state_hash   follows, plus three new (empty) state dicts
```

UNMOVED, asserted rather than assumed:

```text
final_positions       24
ledger_event_counts   IDENTICAL — BUY 30, CASH_MERGER 2, CONVERSION 2,
                      DIVIDEND_ACCRUED 1, DIVIDEND_PAID 1, SELL 3, SPLIT 1,
                      WRITE_OFF 1. Same number of every event type
SEC_STRANDED          still settles at exactly $61.50 via EXACT_TERMS at S210 —
                      the real terms, never a proxy. This is the whole point:
                      the grace did not change the outcome, it stopped the
                      engine foreclosing it
every other terminal  SEC_MERGED $54.00, SEC_BUST write-off at 0, SEC_CONVERTED,
                      SEC_MIXED — all unchanged
```

**DEPLOY CONSEQUENCE, do not miss this.** The certified cross-image hash recorded
elsewhere in this file and in CLAUDE.md is `a09b12a87d1ecc97`. It is now
`5c1af5731f79c702`. All THREE images must be rebuilt from a fresh
`stocker-base` before any parity claim is made again; an unrebuilt image will
emit the old hash and read as a divergence.

### Coverage that MOVED rather than existing

`SEC_STRANDED` was the golden scenario's only case that blocked on missing terms.
It now carries, correctly, so the golden run produces NO `state.unresolved_terminals`
entry and no `blocked` terminal result at all. Two consequences, both deliberate:

```text
test_a_security_that_stops_printing_still_blocks_while_unresolved
  -> replaced by test_a_security_with_an_UNKNOWABLE_outcome_still_blocks, which
     asserts the REMAINING blocks (vendor unresolved_corporate_action) and
     asserts NO terms-block, so a regression that reintroduces one fails here

the terms-block path end-to-end
  -> moved to tests/wealth_core/test_adapter.py::
     TestATermsBlockStillReachesTheEquityGate, which drives the real session
     loop. NOT added to the golden scenario: a new security there perturbs
     rankings and admissions for every other assertion in that file

restart matrix, corrupt_unresolved_terminals
  -> REMOVED, not relaxed. Under the grace this scenario has no state-level
     block at any cut, so the mutation cleared an already-empty dict and could
     no longer fail. A control that cannot fail is worse than none. Replaced by
     test_a_lost_grace_counter_changes_the_outcome, which builds the condition
     the golden stream lacks — a carried security that STOPS printing, where the
     counter actually drives the result
```

### Then, and only then, the rehearsal

`settlement.py` is a NEW shared module and the backtest stack has NO `shared/`
bind-mount, so the base rebuild is mandatory and unconditional. A stale base does
not fail at startup — it surfaces as a `TypeError` deep inside a background task,
minutes into a three-hour job.

The wiring additionally changed FOUR existing shared modules — `state.py`,
`terminal.py`, `marks.py` and `adapter.py` — and `PortfolioState` gained three
persisted fields, so the state hash and the golden result hash both moved. Any
image still running the old base will emit `a09b12a87d1ecc97` and read as a
PARITY DIVERGENCE rather than as a stale build. Rebuild everything, then confirm
the hash BEFORE spending three hours on a run:

```bash
cd /volume1/docker/github/stocker && git pull origin main
docker build --network host -t stocker-base:latest -f Dockerfile.base .
docker compose -f docker-compose.backtest.yml up -d --build bt-engine bt-data
scripts/deploy-all.sh --verify

# GATE: all three images must emit the NEW golden hash before proceeding.
python -m tests.wealth_core.repin_golden --check 2>/dev/null || \
  python -c "from stock_strategy_shared.wealth_core.golden import golden_scenario; \
from stock_strategy_shared.wealth_core.run import run_sessions; g=golden_scenario(); \
print(run_sessions(sessions=g.sessions, bars_by_session=g.bars_by_session, \
meta=g.meta, starting_cash=g.starting_cash, terminal_events=g.terminal_events \
).result_hash())"
# expect 5c1af5731f79c7029d0c92b82275ef3b2b84d2a4fed0afbdc32688dfb6103a89

curl -X POST localhost:8031/wealth-core/jobs/run -H "Content-Type: application/json" \
  -d '{"mode":"chain_rehearsal","start_date":"2021-01-01","end_date":"2023-12-31"}'
```

A SIX-MONTH run (`end_date: 2021-06-30`) is worth doing first. It exercises the
warm-up, the repaired corpus and D together in ~20 minutes instead of three hours,
and is far less likely to reach a terminal event.

Acceptance, in this order — stop at the first failure rather than reading on:

```text
provenance.split_source == "actions"        else the run is not reproducible
provenance.warmup_sessions == 126           else it is the unwarmed defect again
status == "success"                         a divergence RAISES, so success means
                                            the chain reproduced the bulk replay
first measured session                      substantial eligible universe, book
                                            constructing up to 25 at once
trace_problems == []; entries_without_a_price == 0; peak_book_size == 25
the SIX settlement counters PRESENT         WIRED 2026-08-08 — before that fix
                                            NO run emitted them at all, so this
                                            criterion was unmeetable and a run
                                            reporting none was not evidence of a
                                            quiet corpus. A three-year run over
                                            ~2000 names
                                            reporting none of them has not
                                            measured what it claims
derived_last_mark_settlements > 0           THE ONE TO READ FIRST. Sharadar
                                            states no per-share consideration
                                            for ANY of its 19,216 delisted
                                            securities, so essentially every
                                            terminal event must arrive here via
                                            the C1 grace. A run reporting ZERO
                                            of these alongside a nonzero
                                            unresolved_terminal_events has hit
                                            the recency/grace interaction again
                                            and is BLOCKING, not settling —
                                            stop and re-read the constants
pending_terms_carried > 0                   the carry engaged at all
unresolved_terminal_events                  expected SMALL. Large means marks are
                                            failing the recency bound at the
                                            event, which is a CORPUS question
                                            (are prices present up to the
                                            delisting?), not a rule question
orphan_zero_writeoffs                       expected small. Large means
                                            documented events are reaching the
                                            C2 zero, which the sweep ordering
                                            exists to prevent — that would be a
                                            correctness failure, not a datum
performance, NOT chain_performance          the latter carries no fills and so
                                            reports zero turnover by design
```

### PREDECLARED, before the 2021-2023 result was seen

Written 2026-08-09 while the run was still in phase 2, so the settlement counts
are a FALSIFIABLE EXPECTATION rather than a post-hoc reading. Anything a summary
can be made to explain after the fact explains nothing.

```text
                                 golden fixture      real corpus
exact_terminal_settlements       5   (dominant)      ~0   <- INVESTIGATE if not
pending_terms_carried            1                   high
derived_last_mark_settlements    0                   DOMINANT
orphan_zero_writeoffs            0                   low
unresolved_terminal_events       0                   low but possible
```

**Why the two sources are near-DISJOINT on settlement, which is the point.**
Sharadar states no per-share consideration for ANY of its 19,216 delisted
securities, so `EXACT_TERMS` is structurally unreachable from the corpus — while
it is the branch the golden fixture exercises MOST. Conversely the fixture has
one carried deal; the corpus should put thousands of real delistings through
missing terms -> grace -> carry -> last-mark derivation. Neither source covers
the settlement space alone, and the branch each proves best is the one the other
can barely reach.

That is a stronger claim than "fixture is the floor, corpus adds richness":

```text
synthetic fixture   BRANCH COMPLETENESS — proves every required behaviour can
                    still execute, including branches the vendor corpus cannot
                    be relied upon to produce
historical corpus   PRODUCTION-SHAPED STRESS AND FREQUENCY — proves the ugly
                    operational path at a scale no fixture can manufacture
```

So fixture coverage is NORMATIVE and corpus coverage is DESCRIPTIVE. A quiet
window must never lower the bar by exercising fewer branches; it should say so
in its own manifest instead.

**A nonzero `exact_terminal_settlements` from the corpus is an INVESTIGATIVE
EVENT, not a benign counter.** It would mean one of: Sharadar supplies usable
consideration in an action form we did not expect; the adapter inferred terms
from another field; or the completeness test is too permissive. All three change
what the run means, and the first is good news that still has to be verified
before it is believed.

**The counters are the whole point of the run.** The rehearsal's purpose is not
"did it finish" — a run that writes off every acquisition at zero also finishes,
faster, and reports a lower return rather than an error. Read
`derived_last_mark_settlements`, `orphan_zero_writeoffs` and
`unresolved_terminal_events` against each other BEFORE reading any performance
number; the three of them are the only evidence that the waterfall did what it
claims, and a CAGR computed over a book that silently zeroed its terminations is
worse than no CAGR at all.

`BT_ENGINE_MEM_LIMIT` was raised to 8g after the previous attempt pinned at
3.98/4.00 GiB during the bulk-replay pass. That pass emits NO progress, so a
silent stretch at 100% is normal, not a hang.


### Earlier state, kept as HISTORY (superseded by the block above)

The evidence-sequence position as of 2026-08-06, and the two void rehearsal
attempts. Retained because the corpus facts (rows 1-4) are still current and the
two VOID entries record what those runs cost and why — but for "what do I do
next", read only the section above.

```text
DONE   1  base rebuilt, both stacks deployed (scripts/deploy-wealth-core.sh)
DONE   2  every shared/ consumer rebuilt; deploy steps 6-10 all PASSED —
          all THREE deployed images produce golden hash a09b12a87d1ecc97
          (SUPERSEDED — the C1/C2 wiring re-pinned it to 5c1af5731f79c702;
          re-run this after a forced stocker-base rebuild),
          identical on all 7 layers (backtester / pipeline / windtunnel)
DONE   3  bt_actions backfilled: 664,039 rows, 1998-01-01..2026-12-31, 4m29s.
          Every run from here reports split_source: actions, not derived.
DONE   4  exact raw-close scan COMPLETED (not degraded): coverage 99.7649%
          (36,684,527 / 36,770,974). Gaps are per-TICKER vendor gaps in 43
          non-common-stock instruments, NOT a truncated backfill.
VOID   7  chain_rehearsal 2021-2023 ATTEMPTED and its result DISCARDED — the
          run had no pre-start warm-up. Fixed and tested; re-run required.
          See "Step 7 ran and produced an invalid experiment" below.
VOID   7  SECOND attempt (2026-08-07, run da0086fe) also invalid, different
          cause: BLOCKED from 2023-02 to the end of the window by one
          unmarkable holding, then killed at 99.5% of a 4 GiB cap during the
          bulk-replay pass. See "The second attempt" below.
BLOCKED 7  re-run is GATED on corpus defects A, B, D and the orphan contract C
          — docs/data-sources.md and docs/architecture.md "orphan resolution"
BLOCKED 5,6,9  no producer for the backtester-side hashes — see below
```

### The second attempt (2026-08-07, run `da0086fe`) — VOID, and worth the time

The warm-up fix WORKED: the book was invested from session one (10.2% drawdown
and +21.6% by session 20, where the unwarmed run would have been flat cash at
exactly 1,000,000 until ~session 127). Two unrelated problems then made the run
unusable, and the diagnosis of the first is the most valuable output of the
session.

**It blocked.** From roughly 2023-02-03 every session was `blocked` with
`resolved_equity = None`, so `measure(allow_blocked_gaps=True)` dropped them and
the progress block froze — identical CAGR, drawdown AND benchmark across samples
spanning sessions 535 to 610, beside an advancing counter. A frozen BENCHMARK is
the decisive tell: `_benchmark` is computed over `observed_sessions`, so a merely
flat strategy cannot stop it. 218 of 753 sessions, 29% of the run, strictly
unevaluable by the standing rule.

Traced to a single security and, from there, to three independent defects in how
the corpus is READ — full evidence in docs/data-sources.md:

```text
A  bt_universe is keyed (snapshot_date, ticker) while carrying permaticker, so a
   reused symbol collides and one company is overwritten. _upsert_universe
   reports rows ATTEMPTED (49,834) not persisted (21,733) — a ~56% loss behind a
   number that reads as an answer
B  consequence: the erased company has no permaticker, the resolver sees ONE
   owner, skips the window check BY DESIGN, and splices two companies' prices
   under one symbol. All three refusal paths bypassed; reused_tickers silent
D  the vendor supplies EVENT METADATA, not holder-level settlement terms. No
   cash per share and no exchange ratio at ANY action type; `value` is the deal
   size in $M and `contraticker` is the literal string 'N/A' when the acquirer
   is private. `contra = x or None` does not catch 'N/A', so all 19,216
   delisted rows take the CONVERSION branch and block on
   MISSING_DELIVERED_SECURITY. The action-NAME mismatch is real but SECONDARY:
   every ticker with an unmatched terminal action also carries a `delisted`
   row, 12,253 of 12,253, so termination is always detected
```

### Certification philosophy CHANGED by defect D (2026-08-08)

The requirement that historical Sharadar ACTIONS supply broker-grade acquisition
settlement terms is **DROPPED**. The dataset does not contain them, at any action
type, and no re-download or bulk export changes that. Demanding it would keep the
manifest waiting on evidence that cannot exist.

Certification instead proves the SETTLEMENT WATERFALL is honoured and disclosed —
exact terms when genuinely known, real executable prices when available, ONE
deterministic disclosed proxy for known events with absent terms, a DIFFERENT
conservative policy for true unknown disappearances, and every proxy settlement
counted and reported with its dollar contribution. Full contract in
docs/architecture.md "terminal settlement and orphan resolution".

Consequence for step 7: a rehearsal summary must carry
`exact_terminal_settlements`, `market_exit_terminal_settlements`,
`derived_last_mark_settlements`, `orphan_zero_writeoffs` and
`unresolved_terminal_events`. A run reporting none of these on a three-year
window over ~2000 names has not measured what it claims to have measured.

**It then died on memory.** The chain loop finished, and `rehearse_chain` runs
the entire stream a SECOND time in bulk to prove equivalence — with no progress
callback, so a third of the wall time is indistinguishable from a hang. Peak
memory is there (corpus + `out.sessions` + `out.traces` + the bulk `RunResult`
with every session's fills): it pinned at 3.98 / 4.00 GiB thrashing in reclaim
and was killed deliberately. `BT_ENGINE_MEM_LIMIT` raised to 8g.

**The corpus is NOT the problem and a bulk re-download is NOT the fix.**
`bt_actions` holds 664,039 rows across 18 action types, 1998-2026. All three
defects are in the reader, and a re-import would reproduce every one of them on
fresh data — then certify it. Fix the reader first.

### Observability gaps this run exposed (reporting only, none change a result)

```text
provenance is computed in _load_corpus but written only at COMPLETION, so
  split_source / warmup_sessions — the manifest's own hard precondition, meant
  to be checked BEFORE interpreting anything — cannot be read until the run they
  gate has finished
the bulk-replay pass emits no progress at all
/progress reports trade_count: 0 always — _progress_snapshot builds SessionFacts
  without fills, since SessionRehearsal does not carry them — with no field
  saying the figure is unmeasurable rather than measured
the identity of a blocking security is captured NOWHERE: plan_session builds a
  warning naming it, SessionRehearsal drops it, and `sessions` is elided above
  400 anyway. The security here was found by SQL against the corpus, not from
  the run
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
| deployed-image parity | **proven 2026-08-06, now STALE** | all three images emitted golden `a09b12a87d1ecc97`, identical on 7 layers, INSIDE the containers. The C1/C2 wiring re-pinned the golden to `5c1af5731f79c702`, so this must be RE-PROVEN after a forced base rebuild; until then the deployed images disagree with the code |
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

## Suite failures that were provisioning, not code

**RETRACTED (2026-08-08).** This section previously named three "known-failing
suites (pre-existing)" and attributed two of them to the code — "service-contract
probes" and "the `pipeline` TZ probe subprocess fails to start". Re-measured at
`ae2db54`: all three pass. The failures were missing Python packages in the
container that recorded them, and only the `tests/trade_executor` row said so.

| Suite | Recorded as | Actual cause | Re-measured |
|---|---|---|---|
| `tests/contracts` | 4 failures, "service-contract probes" | `httpx` absent | 86 passed |
| `tests/cross_service` | 7 failures, "the `pipeline` TZ probe subprocess fails to start" | `httpx` absent — the probe subprocess died on `import httpx` at `services/scheduler/app/main.py:10`, which the assertion reported as a timezone disagreement | 19 passed, 25 skipped |
| `tests/trade_executor` | 1 collection ERROR, `psycopg2` absent | `psycopg2` **and** `pytest-asyncio` absent | 198 passed, 72 skipped |

**Why this is worth a permanent entry rather than a deletion.** A first full run
during the re-measurement failed exactly three suites too — but a DIFFERENT three
(`tests/llm_gateway`, `tests/pipeline`, `tests/portfolio_builder`, on `ollama` /
`alembic` / `aiosqlite`). Two independently under-provisioned containers each
produced a plausible-looking three-suite failure list, with no overlap. "Three
suites fail" is a property of which packages happen to be absent from the runner,
not of the repository, and it reads identically to a real defect. Before any
suite is recorded as failing, install what it imports and re-run; a failure list
that moves when you install a package is a provisioning report.

The packages the suites import beyond `make test`'s inline list (`-e shared
pytest pandas numpy pydantic pyyaml hypothesis`): `httpx`, `fastapi`,
`sqlalchemy`, `asyncpg`, `psycopg2-binary`, `aiosqlite`, `alembic`, `redis`,
`apscheduler`, `exchange-calendars`, `anthropic`, `ollama`, `pytest-asyncio`.

Separately, three suites cannot share one interpreter with another suite because
every service ships an `app` package: `tests/bt_engine` + `tests/risk_service`,
and `tests/parity` + `tests/shared`
(`test_bt_engine_imports_the_canonical_module`). Both collisions predate this
work and both pass when the suites run in their own process, which is what the
project's runner does.

## Full-suite result (2026-08-08, commit `6dbd777`)

```text
════ 64 suite(s) passed, 0 failed ════   5,223 tests
```

Measured with `scripts/run-tests.sh` on a runner carrying every package the
suites import. The DB-backed `tests/integration/*` files RAN rather than
skipping, which they do not on a bare runner — so this is a strictly stronger
result than the usual green, and the per-file counts below are not comparable to
a run where they skip.

```text
tests/shared        822      tests/wealth_core  550      tests/scheduler   406
tests/bt_engine     397      tests/delta_engine 376      tests/pipeline    356
tests/av_ingestor   227      tests/evaluator    206       tests/api         196
tests/trade_executor 198     tests/bt_data      185      tests/portfolio_builder 172
tests/backtester    170      tests/factor_engine 155     tests/risk_service 138
tests/scripts       110      tests/contracts     86      tests/bt_scheduler 60
tests/parity         45      tests/broker        45      tests/strategy_validator 39
tests/llm_gateway    35      tests/alpaca_sync   24      tests/cross_service 19
tests/alpaca_sim     12      tests/ranker        11      tests/smoke        10
tests/simulation      9      tests/ui             0 (4 skipped)
```

The four lanes that matter for Wealth Core parity, all green AFTER the wiring:
`wealth_core` 550, `parity` 45, `bt_engine` 397 (wind tunnel), `backtester` 170.

