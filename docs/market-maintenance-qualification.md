# Market data acquisition and private staging retention

An acquisition unit inherits the earlier of its enclosing monotonic deadline
and the source job's remaining budget. Alpaca and OpenFIGI check that deadline
before pacing, HTTP attempts, retry delays, and accepting the response.
An asynchronous HTTP cancellation scope measures the complete attempt, including
headers and a slowly streaming body. Each attempt also retains the socket
inactivity timeout. The synchronous producer owns and closes its connection pool.
Rate limits belong to the provider that issued them. The operational source
does not consult cooldowns recorded by a retired provider.

Historical replay can read an explicitly selected local capture and its
verified immutable components. Removed network clients, exporter endpoints,
credential variables and remote retries have no part in replay. A missing
capture fails immediately. Previously issued receipt hashes and archive
format identifiers retain their original meaning. Historical ZIP replay reads
the bounded content and verifies its companion digest. It never prunes,
repairs or rewrites retained files. Replaying a recorded export
does not establish a new remote observation or authorize a current publication.

For splits the normalized ticker, ex-date and exact new/old ratio describe the
economic event. Provider IDs identify its observations. Equal observations
yield one split with the lexicographically least ID and the sorted distinct IDs
when multiple records exist. Corroboration must agree on both the terms and the
observations across pages. Conflicting ratios refuse acquisition. A malformed
record alone follows the documented structural reset policy.

Retention probes the existing fair class order. A private acquisition pass
owns a single bounded transaction and serializes maintenance progress with
other passes. It obtains nonwaiting table locks that freeze the acquisition
parts and every input to the canonical pin predicate, including job state,
lineage, bindings, linked payloads and publication. The database verifies
that ownership before deleting parts or prices and independently checks pins.
Old bindings remain evidence after disposal. Each new binding must reference
an existing part. A previously unpinned price payload must still have its full
declared row count. New captures and already-pinned parts avoid this orphan
count. A writer queued behind disposal rechecks the committed result.
Acquisition cleanup preserves checkpoint authentication and checks backup
authority before disposal. Account and corpus advisory locks continue to
protect retirement of published history. Busy pin writers cause a retry.
