# Issue 183 — Alpaca integration hardening

Status: decided before implementation.

This change hardens the Alpaca transport boundary without weakening Sentinel's existing command identity, recovery, cash, or execution-window invariants.

## 1. Submit responses are classified by economic certainty

A returned HTTP status is not itself an order lifecycle state.

- A network exception, HTTP 408, HTTP 429, or 5xx leaves the command outcome `UNKNOWN`. Sentinel never blindly retries the POST; recovery first resolves the same deterministic `client_order_id` by exact lookup, and only a proven absence may permit the same durable command to be sent again.
- HTTP 401/403 is a typed broker credentials/authority refusal. It is not an economic order rejection and must escape dispatch as an operational authority failure.
- A broker-declared validation/account-policy 4xx remains `REJECTED` when acceptance is not ambiguous.
- A duplicate `client_order_id` remains `UNKNOWN` and is resolved by exact key.

A successful 2xx proves receipt, not final lifecycle. The response must first agree with the durable request on client key, side, quantity, permanent security/symbol, stable asset id when one is known, market order type, DAY time-in-force, simple order class, and `extended_hours=false`. A contradiction is malformed broker evidence and is never acknowledged normally. After a consistent 2xx, submit returns `ACKNOWLEDGED` even if the response already says partially filled or filled; cumulative fill state is established by normal reconciliation.

## 2. Account Activities are durable cash evidence, not a plug

Alpaca cash-affecting Account Activities are read in ascending order, paginated with the broker-native activity id as `page_token`, and bounded by a captured upper timestamp. A partial page walk is unusable and advances no durable cursor.

The existing `sentinel_processed_sessions` table is a keyed durable-cursor store as well as the Wealth Core catch-up row. Issue 183 uses two namespaced cursor families in its `state` JSON rather than introducing an unvalidated authority table:

- one account-activity cursor per bound broker account, retaining `processed_through`, the last native activity id, and the cumulative recognized cash total;
- one plan cash baseline per plan id, retaining the cumulative recognized cash total that existed when that immutable plan was prepared.

Every broker activity is idempotent by its native activity id. Cash events are retained in `sentinel_cash_flows` under reserved broker-native flow ids. Replay of the same id must reproduce the same date, amount and classification; a changed duplicate is corruption, not an upsert.

`sentinel_cash_flows` therefore contains two economic classes:

- **external capital** — deposits, withdrawals and cash ACATS transfers; these are included by `net_external()` and removed from strategy P&L;
- **internal cash movement** — fees, interest, journals, dividends/distributions and similar recognized broker cash adjustments; these explain account cash but remain part of strategy economics and are excluded from `net_external()`.

The class is encoded in a reserved, versioned broker flow-id prefix and validated on replay. Operator-declared `cf-*` rows keep their existing external-capital meaning.

A broker activity never authorizes a silent rewrite of an already prepared plan. If the cumulative broker cash total changes after a plan baseline, that plan remains immutable and is blocked. At the next valid preparation, the prior plan's account cash must reconcile exactly to its baseline plus durable fills plus the recognized broker-activity delta. Only then may the fresh broker balance become the baseline for a new plan. A balance residual with no durable activity remains unexplained and fenced.

## 3. Broker clock corroborates; XNYS remains authority

The deterministic XNYS calendar remains the primary execution window. The existing local gate still blocks every submission outside the certified session, including when Alpaca says open.

For **increases**, immediately before the increase phase Sentinel also reads Alpaca `/v2/clock`. Local-open plus broker-closed, malformed clock evidence, or a clock-endpoint outage refuses the increase. This check is deliberately in the existing increase-authority callback so it is repeated after reductions settle and just before buying.

For **reductions**, the broker clock is not an additional veto. The local certified XNYS gate still applies, but once inside that window a broker-clock discrepancy must not turn an otherwise permitted de-risking action into a forced hold. This preserves Sentinel's established asymmetry: delayed buying is opportunity cost; delayed selling can preserve unwanted risk.

## 4. Boundaries with existing issues

This change does not claim to close the separately tracked work for full asset-id enforcement (#124), restore-grade open-order completeness (#125), late terminal-history aging (#127), account-bound observations (#128), account-snapshot freshness (#129), fill-activity pagination/native fill identity (#131), terminal-watermark integrity (#146), or mutation-authority TOCTOU (#110).

In particular, issue 183 imports non-fill cash activities. `FILL` remains reconciled from cumulative order state until #131 replaces the fill ledger's current content fingerprint with broker-native fill activity ids.
