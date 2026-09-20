# Remaining Stage 1 local review

Base independently fetched 2026-09-20:
`eaae66f9e6626306f8b233fd723d25b278e13351`. Local integration includes #421
`02549411267955c697bacea076fde7e240e1c841`, #422
`a6107d7f599c99a29bfa607a57f0bfccc93279f3`, #423
`1b49f3dcb47229f002cff043b9136947879c8d05`, and #424
`9093cbedb4f5a5703c838a02c9d3587075eae19f`, subsequently integrated with its
CI fixture repair `451993a2ef705daf4b31ad4611642a01a953f067`. Delivery remains PR-only.
The owner subsequently merged #421 as `e4c9b1439962af3353e7f0c0ec3d84aee1f0aeb7`.
That freshly fetched main and #424's `86f174b17020915205429f4f00b75b9fb9a3a434`
are integrated. The latter's 58 real-PostgreSQL cash tests pass; its old CI
synthetic-merge refusal was an advertised-base race, retained separately.
No NAS or real broker contact; no owner merges performed by the agent.

## L02-S1: exact share scaling (design before implementation)

The production close projector first rounds a fractional shadow weight, then
multiplies and floors it. A $3,000 shadow holding ten $100 shares and $2,000 cash
produces nine account shares at the same $3,000 NAV, instead of ten. Opening
sizing similarly scales three Core shares by a rounded one third and floors to
zero account shares instead of one. Six independent boundary cases fail on the
integrated source, with seven adjacent/original controls passing. The direct
Core/sleeve projector also rounds a strictly unaffordable fraction up to one
share. Severity P2; historical economic impact has not been quantified.

Keep exact ratios until the one final whole-lot floor. The shared projector
accepts an optional positive Decimal weight denominator (default one preserves
existing callers). Production passes exact shadow marked-value numerators and
the canonical shadow NAV, rather than prematurely normalized weights. Envelope
validation uses the same exact ratios. Quantities, notionals, residual cash and
decision-close NAV use exact finite-decimal arithmetic. Unpriced reductions and
opening-intent account scaling apply the identical rational floor rule.

The opening scale's retained display uses a fixed 28-digit Decimal context; it
does not determine shares. Rational inputs determine quantities before any
display rounding. Canonical Wealth Core behavior, controller selection, pending
intent and the existing price domains remain unchanged. The execution numeric
helper joins the existing data-semantics source identity; changed code requires
the ordinary reviewed source continuation. Plan fingerprints already bind exact
cash, NAV, resulting shares and strategy identity. No golden repin or historical
certification follows from this execution repair.

The same exact-quantity contract applies to working-order remainders and the
`desired - held - committed` reconciliation equation. Preserve finite decimal
operands through subtraction, signed aggregation and absolute value. This is
conformance to the documented exact arithmetic contract, not a new rounding or
dust policy. Action projection must likewise check exact rational increment
divisibility before rendering a Decimal. Cancellation ratios remain rational
until that check; existing evidenced rational reconstruction and canonical
pending-entry cancellation rules remain authoritative.

## Local resource qualification scope

The 8,408-row maximum and 2,474,682-row 300-session window are retained PIT
inventory facts. A bounded diagnostic may exercise that cardinality with the
existing deterministic source fixture at unchanged service caps. It must be
labeled synthetic and cannot establish admission/completeness of the real PIT
export. Inspect the available export/metadata for an admissible real window;
retain exact missing fields or terms if blocked. Record memory, OOM counters,
elapsed time and source/image/input identity. An unspecified latency budget
remains an external acceptance decision, not a fabricated pass threshold.

## Additional quantity findings and local acceptance

L02-S2 (P2): Decimal context also rounded command/order unfilled remainders,
signed quantities and committed-order sums. That could erase a residual or
classify an excess as an exactly reconciled position. Exact subtraction,
aggregation, sign and magnitude preserve the existing lot/dust classification.
The high-precision cases establish the contract boundary; no historical broker
incident is inferred from them.

L05-S1 (P2): action projection could accept a fractional product rounded to a
whole share. Conversely, a surviving pending-entry ratio of 3/9 applied to three
account shares refused the exact one-share target. The independent example has
pending Core entries of three and six shares before a 1:2 split: the first
cancels, the second becomes three, and the account's surviving target is one.
Four adjoining quantity tests failed before repair, with 35 controls passing.

