# Backtester causal terminal terms

Status: research-only design for `research/backtester`.

## Purpose

The historical replay can encounter an economically live Wealth Core position after its last exchange print. Sharadar ACTIONS identifies terminal corporate actions but its `value` field is aggregate transaction value, not per-share settlement consideration. Exact next-open attribution requires the terminal claim to be converted into the cash or successor security actually owed to the holder when authoritative causal terms are available.

This document defines the research-side input seam used to represent those exact terms. It does not change production strategy code or production accounting semantics.

## Boundary

`backtester/data/causal-terminal-terms-v1.json` is a branch-owned, frozen historical input produced by a separate dataset-maintenance step. The economic replay may read it only after the file and its checksum already exist on `research/backtester`.

Each record must identify:

- the original permanent security ID and historical ticker;
- the legal/economic effective session;
- the date by which the terms were publicly knowable;
- the exact production terminal kind;
- all consideration fields required by that production terminal kind;
- source provenance sufficient to audit the terms;
- any market-price witness required by the contract, tied to the frozen Sharadar source hash.

The loader must fail closed on malformed rows, duplicate `(effective_session, security_id)` keys, future-known terms, unknown security identities, non-positive required values, or checksum mismatch.

## Replay semantics

The frozen research terms are converted into the exact `stock_strategy_shared.wealth_core.terminal.TerminalTerms` type imported from the pinned production-main checkout.

For a session/security already represented by a Sharadar ACTIONS terminal candidate, the exact research record supplies the complete terms for that same terminal event. For a legal effective session that follows the vendor ACTIONS date, the ACTIONS event remains part of the chronological replay and the exact record is supplied on the legal effective session to settle the carried terminal claim.

The production settlement engine remains authoritative for applying cash mergers, conversions, successor-security delivery, fractional-share cash, basis/anchor transfer, and terminal-claim lifecycle.

## Initial source repairs

### Litton Industries (`LIT1`, security `120448`)

Northrop Grumman's 2000 Form 10-K/A, filed before the merger, states that after the exchange offer the remaining Litton common shareholders would receive `$80 per share in cash` in the merger. Northrop announced on April 30, 2001 that the special meeting would occur on May 30 and that each outstanding Litton common share would receive `$80 in cash per share`. The statutory merger completed on May 30, 2001.

Frozen term:

- effective session: `2001-05-30`;
- kind: `CASH_MERGER`;
- cash per share: `80.00`.

### The CIT Group (`CIT.A`, security `122131`)

The March 12, 2001 Agreement and Plan of Merger was incorporated by reference to Tyco's Form S-4 filed March 29, 2001. It states that each eligible CIT common share converts into `0.6907` Tyco common share. Section 1.06(f) states that fractional Tyco entitlement is paid in cash using Tyco's NYSE closing price on the trading day immediately preceding the effective time. Canadian securities-regulator material dated May 31, 2001 independently records the `0.6907` exchange ratio and expected June 1 closing.

The frozen Sharadar 2001 SEP source resolves `TYC` to permanent security `573113`. Its 2001-05-31 as-traded close (`closeunadj`) is `57.45`; this is the contractually required prior-trading-day cash-in-lieu price. The same frozen source contains the 2001-06-04 Tyco row needed for chronological valuation after conversion. The source file SHA-256 is `23f8a84400e69077ad251563c25ece80632d00fe9cce317ac421b0525a0da140`.

Frozen term:

- effective session: `2001-06-01`;
- kind: `CONVERSION`;
- delivered security: `TYC`, permanent security `573113`;
- exchange ratio: `0.6907`;
- cash-in-lieu price per delivered share: `57.45`.

## Provenance

Causal/legal sources used for the frozen dataset:

- SEC Northrop Grumman 2000 Form 10-K/A: `https://www.sec.gov/Archives/edgar/data/72945/000007294501500013/form10k.pdf`
- Northrop Grumman April 30, 2001 special-meeting announcement: `https://investor.northropgrumman.com/news-releases/news-release-details/northrop-grumman-sets-special-meeting-stockholders-litton`
- Northrop Grumman May 30, 2001 completion announcement: `https://investor.northropgrumman.com/news-releases/news-release-details/northrop-grumman-announces-completion-merger-litton-industries`
- CIT/Tyco Agreement and Plan of Merger text: `https://contracts.justia.com/companies/tyco-capital-corp-82500/contract/1143615/`
- SEC exhibit-index evidence that the CIT/Tyco agreement was incorporated by reference to Tyco's Form S-4 filed March 29, 2001: `https://www.sec.gov/Archives/edgar/data/833444/000104746903025320/a2113549z10-ka.htm`
- British Columbia Securities Commission CIT/Tyco MRRS decision: `https://www.bcsc.bc.ca/securities-law/law-and-policy/exemption-orders-prior-to-2002/2001/the-cit-group-inc-et-al-mrrs1`

## Verification requirement

Before a full A/B replay is launched, a branch-side verification job must prove all of the following from frozen inputs:

1. the terminal-term file matches its pinned checksum;
2. `LIT1` maps to security `120448` and settles for exactly `80.00` on `2001-05-30`;
3. `CIT.A` maps to security `122131` and converts to `TYC` security `573113` at exactly `0.6907` on `2001-06-01`;
4. the frozen 2001 SEP source hash matches its manifest pin;
5. the frozen `TYC` 2001-05-31 `closeunadj` is exactly `57.45`;
6. production SEP normalization yields `TYC` 2001-06-04 `VendorBar.raw_open == 56.90` from the frozen row;
7. a fractional CIT entitlement, when present, uses the frozen `57.45` cash-in-lieu price through the production terminal settlement type.

The full replay then remains a fresh chronological A/B run. The source terms do not encode holdings, decisions, allocations, trades, NAV, or any other prerecorded strategy path.
