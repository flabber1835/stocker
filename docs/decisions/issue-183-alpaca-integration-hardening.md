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

Alpaca cash-affecting Account Activities are read from Activity SSE. The two
native identifiers have deliberately different jobs:

- `ref_id` is the economic idempotency key retained with the cash/fill row;
- `event_id` is the monotonically increasing publication cursor retained after
  every complete batch and supplied as `since_id` on replay.

The first read, and an upgrade from the former timestamp-only cursor, performs a
complete historical scan from account binding establishment. Subsequent bounded
reads first capture the current upper `event_id`, then replay the closed
`since_id`/`until_id` interval. A partial walk is unusable and advances no durable
cursor. A timestamp is retained for audit and clock-rollback detection only; it
is never resumption authority. This matters because Alpaca's `since`/`until`
filter the business timestamp (`at`), while a delayed or backfilled activity is
appended later in `event_id` order and can therefore fall behind an already
advanced timestamp boundary.

Terminal-order recovery applies the same rule conservatively. Until that path
has its own durable `event_id`, every bounded terminal recovery scans the full
available Activity SSE lifetime and deduplicates by native fill `ref_id` rather
than trusting the terminal timestamp watermark to find late publications.

The existing `sentinel_processed_sessions` table is a keyed durable-cursor store as well as the Wealth Core catch-up row. Issue 183 uses two namespaced cursor families in its `state` JSON rather than introducing an unvalidated authority table:

- one account-activity cursor per bound broker account, retaining
  `processed_through`, the last processed `event_id`, the last economic
  `ref_id`, and the cumulative recognized cash total;
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

## 5. Recovery and emergency-authority linearization

The account-bound terminal-recovery completion witness is an Alpaca adapter
claim. It is required only while reconciliation is operating on the concrete
Alpaca broker (including a guarded wrapper around it). Broker-independent
simulators and other adapters retain the generic terminal watermark contract;
they cannot be required to manufacture Alpaca account/asset provenance.

Emergency kill and revocation remain immediate database operations. The durable
`PLANNED -> SEND_PENDING` commit is the local side-effect linearization point:

- a kill/revocation committed before `SEND_PENDING` prevents that command from
  crossing the boundary;
- a command already committed as `SEND_PENDING` may reach transport even if an
  emergency transition commits before the network call, but it uses the same
  deterministic client key and is recovered as `SEND_PENDING`/`UNKNOWN`;
- every later authority check and every later command is refused.

No local database lock can both make a network send atomic and keep the
emergency operation non-blocking. Serializing kill behind the execution writer
would make the control appear immediate while it waited on the very work it is
intended to fence, so that design is rejected explicitly.
