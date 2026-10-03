# Alpaca/Nasdaq daily operation after cold-start GO

Decision: 2026-10-02. This extends the Alpaca-led cold-start source choice to
the unattended production path. Sharadar remains an offline historical-data
source for research and future backtests; its stored data and research readers
are preserved. No production service, deployment refresh, or automation cycle
may fetch Sharadar or fall back to its legacy publication when a rolling
snapshot is missing.

The broker-free shadow service is the sole daily market-data writer. It uses
the same bounded, GET-only Alpaca/Nasdaq client as GO, publishes the next
source-final 300-session snapshot, and advances the one canonical shadow book.
It receives Alpaca credentials because Alpaca does not offer separate
data-only keys. It receives no paper account identifier or execution authority;
its code imports no broker/order adapter. This is a code and process boundary,
not a claim that the credentials themselves lack trading permission.

The reviewed 23:45 America/New_York boundary is retained as a conservative
daily source-finality check, now named for the operational snapshot rather than
Sharadar's old update cadence. A boundary crossing alone does not establish
data completeness: the exact published snapshot and verified shadow decision
must pass their existing content and causal checks. Changing the policy identity
invalidates old signed/configured authority; activation must be reviewed anew.
Before installing this revision, remove any explicit old
`SENTINEL_AUTOMATION_PUBLICATION_TIMING_POLICY` or
`SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY` value from `.env` (or set both to
`ALPACA_NASDAQ_DAILY_SNAPSHOT_2345_AMERICA_NEW_YORK_V1`). The Compose defaults
then agree with the new signed configuration. Keep any Sharadar credential for
offline research in a separate research environment file, outside the deployed
`.env`. The old Stocker-to-Sentinel environment migration helper drops Sharadar
variables and requires both Alpaca credentials; production Compose does not
pass a Sharadar key through. The operational host environment bridge also
omits historical Sharadar and Data Link variables from child processes, even
if they remain in an older `.env` for now.

The deployed Compose services set the fixed `SHADOW` and `AUTOMATION` feed
service modes. Those modes reject a legacy publication before either service
can enter its historical Sharadar fallback. They also authenticate the bound
candidate manifest's `ALPACA_NASDAQ` provider, so an older Sharadar-backed
rolling publication cannot pass merely because it uses the rolling schema.
The active and standby automation defaults use the same $50,000 shadow
capital as the Alpaca cold start; a retained explicit override must match the
reviewed genesis identity.
The supported installer fixes its
operational-source gate and refuses `feed-daily`. Compatibility code remains
available to existing offline historical tests, but is not a deployable
operational source; production containers receive no Sharadar credential.

Paper automation only reads the matching verified rolling publication and
shadow intent. If it is late or invalid, automation waits or refuses with its
kill switch and broker guards intact. It never starts another publisher,
reconstructs an independent book, or uses legacy Sharadar catch-up. A legacy
publication encountered in the production path is an explicit refusal, not a
fallback. The existing reviewed dual-shadow paper mode remains the only
rolling paper bridge until a separate paper-mode design is qualified.
Prepare and execute recheck the source on restart even if a persisted cycle
already passed refresh. Recovery remains able to reconcile outstanding broker
commands under its existing signed authority; changing the data source must
not strand an unknown execution outcome.
Exhausted bounded retries for a transient Alpaca transport failure leave the
durable acquisition job retryable while its deadline permits. Invalid source
content, credentials, or provider identity remain refusals.

Deployment after cold-start GO must use the same rolling publication. The
installer quiesces the publisher before binding reviewed evidence; it cannot
wait for that stopped publisher to create a new generation. If the GO frontier
has gone stale during this quiesced interval, installation refuses promptly
and requires a new GO run. It never repairs the frontier with `feed-daily`.
Historical Sharadar tables, downloads, and backtest utilities are
not deleted. A future offline historical adapter may feed the current
strategy transition from those records, but it must not become a production
source or alter the live publication lineage.

The optional bring-up helper now checks only local durability and exact image
availability. It does not query a market-data provider; certified GO performs
the source acquisition and validation. This prevents a diagnostic from
reintroducing Sharadar as a prerequisite for an Alpaca deployment.

Qualification needs a daily successor and restart rehearsal using the real
rolling snapshot contract, a negative test proving legacy fallback is
unreachable, a missing-credential refusal, and source/plan binding tests for
the execution membrane. This change grants no paper activation or certified
NAS verdict by itself.