The repair has 302 directly relevant regression passes. A 12-mutant campaign
detects broken close/open floors, denominator validation, command/broker
remainders, sign/magnitude and action ratios; an additional committed-sum
mutant is also detected. These counts overlap controls and do not measure
review coverage. A first denominator mutation survived because the aggregate
envelope independently rejected negative denominators; the corrected falsifier
removes the guard and detects the zero-denominator case. Keep both logs.

No canonical engine, controller, stop rule, terminal-return schema, economic
golden or provider capability was changed. The new numeric helper dependency
is bound to data-semantics identity, with an actual source-change test. Historical
economic impact remains to be measured in Stage 2; the demonstrated ordinary
case changes one $100 share of intended exposure, not alpha selection.

## L06 populated restore acceptance

The new real-PostgreSQL test initializes and advances the production rolling
runtime to a held-position book, streams a physical `pg_basebackup`, runs
`pg_verifybackup`, and boots an independent cluster. The actual read-only restore
validator accepts it; a fresh writable connection resumes and advances the next
flat-price, action-free session, preserving cash and every slot's security/share
pair. A second fresh connection reproduces the committed state hash, while the
original cluster remains on its prior session. No broker is involved.

The first fixture correctly refused missing predecessor authority because it
used candidate-only advancement. It now earns the authority chain through
`rolling_runtime.advance`; no refusal guard was changed. The next attempt exposed
a test assumption that serialized episodes were a list; they are a keyed map.
Both unsuccessful logs are retained. Four existing missing-origin/checkpoint/
snapshot and genuinely empty controls remain. Combined restore, notification,
supervision, fence and retention validation: **168 passed, one warning**.

This complements the retained PG16 worker/WAL-target tests, whose production
restore-worker source is unchanged. The new page-copy test uses local PG17.11;
it does not replace deployed PG16 populated target-LSN/WAL qualification.
The restore validator establishes structural restart closure, not broker cash
finality or predecessor completeness. Before cash is used, the production cash
ingestor separately checks cursor/ledger agreement; the retained deletion tests
prove partial cursor/ledger restores refuse. A physical backup contains both.

## L09 write-resource repair decision (before implementation)

The separately capped 8,408-series storage probe reproduces initialization's
backend OOM in the SQL statement that concatenates every pair at one tree depth.
The balanced tree bounds operand size but the single INSERT/SELECT statement
does not bound all intermediate executor allocations across its pairs.

First keep the same temporary table, tree and final atomic JSONB row, but execute
one pair per SQL statement. Releasing each statement's executor memory must not
depend on the number of other pairs. No durable schema or transaction boundary
changes; no commit, partial observation, skipped series or changed commitment.
Check exact stored JSONB equality, odd final pairs, rollback/conflicts and
sub-float precision corruption, then repeat the isolated 8,408-series probe at
the same service caps. Treat this as a candidate repair until that measurement
passes; if a single pair or final row still exceeds the cap, retain that failure
and revisit storage rather than raising a limit.

The one-pair-per-statement candidate also OOM-killed the backend in 31.5 seconds
on the independent storage probe. Retain that failed candidate's immutable source
and logs; it does not establish the claimed bound. A single expanded JSONB pair
is itself too large at this cardinality.

Revised storage decision: retain one atomic append-only cursor row, but represent
large `feed.series` values in a versioned storage envelope of independently
compressed canonical-JSON groups. The logical record, genesis/state/record
hashes, public store API and ownership/commit boundaries remain unchanged.
Each group binds its uncompressed length, SHA-256 and series count; the envelope
binds the field and total count. Refuse unknown shapes, nonempty inline series,
missing/duplicated groups or series, invalid compression/checksum/length/count,
and oversized decompression (16 MiB per group). The encoder refuses a group over
that bound; normal 128-series groups are substantially smaller. Decode each
group with the existing request-local scalar pool, including exact Decimal
comparison mode. Reject the reserved envelope key in caller-owned logical input.

Legacy inline rows remain readable without migration. New large rows use the
envelope; small rows keep their existing representation. All genesis, ordinary
record, streamed status and equality/retry readers must reconstruct and verify
the complete logical value. No extra table, orphan chunk namespace, skipped
history or cross-request verdict cache is introduced. PostgreSQL parses only
bounded headers and opaque compressed strings, avoiding expansion of millions
of numeric nodes in a single SQL value construction. Verify canonical equality
against independent standard-library decoding, legacy/new restart, final-series
tamper and transaction rollback before repeating full resource acceptance.
Rollback qualification must pair a restored database with a compatible decoder
and reviewed source identity: an older image cannot interpret newly compressed
rows. This is an explicit storage-version boundary, not permission to bypass
source continuation or rewrite immutable observations.

