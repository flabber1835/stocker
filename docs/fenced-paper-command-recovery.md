# Fenced PAPER command recovery before retained GO

Decision: 2026-11-17. This is a proposed release repair; it grants no authority
to the installed PR601 image. The November 17 activation of that image stopped
at `RETAINED_ADMISSION_REQUIRES_COMMAND_RECONCILIATION`. Its durable CRL command
was `ACKNOWLEDGED` with zero recorded fills, while exact account-bound broker
evidence showed that the order had filled. The refusal kept execution fenced.

The owner requested a local patch before today's close for qualification and
tracing. The patch is not an installed release or permission to bypass the
protected signed-image path. The current predecessor has only a fenced
installation receipt, while the existing backed local application handoff
requires an active predecessor receipt. Close observation can continue read-only
on the fenced installation; financial activation waits for a qualified supported
release path.

## Sequencing and authority

Retained executable admission correctly refuses an overlapping command. The
ordinary dual PAPER preparation can reconcile it only after retained GO has
admitted and advanced the canonical shadow. Automation recovery requires an
enabled, unkilled control and a live recovery grant. Neither can settle this
order while a new image is installed but not activated. An activation retry
through the same order of operations repeats the refusal.

Add one activation-owned **fenced PAPER command recovery** stage after the host
has authenticated the installed receipt and exact image, established disabled
automation with its kill switch engaged, invalidated the lease, and stopped
every older broker-facing writer. Run it before retained GO/source admission,
certificate rotation, plan preparation, control enablement or kill release.
Run it only if durable commands include an overlapping state; a clean journal
continues through the existing sequence. The stage is unavailable for LIVE, an
unbound or different account, a replacement host without its separately
required takeover proof, an unverified installation, or an unfenced writer.

## Supported entry point

The only production entry is a dedicated `recover-fenced-paper-commands`
route in the signed Sentinel PAPER CLI inside `/app/sentinel`. Register it in
the authorized command registry and invoke it through the existing
digest-qualified `sentinel-authorized-cli` Compose profile. The host activation
coordinator may sequence that command only after its quiesce, installation
identity and exact-account preflight, and before any GO child starts. It passes
the exact expected PAPER account and installed commit/image identity; the route
rechecks those facts against the running image and durable binding. The host
does not execute supplied Python, call `python -c`, import the execution
reconciler, manufacture a grant, or update the journal itself. The route verifies
the immutable installed receipt and its digest, plus the fence, account, image
and authority gates on every invocation. Receipt and command flags alone do
not prove a live host activation owner; a direct invocation under those exact
fenced conditions can only settle already durable commands and cannot activate
the system or authorize broker mutations.

The immutable installation receipt is initially private mode `0600` under the
host owner, while the signed CLI runs as UID/GID `10001` with a read-only
authority mount. Before this one route, the existing root-owned
`sentinel-authority-permissions` helper grants group `10001` read access
(`0640`) to **only the exact host-verified regular receipt file** beneath the
configured authority root. The host supplies its canonical relative path as
one validated environment value, not executable shell text. The helper refuses traversal,
symlinks, paths outside that root and a different basename; it never follows
links or edits receipt bytes. The route then rechecks the unchanged SHA-256 and
strict receipt contents from its read-only mount. The broker-capable CLI stays
UID `10001` and no other authority file becomes generally readable.

This is a safety observation of **already durable, exact-owned PAPER commands**.
It does not use the new executable to choose holdings, size a plan, create a
command, acquire financial GO, or interpret an old plan as current. Retained GO
admission itself stays broker-free and keeps its existing command fence. The
predecessor strategy book, account binding, takeover epoch, journal command
identity and economic terms, and source/authority history remain unchanged.

The stage takes the canonical execution writer lock in its ordinary backed
financial-write scope across the complete observation and settlement. The
entry and under-lock backup checks must both pass before any fill or command
state is committed. The recovery-only lock exemption is reserved for
nonfinancial observation and lease work and cannot cover this settlement.
It requires a current signed
`SAFETY_READ` observation authority for the exact PAPER deployment/account,
takeover epoch, endpoint and rollout. This authority deliberately tolerates
runtime/source drift but grants no submission. If it is unavailable or revoked,
the stage refuses; activation cannot manufacture a certificate to resolve the
deadlock. A dedicated typed recovery grant binds the verified installation,
control generation, account, existing command client keys and their durable
broker order IDs. A command without a durable broker order ID cannot obtain a
native-fill read through this pre-GO route; it remains recoverable under the
ordinary execution contract. A certified
generation-fenced execution wrapper freshly rechecks the durable kill, disabled
control, absent lease, account binding, signed safety authority and grant before
and after **each guarded broker read operation**. A complete observation can
contain several underlying HTTP GETs; a fence change during that read must be
caught by its after-read check before any journal advancement. It exposes only
identity, complete observation, exact-client-key lookup and native fills for
those exact owned orders. `submit`
and `cancel` are rejected structurally before transport, including when a
caller invokes the wrapper directly. No broker POST, DELETE or order retry is
part of this stage.

