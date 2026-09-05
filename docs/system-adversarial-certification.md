# System adversarial certification

Status: offline baseline accepted; adversarial depth is expanded by reviewed
falsifiers without changing the certified claim.

## Purpose

Unit coverage is not authority for an assembled financial system. This layer
certifies economic sequences across the production Wealth Core transition,
Sentinel controller, durable execution journal, broker contract, reconciliation,
and restart boundaries. It adds evidence; it does not change strategy economics,
controller thresholds, execution timing, or deployment authority.

The authoritative direction remains one way:

```text
PIT publication -> Wealth Core shadow -> Sentinel scalar exposure
                -> immutable plan -> execution -> broker observation
                -> reconciliation and accounting
```

Broker state never feeds Wealth Core decisions. Research code is a differential
oracle only after its timing and state semantics have been proved equivalent to
the production transition.

## Claims and evidence classes

| Claim | Required evidence | Initial status |
| --- | --- | --- |
| Deterministic economic transition | Repeat run and restart-equivalent ledger | Existing, extend |
| No duplicate order after ambiguous submission | Real process death after broker acceptance; exact-key recovery | New gate |
| No lost or duplicated fill | Real process death after fill observation and before local persistence | New gate |
| Transactional strategy-state cursor | PostgreSQL rollback and resume | Existing gate |
| Broker failure convergence | Combined scheduled contract faults, process death, repeated reconnect and exact replay | Gated offline |
| Financial invariants under generated sequences | Reproducible seeds and invariant checks after every transition | Gated: base campaign plus restart soak |
| Command/runtime state-machine conformance | Independent transition/permission model, generated paths, durable restart replay | Gated |
| Point-in-time causality | Publication/version and decision/effective-time provenance checks | Planned gate |
| Research/production parity | Frozen input, exact first-divergence artifact | Planned gate |
| Historical event behavior | Reviewed event fixtures with immutable expected economics | Controller checkpoints gated; full Wealth Core needs NAS |
| Test sensitivity | Deliberate guard mutations killed by named tests | Gated: eleven reviewed mutants |
| Runtime/deployment identity | Exact SHA, lock hashes, image digest, schema/semantic epochs | Existing gate |
| Broker shadow agreement | Independent expected and observed ledgers with unexplained-divergence alert | Paper-only gate |

`Existing` does not mean complete. The coverage map must name the exact test and
the exact claim; nearby tests do not inherit authority.

The assembled-day gate begins with a known Wealth Core book and a published
production session, advances the canonical kernel, serializes and restores its
state, constructs the immutable next-open plan, submits through the typed broker
port, fills, reconciles, reconnects PostgreSQL, and proves the repeated session
submits nothing. This closes the stale `test_system_simulation` limitation that
covered the controller/execution half without wiring the production Wealth Core
transition into the same scenario.

## Process-death tranche

Logical exceptions prove transaction rollback, but they do not prove that a
kernel, connection, advisory lock, and in-memory broker client all disappear
together. The first tranche therefore uses a real child process and sends it
`SIGKILL` at two load-bearing boundaries:

1. The broker durably accepts an order after `SEND_PENDING` commits, then the
   process dies before the acknowledgement can be journaled.
2. A fresh process observes the resulting fill, then dies immediately before
   the `FILLED` command transition can be persisted.

Recovery must use the original deterministic client key, produce one broker
order and one economic fill, converge the journal to `FILLED`, and make a second
session a no-op. The broker in this test is a durable test double implementing
the typed broker contract. It is not evidence about Alpaca transport semantics.

This is also the falsifier for write ordering: moving the durable
`SEND_PENDING` transition after transport makes the first post-death assertion
fail because there is no recoverable command identity.

## Generated economic-sequence tranche

The initial campaign runs eight stable seeds twice. Each seed produces ten
three-security plans and injects broker outages, accept-then-timeout ambiguity,
rejections, partial fills, complete fills, and repeated reconciliation. After
every economically relevant transition it checks:

- broker order identity is unique and maps to one durable command;
- every fill maps to that order and command and cannot exceed its quantity;
- command filled quantity stays within `[0, quantity]`, with exact equality at
  `FILLED`;
- long-only positions and cash never become negative;
- at the simulator's fixed execution price, `cash + holdings` remains equal to
  initial equity; and
- a client key crosses the submit boundary exactly once.

The second run must produce an identical normalized command, order, position,
fill, and cash ledger. Seeds are fixed because reproducibility is part of the
claim. Expanding the seed set is a reviewed coverage change, not a retry tactic.

The restart soak adds four stable seeds of 24 plans each. Every plan crosses
three fresh PostgreSQL connections before settlement, may encounter an outage
or accept-then-timeout ambiguity, receives partial and final fills, replays fill
evidence in original and reverse order with duplicates, reconciles repeatedly,
then crosses one more connection boundary and proves the settled plan is a
submit-free no-op. The whole campaign runs twice and requires an identical
ledger.

## Combined fault-injection tranche

