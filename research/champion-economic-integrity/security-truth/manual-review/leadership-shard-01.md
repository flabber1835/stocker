# Leadership security-truth review — shard 01

Date: 2026-09-06

Base: `research/champion-security-truth-held-pending-integration` at `5b9d9ea2e378044f49d217fe311b36b45c73124c`

## Assignment

Reproduced exactly from `fresh-path-open-review-queue.csv`:

- filter: `priority == P2_LEADERSHIP`
- sort: `(security_id as integer, ticker)` ascending
- zero-based index `i`
- shard rule: `i % 4 == 1`
- filtered leadership rows: 182
- assigned rows: 46

The exact ordered assignment is retained in `leadership-shard-01.json` before the case records.

## Result

- common: 24
- non_common: 0
- split: 0
- unresolved: 22
- classification changes from the queue's `common` hypothesis: 0
- `outcome_information_used=false` for every case

Resolved cases use primary SEC, issuer, exchange, or depositary evidence. Identifier changes and corporate transitions were treated separately from genuine security-type changes. No assigned case established a preferred-share, preferred ADS/ADR, LP/partnership-unit, trust-unit, warrant, rights, or other non-common episode.

## Unresolved worklist

`GRCE`, `AKAN`, `MKDTY`, `CXRXF`, `AT1`, `FREHY`, `OCNF`, `DSY`, `NRTLQ`, `ORANY`, `GVHGF`, `HYFT`, `PBM`, `AEHL`, `CORZQ`, `BETSF`, `MDVLQ`, `CNL1`, `GSF1`, `CBKCQ`, `ATAC1`, `SKIL2`.

These remain open because the full multi-CUSIP identity chain was not established strongly enough to certify the complete canonical interval. No type split is asserted for them.

## Validation

- assignment formula reproduced: PASS
- every assigned case exactly once: PASS
- zero extras: PASS
- evidence recorded for every resolved case: PASS
- unresolved worklist explicit: PASS
- no outcome information used: PASS

Canonical compact serialization SHA-256 of the reviewed JSON object: `30c993ba2b09158954c59db36a83effbd455b5de7f781f10a41ec8ef5d076e0e`.

No replay was run.
