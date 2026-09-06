# Production-equivalent perfect-classification backtest contract

Date: 2026-09-06

## Target question

> If Wealth Core had received the correct security-type classification on every trading day from 2006 through 2026, how would the frozen Research Champion have performed?

This is the primary economic-performance question for the final clean 20-year backtest.

## Classification semantics

For this backtest, security type is treated as a **truth oracle**. The historical replay must use the security type that was factually true on the historical session. Evidence discovered later may be used to reconstruct that historical fact. The publication date of the evidence does not make the historical classification economically forward-looking because the classification value itself is assumed to be supplied correctly by the live production classifier.

This contract is intentionally different from strict archival PIT provenance. A later SEC filing or archive capture may establish that a security was, for example, a corporation common share, partnership unit, trust unit, ADR, preferred share, or other non-common instrument on an earlier date. The reconstructed truth may be used for the earlier date when the historical fact itself is unambiguous.

## Prohibited information

The truth classifier may use security identity, legal form, share/unit class, issuer/security documents, contemporaneous or later authoritative descriptions of the historical security, exchange/security identifiers, and corporate-action history needed to determine the security's factual type.

The classifier must not use future price performance, future returns, future rank, future portfolio membership, future drawdown, survival, later index membership, the strategy's realized outcome, or any other variable whose value depends on what happened after the decision session.

## Required classification result

Every canonical security episode that reaches a decision-relevant unknown-security-type seam must resolve deterministically to either:

- `common`, meaning eligible for the Champion common-stock universe; or
- `non_common`, meaning excluded by the security-type rule.

No unresolved/ambiguous classification may silently default to common or non-common. Residual ambiguity must be listed and resolved before the final clean result is labeled production-equivalent perfect-classification.

## Current reconstructed classifier

The current reconstructed classifier combines:

1. the 1,751-row historical unknown-security estimate ledger;
2. the reviewed 18-name conflict ledger; and
3. dated historical corrections, including the security-type transitions for PDS and EQM.

The earlier strict-PIT finding that PDS used evidence published after a 2006 decision is **not a defect under this production-equivalent truth-oracle contract**. It remains a limitation only for the separate strict archival-provenance claim. The relevant question here is whether the reconstructed PDS security type is factually correct on each historical interval.

The remaining factual-certainty task is to audit decision-relevant inferred classifications for correctness, prioritizing held/pending securities, durable-ranked securities, and recent-leadership securities. Any factual error changes the truth ledger and requires a fresh economic replay from the frozen base.

## Economic controls

The clean production-equivalent replay keeps fixed:

- Research Champion profile `strategy9-e3-research-champion-v1`;
- all Champion parameters;
- initial shadow cash of $100,000,000;
- canonical PIT market/corporate-action corpus hash `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`;
- pinned runtime `887f479b15ad861313da666ad698034d3847121c`;
- 2006-01-03 warmup start, 2006-07-31 measurement start, and 2026-07-31 end;
- the corrected execution path with the unintended 10%-volume whole-order capacity guard removed.

No return-based tuning, capital change, or parameter adjustment is permitted.

## Current run

Run 34047029680 is the first full-horizon candidate for this production-equivalent classification target. It starts from the 18.15% capacity-corrected certificate path and changes only the unknown-security-type classification layer to the reconstructed historical classifier.

Its result is provisional until the factual classification audit closes. If the factual audit makes no decision-relevant changes, the run can be retained as the production-equivalent classification-oracle economic path. If corrections are required, those corrections are frozen first and one clean full-horizon replay is run.

## Final reporting labels

The final report must distinguish:

- **Production-equivalent perfect-classification backtest** — estimates live economics assuming correct security classification at every decision time;
- **Strict archival PIT certification** — additionally requires proof that each historical datum was available from a source at the historical time.

Only the first label answers the live-production economic question in this document.
