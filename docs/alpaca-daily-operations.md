# Daily market data after cold-start GO

The October 2 design established a single daily publisher. The current
source policy is `ALPACA_OPENFIGI_VALIDATED_CLOSED_SESSION_V2`. GO and daily
publication read Alpaca SIP bars and corporate actions plus OpenFIGI
classifications. The broker-free shadow publisher verifies and publishes the
rolling input generation, then advances the canonical shadow book. Its Alpaca
market-data client admits only GET requests to the approved endpoints. Its
OpenFIGI client reads classifications through the mapping endpoint. The shadow
has no PAPER account binding or order transport.

Acquisition is eligible at the actual XNYS close. Coverage, corroboration,
price-domain and publication checks establish when that session is ready. Use
the deployed Compose defaults for publication timing. Existing explicit timing
settings must match the reviewed policy and signed configuration. The host
requires Alpaca credentials and accepts an optional OpenFIGI key. The same
environment bridge applies to GO and the service publisher.

The `SHADOW` and `AUTOMATION` service modes authenticate the
`ALPACA_OPENFIGI` manifest before consuming a rolling publication. Historical
research replays previously captured inputs. The supported installer preserves
the bound strategy and book and verifies its software receipt under a fence.
See the [operating contract](sentinel-deployment.md).

Paper automation only reads the matching verified rolling publication and
shadow intent. If it is late or invalid, automation waits or refuses with its
kill switch and broker guards intact. It never starts another publisher,
reconstructs an independent book, or uses archived input as a fallback. A legacy
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

Software installation is independent of the time of day. Guarded PAPER
activation separately verifies the reviewed publication, account binding,
reconciliation and backup gates. The bring-up helper verifies local durability
and image availability. GO owns acquisition and source validation.

Qualification needs a daily successor and restart rehearsal using the real
rolling snapshot contract, a negative test proving legacy fallback is
unreachable, a missing-credential refusal, and source/plan binding tests for
the execution membrane. This change grants no paper activation or certified
NAS verdict by itself.
