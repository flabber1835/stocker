# Research Champion PIT metadata closure

**Status:** accepted dataset-maintenance design

## Scope

Close metadata only for securities observed by the frozen Research Champion
strategy-path ledger produced by run `33994291853` at source SHA
`53dc0bf9adbe7d3ee60b2a54d9769dcdfdea7306`.

The Champion profile, parameters, execution rules, portfolio construction, and
controller economics are immutable inputs.  This work may change only the PIT
metadata corpus and the evidence describing that corpus.

## First closure stage

The first stage allocates already-retained ownership-strict V4 security-type
authority to the 1,751 unknown-type candidate-boundary securities.  It uses:

- the exact strategy-path worklist and session ledger from run `33994291853`;
- the issuer-safe, ownership-strict V4 canonical audit from run `33720489684`;
- strict-prior allocation: `usable_after < decision_session`;
- complete rejection of every same-date V4 security-type conflict.

This stage produces an evidence ledger.  It does not rewrite the canonical
corpus and does not run an economic replay.

## Economic priority

Unknown security types are ordered as follows:

1. securities that reached a durable rank or recent-leadership set during a
   classified part of their history;
2. remaining unknown candidate-boundary securities requiring counterfactual
   ranking after classification;
3. securities held during another classified part of history when they did not
   reach either recorded leadership set;
4. remaining candidate-boundary cases.

Terminal work is ordered by direct held-position contact, leadership contact,
then remaining candidate-boundary contact.

## Acceptance contract

Every allocated observation must resolve from a security-ID-bound V4 event
whose usable date is strictly earlier than the decision session.  Ticker-only
joins, future observations, same-session observations, and conflicted events
are rejected.  A security is `ELIGIBLE` or `INELIGIBLE` only when every unknown
candidate observation is resolved consistently.  Partial coverage remains
`PARTIAL`; absence of admitted authority remains `UNRESOLVED`.

The next dataset build may consume only the allocated observation ledger after
it has been retained in a content-addressed package and bound to its source
hashes.
