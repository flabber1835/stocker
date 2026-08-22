# Sentinel NAS financial GO validation

This document defines the final, source-backed deployment decision for a NAS
that has local Sharadar and Alpaca PAPER credentials. Credentials remain on the
NAS. They are never committed, copied into an evidence bundle, or pasted into a
GitHub issue or pull request.

The validator has three independent outcomes. They must never be collapsed into
one generic `GO`:

```text
SHADOW_GO             canonical strategy observation may run without broker writes
DUAL_RUN_GO           SHADOW_GO plus reconciled, non-authoritative PAPER transport
PAPER_EXECUTION_GO    Alpaca PAPER order execution may run
```

`SHADOW_GO` is sufficient for observing the strategy through year end. It is
not permission to submit, replace, or cancel an Alpaca order. Its return series
comes from the canonical Wealth Core state machine, Sharadar-published sessions,
the next published session's open for pending executions, and the same source
cash/action economics used by the strategy. Because it never uses an Alpaca
paper holding as its economic book, Alpaca's paper-only omissions cannot silently
become strategy profit or loss.

`PAPER_EXECUTION_GO` is stronger. It requires every paper execution cycle to
have the affirmative pre-open share-unit authority, official-close account NAV,
complete fixed account-fill interval, and final close-cash activity evidence
defined in `sentinel-execution-contract.md`. Sharadar and Alpaca can provide
positive corporate-action observations, but their public contracts do not
provide a complete per-security pre-open no-event attestation. Source silence
therefore never produces multiplier `1`, and the current two-source
configuration remains `PAPER_EXECUTION_NO_GO` for a nonempty book.

`DUAL_RUN_GO` is the deployable year-end observation mode. Its broker side is
explicitly `INFORMATIONAL_PAPER_MIRROR`, not certified paper execution. The
certified broker-free ledger remains the sole performance authority, while the same
decision plan is sent to Alpaca PAPER so orders, fills, positions, and
informational P/L are visible in the external Snowball iOS app connected to
Alpaca. Snowball is not Sentinel's status UI. It requires `SHADOW_GO` plus a read-only proof that the
configured PAPER account is active, unblocked, unlevered, and cash-only at
enrollment. Before activation and immediately before every broker submission,
the PAPER plan must match the certified shadow decision session, canonical
state hash, data version, following XNYS session, and Core/BIL allocation.
Existing command reconciliation then compares expected orders/positions with
the complete broker observation. A material mismatch latches the activation
generation `BLOCKED`, emits a critical alert, and prevents later strategy
orders until an explicit operator review/reactivation; it does not liquidate
the existing PAPER book. Normal orders awaiting fills remain `RECONCILING`.
Because Alpaca cannot prove the complete pre-open no-event set, the mirror
durably stamps each active raw close-unit plan `PREOPEN_UNPROVEN/PENDING` before
transport and validates its actual unit mapping from source-final Sharadar after
the effective-session close. A post-close unit mismatch blocks future PAPER
mutations but never rewrites or invalidates an otherwise valid shadow result.

## One-command NAS workflow

After a reviewed pull request is merged, the operator runs on the NAS:

```bash
git pull --ff-only
bash scripts/sentinel-go-validate.sh
```

The validator never mutates Alpaca. It has one explicit database preparation
step before the read-only evidence boundary:

- it refreshes `origin/main` with `git fetch --prune origin main` before
  comparing the clean local `main` commit, so a stale remote-tracking ref
  cannot certify an old checkout;
- the exact candidate runtime migrates the existing schema and runs one bounded
  Sharadar daily ingest, including the readiness-required BIL tail, only after
  the fixed 23:45 New York source not-before and while the following XNYS open
  is still future; a run outside that prospective window fails closed and can
  be rerun, while an already-current exact publication is accepted without
  requiring an artificial new publication version;
- Sharadar and Alpaca network calls are GET-only;
- no order, cancellation, replacement, account reset, or cash mutation is
  attempted;
- after preparation, PostgreSQL parity/readiness probes run in read-only
  transactions and the validation boundary records zero database writes;
