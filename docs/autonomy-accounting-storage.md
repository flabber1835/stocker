# Autonomous cash accounting and compact storage

Decision: 2026-10-17, before implementation. The broker remains authoritative
for actual cash, positions and fills; these changes affect the independent
canonical model and its physical persistence only.

The forward cash policy advances to `FORWARD_CASH_DISTRIBUTIONS_V2`. Reconstruct
opening ownership from security-specific legs: a conversion removes its
`shares_in` from the predecessor and credits `shares_delivered` to its named
successor. The historical net share delta is never a successor receipt. Splits
and spin-off receipts precede ordinary same-day trades, while conversion legs
take effect after that day's ordinary dividend entitlement, matching the
canonical transition's existing dividend-before-conversion order. Build one
dated ownership/accrual index per transition rather than scanning the complete
ledger for every observed dividend. Preserve all original events and correct
future recognition through the existing forward adjustment mechanism.

A v1-to-v2 change requires an explicit transition bound to the original state
and both strategy identities. It does not rewrite prior decisions, claim parity
for affected conversion dividends, or admit another controller/capital policy.
Unchanged economic cases must retain their existing results.
The previously absent policy may use the same explicit forward admission.
Retained intermediate v1 admissions keep their original authenticated profile
identity; they are not relabelled as v2 admissions.

Current-window candidate inputs retain only the current signal close plus the
already computed eligible numerical features. Both the ordinary producer and
formation producer use the same compaction. The exact 300-session acquisition
and formula calculation remain mandatory; held, pending and controller witness
histories remain separate protected inputs. Readers continue accepting original
127-close inputs. This changes new input commitments but must preserve canonical
transition, state, target and restart results for the same economic data.

New observation persistence stores sealed groups of 256 canonical ledger events
once in the existing `sentinel_processed_sessions` table under the reserved
content-addressed `observation-ledger:v1:<sha256>` namespace. Their bounded,
compressed canonical JSON payload is inserted in the same transaction as the
observation. An existing address must contain exactly the expected bytes;
conflicts, missing chunks, reordered references, mismatched event counts and
decompression/checksum failures refuse. A separate physical envelope references
complete groups and carries a bounded compressed tail. It never becomes logical
strategy state or trading authority. Generic file/cache encoding remains
self-contained. Old inline states and original feed-series envelopes remain
readable without rewriting historical records.

Decoded logical values and canonical state hashes remain byte-equivalent to
their original representations. Event payload growth becomes incremental;
reference lists and daily bounded tails still repeat, so total metadata growth
is not claimed to be strictly linear. Keep the current backup/transaction and
append-only audit boundaries. Measure logical JSON, actual PostgreSQL bytes and
encode/decode/index work separately. Qualification includes conversion/cash
falsifiers, full state/target/restart parity, legacy mixed storage, rollback,
missing/tampered chunks and representative retention-scale measurements.
Logical state restoration and hashing still inspect the complete ledger. This
change reduces repeated persisted event payloads and indexes dividend queries;
it does not claim constant-time lifetime-state hashing.

## Isolated measurements

The qualification fixture retains 24 daily observations ending at 1,984 events.
The baseline uses the original inline-ledger physical writer; the normalized
run uses the production chunk writer. The sum of PostgreSQL `pg_column_size`
for every retained observation and every new ledger chunk falls from 729,796
to 134,322 bytes (81.6%). Logical canonical JSON totals 6,914,934 bytes in both
runs. These are column payload measurements, excluding heap/index overhead and
WAL, and are not estimates of a deployed book. Append wall time was 1.082 s
versus 1.020 s in this sample; it is not evidence of a general write speedup.
Complete groups are shared, while references and a compressed tail still repeat.

For 5,000 candidate signals, canonical input JSON falls from 7,807,057 to
916,177 bytes (88.3%), with the same numerical signal results. Full transition,
target and restored-state tests compare compact and original 127-close inputs.

A separate full cash-recognition fixture uses 5,000 ledger events and 1,000
unheld cash observations, with equal financial results. Across three process-CPU
runs, median CPU is 0.448 s for the original repeated scans and 0.0402 s for the
indexed transition (about 11.1 times less). It establishes the benefit of indexing
repeated queries in this fixture; deployed latency still depends on the book,
input count, persistence and complete-state hashing.
