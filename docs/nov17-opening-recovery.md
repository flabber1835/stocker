# November 17 PAPER opening recovery

Decision recorded before implementation. This is a local corrective patch for
the installed backed PAPER release at `afff7657`. It does not activate a new
release, alter the canonical book, extend the opening purchase window, or grant
LIVE authority. Preserve the acknowledged CRL command and its broker identity;
never infer that an unrecorded fill did not occur.

## Observed failure and provider contract

The November 17 CRL dollar BUY was journaled once and acknowledged before the
14:40 UTC increase cutoff. Alpaca's account-bound Activity SSE then reported one
`TRD` execution for that exact broker order and client key with
`details.execution_type=partial_fill`, incremental quantity 1, price 335.82,
and native `ref_id=aaa9c61a-3f0b-4472-92ce-cf8695ef58b0`. Repeated reads of
that `ref_id` are one execution, not additional fills. The local owned-fill
adapter accepted only `fill`, retained the native refusal, and returned
`RECONCILING` before a post-order observation or canonical fill could commit.
The automation recovery callback translated that result into a transient
availability retry without an attempt limit. PAPER readiness failed while the
command remained acknowledged and in flight.

Alpaca's [November 6 Activity V2 change](https://docs.alpaca.markets/us/changelog/2026-11-06-partial-fill-214389c)
documents `partial_fill` as an emitted `ActivityV2DetailTRD.execution_type`.
The preceding day's successful MTD purchase has one durable fill, but its raw
wire type is not retained. Its success does not qualify the missing type.

## Selected execution behavior

- Treat `TRD` execution types `fill` and `partial_fill` as positive incremental
  executions in both the exact-owned recovery reader and the bounded fill
  interval candidate. Keep the exact account, order, client key, asset, side,
  USD/status, quantity, price, timestamp, correction/bust, and cumulative
  progress guards. Keep `ref_id` as the economic idempotency key and `event_id`
  as the replay cursor. Do not add trade cash to the separate activity cash
  total or renew any proof deadline.
- Keep unsupported, malformed, corrected or busted native fill activity as
  explicit retained refusal evidence when the reconciliation fill reader
  rejects it. A *positively identified* native fill validation
  refusal is a data-integrity condition, not broker unavailability. Propagate a
  typed marker through reconciliation and PAPER recovery so automation blocks
  that cycle with a precise cause rather than retrying an immutable bad event
  indefinitely. Do not classify ordinary incomplete observations, pending
  orders, timeouts, order-cumulative progress lag or source waits as this
  condition; their existing recovery remains automatic. For Activity SSE
  envelope validation, a decoded `TRD` with a nonempty native `ref_id` is
  identifiable refusal evidence even when another envelope field is malformed.
  An undecodable stream or a row without that execution identity is not a
  retained fill refusal. A decoded native fill
  whose immutable asset, side or client key contradicts its exact owned order
  is also a typed data-integrity refusal. Do not identify this case by matching
  an error string or by turning every fill-validation `ValueError` terminal.
  A blocked cycle does not cancel or erase an acknowledged order, create a
  replacement key, or imply flat exposure.
- Keep the typed PAPER refusal owned by `sentinel.paper.model` and import it
  directly at the automation boundary. The canonical `sentinel.paper` package
  root API remains unchanged; this recovery classification does not create a
  new public lifecycle operation or alter the frozen package equivalence
  manifest. Qualify the new internal class and refusal helper, plus the changed
  clean-evidence and recovery definitions, in the existing paper lifecycle
  delta registry with their exact ASTs and behavioral acceptance tests. Keep
  their historical AST pins unchanged and falsify unknown neighboring edits.
- The separate cash-activity correction/bust guard can refuse before fill
  reconciliation. It remains terminal and fail-closed, but it does not yet
  retain a raw native-refusal row. This adjacent evidence gap is separate from
  the observed `partial_fill` failure and requires its own qualification.
- Historical native-refusal rows remain immutable. After the parser accepts
  `partial_fill`, ordinary exact-id replay must safely observe and apply the
  previously refused event once through canonical reconciliation. The repair
  must not synthesize a fill from this document or from dashboard state.

## Qualification and why CI missed it

The fractional simulator represented partial order status and quantity but
still emitted `execution_type=fill` in its synthetic Activity SSE. Green CI
therefore exercised partial command progress without the provider's emitted
partial execution type. Change that fixture and add exact-owned, same-`ref_id`
replay, partial-to-final distinct-id, cash non-double-count, and bounded
fill-interval cases. Falsify the parser by restoring the old allowlist; the
new case must fail. Separately inject an unsupported execution type and a
genuine transient read failure to prove data-integrity terminalization and
automatic availability recovery remain distinct. Offline fixtures cannot
detect future vendor schema additions on their own; review the provider's
published Activity V2 changes as part of release qualification.

No test may infer a canonical fill from native evidence without passing the
existing exact account/order/economic validation and one durable commit.

## Independent economic source contribution

