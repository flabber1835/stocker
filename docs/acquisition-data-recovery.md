# Acquisition data recovery and reviewed correction datasets

Decision, 2026-09-30, before implementation. This supersedes embedding reviewed
ticker/session facts in production Python. Sharadar is temporary, but unattended
operation must distinguish missing source data from a software defect now.

## Correction data, not per-ticker algorithms

Move the existing 40 exact coverage allowances and one cash-event adjudication,
including its independent dispute flag, into a versioned JSON bootstrap dataset.
Preserve their exact matching and economic semantics. The immutable image carries
that initial dataset; Python contains only schemas, matching and validation.

An attended, broker-free import accepts an explicitly reviewed dataset with an
expected content digest and expected predecessor digest. It validates bounded
size, strict fields, dates, uniqueness, evidence references and the existing cash
authority contract. Updates are additive: they cannot remove or silently change
previously reviewed facts. More general correction revocation or replacement
requires a separately designed data-repair operation.

Use the existing shared Sentinel state volume, an exclusive nonblocking kernel
file lock, atomic replacement and fsync. Sign imported records using the existing
publication receipt key with a distinct purpose. Keep immutable content-addressed
versions. A digest detects corruption; the signature authenticates the attended
installation. Neither proves that a reviewer interpreted an external source
correctly. An absent optional installation uses the bundled bootstrap; malformed,
incomplete or unauthenticated installed state refuses, never falls back.

Each acquisition attempt captures one dataset before normalization. Persist the
full dataset in immutable snapshot source evidence, which the snapshot manifest
and publication receipt already bind. READY retries use that pinned dataset;
later installations cannot rewrite a sealed or published snapshot. Pre-upgrade
READY evidence without a dataset retains its original evidence shape and uses the
exact bundled facts moved from that release; upgrading cannot repin its contents. A pre-seal
attempt may select newly reviewed data, but must repeat coverage and normalization.
Retained raw source parts remain reusable because they have no correction policy.
Legacy operations use the same validated dataset loader; existing historical
readers continue consuming already-normalized published rows.

The strategy's existing data-semantics source fingerprint covers the generic
correction loader and schema/validation code as transitive economic dependencies.
Correction records themselves remain input data, bound by the snapshot's source
evidence digest. An attended data addition does not change strategy code identity;
changing the code that validates or selects it must change that identity.

This is an operator data action, not a source-code release or a certificate that
authorizes trading. No automatic URL retrieval, arbitrary Python, inferred price,
identity merger, skipped eligible instrument, or weakened coverage is introduced.

## Missing-data recovery

Pure missing eligible-set coverage raises a typed source-data pending condition.
Unexpected identities, malformed input, conflicting evidence and damaged local
state retain their integrity refusals. Record the pending evidence and selected
correction digest under the existing acquisition job fence in an additive small
table; retain the original absolute deadline and completed raw parts.

On retry, inspect generation changes and run the existing bounded independent
source probe before replaying the complete window. Changed metadata must reach
full revalidation even if the previously expected price still does not exist. A still-missing source stays WAIT_SOURCE. A changed correction
dataset triggers full validation against retained data. A successful source probe
only permits reacquisition of the affected SEP partition through the existing
bounded successor mechanism; invalidate its optional ZIP cache and preserve all
unaffected parts. No probe result becomes a price or permission to omit one.
Successor count and the original deadline remain binding. Scheduled single-attempt
callers must persist the same bounded successor before yielding to their scheduler;
the next worker claims that child, rather than creating an unrelated fresh job. Foreground GO reports
pending/exhausted data explicitly; it does not fabricate GO.

Shadow service maps this typed source wait to its existing waiting exit, preserving
supervisor liveness and the existing following-open warning/escalation. Software,
authentication and local integrity failures retain their terminal handling.
Paper refresh waits for verified shadow data without permanently latching the
activation merely because a data retry count is reached. Retry spacing remains
bounded; missed execution windows are superseded by the existing state machine.
Existing transport recovery runs before refreshing data. UNKNOWN outcomes and
open orders remain execution/reconciliation responsibilities; a source wait
cannot liquidate holdings, create intent, or authorize stale plans.