- a separate financial database-health gate proves the exact behavioral/feed
  migrations, current publication and XNYS axes, unique economic keys, writer-
  excluding publication pin, required indexes and live query plans, and measured
  NAS timing margin before the following open;
- six network-disabled test groups run from the exact candidate lenses—Sentinel,
  Wealth Core, the validator/deployer gate, backtester, bt-data, and bt-engine—
  with skips and expected failures refused. The prospective Wealth Core group
  explicitly deselects exactly three named non-forward historical golden-pin
  tests whose documented re-pin requires unavailable historical TICKERS
  evidence; their exact node ids are included in `test-summary.json`, and the
  deployer refuses a missing, changed, or enlarged exclusion list;
- the command emits a sanitized evidence ZIP under `artifacts/` and prints its
  SHA-256.

The operator uploads only that ZIP for review. A reviewed result is bound to the
candidate Git commit, exact image/runtime identities, the held publication
fingerprint and visible frontier, and the complete shadow model configuration.
A later commit, expired result, changed account binding, changed publication or
frontier, changed image, changed observation id, or changed starting cash
invalidates it before deployment changes a service.

## Evidence bundle contract

Only these members are allowed:

```text
validation.json
test-summary.json
manifest.json
README.txt
SHA256SUMS
secret-scan.json
```

`validation.json` uses schema `sentinel.nas-go-validation/1`. It contains:

```text
created_at / valid_until
git commit and clean-tree verdict
candidate image and runtime digests
explicit prevalidation schema/Sharadar preparation result
sanitized financial database checks, counts, timings, thresholds, and margin
bound-subject digests (never raw account or host identifiers)
financial-source gate verdicts
broker_mutation_attempts
production_db_writes
shadow_verdict
dual_run_verdict
paper_execution_verdict
machine failures
review status and reviewed bundle digest
```