The first PR CI run exposed a second qualification gap. The execution-only
changes to `execution/reconcile.py` changed its raw bytes, but the existing
operation-read source compiler knew only the earlier read-elision edit. It
could no longer reconstruct the exact independently pinned predecessor and
therefore changed the economic manifest and production strategy identity.
This is a source-qualification failure, not evidence that Wealth Core economics
changed. Extend the exact reviewed compiler edge only for the new reconciliation
fields and refusal propagation, preserving the original predecessor bytes,
economic contribution, strategy identity and all historical pins. Reject any
other altered reconcile bytes. Do not update the expected economic or strategy
digest merely to satisfy CI. Falsify the new reverse transform and test the
complete source and strategy identities before resealing the final source
inventory.

## Selected dashboard behavior

The opening exposed two different HTTP 503 meanings. At 14:31:22 UTC a signed
PAPER receipt changed after the DASHBOARD snapshot was generated, with the
native PAPER revision and account anchor unchanged. Strict health correctly
withdrew current authority for about eleven seconds; a later gap also included
SHADOW receipt renewal. From 14:38 UTC onward a current signed snapshot instead
reported an actual failed PAPER readiness row while execution recovery was
unproved. These must remain distinguishable. A human display may keep separately
proved rows during a receipt handoff, but it cannot make the old snapshot
strict-current or authorize acknowledgement.

- Wake the existing verifier-owned dashboard publisher immediately *after* a
  financial receipt or review diagnostic commit. Coalesce wakeups and preserve
  one follow-up wake if publication was already in progress. The existing fast
  and full composition workers, ownership, exact subject checks, original row
  deadlines and signed publication remain authoritative. This removes an
  avoidable idle poll from the handoff; it does not promise zero 503 time under
  continuous mutations or permit HTTP requests to collect or publish evidence.
- For a strict-noncurrent response whose signed display was read, expose its
  existing observation cause and clocks in the machine response, along with a
  short retry hint. A current red failure remains a current red failure and
  retains its row and source-error detail. When no authenticated snapshot is
  available at all, the generic 503 page must explain that signed status is
  temporarily unavailable and will retry, without claiming an installation
  stage that has not been authenticated.
- A financial receipt read that becomes UNKNOWN must name a finite failure
  site and exception class in its signed source error: subject facts or read,
  receipt row or clock, subject rebase or wait, receipt decode, SHADOW
  projection, or PAPER activation projection. The code is set at the operation
  that failed; never retain exception text, raw receipt contents, subject
  hashes, or credentials in this diagnostic. A new failed review condition
  records the code in its durable evidence. If the site changes while the same
  condition stays active, the signed current source error reflects the latest
  site; this does not create a new review event solely for diagnostic churn.
  UNKNOWN rows and strict red health retain their existing authority.
- Separate an older historical PAPER mirror mismatch from an unproved current
  cycle. When RETRY_WAIT has no current clean reconciliation, the PAPER row
  remains red/FAIL and preserves historical warning details, but its value
  names *current readiness unproved*. Reserve `MISMATCH` wording for a proved
  current mismatch. This is presentation provenance only; it cannot relax
  PAPER verification or turn the cycle green.

During the PR600 installation the verifier was stopped under a fenced
qualification/activation handoff, so the prior signed snapshot could not be
presented as current for roughly nine minutes. Strict 503 was the correct
financial answer. The old rollout certificate and saved plan genuinely
disagreed until the new plan was prepared, and per-attempt review history
recorded each failed verifier attempt. This patch does not erase or coalesce
those immutable records, hide `SUPERSESSION_EXHAUSTED`, extend a financial
proof clock, or label an unproved installer phase as healthy. Existing PR599
source-error ownership and PR600 fee-wait refresh corrections are retained.

The 13:56:42–13:57:09 activation review recorded a PAPER receipt failure only
as `ValueError`; the reader collapsed distinct failure sites to that class.
The exact old exception cannot be reconstructed. Access logs show brief 503s
at 14:00:28, 14:00:49, and 14:17:09 UTC, each bracketed by 200 responses,
but did not retain response bodies. Their exact strict condition is likewise
unproved. The finite receipt codes and strict response metadata above improve
future diagnosis; they do not establish a retroactive cause or eliminate the
deliberate 503 while a fenced install has no current signed snapshot.

Qualify a real receipt publication racing the producer: strict health must
refuse the old snapshot, then recover from a newly signed snapshot after the
post-commit wake. Falsify a lost wake during an in-flight publish. Cover a new
negative receipt, changed review head, current red failure, unavailable
snapshot, and historical-mismatch/current-unproved wording separately.

Prior dashboard tests covered a static noncurrent snapshot and ordinary
projection publication, but not the receipt commit between collection and
strict read, the verifier's idle poll after that commit, or historical mismatch
fallback while the current cycle was in `RETRY_WAIT`. The fenced-install
no-snapshot state also lacked a direct copy test. These are separate fixture
gaps from the native Activity SSE vocabulary gap above.