Candidate acceptance: the independent storage-only 8,408-series probe passes
in 42.17 seconds, with PostgreSQL peak 323,059,712 bytes and no OOM events.
The 112-test storage/status/static-ownership/physical-restore selection passes,
including 25-series inline and 129-series compressed populated restores.
Nineteen positive controls pass and all eight deliberately broken storage
variants are detected. This does not yet close L09: the complete separately
capped publication/initialization/status/HTTP/next-session campaign is running.

The full campaign subsequently passes initialization (659.77 s, runtime peak
3,106,545,664 bytes, zero OOM), but both 512 MiB status and HTTP processes OOM.
Retain those failures. A separately labeled 1 GiB, read-only allocation diagnostic
shows genesis decoding at 351,892 KiB, canonical construction at 423,624 KiB,
and hashing at 531,144 KiB before adding the full panel's larger imports.
Canonical feed-array copies, not missing provider authority, are the next local
defect. The larger diagnostic cap is not acceptance.

Read-allocation decision before implementation: keep public state serialization
and ordinary construction detached. Add a private canonical view which borrows
already bounded feed arrays only for synchronous hashing or the existing
single-use, repeatable-read, read-only status verifier. All fields still undergo
the same canonical validation, trimming and commitment checks; trimming creates
new arrays when needed. No verdict/hash cache, abbreviated record, ignored tail,
or new public mutable alias is allowed. Status owns its freshly decoded database
value and releases genesis before reading the current record. Ordinary writer,
kernel and exported-dictionary paths retain their copying contract. Compare
canonical bytes with an independent JSON encoder, test output ownership and
tail tampering, and falsify the allocation bound by restoring the copies.

The allocation/state/status/restore/ownership selection passes 141 tests.
Five positive controls pass and four read/CI mutants are detected: restoring
the hash's full copy breaches the 4 MiB allocation budget at 11,444,118 bytes;
exporting borrowed arrays breaks public ownership; reversed working-order and
cash-residual signs fail the existing economic oracles. The latter two CI
mutants needed updated textual anchors after exact arithmetic was introduced
(run 35531327152, job 106133309207 reports zero matches, not surviving bugs).
Two public-status cases additionally reject a changed last compressed series
even after its physical length/checksum are coherently recomputed.
The final capped campaign uses a fresh immutable source copy and fresh database;
no old strategy/source identity is silently relabeled for the new implementation.

The cached production PostgreSQL 16.14 image also passes 49 targeted storage
cases and the 8,408-series storage diagnostic in 50.66 seconds. Its database
peak is 300,748,800 bytes with zero OOM/reclaim-limit events. This complements
PG17 structural and full-pipeline measurements; it does not qualify the NAS.

The intermediate campaign also exposed an audit-reader defect after successful
production advancement: its accounting probe queried the former inline feed
price location. The replacement independent oracle reads the published snapshot's
open/close prices, then calculates twenty whole-share positions' notional, 10 bp
fees, cash and NAV. Both populated physical restores (25 inline / 129 compressed)
pass; a deliberate $1 cash invention fails, and removing that cash guard is
detected. The old campaign remains failed. During the final campaign, only the
host coordinator was resumed to use this corrected audit reader; the retained
database, service caps and all 406 production file bytes remain identical.

CI run 35532202153/job 106135398245 passed 5,000 tests but failed the allocation
test: process-wide tracing peaked at 19,706,514 bytes. The narrow local run had
passed. Allocation measurement now runs in a fresh interpreter so unrelated
suite threads/tracing cannot contribute. The same 4 MiB bound, independent hash
oracle and tail-mutation assertions remain; restoring the production array copy
must still fail. This is test isolation, not permission to raise the panel cap.

## Current finding-to-caller cross-check

Paths below are relative to `sentinel/`. The finding index retains all original
issue/comment identities, including reused A4/A5/A6 labels. This supplements its
existing requirement map; it does not replace historical evidence.

