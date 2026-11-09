# Separate verifier input availability from worker outcome

Decision: November 8, 2026, before implementation. The owner authorizes a
qualified local PAPER patch, with PR delivery after local stability.

The retained incident proves that attempt c1f08fd5abf1465c960402663efa686d
was marked FAILED at 14:35:02 UTC by a parent identity-read ConnectionTimeout
while its worker was still running. That same attempt completed VERIFIED at
14:35:28, within its original 14:36:45 work deadline. This patch corrects that
state ownership error. It does not assert a cause or cure for host/network/
PostgreSQL connection latency.

Reader owns two independent facts: the actual bounded worker lifecycle and
availability of the current input identity. A parent identity-read exception
must set a separate private availability diagnostic and failure time, without
changing the worker's outcome, completion, diagnostic, latched financial failure,
answer, retained result, attempt ID, subject or deadlines. Return UNKNOWN current
evidence immediately; an unavailable identity cannot confer readiness. Preserve
the existing sanitized diagnostic in the unknown rows, which the ordinary
operational review can record, without inventing a failed financial attempt.

Availability remains withdrawn until a full successful result for the freshly
revalidated current subject completes at or after the latest identity-read
failure. A previously cached or already-completed answer from before that failure
cannot clear it. An already-running worker may supply that later result; do not
start a duplicate worker, reset its clock or discard its answer. Otherwise the
existing retry cadence admits one fresh check. Actual negative results and worker
failures retain their own diagnostics and failed-attempt history independently
of any availability failure. Partial/source-wait outcomes keep their existing
scope and cannot clear availability as a full verified result.

This adds no durable schema or authority. Existing attempt/review history remains
immutable; no automatic acknowledgement is performed. Preserve the canonical
book, broker membrane, UNKNOWN outcomes, all original deadlines and PAPER guards.
Deliver through the backed application installer with exact-image/source and
unchanged-state qualification, using the installed build-reuse/readiness fixes.

## Exact operational source handover

Retain the original installed 34a28504a87610fd5c159115fc0b75017ae944ea
source as a complete 460-module map with closure
e7d7971f85feb8e4432589d06cf796e4395dc2b1c2d7eddf4f5f38877d5ee73c.
Append that independently archived map as IDENTITY_AVAILABILITY_PREDECESSOR_REVISION
in source-profile schema21. Preserve all 19 earlier maps, original base and
structural identities, all 116 economic contributors and both financial witnesses.
Before sealing, only panel/authority_reader.py may differ in the application
map. The checker changes only exact registration/membership/schema/checksum
metadata; reversing it must recover the complete original checker bytes.

The schema20 JSON was 959,678 bytes. Serialize schema21 compactly to retain every
full inventory within the unchanged 1,000,000-byte bound; decoded historical
maps and policy fields remain identical. Do not omit entries, shorten hashes,
increase the bound or replace original financial witnesses. The reviewed
preparation plan binds exact input/output hashes before source application.
