# November 25 opening follow-up

The sale filled after the original settlement check and a buy missed its
opening cutoff after the retry repeated the gateway. The installed single-sale
continuation waits for a positive exact-key fill hint and follows it with a
complete reconciliation. The installed opening frontier and dashboard fixes
cover the duplicate frontier lookup and false trading stop. This change
addresses the remaining verification and sizing work on the opening path.

## Proof work during one opening

The live idle investigation identified the same standing PAPER metadata check
used by guarded opening broker reads. Its full path reconstructs the entire
market reference bundle each time, even when the authenticated input and
comparison proof are unchanged. Use the existing compact result from the
broker-free idle reader inside one automated PAPER execution or recovery
callback. Its first use performs the canonical verification. Subsequent
uses still pin and authenticate the current publication and comparison
evidence, compare the exact metadata proof key and check the current database
identity. Bound the slot to the callback and discard it when the callback
ends. Start a fresh slot after retries or restarts. Each broker read or
mutation retains the original authority and lifecycle check, current binding,
lease, operation, price and account checks. PAPER and LIVE remain separate.

Acquire the automated PAPER opening publication pin at operational input
validation. Use that exact authenticated publication to check the source
provider and keep the pin through the plan lookup and adapter construction.
The earlier cycle-authority read and the independently callable gateway
retain their original checks. The first and later account snapshots still
bound distinct broker observations so a fill can never turn old cash into
new funding authority.

Carry forward the sizing change from PR #634. It uses the verified strategy
state only when the retained exact canonical state commitment matches the
current verified state and the same saved plan. Keep the full legacy restore
and the canonical sizing derivation. Keep both account observations where
funding, holds or orders can change between them.

## Qualification

Use a disposable network-isolated database and simulated broker. Exercise the
opening admission and durable scheduler, then verify 20 independent sales,
the defensive BIL purchase after settlement, and restart after broker
acceptance. Include slow settlement and an unresolved order. Measure from
the opening wake through accepted orders and eventual confirmation, preserving
the original cutoff and pending order evidence. Use the retained pre-open
database separately to identify remaining time in production-sized reads.
State the coverage and limitations of each rehearsal explicitly.