The certified production adapter does not claim complete recent terminal-order
history. Its terminal-history operation correctly reports PARTIAL. This route
uses its certified complete current account observation, exact client-key GETs
for the retained durable commands, and native owned-fill GETs. It rejects an
unknown Sentinel key present in that current observation before canonical
reconciliation. A closed broker-only key absent from that observation is not
enumerated, adopted, or used as evidence for this recovery. The route cannot
upgrade the adapter's terminal-history capability to make admission pass.

Use the existing execution reconciliation membrane and journal to validate
account-bound observation, exact order economics and client key, native fill
identity and cumulative quantity/cash, corporate actions, position and command
state. The route and guarded observation enforce the narrower scope *before*
passing a broker observation to canonical reconciliation: every observed
Sentinel client key must already name a durable command for this binding, and
exact-key and native-fill reads are limited to those commands. A broker-only
key or unrelated order is a refusal here, not permission to adopt or submit
it before source admission. The canonical reconciliation algorithm does not
need a second implementation or a changed command-transition rule. Preserve the
ordinary informational dual-account treatment of exact owned fills; do not use another
strategy book or treat Activity SSE cash and the same fill ledger as two trades.
Persist positive fills and the command transition only through canonical journal
operations. UNKNOWN, absent exact-key evidence, still-working orders, malformed
or corrected native fills, contradictory account or asset identity, incomplete
observations and foreign activity remain explicit refusals. Ordinary subsequent
plan preparation independently refuses unexplained cash; the pre-GO stage does
not assert a cash baseline or replace that check.
Diagnostic evidence may be retained under its existing rules; no refusal clears
or resets a command.

The stage succeeds only with a complete, clean reconciliation and no remaining
overlapping command. Re-read the control fence and exact binding before
returning. Retained GO then independently rechecks its unchanged fence and full
source/book/backup compatibility before appending its admission. Subsequent
ordinary dual PAPER preparation must independently re-observe the account,
reconcile cash and plan economics, and satisfy signed authority, restore and
activation gates. A successful pre-GO settlement alone is never financial
activation.

An exception, broker outage, lock conflict, fence change or deadline expiry
leaves automation disabled and killed, reports the exact stage and cause, and
stops the activation attempt. Retry only through the existing bounded
activation ownership/deadline rules with a fresh observation and unchanged
receipt/fence. Data-integrity refusals are terminal for that attempt; do not
translate them into a generic availability wait or an unbounded retry. A lost
acknowledgement after a journal commit is resolved by re-reading the same
command and native fill identities; replay must be idempotent. The existing
source-transition registry must pin every changed Sentinel Python source byte
to an exact reviewed predecessor and destination. The exact tested Git tree
and immutable image digest bind the host coordinator and its command wiring;
the source registry does not claim to pin host scripts. No economic strategy
contribution, backtest authority, or LIVE permission changes.

## Qualification and falsifiers

- Starting from the exact `ACKNOWLEDGED` CRL shape, replay the two native
  `partial_fill` events and terminal `fill` under one broker order. Require
  exactly three durable incremental fills, the correct final quantity/cash,
  `FILLED` command, zero overlapping commands, unchanged immutable identity and
  GO admission afterward. Repeat the stage and prove no additional journal
  effect or broker mutation.
- Mutate the guard to allow `submit` or `cancel`, or remove any one of disabled,
  kill, absent-lease, exact account, signed `SAFETY_READ`, current control
  generation, certified transport or writer-lock checks. The corresponding
  negative test must fail before transport or journal advancement.
- Supply an unknown/foreign client key, conflicting broker order or asset,
  missing exact lookup, incomplete observation, working remainder, malformed
  or revised native fill, correction/bust and stale takeover. Each must leave
  GO refused and the original command recoverable; no branch may label the
  broker outcome FAILED from absence alone. A separate cash-mismatch case must
  pass any exact fill settlement but fail the subsequent plan preparation,
  leaving activation fenced.
- Stop after positive fill persistence but before the host receives success;
  retry from the same installed receipt and prove idempotent settlement and
  retained GO. Also test broker/DB failure and original deadline expiry with
  the durable fence intact.
- Drive the real activation coordinator and engine handlers against an isolated
  PostgreSQL database and simulated GET-only broker. Assert the ordered stages
  are fenced recovery, retained GO, dual plan preparation, coordinated restore
  and only then kill release. Test a clean journal skips broker recovery, and a
  failed recovery cannot reach GO or any activation authority mutation.
- Assert the host calls only the digest-qualified authorized CLI route, with
  exact installed commit/image/account arguments, and cannot use a `python -c`
  execution shortcut. A direct CLI call with a missing or altered receipt,
  wrong account, altered image, LIVE URL or stale control generation must refuse.
- Start with a `0600` immutable receipt owned by another UID. Prove the
  one-file permissions helper grants UID/GID `10001` read access without
  changing its bytes or SHA. Traversal, symlink, wrong basename and a path
  outside the authority root must refuse before any permission change; the
  signed CLI itself must remain non-root.
- Mutation-test the exact source-transition profile and command-overlap fence;
  changed/unreviewed source bytes or a skipped/failed preflight must still make
  retained admission refuse. Keep the focused PR checks and protected exact-head
  CI separate from real installation and activation evidence.
