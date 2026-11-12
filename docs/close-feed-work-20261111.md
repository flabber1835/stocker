# November 11 close feed work

The November 11 close fetched 1,703,793 Alpaca SIP rows across 15 monthly
windows and inserted all of them. Fetch through durable part storage took
37m48s, compared with 20m38s for 1,703,613 rows the previous day. The passive
trace timed the whole operation and cannot resolve which portion was transport
latency, retries, decoding, price pairing or durable storage. Measure these
phases separately with per-part aggregate counts and times. Transport counts
requests, response bytes and rate limits and times pacing, HTTP/read, decode
and retry backoff. Record a distinct observation only after the publication
commit returns. The signed in-transaction publication time retains its
existing meaning and receipt format.

The current raw and split-adjusted reads bind the target `asof`, selected
universe, action dispositions and identities. A different close changes this
generation. The transport supplies bytes and request evidence, and provides
no verified historical revision watermark or whole-window unchanged proof.
November 11 even returned different row counts in every exactly matching
historical monthly range. Keep source reobservation, full daily acquisition,
same-generation resume and exact content deduplication. A future proposal to
skip downloads needs an authoritative correction boundary, complete key and
economic equivalence under universe/action changes, and an explicit full-read
fallback. The bounded daily strategy continuity contract still compares the
new authenticated data with its predecessor and does not authorize assuming
unchanged provider bytes.

The November 11 publication spent 4m40s in its atomic phase. The predecessor
query for a single action and security was active in 45 of 56 database
samples. Collect action-day/security coordinates and traverse the existing
logical bar layout once in session order. A last observation per requested
security yields the actual strictly earlier bar, including across gaps. Keep
the candidate and corpus pinned and preserve the original day-local security
ordering, prices, absent predecessors and immutable receipt contents. Stream
the prices in bounded batches. Work in memory is proportional to requested
securities and coordinates, with no history-sized application cache. No schema
or publication transaction boundary changes.

Qualification compares the batched reads with the existing exact point
query for legacy and shared layout candidates, repeated securities, missing
keys and gaps. A real PostgreSQL plan must decode each shared session at most
once per batch of action coordinates. Provider timing measurements are tested
with scripted transport responses and do not enter evidence hashes.

The physical read qualification composes a new exact-byte successor with the
existing authenticated action-history source witness. It recognizes the new
compiler only together with the exact batch traversal and unchanged logical
read contract. Tests reconstruct the independent preceding compiler and retain
its existing contribution. Changes outside the qualified bytes contribute
their actual identity. Older source witnesses and strategy expectations stay
intact.
