# PAPER PostgreSQL planning for absent candidate guards

The October 26 recovery found normalized-reference INSERTs repeatedly waiting
on old bar-history reads. The unchanged trigger verifies that no legacy rows
belong to the new shared candidate. Its parameterized EXISTS query can acquire
a cached generic sequential-scan plan: average existing-candidate selectivity
predicts an early match, while a genuinely new candidate has no match at all.
Each reference can therefore scan the complete retained legacy table.

Read-only, non-executing EXPLAIN on the actual primary reproduced the difference:
force_generic_plan selected a sequential scan (estimated 1,688,774 matching
rows), while force_custom_plan selected the existing candidate-prefix index
and estimated one row for the absent UUID. Neither EXPLAIN executed the scan.

For this inspected owner PAPER primary, select PostgreSQL 16's supported
`plan_cache_mode=force_custom_plan` through ALTER SYSTEM and configuration reload.
This physical planner policy is persistent until separately reviewed replacement
or rollback. Preserve every SQL predicate, integrity guard, source/price/book
identity, transaction, job deadline, lease, financial control and archive setting.
Keep the same PostgreSQL process, image, command and volume. No restart or
financial-state mutation is part of this operation.

Choose a configuration reload here to preserve the already-running owned
transaction. Replacing its connection options would require discarding its
uncommitted normalization work. A later reviewed guard-specific implementation
may narrow the policy; reverting automatically would restore the same generic
absence-plan problem on a future daily candidate.

Before applying, require the exact primary container/start/system identity,
archive-on state, default auto setting without a role/database override and a
still-valid owned preparation job. Retain both plans and prove the custom query
returns true for an existing legacy candidate and false for an absent UUID in
a read-only transaction. The generic sequential plan is the work-bound
falsifier. Record the original value and config source, apply the supported
setting, reload, and independently reread its effective value and unchanged
physical/financial subject. Preserve failure evidence rather than relaxing a
guard or clock. Rollback resets this setting and reloads configuration.

Per-execution planning adds planning work; observe leadership and publication
afterward. This is not new source admission, financial verification or trading
readiness. The exact-image restore and normal current-source/book, plan,
reconciliation and application handoff gates remain mandatory.

PostgreSQL documents generic versus custom plans and the setting in its
[query-planning configuration](https://www.postgresql.org/docs/16/runtime-config-query.html).
