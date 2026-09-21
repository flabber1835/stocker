# Production formation classification diagnostic

This package calls the unchanged production kernel from the retained PR #426
checkout. It changes research input classifications in memory and writes new
outputs. It does not edit that checkout or the source archive.

## Run

Use Python 3.12 with the numeric/calendar versions in the selected production
checkout's sentinel/requirements.txt. The diagnostic records loaded package
versions. Run from this feature checkout:

    python -B -m research.classification_check.runner
      --harness <read-only-PR426-checkout>
      --archive <pit-source-5bdc6b39.zip>
      --sfp <PIT-input-data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz>
      --sources <PIT-input-data>
      --output <new-output-directory>
      --seconds 1800

The four modes are unchanged control, corrected dates, seven explicit identity
links, and both corrections together. Each independently starts with cash on
January 3, 2006 and stops after July 6. No holdings, rankings or reference NAVs
are fed into the strategy. The links are diagnostic inputs chosen to test the
previously observed first divergence, not an out-of-sample strategy evaluation.

## Retained evidence for the seven links

| Vendor episode | Historical symbol / CIK | Pre-decision evidence |
| --- | --- | --- |
| CHAP1 / 214820292338870148 | CHAP / 1319048 | Form 4 accession 0001209191-06-001857, January 5, 2006 |
| AVL1 / 353685636371040898 | AVL / 701650 | Form 4 accession 0001192714-06-000002, January 30, 2006 |
| VOLT2 / 840588175708298328 | VOL / 103872 | Form 4 accession 0001157523-06-000817, January 30, 2006 |
| FTI1 / 1099247927332588244 | FTI / 1135152 | Form 4 accession 0001303279-06-000009, January 4, 2006 |
| WEBX1 / 88378928586164151 | WEBX / 1109935 | Form 4 accession 0001109935-06-000004, January 4, 2006 |
| FALB / 1040633074096912075 | FAL / 889211 | Retained admitted manual record, August 15, 2005 evidence |
| LFCHY / 788900523736619527 | LFC / 1268896 | Retained admitted manual record, May 30, 2006 Form 20-F |

The first five rows are present in the hash-bound positive evidence source.
FALB and LFCHY are in the hash-bound manual admission audit, originally limited
to June 29 and June 8 purchases respectively. Original research episode reviews
are retained at eaddca3f04f279e99663f832bf7293e92ee15662 under
research/champion-economic-integrity/security-truth/manual-review/held-pending-shard-*.json.

Primary supporting documents:
- [Falconbridge common shares, 2005 release](https://www.sec.gov/Archives/edgar/data/1001085/000090956705001329/t17714exv99w1.htm).
- [China Life 2005 Form 20-F, filed May 30, 2006](https://www.sec.gov/Archives/edgar/data/1268896/000119312506121269/d20f.htm).

These links assert only the bounded episode identities and type. Issuer grouping,
sector grouping, prices and actions remain unchanged to isolate eligibility.
Unknown issuer classification continues the source authority's symbol-only
fallback, but requires genuinely prior evidence after date parsing.

## Verification

    python -B -m pytest -q -p no:cacheprovider research/classification_check/test_classifier.py

The calendar oracle covers a late-month past date, a future date, a same-day
date and an ISO date. Replacing filing_date with the old ten-character slicing
in memory makes the first three checks fail. Identity tests reject unreviewed
episodes and contradictions and stop the explicit links after the diagnostic.
No golden fixture is repinned.

## Compare completed outputs

    python -B -m research.classification_check.compare
      --output <completed-new-output-directory>
      --control <retained-january-001/daily.jsonl>
      --archive <pit-source-5bdc6b39.zip>
      --repo <local-repository-with-reference-commit>

This writes a new comparison.json and refuses to overwrite one. It verifies
the unchanged control and independently adds ledger cash to raw marked shares.
The retained first-formation results are in audit/classification_formation.