The `shadow_configuration` subject is the exact SHA-256 of canonical JSON over
the observation id, normalized explicit starting cash, execution model
`PROSPECTIVE_CONCORDANCE_SCALAR_CORE_BIL_V3`, cutoff policy
`STRICT_BEFORE_OFFICIAL_NEXT_XNYS_OPEN_V1`, fixed source-finality policy
`SHARADAR_SEP_SFP_SECOND_UPDATE_PLUS_15M_2345_AMERICA_NEW_YORK_V1`, and
validated source identity. The source-finality policy waits until 23:45 New
York time on the decision session—15 minutes after the documented second 23:30
ET daily update for both [Sharadar SEP](https://data.nasdaq.com/databases/SEP)
and [Sharadar SFP](https://data.nasdaq.com/databases/SFP)—before trusting an
existing frontier or calling ingest. The same configuration digest is required
by the runtime. The `data_publication` subject binds the held current
publication fingerprint and exact visible frontier without publishing either
raw preimage.

The required financial gates are:

```text
git_identity
certified_suite_no_skips
database_financial_health
wealth_core_nas_parity
sharadar_readiness
preopen_share_unit_authority
alpaca_paper_account
official_close_nav
account_fill_interval
close_cash_finality
paper_dividend_attribution
zero_mutation_boundary
```

For `SHADOW_GO`, the first five and `zero_mutation_boundary` must pass, the
shadow state must be fresh and internally coherent, and all paper-only gates
must still be reported. A paper-only failure is visible but does not authorize
or contaminate a broker-free shadow. For `PAPER_EXECUTION_GO`, every gate must
pass. For `DUAL_RUN_GO`, every `SHADOW_GO` gate plus
`alpaca_paper_account` must pass. The enrolled account may have any positive,
empty, cash-only starting equity; account sizing does not require it to equal
the shadow research capital. The official-close NAV, fill-finality,
close-cash and paper-dividend gates remain visible and may keep
`PAPER_EXECUTION_NO_GO`; they cannot downgrade the independently certified
shadow return or silently promote Alpaca's P/L to strategy truth.

## Financial database-health gate

`database_financial_health` is deliberately narrower than general database
hardening. It does not certify backups, disaster recovery, storage redundancy,
or host security. It fails deployment only for a database property that could
change a strategy decision, its causal data identity, or whether the decision
can finish before trading.

The exact candidate runtime performs these read-only proofs after preparation:

- both behavioral and feed migration ledgers/catalog witnesses match exactly;
  required columns, constraints, views, unique keys, and every reviewed critical
  index are present, valid, ready, live, and semantically unchanged;
- the held current publication is exhaustively coherent, its visible frontier
  equals its declared end, its chain has zero gaps and zero duplicate non-null
  ingest run ids, the latest 252 dates equal the independent XNYS axis, and the
  frontier has zero duplicate security keys;
- a repeatable-read, read-only transaction holds the shared corpus pin; a second
  connection is unable to acquire the exclusive writer lock, while publication
  identity and visible frontier are identical before and after every probe;
- `EXPLAIN (FORMAT JSON)` proves the sparse predecessor lookup uses
  `idx_sentinel_bars_predecessor` without a `sentinel_bars` sequential scan or
  global sort, and the live frontier load uses `idx_sentinel_bars_session`
  without a `sentinel_bars` sequential scan;
- an uncached canonical revision scan reloads and hashes the exact 252-session
  warm-up bars and causal metadata used by `durable_status`; the already-required
  forward differential is timed as a much heavier 7,188-session decision replay;
  the actual bounded schema/daily-ingest preparation is timed as well.

The sanitized bundle publishes integer milliseconds, not raw SQL, DSNs, rows,
tickers, or host paths. These bounds are fixed and independently revalidated by
the deployer:

| Measured workload | Maximum |
|---|---:|
| Bounded schema + Sharadar daily ingest command | 7,200,000 ms (2h) |
| Full 7,188-session forward decision replay | 14,400,000 ms (4h) |
| Cold 252-session warm-up revision scan | 1,800,000 ms (30m) |
| Sum of all three | 17,550,000 ms (4h52m30s) |

The shortest fixed 23:45 ET source-final to following 09:30 ET XNYS-open
window is 35,100,000 ms (9h45m). The combined bound consumes at most half and
therefore preserves at least 17,550,000 ms (4h52m30s) of margin. A weekend or
holiday may increase the observed window but can never relax the weekday bound.
Any missing measurement, slow component, changed query plan, failed pin,
partial/mixed publication, schema/index drift, non-XNYS gap, duplicate key, or
post-preparation database write makes every deployment verdict `NO_GO`.

## Redaction boundary

The bundle contains booleans, counts, dates, static source names, and one-way
digests only. It must not contain API keys or encoded forms, passwords, DSNs,
authorization headers, response bodies, query strings, account balances,
account/order/activity IDs, tickers, positions, hostnames, or local paths. The
secret scan examines every member and the archive member list; any finding
changes both verdicts to `NO_GO` and prevents upload guidance.

## Review and activation

External review does not rewrite the immutable ZIP; its embedded review field
remains `UNREVIEWED`. The operator's explicit `--confirm-reviewed-go` value must
equal the exact reviewed ZIP SHA-256. Deployment then independently verifies
the schema, freshness, clean candidate HEAD, image/runtime digests, requested
verdict, and that exact digest before changing a service.

The supported post-review modes are deliberately separate:

```bash
bash scripts/sentinel-autonomous-deploy.sh \
  --mode dual \
  --validation-bundle artifacts/<bundle>.zip \
  --confirm-reviewed-go <bundle-sha256>

bash scripts/sentinel-autonomous-deploy.sh \
  --mode shadow \
  --validation-bundle artifacts/<bundle>.zip \
  --confirm-reviewed-go <bundle-sha256>

bash scripts/sentinel-autonomous-deploy.sh \
  --mode paper \
  --validation-bundle artifacts/<bundle>.zip \
  --confirm-reviewed-go <bundle-sha256>
```

The shadow command may consume only `SHADOW_GO`; the dual command requires the
separate `DUAL_RUN_GO`. Before any deployment mutation,
it rechecks the clean commit, all recorded local image IDs, runtime source
identity, current publication/frontier, exact shadow configuration, and the
existing shadow lineage. The lineage must be either truly `NOT_STARTED` or a
fully attested matching history. A crash after an exact validated genesis or
after one durable candidate but before its authority is classified explicitly
as `RECOVERY_REQUIRED` (`GENESIS_ONLY` or `TRAILING_CANDIDATE`) and may resume
only that exact session while its following XNYS open is still future. At or
after that open, or for multiple/malformed candidates, a gap, config/source
drift, or malformed authority, activation refuses permanently.
For a truly new lineage, service/deployment health also refuses outside that
same prospective window; it never reports a retrospective `NOT_STARTED`
installation as healthy and instead waits for a later close.

After image promotion and after the old publisher is stopped, deployment
rechecks the exact reviewed publication/frontier and lineage under the writer
fence immediately before persisting reviewed facts. The non-secret reviewed
data-publication digest is then passed into `sentinel-shadow`; a fresh or
genesis-only start recomputes it inside the held publication pin before any
genesis/candidate commit. A corpus change in the small recheck-to-start window
therefore refuses rather than beginning an unreviewed lineage.

Reviewed shadow mode starts only the dedicated `sentinel-shadow` service. That
service receives Sharadar, PostgreSQL, and reviewed identity/configuration
and data-publication bindings, but no Alpaca key, secret, or account id. The broker-capable
`sentinel-automation` service remains stopped while its durable control stays
disabled and killed. The paper command requires `PAPER_EXECUTION_GO`;
`SHADOW_GO` can never be promoted by a flag, and the present two-source bundle
therefore refuses paper mode.

Reviewed dual mode first starts and attests that same broker-free shadow
service while automation remains disabled and killed. It then proves the
empty/owned, positive, cash-only PAPER account, installs the existing signed
`PAPER_OBSERVATION_ONLY` authority, and prepares one immutable plan directly
from the exact verified shadow state/record. The canonical adapter account-sizes
that intent using the bound complete Alpaca snapshot/observation and pinned
Sharadar close marks; it persists a one-way commitment to every sizing input
and re-derives the basket/fingerprint before transport. Dual mode may not
advance or read a separate PAPER catch-up strategy lineage. The PAPER account
may have any positive enrolled starting equity and reports only normalized,
non-authoritative return; it need not equal shadow research capital. Only after
that one-way bridge is re-earned inside the promoted runtime does deployment
start PAPER automation behind the kill fence and explicitly release it. The
automation container receives the reviewed shadow identities for
reconciliation but receives `SENTINEL_SHADOW_OBSERVATION_ENABLED=0`; it cannot
write or impersonate the certified ledger.

The broker transport follows
`docs/decisions/informational-paper-mirror.md`: it persists
`PREOPEN_UNPROVEN/PENDING` before any order mutation, transports only the exact
immutable close-unit basket, and post-close validates every active unit mapping
from the next source-final publication. A mismatch makes the overall/PAPER
surface red and blocks later mutations without cancellation or liquidation.
The independent shadow strategy return remains `VERIFIED` unless its own
data/revision/lineage gate fails.

## Meaning of a verified result

The strongest honest statement is:

> Every result labelled VERIFIED is attributable to the strategy, the accepted
> Sharadar inputs, and the explicitly named observation model. Unsupported,
> revised, or incomplete evidence stops verification instead of changing the
> reported strategy result.

The statement applies to Sentinel's verified series. It never applies to raw
Alpaca dashboard P/L: Alpaca PAPER does not simulate every live-account economic
event, including dividends. In dual mode the external Snowball app is therefore useful for
observing transport, orders, positions, and rough account movement. Sentinel's
separate mobile web panel shows the certified shadow return, PAPER
reconciliation, and combined operational red/green status; the
broker-free `SHADOW_GO/VERIFIED` series is the number used to judge the
strategy. A red/blocked PAPER reconciliation makes overall operational status
red and Alpaca/PAPER performance `NOT_VERIFIED` until reviewed. It does not
withdraw an independently valid shadow strategy return; only a shadow data,
revision, model, or lineage failure does that.
