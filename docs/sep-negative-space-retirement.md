# SEP negative-space retirement contract

Status: adopted for PR #330.

A published SEP row may be retired automatically only when current vendor authority proves the row is absent and the retirement preserves the canonical economic interpretation of the surviving series.

## Source authority

Repeated cursor-paginated SEP traversals establish stability, not completeness. They cannot authorize deletion by themselves. Every production retirement must be corroborated by complete Nasdaq Data Link SEP Exporter authority covering the exact reconciliation partition. Large partitions may be assembled from bounded Exporter subpartitions only when every part reports the same vendor `last_refreshed_time`; crossing a vendor refresh refuses deletion. Exported rows are spooled to disk for replay so annual reconciliation remains bounded in Python memory. The complete authority evidence must be durable in the retirement plan, and the normalized export key/value proof must equal the source proof that detected the local surplus. Any disagreement refuses retirement.

A destructive retirement also requires fresh complete ACTIONS authority. Immediately before deletion, Sentinel forces complete ACTIONS reconciliation, obtains a second fresh complete ACTIONS Exporter snapshot through the published market frontier, and requires that canonical row set to equal the active published ACTIONS projection. The snapshot evidence and bound publication version are persisted in the retirement plan. A cadence cursor alone cannot authorize deletion.

Injected/replay sources remain deterministic test seams and do not gain production deletion authority.

## Economic preservation

A disappearing row may carry no effective split event and no dividend entitlement. The guard checks both the values currently stored on the bar and every current canonical ACTIONS dividend/split row, including dividend rows whose amount is unusable or unresolved. Removing an event-free row must also preserve the next surviving split edge under the same canonical split semantics used by ingest.

For a surviving effective split of 1.0, bridge price evidence inside the canonical no-event band remains no-event; material bridge evidence refuses retirement. For a surviving non-unit effective split, the bridge is resolved through the canonical explicit-split precision rules, including the exact mill-rounded price interval for small splits. If retirement leaves no surviving predecessor, a non-unit successor split is refused because canonical predecessor-derived normalization can no longer establish that edge. `SPLIT_UNRESOLVED`, a changed resolved multiplier, or contradictory bridge evidence refuses retirement.

## Observation boundary

A production reconciliation operation uses one explicit source-observation date for SEP CDC and complete SEP proofs. If an earlier phase establishes a stronger SEP cursor before a later phase consumes the frozen boundary, the stronger durable cursor satisfies that older boundary without another source traversal. Recent-window proof reuses the established SEP observation ceiling.

## Publication

The exact retirement keys, complete SEP Exporter authority, fresh ACTIONS authority, normalized source digests, and key digest are persisted before mutation. Exact deletion and publication remain one transaction. Reconciliation re-runs after publication before any cursor/readiness authority is granted.
