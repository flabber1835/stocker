# January formation, bounded resumable replay

This is a provisional economic-engine experiment, not economic certification.
The unchanged production kernel starts with USD 100,000 on 2006-01-03;
performance measurement starts at the 2006-07-31 close with the formed book.
First purchases occur on 2006-07-06. No holdings or controller reset occurs in
July. The original golden artifacts and earlier July cash-start pilot remain
unchanged.

Production revision: `624395dd04c48af7de3a8930cfd586ca2cc81245` (#425).
Harness revision: `c98dc7b57b65f47f64ad72f6ecc775515fafd12d`.
Verified main: `48f88fd4f3957c0dfc264e2eef2e35ecd753c9c1`.
Delivery: #426, dependent on #425. No production algorithm changed.

## Stopped result

Both authorized 30-minute segments stopped normally (exit 0, no OOM). Final
checkpointing extended their wall times to 1,815.32s and 1,813.22s respectively;
no new session began after either deadline. Total successful sessions: 712,
2006-01-03 through 2008-10-29. The next session is blocked by IKN below.

| July 31, 2006 through October 29, 2008 | Current production replay | Retained research reference |
| --- | ---: | ---: |
| Multiple | 0.9498118143x | 1.3135306605x |
| CAGR | -2.26468673% | 12.89926342% |

Current account NAV: USD 86,325.2667333044. Measurement-period maximum drawdown:
30.39593099%. The economically significant return gap remains unattributed;
see `investigation-prompt.md` for a separate, bounded diagnostic task.

Eight supplemental records were applied: REY, HET, MOGN, XMSR, SPSX, EAS,
SCRX and NWA. XMSR and NWA correct cash-versus-stock event classifications.
These corrections apply only to this experiment. IKN remains unresolved.

All 712 dates match the retained input-session calendar with no gaps or
duplicates. The real restart continues November 16 with November 19, preserving
previous NAV and the July baseline. Every reported current/reference multiple
and current CAGR was independently recomputed from retained NAVs. These are
continuity/report checks, not proof that strategy economics are correct.

Final checkpoint load: `RESUME_VERIFIED`, state hash
`8530f81d5f40c5138e07844317accb6b11c9e65dbe788892eb4dda81c83795b1`.
Checkpoint gzip: 14,333,865 bytes; SHA256
`b3914e3ef8a71f176b920dcfb0fe7c4359a0bc16d676163b6444879ee2e52d66`.
The full checkpoints remain locally under
`C:/GitHub/stocker/.codex-tmp/january-replay-evidence/` and are excluded from
the compact Git evidence archive. `local-artifact-manifest.json` records their
sizes/hashes. Preserve this directory and the bound input archive for resume.
Git evidence alone does not contain a restorable checkpoint.

## Interpretation and comparison

The retained research result was 56.265349336558316x / 22.323600023175572%
CAGR over its full measurement window. Every reported comparison here instead
uses the same July 31 baseline and same last simulated date. Short-prefix
annualized returns are not twenty-year forecasts. Baseline strategy NAV is
USD 90,886.7055916009799999999999; formation-period losses are excluded from
the July-based multiple, not erased from account NAV.

Matching initialization does not establish implementation equivalence. The
historical research run carried missing prices and eventually proxy-settled
missing terms; the production path refuses unresolved strategy valuation.
Classification policies also differ. This run does not attribute the entire
return delta to any single change or certify its economic correctness.

## Action evidence

REY security ID `659080056497857391` had 107 held shares when the original
2006-10-26 PIT terminal record lacked cash consideration. The next transition
refused unresolved equity. The issuer's October 26 completion announcement
identifies NYSE REY, confirms closing and October 27 delisting, and specifies
USD 40 per Class A common share. The September definitive proxy independently
specifies those terms. Class B's different conversion basis is not used.

- [Issuer completion release, syndicated by PR Newswire](https://www.advfn.com/stock-market/NYSE/REY/stock-news/17422912/reynolds-and-reynolds-announces-closing-of-merger)
- [SEC definitive merger proxy](https://www.sec.gov/Archives/edgar/data/83588/000095012306011813/y22076fdefm14a.htm)

The supplement enters on 2006-10-27, after the known completion date, without
changing the already-processed October 26 session. Consideration is USD 4,280
(107 x 40). This is the production model's economic recognition convention;
the sources do not establish when a particular broker credited spendable cash.
The successful subsequent sessions establish that the guarded transition
accepted these exact terms. They do not establish provider completeness.

HET security ID `192586880711243639` blocked the 2008-01-28 closing leadership
witness because its cash terminal lacked consideration. The book held no HET
shares. The issuer's January 28 release confirms completion and USD 90 per common
share, with trading ending that close. Its dated release is retained as an
[SEC exhibit](https://www.sec.gov/Archives/edgar/data/858339/000089882208000159/pressrelease.htm)
to a January 31 filing; the release date, not the later filing date, supplies
day-level availability. The supplement applies to the January 28 closing witness
and makes no opening cash or broker settlement claim. No processed session was
rewritten. Intraday provider publication evidence remains outside this replay.

The same transition also required MOGN ID `68479681776669621`, another unheld
leadership constituent. Eisai's [December 10 agreement announcement](https://www.sec.gov/Archives/edgar/data/702131/000095013307004863/w44303exv99w1.htm)
specifies USD 41 per common share, and its [completion release](https://www.eisai.com/news/pdf/enews200803pdf.pdf)
is explicitly dated January 28, 2008 in U.S. time. Those terms enter the
January 28 end-of-day leadership calculation; opening availability is not
asserted. The HET-only retry and subsequent MOGN refusal share a session; the
worker's block JSON is replaced on retries, while its container log preserves
both error identities.

XMSR ID `512429007987298889` refused on 2008-07-28. The retained acquisition
row incorrectly labels an all-stock deal as `CASH_MERGER`. The
[February 19, 2007 issuer agreement announcement](https://investor.siriusxm.com/sec-filings/all-sec-filings/content/0000950123-07-002460/y30604exv99w1.htm)
already fixes consideration at 4.6 SIRI common shares per XM common share.
The supplement corrects the event kind to `CONVERSION` and uses SIRI ID
`881960888100488127` and its retained metadata issuer key. The original PIT
July 28 event date is preserved. July 29 completion news is later corroboration,
not claimed as information available on July 28. Exact intraday confirmation
remains unqualified. XMSR was unheld; the fractional notional leadership witness
uses delivered closing price and does not require a broker cash-in-lieu price.
This repairs this experiment's input only, not the underlying canonical export.

SPSX ID `776999869916961922` had 115 held shares and pending incomplete terms
on August 7, 2008. Its [SEC filing made August 7](https://www.sec.gov/Archives/edgar/data/1271193/000090342308000647/s8-114844.htm)
confirms completion at 17:00 New York time and USD 45 per common share. The
supplement enters August 8, leaving the processed prior day intact: contractual
consideration is USD 5,175 (115 x 45). Actual broker cash availability remains
unqualified, as for REY.

EAS ID `141792502181756432` was unheld but blocked the September 16, 2008
leadership witness. The [issuer's November 20, 2007 release](https://www.sec.gov/Archives/edgar/data/1046861/000104686107000080/e8k112007e99-1.htm)
establishes USD 28.50 cash per common share; the
[September 16 exchange notice](https://www.nasdaqtrader.com/content/phlxmemos/2008/sep/1635-08.pdf)
confirms the effective event date. The exchange explicitly calls its terms
summary unofficial, so consideration relies on the issuer source. Terms enter
the closing witness without claiming opening or broker cash availability.

SCRX ID `486323212632963393` was another unheld leadership constituent. Its
[October 9, 2008 completion release](https://www.sec.gov/Archives/edgar/data/1106773/000110465908063286/a08-25921_1ex99d1.htm)
specifies USD 31 per common share and a 17:00 EDT effective merger. Terms enter
the October 9 end-of-day witness after that event; they are not treated as
opening-session information or a broker cash credit.

NWA ID `680121237621218261` refused October 29, 2008. Like XMSR, its retained
cash-merger label is incorrect. [Delta's dated completion announcement](https://ir.delta.com/news/news-details/2008/Delta-and-Northwest-Merge-Creating-Premier-Global-Airline/default.aspx)
and merger agreement specify 1.25 DAL shares per NWA common share. The corrected
conversion uses the post-2007 DAL identity `776140674308328073` and retained
issuer key `P:SEC_CIK:27904`. NWA was unheld; the closing leadership witness uses
fractional contractual value, not rounded broker delivery or assumed cash-in-lieu.

## Remaining blocker: IKON event date and observation coverage

**Blocking historical-input defect (high severity for this replay):** IKN ID
`1112473731749479571` is held, 274 shares. Its retained terminal is dated October
30, 2008, but [Ricoh's completion release](https://www.sec.gov/Archives/edgar/data/3370/000129993308005163/exhibit1.htm)
and the [SEC completion filing](https://www.sec.gov/Archives/edgar/data/3370/000129993308005163/htm_29787.htm)
say shareholder approval and closing occurred October 31, with trading ceasing
at the November 3 open. Consideration is USD 17.25 per share (USD 4,726.50 for
this holding). Supplying that amount on October 30 would recognize the merger
early. No IKN supplement was applied.

The canonical export includes an October 30 IKN bar (open 17.09, close
17.120000000000001) but no October 31 IKN bar. The raw extracted rows are retained
in `ikon-date-conflict.json`. The next continuation requires checking the
authoritative underlying tape for October 31 prices/volume and reconciling the
event date, rather than manufacturing a mark or cash finality. Add explicit,
source-bound event rescheduling and any authoritative bar repair to a separately
reviewed input/harness revision. Preserve old data/checkpoints and validate an
explicit checkpoint migration or replay from an earlier state; current bindings
intentionally reject silent source/data changes. October 30 must remain an
ordinary market session, and the first post-completion accounting must recognize
exactly 274 x 17.25 once, subject to any intervening genuine strategy trade.

This is an input/harness capability gap, not a demonstrated production valuation
defect. The existing leadership guard correctly refused the incomplete event.
No required certification gate is closed by this experiment.

## Execution and resume

The 1,800-second budget begins at worker start and includes input validation,
checkpointing and research pauses. Started 2026-09-20 23:08:37 UTC. A final
checkpoint may complete just beyond the deadline. The worker has no network,
broker, database or NAS access. Research is performed separately.

At 23:35 UTC the owner authorized another 30 minutes. The first worker retains
its original deadline. A second worker resumes its final checkpoint into
`january-002`, preserving the book, July baseline and applied evidence; its
separate budget is 1,800 seconds. This exercises real continuation without
changing the hash-bound harness while it is running.

```powershell
docker run -d --name sentinel-january-30m --network none --memory 4g --cpus 2 --entrypoint python -e PYTHONPATH=/work:/work/shared -e PYTHONDONTWRITEBYTECODE=1 -v C:/GitHub/stocker/.codex-tmp/bounded-production-replay-worktree:/work:ro -v C:/GitHub/stocker/.codex-tmp:/inputs:ro -v C:/GitHub/stocker/.codex-tmp/january-replay-evidence:/evidence -w /work sentinel-test:ci -u -m research.bounded_20y.january --archive /inputs/pit-source-5bdc6b39.zip --sfp '/inputs/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' --output /evidence/january-001 --supplements /evidence/supplements.json --seconds 1800
```

Image: `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
Source, input members, reference bytes and checkpoint state are hash-bound.
Checkpoints retain the production book, pending orders, controller, feed,
metadata, cumulative factors, scalar economics, measurement statistics and
applied supplements. Preserve the same source/data and `/evidence` mount.

To resume after separately authorizing another budget, use the same command
with a new container name and output directory (`/evidence/january-002`), and
add `--resume /evidence/january-001/latest-checkpoint.json`. Never reuse the
previous output directory: the daily trace is opened for writing.

After the extension, the latest pointer is
`/evidence/january-002/latest-checkpoint.json`; use a new `january-003` output
for any subsequently authorized continuation. The current harness will refuse
IKN again until the separately reviewed date/bar repair described above exists.
`--verify-resume` with those inputs validates and deserializes without advancing
the simulation. No additional execution budget is implied by this handoff.

## Targeted validation

Commands run in the same offline dependency image with the source mounted at
`/work`, `PYTHONPATH=/work:/work/shared`, and bytecode writes disabled:

```text
python -m pytest -q -p no:cacheprovider tests/sentinel/test_resumable_historical_replay.py --junitxml=/evidence/january-tests.xml
3 passed in 6.46s
python -m research.bounded_20y.january_mutations
6/6 killed: july_baseline, checkpoint_bytes, checkpoint_binding,
state_commitment, past_action_change, future_action
```

Python AST and pyflakes checks passed for the new runner, mutations and tests;
test ownership has 497 modules and zero unowned modules. A real May 25 checkpoint successfully
loaded with source binding and state hash verification. Final checkpoint
verification and exact stopped results are retained with this report.
