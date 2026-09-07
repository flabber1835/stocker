# SEP negative-space retirement contract

Status: adopted for PR #330.

A published SEP row may be retired automatically only when current vendor authority proves the row is absent and the retirement preserves the canonical economic interpretation of the surviving series.

## Source authority

Repeated cursor-paginated SEP traversals establish stability, not completeness. They cannot authorize deletion by themselves. Every production retirement must be corroborated by a fresh Nasdaq Data Link bounded SEP Exporter snapshot for the exact reconciliation partition. The exporter evidence must be durable in the retirement plan, and the normalized export key/value proof must equal the source proof that detected the local surplus. Any disagreement refuses retirement.

Injected/replay sources remain deterministic test seams and do not gain production deletion authority.

## Economic preservation

A disappearing row may carry no effective split event and no dividend entitlement. Removing it must also preserve the next surviving split edge under the same canonical split semantics used by ingest.

For a surviving effective split of 1.0, bridge price evidence inside the canonical no-event band remains no-event; material bridge evidence refuses retirement. For a surviving non-unit effective split, the bridge is resolved through the canonical explicit-split precision rules, including the exact mill-rounded price interval for small splits. `SPLIT_UNRESOLVED`, a changed resolved multiplier, or contradictory bridge evidence refuses retirement.

## Publication

The exact retirement keys, bounded-export authority evidence, normalized source digests, and key digest are persisted before mutation. Exact deletion and publication remain one transaction. Reconciliation re-runs after publication before any cursor/readiness authority is granted.
