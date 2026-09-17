# Automatic share-unit reconciliation

Decision, 2026-09-17: automated operation and automatic recovery are required.
This replaces the universal affirmative pre-open certificate requirement in
the execution/deployment contracts. It is a paper execution policy change,
not live-money authorization or a change to Wealth Core or Sentinel decisions.

## Ordinary operation

Absence of a pre-open certificate means no additional event evidence is
available; it is not a NO_EVENT attestation and does not block transport.
Published action history, durable commands, and fresh complete broker evidence
remain the inputs. An existing certificate remains optional evidence and must
still pass its exact plan/session/content checks before use.

Execution always retains the canonical action/opening-price target projection.
V5 new entries use their existing opening dollar reservations and opening
prices. Held quantities use evidenced scalar transformations. No daily weight
rebalance, broker-derived shadow, synthetic paper split, or broker-native close
is introduced. Retried commands retain their identities and quantities.
The existing source-identity bundle includes the new execution restriction
module; deployment identity checks continue to bind these execution semantics.

This accepts residual risk from a corporate action that neither the available
source nor broker observations reveal in time. Equal quantities do not prove
absence. The former completeness guarantee was unavailable operationally;
we do not manufacture it from repeated empty API responses.

## Restrictions and recovery

Known unsupported/non-scalar actions restrict their intersecting permanent
security identities. A known scalar action for which the broker still reports
the unchanged command-derived quantity is an unresolved corporate-action
position, not a reason to buy compensating shares. Record and defer that
security. Reconciliation continues recovering orders for all securities.

Restrictions are derived again on each invocation from current published
actions and broker observations. They require no acknowledgement and clear
when the inconsistency resolves or the affected economic position disappears.
The original observations, historical mismatches, and projections remain
immutable. Historical informational-paper mismatches remain reporting evidence;
they do not permanently prohibit future trading after current state is usable.

The executor checks restrictions on its own reconciliation before command
reservation. Unaffected reductions proceed. A deferred required reduction
still prevents dependent increases from spending proceeds that do not exist.
Existing cash-only account checks apply to every purchase. Foreign orders,
unexplained ownership, inconsistent account observations and unresolved command
identity retain their existing safety handling. No generic ignore-error path
is introduced.

Preparation and read-only recovery do not require an absent certificate.
Scoped restrictions are incomplete execution, never full convergence or
verified paper performance. Automation re-observes/retries within its existing
bounded schedule; an expired plan is superseded without late opening buys.
Recovery distinguishes transport-ready evidence from clean convergence in its
typed callback result. A transport observation may authorize retry or
supersession of a resolved plan; only a clean observation may declare success
or populate the persisted last-clean reconciliation identity. The current
observation and restrictions remain in cycle diagnostics.

## Validation

Test ordinary certificate-free buys/holds and recovery, split-aware quantities,
unchanged paper split positions, unrelated execution during a restriction,
automatic clearing, funding dependencies, V5 projection/restart identity,
historical mismatch reporting without a permanent latch, and malformed optional
evidence. Falsify the per-security mutation restriction by removing it and
observing the corresponding transport test fail.

Sources: [Alpaca corporate actions](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions),
[announcement timing](https://docs.alpaca.markets/us/reference/corporateactions-1),
[paper limitations confirmed July 2026](https://forum.alpaca.markets/t/corporate-actions-handeling/19325).
