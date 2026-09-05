# System adversarial certification

Status: implementation in progress. This document defines the claim before the
test suite is allowed to make it.

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
| Broker failure convergence | Scheduled contract faults and repeated recovery | Existing, extend |
| Financial invariants under generated sequences | Reproducible seeds and invariant checks after every transition | New gate: seeds 0-7, ten plans each |
| Point-in-time causality | Publication/version and decision/effective-time provenance checks | Planned gate |
| Research/production parity | Frozen input, exact first-divergence artifact | Planned gate |
| Historical event behavior | Reviewed event fixtures with immutable expected economics | Controller checkpoints gated; full Wealth Core needs NAS |
| Test sensitivity | Deliberate guard mutations killed by named tests | New gate: three reviewed mutants |
| Runtime/deployment identity | Exact SHA, lock hashes, image digest, schema/semantic epochs | Existing gate |
| Broker shadow agreement | Independent expected and observed ledgers with unexplained-divergence alert | Paper-only gate |

`Existing` does not mean complete. The coverage map must name the exact test and
the exact claim; nearby tests do not inherit authority.

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

## Mutation tranche

The pinned test image creates disposable source overlays and changes three
load-bearing production rules: journal ordering around submit, working-order
delta arithmetic, and the ramp confirmation comparison. Each mutant has one
named falsifier test and must produce a normal pytest assertion failure. A test
collection error, timeout, skip, or harness error is not a killed mutant. The
machine-readable report retains source and mutant hashes plus the failure tail.

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

## Safety boundary

This project may create tests, deterministic simulators, fixtures, evidence
tools, and CI workflows. It may fix implementation defects proved by those
tests when the fix preserves documented economics. It must stop for explicit
approval before changing strategy decisions, changing Sentinel thresholds,
weakening a fail-closed guard, merging, publishing a deployable image, activating
paper transport, or contacting a live broker.