| Findings | Production caller and durable/restart boundary | Acceptance and disposition |
| --- | --- | --- |
| F2/F9/F10/F11/C2 | `core/decision` -> `execution/projection` and `opening_sizing`; canonical state/plan fingerprints, `core/session`; inclusive stop in canonical v5 and split-before-terminal consideration in `controller/terminal_returns` | New independent share/cash oracles plus existing economic-boundary and terminal tests. Canonical state stays immutable; rounded ratios are diagnostics only. Cash identity remains the #421/#424 contract. L02 local code repaired; historical delta B1 remains. |
| F1/F3; A9/A10/A15 | `rolling_daily` -> `core/rolling_continuity.prepare` -> dated snapshot references -> authenticated daily checkpoint | Raw values and historical identity prefixes stay exact; common rational precision intervals admit rounded rebases. Fresh inactive returnees reform features; held/cooldown/sensor anchors cannot be discarded. Existing rebase/rename/returning-identity controls and falsifiers remain applicable. |
| F15/F18; F1/F3 action seams | `feed/action_history` -> `execution/feed_actions` -> `target_reprojection` -> immutable projected-target cursor -> executor | Required rows are enumerated from publications, not surviving history. Missing coverage/records refuse before fallback; action evidence binds target units. New exact action tests and mutants cover the remaining numeric seam. |
| F16; A14/A16 | `paper_performance.scan_entitlements` -> durable account-owned fills/commands -> scoped `SnapshotCashInputs` -> expected dividend evidence; `core/spinoffs` on held parents | Independent affected-owner cash oracles (equity $120, BIL $60), repeated fresh SQL connections, missing/ambiguous owner refusals. Unheld names require no irrelevant price. Held spinoffs explicitly refuse even if terms exist; missing opening entitlement refuses. No invented child or cash credit. E4 remains. |
| F14/F15; A21 restore | `restore_validation` -> publication/action coverage -> origin/daily authenticated checkpoint -> current retained input/observation -> `rolling_runtime._closure` | New populated physical restore and next-session control; corrupt HMAC/content/missing-origin tests; retained action omission controls. Production page/WAL worker separately verifies target pause/promotion. Local structural evidence only; N1 remains. |
| F12/F13; A4 alerts/A6 notifications/A18 | `alert_service._observe_health` -> locked occurrence cursor + outbox insertion -> `automation/outbox.dispatch_once` -> `web_push.deliver_fenced` | Claim commits before transport. Renew/result updates require holder, attempt and unexpired lease. Recipient resolution and recording share policy-row lock order with enrollment. Failed old attempts cannot acknowledge successors; temporary peer failures keep retries alive, permanent peers stay visible. Real PostgreSQL death/rotation/recurrence tests pass. HTTP acceptance is not exactly-once physical device delivery. |
| A1/A17/A19/A24/A25 | alert/automation/shadow supervisors -> bounded dependency subprocesses/process groups; `panel/push_enrollment` thread + SQL budgets; deployment bounded runner | New invocation identity resets a deadline once; heartbeat cannot extend callback time. Parent enforces kill/reap despite SQL/log stalls. Durable shadow latch and independent critical-health evidence survive restart. Existing silent dependency, pipe, same-phase, finite timing and enrollment responsiveness tests remain. Uninterruptible host I/O and devices are N1. |
| F4; A2/A3/A4 preparation/A5 latch/A7/A11/A13/A20/A21/A22 | operational preparation request/lease -> rolling runtime/recovery -> typed dependency refusal/retry -> maintenance/retention drain; deployed DUAL shadow preparation | Dependency loss/timeouts stay retryable; terminal integrity stays persistently fenced. Expired jobs allocate one successor. Authority rechecks preserve that distinction. Retention commits before a separately bounded diagnostic. Existing composed preparation/recovery and source-bound admission tests apply. |
| A5 WAL/A6 backups/A23/A26/A27 | host scheduler -> `scripts/sentinel_maintenance_process.py` -> owned coordinator/worker -> verified successor -> restore receipt -> retention journal/WAL floor; installer durable fence before migration | Worker and parent locks, bounded process groups and exact selected-base/cluster/image/LSN receipt identity gate deletion. Journal resumes after interruption; mixed timelines are preserved. Independent retention generation counts, worker-death and crash tests retained. Current recurring-retention/fence tests pass. Scheduler installation/filesystem guarantees remain N1. |
| F5/F7/F17/C3; A8 | Original immutable plan/command -> executor send journal -> paper recovery after later shadow -> takeover epoch gate | #423's compound SIGKILL/late-fill and nonempty predecessor controls; current integration revalidation includes actual process death. E3 stays unresolved. |
| F6/F8/F19/C1 | Account-bound adapter -> cash/fill identity validation -> one journal transaction -> cash authority/performance | #421 exact arithmetic and #424 zero-identity witnesses compose locally. #424's stale pagination mock is replaced by real PostgreSQL. Corrections/busts or incomplete authority refuse; empty responses do not grant finality. E1/E2 stay unresolved. |
| A12 | Full status HTTP/readers and runtime initialization/daily advancement with PostgreSQL separately capped | L09 reproduced a PostgreSQL OOM at 8,408 synthetic securities during `observation_storage.insert` pairwise JSONB assembly. One backend was killed; initialization refused. This is a P2 local implementation gap, not an external-data disposition. Repair and repeated resource acceptance remain required. |

