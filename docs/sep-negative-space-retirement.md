# SEP negative-space retirement contract

Status: adopted for PR #330.

A published SEP row may be retired automatically only when current vendor authority proves the row is absent and the retirement preserves the canonical economic interpretation of the surviving series.

## Source authority

Repeated cursor-paginated SEP traversals establish stability, not completeness. They cannot authorize deletion by themselves. Every production retirement must be corroborated by complete Nasdaq Data Link SEP Exporter authority covering the exact reconciliation partition. Large partitions may be assembled from bounded Exporter subpartitions only when every part reports the same vendor `last_refreshed_time`; crossing a vendor refresh refuses deletion. Exported rows are spooled to disk for replay so annual reconciliation remains bounded in Python memory. The complete authority evidence must be durable in the retirement plan, and the normalized export key/value proof must equal the source proof that detected the local surplus. Any disagreement refuses retirement.

The destructive guard validates complete authority again at the mutation boundary. SEP evidence must identify the complete composite Exporter authority, ACTIONS evidence must identify a fresh complete Exporter snapshot, and the SEP evidence must carry the exact frozen observation ceiling. An injected or paginated source cannot satisfy this mutation contract.

A destructive retirement also requires fresh complete ACTIONS authority. Immediately before deletion, Sentinel forces complete ACTIONS reconciliation, obtains a second fresh complete ACTIONS Exporter snapshot through the published market frontier, and requires that canonical row set to equal the active published ACTIONS projection. The snapshot evidence and bound publication version are persisted in the retirement plan. A cadence cursor alone cannot authorize deletion.

Injected/replay sources remain deterministic test seams and do not gain production deletion authority.

## Economic preservation

A disappearing row may carry no effective split event and no dividend entitlement. The guard checks both the values currently stored on the bar and every current canonical ACTIONS dividend/split row, including dividend rows whose amount is unusable or unresolved. Removing an event-free row must also preserve the next surviving split edge under the same canonical split semantics used by ingest.

For a surviving effective split of 1.0, bridge price evidence inside the canonical no-event band remains no-event; material bridge evidence refuses retirement. For a surviving non-unit effective split, the bridge is resolved through the canonical explicit-split precision rules, including the exact mill-rounded price interval for small splits. If retirement leaves no surviving predecessor, a non-unit successor split is refused because canonical predecessor-derived normalization can no longer establish that edge. `SPLIT_UNRESOLVED`, a changed resolved multiplier, or contradictory bridge evidence refuses retirement.

## Observation boundary

A production reconciliation operation uses one explicit source-observation date for SEP CDC and complete SEP proofs. Complete SEP negative-space authority must come from a vendor `last_refreshed_time` whose timestamp is on or before the captured mismatch observation instant. That instant must fall on the frozen source-observation date. The durable Exporter evidence records both `observation_ceiling` and `source_observation_boundary`. A later vendor refresh refuses retirement before mutation.

A SEP cursor newer than the frozen observation date refuses the pass. Equal cursors can be re-observed explicitly. Recent-window proof reuses the established SEP observation ceiling.

## Publication

The exact retirement keys, complete SEP Exporter authority, fresh ACTIONS authority, normalized source digests, and key digest are persisted before mutation. The `sep_source_retirement` publication appends its exact keys as tombstones. The physical bars and split-repair children retain their original contents and generation ownership. SEP visibility excludes a key only when its retirement publication is newer than the bar generation's first publication. Republishing an existing ingest run cannot revive its retired rows. A later published bar generation restores visibility. An identical vendor reappearance must still move the row to the new ingest generation; value equality cannot preserve retired ownership. Ingest predecessor lookup excludes published tombstoned rows while retaining the existing ability to read unpublished rows from an active chunked ingest. Unpublished or rolled-back retirement evidence has no effect.

SPY total-return, defensive SFP prices, and universe snapshots use generation-only visibility (`sep_retirements=False`); SEP tombstones apply only to equity bars. Callers identify the relation explicitly, independently of SQL alias spelling.

Every concrete retirement mutation entry point requires the validated SEP and ACTIONS capability, including calls with absent evidence. Injected source tests may replace the mutation with a test double; they cannot publish a real retirement. Publication validates the capability before making tombstones visible.

Reconciliation re-runs after publication before any cursor or readiness authority is granted.