The combined campaign drives one durable account through a fixed schedule of
submit outage, accept-then-timeout, never-received ambiguity, explicit broker
rejection, cancel outage, an acknowledged-but-ignored cancel, incomplete and
truncated observations, partial and final fills, cancel/fill races, duplicate
and reverse-ordered fill delivery, and fresh PostgreSQL connections.
These faults overlap across immutable plans instead of being certified only as
isolated examples. Every retry retains the original economic identity, every
transition rechecks the financial invariants, and each seed is run twice with
an exact normalized-ledger comparison.

An additional restart guard persists an `UNKNOWN` command, closes the database
connection, reloads it, and proves that a second command for the same permanent
security identity is refused until complete broker evidence resolves the first.
The existing process-death tranche supplies real `SIGKILL` at both sides of the
broker/persistence ambiguity window; its evidence is included in this layer.

This is offline software fault injection. It does not claim a NAS host reboot,
Docker-daemon death, disk-full or PostgreSQL WAL-pressure recovery, network
partition against Alpaca, or broker event-stream behavior. Those destructive or
external conditions require an isolated NAS/PAPER campaign with host control
and are recorded as external evidence, never inferred from CI.

## Model-based state-machine tranche

The command lifecycle and runtime permission kernel are checked against an
independent test model expressed only in public state and action names. The
model does not import the production transition or permission tables. It
exhaustively compares every command-state pair and every runtime-state/action
pair, requiring every forbidden operation to raise through the public guard.

Deterministic generated campaigns then interleave legal and illegal command
transitions. They prove that rejected edges leave the immutable command
unchanged, fills are monotonic and bounded by authorised quantity, terminal
states are absorbing, in-flight states continue to block overlap, and a new
lifecycle receives a new command identity. The fixed seeds and complete trace
are replayable evidence.

A PostgreSQL edge-cover campaign constructs the shortest reachable path to
every legal command edge, including repeated partial fills and cancel/fill
races. It persists each transition, closes and reopens the database connection,
reloads the command, and compares both current state and append-only history to
the independent model. This is state-machine certification of the command and
runtime kernels; the assembled executor/reconciliation economics remain covered
by the process-death and generated economic-sequence tranches.

## Mutation tranche

The pinned test image creates disposable source overlays and changes eleven
load-bearing production rules. The reviewed set covers journal ordering around
submit, working-order delta arithmetic, ramp confirmation, broker-position gap
direction, corporate-action aging, same-session PIT metadata, next-open timing,
cash residual arithmetic, stable Alpaca asset identity, and illegal state-edge
enforcement, plus the rule that an unresolved `UNKNOWN` command blocks a second
command for the same security after restart. Each mutant has one
named falsifier test and must produce a normal pytest assertion failure. A test
collection error, timeout, skip, or harness error is not a killed mutant. The
machine-readable report retains source and mutant hashes plus the failure tail.

## PAPER ledger certificate tranche

`tools/sentinel_paper_ledger_certify.py` compares two independently produced,
canonical and sanitized ledgers: Sentinel's expected post-reconciliation book
and the complete Alpaca PAPER observation. It performs no network or broker
operation. Account, plan, client-key, security, and fill identities enter only
as SHA-256 subjects; raw account or broker identifiers are structurally
refused.

The comparison requires the same commit, account subject, plan subject,
decision session and effective session; exact long-only positions, orders and
fills, including average prices; exact corporate-action evidence; and cash and
equity within one cent. Incomplete, duplicate, noncanonical or time-regressed
evidence refuses certification. A divergence report contains only hashed
subjects and component names. It always records
`CERTIFIED_SHADOW_ONLY` as performance authority, so a matching PAPER book does
not turn broker P/L into strategy truth.

## Historical tranche

Named controller checkpoints cover the global financial crisis, 2010 flash
crash, August 2015 shock, February and Q4 2018, March 2020, the meme-stock
period, and the 2022 bear market. Each is replayed in sequence from the start of
the 5,032-session frozen oracle and checks exposure plus durable session state.
The existing every-session differential remains the stronger equality test.

These offline checkpoints certify the controller only. Full Wealth Core
universe, selections, orders, holdings, cash, and terminal-security economics
require the authoritative Sharadar corpus on the NAS. CI must report that layer
as outstanding; it may not infer a pass from the controller tape.

## Reproducibility and artifacts

Adversarial campaigns are deterministic. Every generated case has a stable seed
and records the tested commit, source-tree hash, dependency-lock hash, test
manifest hash, scenario name, seed, result, and first failing transition. A
failure is investigated from that exact artifact; rerunning until green is not
certification.

CI runs inside the pinned Sentinel test image with networking disabled. No skip
is a pass. Local runs without PostgreSQL or Docker are diagnostic only and must
be reported separately from the authoritative exact-head and synthetic-merge
jobs.

The CI report is an `offline_ci_software` certificate. It always carries four
explicit external statuses: authoritative Sharadar full history, historical
metadata causality, the NAS resource envelope, and the Alpaca expected/observed
paper ledger. None can become PASS from an offline CI result.

## Safety boundary

This project may create tests, deterministic simulators, fixtures, evidence
tools, and CI workflows. It may fix implementation defects proved by those
tests when the fix preserves documented economics. It must stop for explicit
approval before changing strategy decisions, changing Sentinel thresholds,
weakening a fail-closed guard, merging, publishing a deployable image, activating
paper transport, or contacting a live broker.
