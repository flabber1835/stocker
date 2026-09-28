# Acquisition resource containment

Decision, 2026-09-28, before implementation: bound complete export acquisition
without changing the requested history or accepting partial source evidence.
This closes the export/cache defects identified in acquisition resource
qualification. It is not a claim about total process RSS, PostgreSQL capacity,
paginated JSON transport, or NAS workload headroom.

## Reviewed envelope

The production image owns fixed limits, with no environment-variable bypass:

| Boundary | Inclusive limit |
| --- | --- |
| Downloaded ZIP, including a reused cache entry | 64 MiB |
| Expanded CSV | 256 MiB |
| Data rows per export | 1,000,000 |
| Retained CSV cells per export | 8,000,000 |
| Columns per row/header | 64 |
| CSV record, including quoted multiline input | 1 MiB of characters |
| ZIP central directory / entries | 1 MiB / 32 |
| Cache ZIPs and checksums, including a pending write | 512 MiB / 64 ZIPs |

These are admission ceilings, not measured provider-size guarantees or an RSS
budget. Ordinary monthly SEP files and complete ACTIONS/TICKERS exports must
fit; if a legitimate export exceeds an envelope, refuse and review its observed
size and a new implementation/limit. Never shorten history, silently drop rows,
ignore an oversized component, or automatically raise the limit.

## Transport and parsing

Use HTTP streaming, request identity content encoding and reject other encodings
before consuming the response. Count raw chunks before retaining them; an absent
or understated Content-Length cannot bypass the limit. A declared oversize body
refuses before transfer. Close the response on failure, do not cache partial
bytes, and do not retry a deterministic resource refusal as provider pending.

Validate ZIP directory bounds before constructing ZipFile, then check declared
and observed expanded CSV bytes. Accept only stored or deflated, unencrypted CSV
members; alternative codecs can allocate large decoder dictionaries before an
output-byte check. Reject ZIP64/multidisk archives, which are not needed inside
this envelope. Bound records before CSV parsing, then columns,
rows and cells before retaining row dictionaries. Cached files undergo the same
parser checks; a checksum is not a resource exemption. Error messages contain
the boundary and limit, never a signed URL or source row.

## Cache ownership and recovery

Keep the existing per-key download locks. Add a cache-wide bounded kernel lock
around reads and all cache mutations, acquired after the per-key lock. Network
transfer and parsing do not hold the global lock. Writers reserve space by
evicting oldest non-authoritative ZIP/checksum pairs before creating temporaries.
Readers hold the global lock until bytes and checksum have been read, so eviction
cannot race a read or hide still-open disk allocations from quota accounting.
Read attempts also prune a legacy cache to the current aggregate envelope; an
evicted entry is a cache miss and must be reacquired normally.

All writers use the global lock. Under it, abandoned partial files and orphan
checksums can be removed immediately, including after process death. Replacing
a cache entry may discard its old bytes before the replacement commits; a crash
then causes reacquisition, never acceptance of incomplete evidence. No published
corpus, preparation checkpoint, backup or WAL file is eligible for eviction.
Write/fsync/rename failures clean partial state and propagate; the next attempt
can reacquire. The quota bounds cache payloads, not filesystem metadata, lock
files, the separate cooldown database, or unrelated disk users.

## Required falsifiers

Exercise exact-limit acceptance and limit-plus-one refusal for transfer,
expansion, records, rows/cells and cache bytes. Include missing/false length,
compressed HTTP encoding, many ZIP entries, cached oversize files, concurrent
writers/readers, interrupted writes and retry with a valid complete export.
Verify a resource failure cannot publish a rolling candidate and that its
durable reason distinguishes it from SOURCE_EXPORT_PENDING. Remove guards in
isolated mutation runs and require behavioral failures. Reuse existing CI test
ownership; do not create another certification pipeline.