Crossing a causal cutoff does not authorize retrospective execution or a new
shadow book. Existing preserved-state reconstruction requirements still apply.
Moving the source provider to Alpaca does not alter these authority boundaries.

## Qualification and rollout

Use synthetic previously unknown identities and real PostgreSQL jobs/publication.
Exercise missing source, cheap repeated probes, provider repair, reviewed data
repair, new worker/restart, unchanged deadlines, sealed dataset pinning, rejection
of ambiguous/altered records and retry exhaustion. Verify the original allowances
and cash adjudication remain semantically identical. Exercise the shadow worker
and paper scheduler wait/recovery paths, including transport obligations and
no duplicate execution. Falsify new content/signature and coverage gates.

Stop old acquisition workers and run the ordinary explicit feed-schema migration
before the updated runtime. No operational book migration or backtest rerun.
Existing publication, backup, reconstruction and paper activation gates remain.
Local qualification proves these transitions, not provider availability or NAS GO.

## Window and account authority

The normal rolling market window is 300 sessions. First-start formation currently
has a separate 379-close requirement. This change does not alter either contract.
A bounded price window does not mean deleting the book checkpoint, permanent
security identity or unresolved action facts at its left boundary. ACTIONS still
uses the existing reference acquisition interval; reducing that interval needs a
separate dependency analysis, not a silent change to this recovery fix.

Alpaca account observations are authoritative for actual positions, cash, fills
and pending execution obligations. They are not source history for Wealth Core.
A quantity change alone cannot establish a split ratio or distinguish a split
from a fill, transfer or other adjustment. Execution must establish a consistent
share basis from explicit action evidence before acting on conflicting source
and account units. It must not reinterpret the shadow book from broker balances.
No new Alpaca corporate-action fallback or provider migration is introduced here.

## Operator data update

Use the deployed, digest-qualified image and the existing shared Sentinel state
volume. Run the following module commands inside that container, with its normal
publication receipt key. They perform no network, database or broker operations:

```sh
python -m sentinel.feed.corrections_cli status
python -m sentinel.feed.corrections_cli export
python -m sentinel.feed.corrections_cli validate /review/corrections.json
python -m sentinel.feed.corrections_cli install /review/corrections.json --expected-sha256 REVIEWED_CONTENT_DIGEST --expected-parent CURRENT_DATASET_DIGEST --reviewer REVIEWER
```

`export` emits the complete starting dataset. Add only externally reviewed exact
facts; retain the previous records. `validate` prints the canonical content digest
(not the hash of a pretty-printed file). `status` prints the active predecessor
digest. Supply those two digests explicitly at installation. Mount the reviewed
input file read-only. A stale predecessor, concurrent installer, missing signing
key, malformed record or replacement of existing facts refuses the update.

Keep the reviewed JSON outside the NAS as a recovery copy. Installation persists
under `SENTINEL_STATE_DIR/source-corrections-v1`; published snapshots also retain
their selected dataset in PostgreSQL evidence. The current installation pointer
is not part of the PostgreSQL backup. After complete state-volume loss, reinstall
the reviewed export before acquiring new data that needs those facts. Previously
sealed snapshots retain their original interpretation. An interrupted first
installation leaves the bootstrap active; an interrupted update leaves either the
old or fully committed new version, and retrying the same reviewed update is safe.
Unused `.corrections-*` staging directories after power loss are non-authoritative.

Installing data does not revive an expired job, alter an existing shadow book or
authorize a missed order. Retry GO through the usual deadline and target checks;
active workers select the new dataset only at their next unsealed attempt. A
successful source probe may replace one affected export, but every candidate still
must pass the full independent coverage, normalization and publication checks.
