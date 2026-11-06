# Qualify the owned Trading API activity stream

Decision: 2026-11-06, before implementation. Correct the quarantined candidate
reader's account-scoping contract before considering any cash capability
promotion. Existing cash/fill/finality capabilities remain false in this change.

The owned PAPER endpoint `/v2beta1/events/activities` returned HTTP 200 and five
native events in a terminated November 1–6 query: two trades, two fees and a
$75.89 ordinary BIL cash dividend. The retained response has no `account_id`
field. Requiring the partner stream's per-event account field makes the current
candidate reject the real Trading API response. The ordinary execution path
does not call this quarantined reader, so its missing cash evidence remains
explicit rather than being inferred from a balance.

The [Trading API endpoint](https://docs.alpaca.markets/us/reference/subscribetoactivitiessse)
uses the owned account's API origin and credentials. The
[partner integration guide](https://docs.alpaca.markets/us/docs/activity-sse)
describes a distinct account-bearing envelope; do not assume the envelopes are
identical. Documentation/reachability alone do not earn financial acceptance.

For each candidate stream request, retain the existing sealed credentials and
transport checks and require an account read before and after the completed
response. Both broker/account number and nonempty native UUID must agree.
An event with an explicit account field must match that native UUID; an absent
field may rely only on this owned-endpoint bracket. Preserve currency, executed
status, native ref/event identities, strict ordering, bounded business-time
snapshot, correction/bust refusal and cursor replay checks. A failed closing
identity read yields no batch and no durable cash.

Qualify missing event account fields, wrong/empty explicit fields, account-number
and UUID changes, replay and empty snapshots. Remove the account-bracket and
explicit-event guards to falsify their oracles. Retain the real responses only
in private diagnostic evidence; use synthetic account/command identities in CI.

This does not backfill the running plan's absent activity baseline, resize that
plan, declare its cash coherent or certify a historical close. The observed
dividend's publication precedes the saved plan, whereas the saved account cash
differs from today's by that payment; the original account response and accepted
plan-time event set remain separate missing evidence. Any production cash
promotion or explicit legacy-plan retirement needs its own documented, qualified
transition. LIVE and the backtest remain excluded.
