# Rolling activation index proof after legacy retirement

The November 11 signed release passed the two database index checks against
publication 19. The November 12 installation retained the same verifier code
and reached publication 20. Its activation refused both checks. The live
read-only plans use the expected primary indexes for candidate references and
normalized blocks. They also scan the legacy snapshot-bars branch of the
registered UNION view. That relation has zero main-fork bytes and zero rows.
The earlier activation evidence records the checks, without either plan tree.

Keep the actual EXPLAIN queries and normal PostgreSQL planner configuration.
In the existing read-only transaction and authenticated publication pin, accept
a sequential scan of the exact legacy bars branch only if both shared
relations are also present and all other scans use their reviewed indexes.
Require zero physical heap bytes and an independent row absence check in the
same snapshot. A legacy-only, nonempty legacy, unreviewed index, missing
shared branch or sequential shared scan still refuses. The shared candidate
and its immutable layout are already validated before these measurements.
Do not force index selection, change query results or modify the database.

Exercise both production query shapes on a real sealed shared candidate, with
normal PostgreSQL planning. Prove that a populated unrelated legacy candidate
with the same sequential plan still fails, and retain the existing index and
shared-scan falsifiers. The executable handover retains exact historical
inventories, including the certified source that stopped at this gate.
No data, strategy, account, plan, journal or transport authority changes.
