# Closing-cycle readiness handoff

Decision: 2026-10-28, before implementation. The installed close exposed a
publication-pin wait reported as infrastructure failure, an overdue alert while
an existing cycle waited for the financial writer, and a current source with no
matching display verdict. A recovered same-session trial also collided with an
immutable record belonging to an earlier cycle.

## Preserve the actual wait and financial boundaries

REFRESH may classify only a native `CorpusLockUnavailable`, including its
explicit reviewed authority wrapper, as closing-data availability. Use the
caller's exact cycle identity even if the preliminary authority read failed.
The independent existing live-publisher proof must still name that decision,
original deadline and actual lock owner. Missing, ambiguous or unreadable proof,
unrelated exceptions and other phases retain their ordinary refusal/alert.

An already-existing current-generation cycle is a read, not a request to create
another cycle. Read it without the financial writer lock, requiring the live
leader, exact immutable spec and unchanged current control binding. New cycles,
generation replacement, transitions, preparation and broker operations keep their
existing ownership, replay, time and fresh-authority guards. The watchdog's
deadline is unchanged; do not hide a genuinely overdue worker.

The shadow attestation already measures the full current-input report under its
pinned publication. Persist a copied, publication-bound readiness snapshot in
the same final transaction as that attestation. Do not run another full scan,
use a verdict from another publication, change the attestation's original report
hash or let the auxiliary INSERT commit financial state early. A page with no
matching verdict says current-publication verification is pending; it must never
instruct an operator to run a legacy repair command or claim the inputs failed.
Slot visibility continues to require the ordinary current financial proof.

### Bounded post-publication display handoff

Decision: 2026-10-30, before implementation. After the real October 30 data
publication committed, its readiness snapshot was correctly still absent while
the signed publisher was checking strategy. The feed's unsupported pending
warning became red despite the existing finite attestation proof. Represent
that interval as pending only when the exact current publication and target
session captured under the canonical source pin match the independently
authenticated SHADOW_ATTESTATION proof and a fresh owned shadow worker.

The canonical read-only status reader may optionally return the publication
identity it already owns; retain its existing two-value default and perform no
second assessment or corpus scan. Preserve that identity as structured display
evidence. Only a genuinely missing measurement is eligible: never relabel a
measured negative verdict, unreadable source, unknown lag or mismatched/stale
publication. Bind the pending display to the minimum original producer/worker
deadline, preserve original observation times and withdraw it on lost proof or
expiry. No check is marked passed and readiness remains unearned; execution and
installation still require their existing affirmative measured evidence.

The human health banner may describe this proven, on-time verification as
healthy work while its separate plan/readiness display remains pending. A
PUBLISHED source job, a generic RUNNING string, or an old signed result alone
does not earn that classification. The actual publisher continues to save the
real readiness snapshot with its final attestation transaction.

Existing authenticated verification receipts predate the structured publication
fields. A read-only compatibility adapter may recover the session/publication
only from the exact existing SHADOW_ATTESTATION row encoding, with matching
dated value and fixed producer-description prefix, after the ordinary receipt
authentication and live-worker/deadline checks. Unknown encodings refuse the
pending display. This does not interpret arbitrary logs or error text, create a
new proof, or move observation clocks. New producers emit the structured fields
directly; an HTTP update must not start another financial observer merely to
upgrade a cached receipt's display shape.

## Immutable trial attempts and one daily financial projection

New v3 verification records use
`trial-account:v2:verification-attempt:v1:<effective-session>:<cycle-id>`. This separate namespace keeps an older date-only reader from double-counting
new attempts. The v3 financial evidence format and checks are unchanged. The exact new
child namespace inherits the installed trial-account broker-only classification.
Account snapshots still use exact observation-ID keys. This preserves the installed
operational DDL/catalog contract and avoids an unnecessary schema migration.
Unknown namespaces keep their existing economic-input treatment.
Existing date-only rows
remain immutable and readable for their exact embedded cycle. Every terminal
attempt keeps its own failed/superseded/successful evidence. The recording writer
may recover a missing non-success attempt for this exact session only from
authenticated native lineage plus a positive absence of transport events and
commands. It appends a failed record, never a successful economic result. Other
missing callbacks remain explicit debt. No account, cycle, plan, cash, fill or
old verdict is reset.

Readers authenticate all retained attempt records and their existing financial
references. The daily/cumulative projection may select at most one successful
economic cycle per session. Other same-session attempts must be positively
unsent, terminal, and bound to the same account/deployment/takeover/decision.
Multiple successes, another transported attempt, foreign bindings, changed
cycle identities and missing/corrupt evidence refuse projection. With no success,
retain a deterministic failed daily result while exposing all attempt records
through the attempt reader. A successful replacement still earns every existing
close/fill/cash check; historical failure is never promoted into success.

## Qualification and delivery

Use isolated PostgreSQL and simulated broker boundaries. Join the real early
authority wrapper to the closing-wait classifier, hold the real financial writer
while a known retry becomes due and read scheduler health, commit/roll back a
shadow attestation with its exact readiness snapshot, and record/restart multiple
same-session trial attempts. Exercise absent/foreign/tampered proof, changed spec,
new-cycle contention, premature commit, second success, transported predecessor,
cross-account and missing-callback falsifiers. Keep the original deadlines,
financial baselines, canonical strategy and all broker/UNKNOWN guards.

Deliver a reviewed PR from current main. Qualification does not install or
activate this candidate, mutate the running paper account, or touch the backtest.