Retained source bindings are compared by `audit/economic_399/local_closeout/prior_sources.py`.
Unchanged source supports reusing the named component evidence; changed dependencies
are not described as byte-identical or as a replay of the earlier campaign.

## Input boundary and NAS handoff

Both retained PIT packages are now present locally: schema 1 dataset `7ceaaf4f...`
and champion schema 2 dataset `5bdc6b39...`. Therefore the old statement that only
schema 1 is available is superseded. Their manifests are retained separately in
`pit-input-inventory.json`; neither identity is silently substituted for the other.
Both observation tables carry raw equity open/close, signal close, split/dividend
values and dated metadata. Their benchmark table contains a return factor and
level; their cash table contains gap/intraday/close factors and source, **not raw
BIL open/close and the full SFP price domains required by rolling publication**.
The archives also do not contain the production publication/coverage receipts.
The known provisional engine run does not establish that missing contract: it
stopped after 34 measured sessions on unresolved held terminal economics.

A separate local Git search also found original Sharadar archives at
`research/backtester` commit `e088bfd26c695309e259cfc44ab1e8982d6f858d`.
The four SFP parts reconstruct the exact Phase-1 source hash
`8d2ebf7485977d9c40ec379eb33bd9d36d39d69db13602e5c51862d03172400c`.
They contain `open`, `close`, `closeadj`, `closeunadj`, volume and update dates;
SPY spans 1997-12-31 through 2026-08-03 and BIL starts 2007-05-30.
Raw SEP, full ACTIONS fields and TICKERS are present too. All 21,939 SEP TICKERS
identities pass the current structural and metadata checks. Reproduce with
`python audit/economic_399/local_closeout/input_inventory.py --scratch ../stage-one-raw-source`.
The retained `raw-input-inventory.json` distinguishes these raw archives from
both derived PIT packages. Therefore **raw SFP price availability is not the
remaining blocker**. These files do not establish the export refresh bracket,
complete API/CSV reference agreement or authenticated production publication
and coverage receipts required by `rolling_source.SharadarSource` and
`operational_source.OperationalCapture`. Git provenance alone cannot substitute
for those authority claims. No provider request or receipt fabrication occurred.

To qualify a real 300-session production window, supply the corresponding
authenticated SEP, dated TICKERS/alias and ACTIONS history, raw/adjusted SFP
SPY/BIL rows including the necessary predecessor, source manifests and authoritative
terminal/spinoff terms for affected holdings/sensors. Authenticate and admit the
window through the ordinary rolling publisher; record explicit rejection if any
required field/term is unavailable. Do not invert return factors to fabricate
absolute prices, completeness receipts or a tradeable pre-inception BIL sleeve.
This does not require running the deferred 20-year backtest now.

Before NAS qualification: owner merge with required CI, reviewed immutable image
and dependency digests, ordinary source-continuation approval, exact schema and
accepted provider/policy evidence E1-E4, independently fenced old writer, private
backup media, authoritative input manifest and accepted latency budget. Use the
existing [resource handoff](../audit/economic_399/status_cost/README.md#nas-handoff-not-executed)
for full HTTP/cgroup captures and [deployment handoff](economic-code-closure.md#concrete-nas-handoff--not-executed)
for scheduler, locking and WAL drills. All are **unexecuted on NAS**.

On a disposable local or NAS qualification restore, run:

```sh
python -m sentinel.restore_validation
python -m pytest tests/sentinel/test_rolling_restore_integrity.py -q
python -m pytest tests/sentinel/test_nav_quantity_precision.py tests/sentinel/test_issue209_target_reprojection.py -q
python audit/economic_399/local_closeout/run_local.py
```

The pytest commands are isolated fixture acceptance, not a substitute for the
deployed populated database. The first command must use that isolated restored
database and exact authorized image; retain its JSON, read-only proof and full
logs. Capture the production worker's base identity, manifest verification,
target LSN pause/promotion and post-base marker; then run the supported next-session
shadow path with broker mutation disabled. Pass requires exact preserved prior
intent/cash/holdings, authentic publication/action closure, reproducible next
state, no duplicate submission, and deliberate missing/corrupt dependency refusal.
Any authority gap, unexplained economic delta, OOM or failed required gate keeps
certification blocked. No NAS or real broker activity is authorized by this work.
