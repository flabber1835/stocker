# Daily Sharadar production replay

Implements the first ingest milestone of [issue #332](https://github.com/flabber1835/stocker/issues/332).
The synthetic-world generator remains tracked in [PR #331](https://github.com/flabber1835/stocker/pull/331).

## Contract and scope

Advance an explicit provider clock, run the actual production daily ingest,
inspect PostgreSQL, and compare its observable corpus and readiness against an
independent expected state. The provider implements paginated Tables JSON and
Exporter ZIP/CSV responses through an in-process HTTP transport. Production
pagination, schema validation, completeness checks, reconciliation, identity,
normalization, publication and recovery execute normally.

The fixture is a small, hand-auditable fictional market with more than 127
sessions. Bootstrap uses the existing non-certifying injected seed entry point;
its HTTP parsing and canonical storage still run. Production seed certification
has a calibrated 4,000-security floor and needs a separately validated world.
Daily replay uses the default production source and its full export checks.
An ordinary recent BBB dividend supplies the global ACTIONS activity required
by production readiness; its cash value is independently checked in every run.

An isolated worker supplies a clearly synthetic producer identity and receipt
key. This tests data behavior; it conveys no deployment or execution authority.
The fixture installs the real feed schema with `store.migrate_schema` and uses
a newly created, uniquely named test database. It never imports the compatibility
fixtures in `tests/sentinel/conftest.py`.

## Production call map

| Operation | Current owner and relevant dependencies |
|---|---|
| Daily orchestration | `sentinel.feed.ingest.daily` |
| Orphan/retry recovery | `ingest_authority_impl._recover_before_run`, `recovery` |
| Identity preflight | `identity_refresh.stable_current_tickers`, candidate history check and resolver |
| Daily writes | `ingest_impl._daily_locked`: TICKERS, ACTIONS, SFP, SEP |
| Stable observations | `source_authority.StableSharadarFetch`, canonical row/envelope validation |
| Transport | `sharadar.fetch_table`, strict Tables decoder and pagination |
| Whole-file authority | `snapshot_source`, `snapshot_export` |
| Historical audit | `sep_reconciliation.reconcile_next`; production reconciles ACTIONS/CDC first |
| Old corrections | `maintenance.reconcile_sep_mutations`, `renormalize` |
| Action repairs | `maintenance_impl.reconcile_actions_if_due` |
| Recent-window proof | `recent_reconciliation.reconcile_recent` |
| Publication | `publication.publish`, validation receipts, generation visibility |
| Readiness | `readiness.check_readiness` with explicit observation time |

Injection at `ingest.daily(fetch=custom)` takes different branches: it omits
production identity preflight, export-backed recent proof and equal-date CDC
reobservation. Daily tests must therefore keep the default source callable.
Only HTTP transport, source-clock reads, synthetic producer identity and named
fault boundaries are replaced in the isolated research process. No validator,
normalizer, publication verdict or readiness result is replaced.

## Independent oracle and evidence

Scenario expectations describe security IDs, dates, signal/raw/open values,
volume, split ratios and dividends independently of production helpers. Provider
observations and expected states are separate scenario inputs. The checker
compares complete canonical rows, action source contents, reference series,
identity intervals and declared readiness outcomes. A missing key, extra key,
changed field or unexpected readiness result fails the replay.

The current production contract retains detection-level corpus versions; full
historical bar reconstruction is deferred (`docs/sentinel-execution-contract.md`
section 8). The harness captures immutable per-step input snapshots and their
digests. It preserves earlier observations across later corrections. These are
research evidence, not a claim that production supports historical bar-version
queries. Strategy attachment must preserve the same decision-time snapshots.

Recovery scenarios declare a retry deadline before execution. The clock begins
at the first scheduled attempt after correct authoritative input is available.
Every intermediate expected blocked state is checked. Exceeding the attempt
budget is a failure even if a later retry might succeed. An unrecoverable case
must retain its explicitly expected blocker over the observation horizon.
Interrupted daily writes and publication attempts must retain the prior
publication pointer. The expected intermediate corpus explicitly accounts for
the current in-place bar/reference writes becoming hidden while unpublished.
Recovery must restore the complete expected reader view on the first eligible
retry. The older captured research snapshot remains byte-stable throughout.

## Delivery stages

1. Daily production replay: normal arrivals, same-day CDC, old corrections,
   late actions, malformed/partial delivery, retries, and publication faults.
2. Extend the scenario map to full seed/reseed authority, all identity/retirement
   cases, process death and concurrent workers; validate the synthetic generator.
3. Attach an explicitly authorized frozen strategy to the validated daily
   published-state runner. Report corpus correctness and portfolio outcomes.

This first milestone makes no strategy-performance or complete-system
certification claim. Production economics, certified datasets and existing
backtest evidence remain outside its write scope.

## Running

Run `python -m pytest research/sharadar_replay/tests -q` with repository root and
`shared/` on `PYTHONPATH`. Integration cases require `SHARADAR_REPLAY_TEST_DSN`
pointing to a disposable PostgreSQL server on loopback. Tests create and remove
only databases with their own random `sharadar_replay_` names. Missing PostgreSQL
is an error for the integration tier. `-m 'not postgres'` runs the provider and
oracle tier locally.

The dedicated GitHub Actions workflow runs both tiers, records progress and
retains scenario definitions, HTTP transcripts, per-step corpus snapshots,
readiness details, comparison failures and exact code/runtime identity.

## Recovery defect discovered by the replay

[Run 34414566003](https://github.com/flabber1835/stocker/actions/runs/34414566003)
reproduced a daily recovery deadlock on the original production implementation.
A failed SEP traversal had already committed the 41-session SPY/BIL window.
The following day's retry requested its newly shifted 41-session window. One
older SPY row and one older BIL row retained the failed writer identity, so the
publication gate correctly refused the retry with `CorpusIncoherent`.

The recovery contract now requires the reference request to begin at the earlier
of its ordinary required start and the earliest reference row owned by a durably
failed unpublished run. Both SPY and BIL contribute to that boundary. The
complete source response rewrites the affected keys before publication. A
failed reference row beyond the requested through-date remains an explicit
refusal. Published owners and ordinary healthy data do not widen the request.
The publication guard and reference prices retain their existing semantics.

`incomplete_sep` exercises the original failure and first-retry convergence.
An executable falsifier restores the old moving-window behavior and must fail
with the original stranded-reference ownership error.

## Adversarial expansion contract

The additional suite crosses feed tables with malformed envelopes, interrupted
pagination, duplicated rows and provider errors. Each transport fault declares
its expected rejection before execution. Corrupted Exporter archives and stale
identity snapshots are separate authority cases. Repeated failures span several
sessions and require recovery on the first subsequent correct observation.

Seeded scenarios vary response ordering, pagination size, historical correction
date/value and repeated delivery. The seed is retained in the scenario contract.
These schedules must reproduce exactly and preserve the independently declared
economic corpus. Corporate-action cases exercise disagreement between action
and price evidence, followed by correct authoritative observations. Persistent
faults retain a specified blocked outcome across their observation horizon.

Faults operate at the HTTP boundary. A page-offset threshold permits a valid
prefix before the failure. No production exception is accepted generically;
each case names its expected diagnostic. An unexpected exception or changed
corpus is a failing case requiring investigation. Frozen expected snapshots
remain independent of production output.

CI distributes the collected test IDs deterministically over four independent
PostgreSQL jobs. Each shard records its collected IDs and selection. Their union
must cover the full suite exactly once. The case catalogue and seeded schedules
are fixed for a run; an individual failure can be replayed with pytest `-k`.
The PR workflow owns routine execution; manual dispatch supports focused runs.
Rate-limit/service-unavailable cases honor a one-hour Retry-After deferral and
schedule their next attempt on the following day.

### Repeated pre-price failure recovery

The expanded replay found that two failures after TICKERS but before reference
writes leave two failed daily runs owning only dated universe snapshots. The
single-candidate dispatcher rejects that state even though the existing
publication transaction can retire every older failed universe snapshot after
a complete, validated TICKERS replacement succeeds.

Allow this precise metadata-only cohort through daily dispatch when every live
candidate is a failed daily run and full coherence reports universe rows as its
only pending rows. The dispatcher uses a representative only to select the daily
recovery path. The existing publisher still requires all prior owners cleared.
Mixed operation kinds or any pending bars, references, repairs, actions or
anomalies retain the existing refusal. An executable falsifier restores the old
multi-candidate refusal and must reproduce the repeated-outage failure.

### Non-finite price input

The corrupted-price case reproduced acceptance of positive infinity as a raw
close/open by the production normalizer. Finite-price arithmetic is required:
non-finite source numbers must follow the existing missing-domain path, where
coverage and readiness determine refusal. Extend the numeric parser's NaN
rejection to both infinities; ordinary finite inputs retain their semantics.
A normalizer falsifier restores the old parser and proves that the raw-price
coverage assertion then accepts the corrupt observation.

A final evidence gate verifies that shard manifests form an exact partition of
the full collection, JUnit results contain only passes, every selected scenario
has a passing report with matching expected/actual digests, and all reports name
the requested code commit. Missing artifacts or duplicate/omitted test IDs fail
this gate. This makes suite completeness an executable CI requirement.

### Daily observation ceiling and publication phases

A future SEP `lastupdated` value was rejected only by post-publication CDC.
Daily date-window acquisition must apply the same frozen upper observation
ceiling before any daily generation publishes. Extend the stable source wrapper
with an optional SEP update envelope and supply it on production daily reads.
Missing update dates retain the existing date-read contract; bounded CDC still
requires them and blocks readiness when they are absent.

A daily command contains multiple publication-bound operations. Scenarios that
fail during later maintenance explicitly declare that a valid daily generation
has already published, assert its exact corpus, and require the maintenance
blocker. Pre-publication failures continue to require the old pointer. A missing
reference series may similarly publish an incomplete reader view whose named
reference readiness check must fail; a complete next-day source must restore it.

### Revisit unresolved split evidence after price corrections

A new split can restate older adjusted prices and create a temporary seam
anomaly at the daily overlap boundary. CDC repairs those historical prices, but
its price-only generation cannot supply the complete ACTIONS negative-space
authority needed to resolve the seam. ACTIONS reconciliation previously skipped
replay whenever its action rows were unchanged, leaving correct prices blocked.

Unresolved split dispositions inside retained history now contribute their dates
to the complete ACTIONS reconciliation replay. They override the ordinary
same-day cadence shortcut. Each attempt obtains fresh complete action authority
and replays the bounded predecessor/event/following windows before publishing.
Price/source disagreements continue to block readiness until that independent
proof resolves them. Correctly corroborated and already-resolved events do not
trigger this additional replay. A falsifier disables unresolved-date discovery
and must reproduce the valid-current-split readiness failure.

## Current adversarial inventory

The suite contains 118 independently checked PostgreSQL scenarios and 229 tests
in total, including four end-to-end recovery falsifiers.

| Area | Variations |
|---|---|
| Transport | All four feeds; malformed JSON/schema/row widths/cursors, provider errors, loops, rate limits and service deferrals |
| Partial delivery | Failure after valid prefixes, missing tickers/reference series, corrupted ZIP and stale export authority |
| Duplicate data | Identical and conflicting SEP/SFP keys |
| Prices | Missing, zero, negative, non-finite and nonnumeric raw closes; invalid keys and source clocks |
| Corrections | 16 seeded schedules with old-date changes, same-day revisions, shuffled pages and varying page sizes |
| Identity | Missing keys, impossible/reversed listing dates, invalid delisted state and overlapping ticker ownership |
| Actions | Invalid dividend numbers; missing, conflicting, zero, negative and unsubstantiated split records |
| Split economics | Late restatements; 1-for-4, 1-for-2, 2-for-1, 4-for-1 and 10-for-1 splits at overlap and current-session boundaries |
| Recovery | Consecutive outages, first-correct-attempt recovery, repeated same-day input, persistent incomplete identity and publication interruption |
| Test sensitivity | Restored production defects, corrupted expected-state comparisons, incomplete/forged CI evidence and inactive fault definitions |

This is a deterministic adversarial regression suite with seeded variations.
Process death during database commits, concurrent workers, full-scale certified
seed/reseed, broader lifecycle histories and a strategy consuming each daily
snapshot remain the next coverage stages.
