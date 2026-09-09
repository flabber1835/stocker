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
