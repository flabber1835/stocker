# Autonomous feed corrections and bounded reuse

Decision: 2026-10-17. Preserve the canonical book, original published observations,
execution membrane, provider identity and finite preparation deadlines.

The source inventory uses the exact validated Alpaca trading origin's assets
endpoint, defaulting to paper. Paper/live origins are fixed allowlisted choices;
the source client still exposes only GET inventory/bars/actions. Inventory
generation and transport evidence bind the chosen endpoint. This grants no
account, order, execution or live-admission authority to the feed.

An absent action outside the current Alpaca reference coverage is unknown source
coverage, not a deletion. Compare historical source removals only inside the
current authoritative per-listing action interval. A genuinely observed unresolved
correction retains its original evidence when that interval later moves past it;
absence of coverage cannot heal a correction. Full historical Sharadar references retain
their existing wider correction checks. Previously accepted event evidence and
its canonical identity remain immutable. Current covered corrections still
produce scoped unresolved evidence; ordinary rolling retirement must not do so.

Foreground preparation handles the same typed transient Alpaca/OpenFIGI failure
as the durable publisher. Retry only while the existing job remains retryable
and its original deadline permits; do not turn permanent input refusals into
retries or extend clocks.

For an unheld candidate, restart the usable tail after an uncorroborated price
basis break. Explicit split terms retain their existing agreement and predecessor
requirements. Protected ownership and controller dependencies continue through
the ordinary continuation checks; a shortened candidate history cannot erase
their economic evidence. This changes normalization admission to Alpaca current
window version 3. Version 2 remains readable for retained history, while fresh
acquisitions require version 3. The acquisition source remains version 3 because
the provider requests, dated identity evidence and reference formats are unchanged.

## Acquisition payload sharing

Continue fresh complete-window raw and split acquisition and final source
corroboration. Only after a fresh partition's complete content commitment agrees
may a new immutable acquisition part reference an existing fully verified price
payload. Each part retains its own job, generation and new transport observation;
sharing bytes never refreshes the age of an older observation or claims delta
coverage. A changed row, removed row, split restatement, identity dependency or
schema remains independently detectable. Interrupted or corrupt payloads refuse.

Use an additive immutable part-to-payload link, with direct root links only.
Acquisition-part schema 2 binds the auxiliary reference payload independently of
the price commitment, including raw/adjusted missing-key evidence. Historical
schema 1 remains readable under its original integrity contract; new parts use
schema 2. A shared price payload does not share or replace fresh auxiliary facts.
Existing unlinked parts remain their own payload roots. The latest operational
publication retains its completed price roots as a bounded deduplication seed;
replacement releases roots no longer used by that publication or any active job
and predecessor chain. References and job receipts remain immutable. Readers
verify the original complete content commitment and exact keys before reuse.
This reduces repeated database writes/WAL and storage duplication, not provider
downloads. Delta-only acquisition remains unqualified.

## Retention and verification

Bulk price DELETE authorization runs in statement-level transition-table triggers.
It checks behavioral/corpus ownership once and proves every distinct affected
candidate is retired or every distinct acquisition payload is unpinned. Trigger
failure rolls back the complete statement. UPDATE/TRUNCATE remain forbidden;
there is no session flag, disabled trigger or alternate deletion permission.
The existing short timeout, writer ordering, backup authority and batch bounds
remain. Avoid caching historical chain verification beyond its existing immutable
publication pin unless a separate corruption/concurrency proof establishes safety.

## Qualification

Add regressions that fail on the original action roll-off, foreground retry and
candidate-tail implementations. Exercise real PostgreSQL publication, corrections,
sharing, changed/deleted rows, corruption, restart, active-job and current-publication
pins, direct SQL refusal and statement rollback. Measure stored payload rows,
provider calls and database relation sizes on repeated identical and changed
partitions; timing is diagnostic rather than a semantic assertion. Run the actual
GET-only source/GO qualification separately before publication. None of these
tests issues admission, activates execution or submits broker orders.

## Isolated real-provider diagnostic

`tools/autonomy_feed_qualification.py` first uses the exact committed runtime image
in a read-only, disposable data probe. It creates no database, Compose services or
financial publication. The required next-stage financial diagnostic uses a unique
private Compose project containing only PostgreSQL, the CLI and backup client;
that second-stage runner is not implemented by this read-only probe. No environment file, installed
runtime selector, existing service, account, order or production volume is written.
Read only the Alpaca/OpenFIGI credential names from the operator environment file
into process memory; child commands pass names, not secret values. Reports contain
status, timing, counts and content commitments rather than account/source payloads.

Run a genuine GET-only market-data/OpenFIGI mapping probe first. Complete financial
preparation then requires an actually mounted, already owner-attested independent
backup target. Verify that parent through the ordinary read-only backup helper;
only a fresh private child on that same verified filesystem may inherit its media
attestation. A local Docker volume or absent NAS/USB path cannot acquire that
attestation. If the target is unavailable, record the exact unmet gate and stop
before creating a publication. Never fabricate backup receipts or certificates.

The required next stage, when that target is available, must use genuine
base-backup and full restore producers,
the real Alpaca/OpenFIGI preparation, the unchanged finite backup-renewal runner,
canonical startup/restart parity and the existing read-only readiness/financial
health probes. The private Compose name is fixed in both generated files and all
Python probe arguments, including host backup helpers. Stop only this private
project on exit and retain its dedicated data and diagnostic artifacts for review.
Software certification, NAS capacity and live trading authority remain explicitly
NOT_PROVEN; a local financial diagnostic never creates a deployable GO document.

The checked-in driver always reports overall NOT_PROVEN: successful source access
is only one prerequisite. It reports the actual backup mount availability and
records preparation, formation/restart parity, renewal and financial readiness as
unexecuted. Do not treat its exit status or source PASS as the required GO pass.

Run the read-only prerequisite after the root agent has committed the complete
change and built its exact image (from WSL, where Docker is available):

```sh
python3 tools/autonomy_feed_qualification.py --runtime-image sha256:<64-hex-image-id> \
  --commit <40-hex-commit> --credentials-file /mnt/c/GitHub/stocker/.env \
  --output-dir /mnt/c/Users/mbron/.codex/visualizations/<fresh-evidence-directory>
```

Exit 2 is intentional NOT_PROVEN. `--plan-only` performs no provider calls. The
600-second data probe removes only its randomly named private container on every
exit, including a timeout. It retains only the redacted JSON report.

The pending financial producer chain is reported explicitly in `report.json`.
Those host scripts must run from the private Compose workspace described above;
they must never be invoked against the installed stack as a shortcut. Full GO
uses the operational command documented in `docs/sentinel-deployment.md` after
independent media and isolated fixture ownership are available. This tool does
not replace that required pre-publication qualification.
